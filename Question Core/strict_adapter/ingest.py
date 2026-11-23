"""D9-aware persistence for one mapped unit.

Replaces the historical "lookup candidate key, else create everything":
the candidate key no longer carries processing hashes, and identity is
resolved from the source anchor, so re-processing a paper reuses the existing
Question and appends a Revision instead of minting a duplicate Question.

Decision table (D9, Owner 2026-11-23):

* no Question for the anchor            -> create Question + Revision(1)
* Question found, content hash equal     -> skipped_duplicate
* Question found, content hash differs   -> append Revision(n+1),
                                            not_ready / unpublished
* anchor ambiguous in the paper          -> AmbiguousIdentityError (fail closed)

The candidate row stays an ingestion audit record: it is inserted when its
``qk2_`` key is new and skipped when the same key has already been ingested.
Traceability of the new content's processing artifacts lives in the
revision's ``change_note`` (manifest / md / pdf hashes + run id).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from question_core.contracts.v1 import (
    Completeness,
    IdentityAnchor,
    Revision,
    StateSnapshot,
    withdraw_publication,
)
from question_core.persistence.exceptions import NotFoundError
from question_core.persistence.identity_resolve import resolve_identity

from . import ADAPTER_VERSION


def _candidate_exists(repo, key: str) -> bool:
    try:
        repo.get_candidate_by_key(key, ADAPTER_VERSION)
        return True
    except NotFoundError:
        return False


def _ingestion_note(candidate) -> str:
    ing = candidate.core.ingestion
    return json.dumps(
        {
            "manifest_hash": ing.input_hashes.manifest_hash,
            "source_md_hash": ing.input_hashes.source_md_hash,
            "source_pdf_hash": ing.input_hashes.source_pdf_hash,
            "ingestion_run_id": str(ing.ingestion_run_id),
            "adapter_version": ing.adapter_version,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def persist_mapping(repo, mapping, admission, *, paper_id: str) -> dict[str, Any]:
    """Persist one unit, reusing an existing Question when the anchor matches.

    ``mapping`` is a ``strict_adapter.mapper.UnitMapping``; ``admission`` is
    its ``AdmissionResult`` (aggregate with a fresh Question/Revision).
    Returns a per-unit record for the persistence log.
    """
    candidate = mapping.candidate
    key = candidate.core.ingestion.candidate_idempotency_key
    anchor_dict = dict(mapping.identity_anchor or {})
    record: dict[str, Any] = {
        "unit_id": mapping.unit_id,
        "identity_key": key,
        "identity_anchor": anchor_dict,
        "persist": "begun",
    }
    if not anchor_dict:
        raise ValueError(
            f"{mapping.unit_id}: mapping carries no identity_anchor — refusing "
            "to persist (D9 importer requires a source anchor)"
        )
    anchor = IdentityAnchor(
        paper_segment_id=anchor_dict["paper_segment_id"],
        section_id=anchor_dict["section_id"],
        question_numbers=tuple(anchor_dict["question_numbers"]),
        source_hash=anchor_dict["source_hash"],
    ).validate()

    aggregate = admission.aggregate
    new_revision = aggregate.revisions[0]

    slots = repo.list_instance_slots(paper_id, anchor.paper_segment_id)
    resolved = resolve_identity(
        slots,
        paper_segment_id=anchor.paper_segment_id,
        section_id=anchor.section_id,
        question_numbers=anchor.question_numbers,
    )
    record["matched_by"] = resolved.matched_by
    record["section_drift"] = resolved.section_drift

    if resolved.question_id is None:
        repo.save_candidate_with_question(candidate, aggregate)
        record.update(
            persist="committed_new",
            question_id=str(admission.question_id),
            revision_id=str(new_revision.revision_id),
        )
        return record

    question_id: UUID = resolved.question_id
    existing = repo.get_question_aggregate(question_id)
    latest = max(existing.revisions, key=lambda r: r.revision_number)
    record["question_id"] = str(question_id)

    if latest.content_hash == new_revision.content_hash:
        if not _candidate_exists(repo, key):
            repo.save_candidate(candidate)
        record.update(
            persist="skipped_duplicate",
            revision_id=str(latest.revision_id),
            revision_number=latest.revision_number,
        )
        return record

    revision_id = uuid4()
    new_state = new_revision.state
    complete = new_state is not None and new_state.completeness == Completeness.COMPLETE
    snapshot = StateSnapshot(
        revision_id=revision_id,
        content_hash=new_revision.content_hash,
        completeness=Completeness.COMPLETE if complete else Completeness.INCOMPLETE,
        review="pending_review" if complete else "not_ready",
        publication="unpublished",
    )
    appended = Revision.create(
        question_id=question_id,
        revision_id=revision_id,
        revision_number=latest.revision_number + 1,
        question_type=new_revision.question_type,
        content=new_revision.content,
        answers=new_revision.answers,
        explanation_blocks=new_revision.explanation_blocks,
        evidence=new_revision.evidence,
        answer_visibility=new_revision.answer_visibility,
        explanation_visibility=new_revision.explanation_visibility,
        created_by=new_revision.created_by,
        change_note=(
            "D9 re-import: same source anchor, different content. "
            f"previous_revision={latest.revision_id}; "
            f"ingestion={_ingestion_note(candidate)}"
        ),
        state=snapshot,
    )

    # ---- D9 C1: the superseded revision must lose its published status -----
    # Revisions are immutable (DB trigger), so the current lifecycle lives in
    # the append-only state history. Publishing state moves published ->
    # withdrawn with a PublicationRecord bound to revision + content hash; the
    # withdrawn revision is *not* rejected, it is simply no longer current.
    retired_revision_id = None
    published = existing.published_revision()
    if published is not None:
        latest_snapshots = {}
        for snap in existing.state_history:
            latest_snapshots[snap.revision_id] = snap
        published_snapshot = latest_snapshots.get(
            published.revision_id, published.state
        )
        if published_snapshot is not None:
            withdrawn = withdraw_publication(
                published_snapshot,
                acted_by="qcore-d9-reimport",
                content_hash=published_snapshot.content_hash,
                note=(
                    "superseded by revision "
                    f"{appended.revision_number} ({appended.revision_id}); "
                    "content replaced by a newer revision"
                ),
            )
            repo.append_state_snapshot(question_id, withdrawn)
            retired_revision_id = str(published.revision_id)
            record["retired_revision_id"] = retired_revision_id

    if not _candidate_exists(repo, key):
        repo.save_candidate(candidate)
    repo.add_revision(appended)
    repo.append_state_snapshot(question_id, snapshot)
    record.update(
        persist="revision_added",
        revision_id=str(revision_id),
        revision_number=appended.revision_number,
        previous_revision_id=str(latest.revision_id),
    )
    return record


__all__ = ["persist_mapping"]
