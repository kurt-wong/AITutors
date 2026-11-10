"""Three-dimensional state model: Completeness × Review × Publication.

The three axes are independent. The rules encoded here (direction document
§4.2) are:

1. ``incomplete`` may not become ``approved``.
2. ``approved`` does **not** imply ``published``.
3. ``rejected`` may not become ``published``.
4. Content change produces a **new Revision**; it never mutates the old one.
5. Approval binds ``revision_id + content_hash``.
6. Publication binds ``revision_id + content_hash``.
7. A new Revision does **not** inherit the old Revision's approval.
8. A Question has at most one current published Revision at a time.
9. History of approvals and publications is preserved.

"Unpublished" never means "unreadable": review staff must be able to read the
full content of a candidate before it is published. That is a *visibility*
property (``Visibility.REVIEW_ONLY``), not a publication property, and is
enforced by the read side — the state machine here only guards transitions.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Annotated
from uuid import UUID

from pydantic import Field, model_validator

from .common import (
    ActorId,
    Completeness,
    ContractModel,
    NoteText,
    PublicationState,
    ReviewState,
    Sha256Hex,
    new_id,
    utc_now,
)

if TYPE_CHECKING:
    from .evidence import EvidenceBundle


def _transition(snapshot: "StateSnapshot", **updates) -> "StateSnapshot":
    """Create a new StateSnapshot with ``updates``, going through full
    validation.

    This is the only sanctioned way to derive a new snapshot from an
    existing one — ``model_copy(update=…)`` is forbidden on contract
    models because it bypasses validation.
    """
    data = snapshot.model_dump(mode="json")
    data.update(updates)
    return StateSnapshot.model_validate(data)

# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------

#: Review-state transitions. ``not_ready → pending_review`` requires the
#: content to be complete (checked separately by :func:`check_review_transition`).
REVIEW_TRANSITIONS: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.NOT_READY: frozenset({ReviewState.PENDING_REVIEW}),
    ReviewState.PENDING_REVIEW: frozenset(
        {ReviewState.APPROVED, ReviewState.REJECTED, ReviewState.CHANGES_REQUESTED}
    ),
    ReviewState.CHANGES_REQUESTED: frozenset(
        {ReviewState.PENDING_REVIEW, ReviewState.NOT_READY}
    ),
    ReviewState.APPROVED: frozenset(
        {ReviewState.CHANGES_REQUESTED, ReviewState.REJECTED}
    ),
    ReviewState.REJECTED: frozenset({ReviewState.PENDING_REVIEW}),
}

#: Publication-state transitions. ``published → withdrawn`` is allowed;
#: ``withdrawn → published`` re-publishes the *same* revision only when the
#: revision is still the approved one (checked separately).
PUBLICATION_TRANSITIONS: dict[PublicationState, frozenset[PublicationState]] = {
    PublicationState.UNPUBLISHED: frozenset({PublicationState.PUBLISHED}),
    PublicationState.PUBLISHED: frozenset({PublicationState.WITHDRAWN}),
    PublicationState.WITHDRAWN: frozenset({PublicationState.PUBLISHED}),
}


def review_transition_allowed(
    current: ReviewState, target: ReviewState
) -> bool:
    return target in REVIEW_TRANSITIONS.get(current, frozenset())


def publication_transition_allowed(
    current: PublicationState, target: PublicationState
) -> bool:
    return target in PUBLICATION_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


class ApprovalRecord(ContractModel):
    """A reviewer's approval, bound to one exact revision."""

    approval_id: UUID = Field(default_factory=new_id)
    revision_id: UUID
    content_hash: Sha256Hex
    approved_by: ActorId
    approved_at: datetime = Field(default_factory=utc_now)
    note: NoteText | None = None

    #: Fields the reviewer explicitly confirmed (e.g. ``["content",
    #: "answer:1", "answer:2"]``). Used for audit, not for grading.
    confirmed_fields: tuple[str, ...] = Field(default_factory=tuple)


class PublicationRecord(ContractModel):
    """A publication event, bound to one exact approved revision."""

    publication_id: UUID = Field(default_factory=new_id)
    revision_id: UUID
    content_hash: Sha256Hex
    state: PublicationState
    acted_by: ActorId
    acted_at: datetime = Field(default_factory=utc_now)
    note: NoteText | None = None


