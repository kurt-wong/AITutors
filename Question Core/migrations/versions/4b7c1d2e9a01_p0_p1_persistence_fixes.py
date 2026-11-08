"""P0-2/P1 fixes: candidate key versioning, revision pairing FK.

* qcore_candidates: UNIQUE(idempotency_key) -> UNIQUE(idempotency_key,
  adapter_version).  adapter_version is NOT NULL (contract requires it),
  so the PostgreSQL NULL-inequality quirk cannot occur; a NULL insert is
  rejected by the NOT NULL constraint itself.
* qcore_revisions: UNIQUE(question_id, revision_id) as the pairing target.
* qcore_question_instances: composite FOREIGN KEY (question_id, revision_id)
  -> qcore_revisions(question_id, revision_id) so Question A can never point
  at a Revision of Question B.  The database rejects it directly.

Revision ID: 4b7c1d2e9a01
Revises: 1230cc4692f1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "4b7c1d2e9a01"
down_revision: Union[str, None] = "1230cc4692f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- C: candidate idempotency key becomes (key, adapter_version) ---
    op.execute(
        "ALTER TABLE qcore_candidates "
        "DROP CONSTRAINT IF EXISTS qcore_candidates_idempotency_key_key"
    )
    op.create_unique_constraint(
        "uq_candidate_key_version",
        "qcore_candidates",
        ["idempotency_key", "adapter_version"],
    )
    # adapter_version stays NOT NULL (created that way in 0001): a NULL
    # version can never enter the unique key.
    op.alter_column(
        "qcore_candidates", "adapter_version", existing_type=sa.Text(), nullable=False
    )

    # --- E: question/revision pairing ---
    op.create_unique_constraint(
        "uq_revision_question_ref",
        "qcore_revisions",
        ["question_id", "revision_id"],
    )
    op.create_foreign_key(
        "fk_instance_revision_pair",
        "qcore_question_instances",
        "qcore_revisions",
        ["question_id", "revision_id"],
        ["question_id", "revision_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_instance_revision_pair",
        "qcore_question_instances",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_revision_question_ref", "qcore_revisions", type_="unique"
    )
    op.drop_constraint(
        "uq_candidate_key_version", "qcore_candidates", type_="unique"
    )
    op.create_unique_constraint(
        "qcore_candidates_idempotency_key_key",
        "qcore_candidates",
        ["idempotency_key"],
    )
