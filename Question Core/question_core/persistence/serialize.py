"""Contract ⇄ payload serialization.

The payload stored in the JSONB columns is exactly
``model_dump(mode="json")`` of the contract object.  Restoring always goes
through ``model_validate`` so every contract validator (content hash
binding, F1/F2/F4 rules, tree consistency, …) runs again on read.

One contract quirk needs a hydration step: ``Revision.explanation_blocks``
is an untyped ``tuple``, so after a JSON round-trip its items arrive as
plain dicts and ``Revision``'s content-hash validator would crash on them
(``dict`` has no ``model_dump``).  We rebuild those items into their
contract models (the same ``content_block_adapter`` the contract exports)
before validation.  The contract itself is not modified.
"""

from __future__ import annotations

from typing import Any

from ..contracts.v1 import (
    Candidate,
    QuestionAggregate,
    QuestionIdentity,
    QuestionInstance,
    Revision,
    StateSnapshot,
    candidate_adapter,
    content_block_adapter,
    typed_answer_adapter,
)
from .exceptions import ContractViolationError

#: Discriminator keys used to pick the right contract adapter for an
#: ``explanation_blocks`` item coming back from JSON.
_EXPLANATION_KINDS = frozenset(
    {"text", "math", "chemical", "image", "table", "material_ref"}
)


def dump_contract(model: Any) -> dict[str, Any]:
    """Canonical JSON-form dump of a contract model (stored as JSONB)."""
    return model.model_dump(mode="json")


def _hydrate_explanation_block(block: Any) -> Any:
    if not isinstance(block, dict):
        return block
    kind = block.get("kind")
    if kind in _EXPLANATION_KINDS:
        return content_block_adapter.validate_python(block)
    if "answer_type" in block:
        return typed_answer_adapter.validate_python(block)
    raise ContractViolationError(
        "cannot rehydrate explanation_blocks item without a known "
        f"discriminator (kind/answer_type): keys={sorted(block)[:8]}"
    )


def restore_revision(payload: dict[str, Any]) -> Revision:
    """Rebuild a Revision from its stored payload, re-running validation."""
    data = dict(payload)
    blocks = data.get("explanation_blocks") or []
    data["explanation_blocks"] = [
        _hydrate_explanation_block(b) for b in blocks
    ]
    try:
        return Revision.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - surface as persistence error
        raise ContractViolationError(
            f"stored revision payload failed contract validation: {exc}"
        ) from exc


def restore_candidate(payload: dict[str, Any]) -> Candidate:
    """Rebuild a Candidate (both source branches) from its stored payload."""
    try:
        return candidate_adapter.validate_python(payload)
    except Exception as exc:  # noqa: BLE001
        raise ContractViolationError(
            f"stored candidate payload failed contract validation: {exc}"
        ) from exc


def restore_instance(payload: dict[str, Any]) -> QuestionInstance:
    try:
        return QuestionInstance.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise ContractViolationError(
            f"stored instance payload failed contract validation: {exc}"
        ) from exc


def restore_identity(payload: dict[str, Any]) -> QuestionIdentity:
    try:
        return QuestionIdentity.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise ContractViolationError(
            f"stored question identity failed contract validation: {exc}"
        ) from exc


def restore_state_snapshot(payload: dict[str, Any]) -> StateSnapshot:
    try:
        return StateSnapshot.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise ContractViolationError(
            f"stored state snapshot failed contract validation: {exc}"
        ) from exc


def restore_aggregate(
    *,
    identity: QuestionIdentity,
    revisions: tuple[Revision, ...],
    instances: tuple[QuestionInstance, ...],
    state_history: tuple[StateSnapshot, ...],
) -> QuestionAggregate:
    """Assemble a QuestionAggregate and re-run its consistency rules."""
    try:
        return QuestionAggregate(
            identity=identity,
            revisions=revisions,
            instances=instances,
            state_history=state_history,
        )
    except Exception as exc:  # noqa: BLE001
        raise ContractViolationError(
            f"stored question aggregate failed contract validation: {exc}"
        ) from exc