class StateSnapshot(ContractModel):
    """The three-dimensional state of one Revision.

    ``completeness``, ``review`` and ``publication`` are stored and
    validated together so the cross-axis rules can be checked in one place.
    """

    revision_id: UUID
    content_hash: Sha256Hex
    completeness: Completeness = Completeness.INCOMPLETE
    review: ReviewState = ReviewState.NOT_READY
    publication: PublicationState = PublicationState.UNPUBLISHED
    approval: ApprovalRecord | None = None
    publication_record: PublicationRecord | None = None

    @model_validator(mode="after")
    def _cross_axis(self) -> "StateSnapshot":
        # Rule 1: incomplete never approved.
        if (
            self.completeness == Completeness.INCOMPLETE
            and self.review == ReviewState.APPROVED
        ):
            raise ValueError("incomplete content may not be approved")

        # Rule 3: rejected never published.
        if (
            self.review == ReviewState.REJECTED
            and self.publication == PublicationState.PUBLISHED
        ):
            raise ValueError("rejected revision may not be published")

        # Rule 5: approval binds revision_id + content_hash.
        if self.review == ReviewState.APPROVED:
            if self.approval is None:
                raise ValueError("approved state requires an ApprovalRecord")
            if self.approval.revision_id != self.revision_id:
                raise ValueError("approval must bind this revision_id")
            if self.approval.content_hash != self.content_hash:
                raise ValueError("approval must bind this content_hash")
        elif self.approval is not None:
            raise ValueError("approval record present but review is not approved")

        # Rule 6: publication binds revision_id + content_hash.
        if self.publication in (
            PublicationState.PUBLISHED,
            PublicationState.WITHDRAWN,
        ):
            if self.publication_record is None:
                raise ValueError("published/withdrawn requires a PublicationRecord")
            if self.publication_record.revision_id != self.revision_id:
                raise ValueError("publication must bind this revision_id")
            if self.publication_record.content_hash != self.content_hash:
                raise ValueError("publication must bind this content_hash")
        elif self.publication_record is not None:
            raise ValueError(
                "publication record present but publication is unpublished"
            )

        # Publishing requires approval of THIS revision (rule 5/7 combined).
        if self.publication == PublicationState.PUBLISHED:
            if self.review != ReviewState.APPROVED:
                raise ValueError("only an approved revision may be published")
        return self

    # -- transition helpers ------------------------------------------------

    def can_transition_review(self, target: ReviewState) -> bool:
        if not review_transition_allowed(self.review, target):
            return False
        if target == ReviewState.APPROVED and self.completeness == Completeness.INCOMPLETE:
            return False
        return True

    def can_publish(self) -> bool:
        return (
            self.review == ReviewState.APPROVED
            and self.completeness == Completeness.COMPLETE
            and self.publication == PublicationState.UNPUBLISHED
        )


def new_revision(
    previous: StateSnapshot,
    *,
    revision_id: UUID,
    content_hash: Sha256Hex,
) -> StateSnapshot:
    """Create the state for a **new** revision of the same question.

    Rule 7: the new revision starts from scratch — it does not inherit the
    previous revision's approval or publication. The previous snapshot is
    left untouched (rule 9: history is preserved by the caller's store).
    """
    if content_hash == previous.content_hash:
        raise ValueError(
            "a new revision must change content_hash; "
            "use the existing revision instead"
        )
    return StateSnapshot(
        revision_id=revision_id,
        content_hash=content_hash,
        completeness=Completeness.INCOMPLETE,
        review=ReviewState.NOT_READY,
        publication=PublicationState.UNPUBLISHED,
    )


def has_blocking_conflicts(evidence: "EvidenceBundle | None") -> bool:
    """True when the evidence bundle carries blocking conflicts.

    Used both by the Revision validator (authoritative) and by the
    transition helpers (defense in depth) so an illegal ``approved`` or
    ``published`` state cannot be reached through either path.

    Source-internal conflicts are preserved facts of the source document
    and are not blockers (Owner D-2 / G-08); only unresolved critical
    pipeline disagreements block.
    """
    if evidence is None:
        return False
    return bool(evidence.blocking_conflicts())


def approve_revision(
    snapshot: StateSnapshot,
    *,
    approved_by: ActorId,
    content_hash: Sha256Hex,
    confirmed_fields: list[str] | None = None,
    note: NoteText | None = None,
    evidence: "EvidenceBundle | None" = None,
) -> StateSnapshot:
    """Transition a snapshot to ``approved``, binding this revision + hash.

    The caller passes the ``content_hash`` it believes it is approving; the
    function refuses if it does not match the snapshot, which is how rule 5
    is enforced at the API boundary.

    ``evidence`` is optional but recommended: when supplied, unresolved
    critical conflicts block approval (F1).
    """
    if content_hash != snapshot.content_hash:
        raise ValueError("content_hash does not match the revision being approved")
    if has_blocking_conflicts(evidence):
        raise ValueError(
            "unresolved critical evidence conflict blocks approval"
        )
    if not snapshot.can_transition_review(ReviewState.APPROVED):
        raise ValueError(
            f"review transition {snapshot.review} -> approved is not allowed"
        )
    record = ApprovalRecord(
        revision_id=snapshot.revision_id,
        content_hash=snapshot.content_hash,
        approved_by=approved_by,
        confirmed_fields=list(confirmed_fields or []),
        note=note,
    )
    return _transition(
        snapshot,
        review=ReviewState.APPROVED,
        approval=record,
        publication=PublicationState.UNPUBLISHED,
        publication_record=None,
    )


def publish_revision(
    snapshot: StateSnapshot,
    *,
    acted_by: ActorId,
    content_hash: Sha256Hex,
    note: NoteText | None = None,
    evidence: "EvidenceBundle | None" = None,
) -> StateSnapshot:
    """Publish an approved revision (rule 6: bound to revision + hash).

    ``evidence`` is optional but recommended: when supplied, unresolved
    critical conflicts block publication (F1).
    """
    if content_hash != snapshot.content_hash:
        raise ValueError("content_hash does not match the revision being published")
    if has_blocking_conflicts(evidence):
        raise ValueError(
            "unresolved critical evidence conflict blocks publication"
        )
    if not snapshot.can_publish():
        raise ValueError(
            f"cannot publish: completeness={snapshot.completeness} "
            f"review={snapshot.review} publication={snapshot.publication}"
        )
    record = PublicationRecord(
        revision_id=snapshot.revision_id,
        content_hash=snapshot.content_hash,
        state=PublicationState.PUBLISHED,
        acted_by=acted_by,
        note=note,
    )
    return _transition(
        snapshot,
        publication=PublicationState.PUBLISHED,
        publication_record=record,
    )


def withdraw_publication(
    snapshot: StateSnapshot,
    *,
    acted_by: ActorId,
    content_hash: Sha256Hex,
    note: NoteText | None = None,
) -> StateSnapshot:
    if content_hash != snapshot.content_hash:
        raise ValueError("content_hash does not match the revision being withdrawn")
    if not publication_transition_allowed(snapshot.publication, PublicationState.WITHDRAWN):
        raise ValueError(f"cannot withdraw from {snapshot.publication}")
    record = PublicationRecord(
        revision_id=snapshot.revision_id,
        content_hash=snapshot.content_hash,
        state=PublicationState.WITHDRAWN,
        acted_by=acted_by,
        note=note,
    )
    return _transition(
        snapshot,
        publication=PublicationState.WITHDRAWN,
        publication_record=record,
    )


def check_single_published(
    snapshots: list[StateSnapshot],
) -> None:
    """Rule 8: at most one currently-published revision per question.

    ``WITHDRAWN`` counts as not currently published. Call this with every
    revision-state of one Question.
    """
    published = [
        s for s in snapshots if s.publication == PublicationState.PUBLISHED
    ]
    if len(published) > 1:
        ids = [str(s.revision_id) for s in published]
        raise ValueError(f"multiple published revisions: {ids}")


__all__ = [
    "ApprovalRecord",
    "PublicationRecord",
    "PUBLICATION_TRANSITIONS",
    "REVIEW_TRANSITIONS",
    "StateSnapshot",
    "approve_revision",
    "check_single_published",
    "has_blocking_conflicts",
    "new_revision",
    "publication_transition_allowed",
    "publish_revision",
    "review_transition_allowed",
    "withdraw_publication",
]
