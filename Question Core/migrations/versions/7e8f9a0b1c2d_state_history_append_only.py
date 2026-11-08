"""State history append-only protection (R1-FIX-2).

qcore_state_history is the single authority for a question's current
lifecycle state, so its rows must be immutable like revision content:
INSERT only - UPDATE and DELETE are rejected by a database trigger.

Revision ID: 7e8f9a0b1c2d
Revises: 4b7c1d2e9a01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from question_core.persistence.models import (
    STATE_HISTORY_IMMUTABILITY_FUNCTION_SQL,
    STATE_HISTORY_IMMUTABILITY_TRIGGER_SQL,
)

revision: str = "7e8f9a0b1c2d"
down_revision: Union[str, None] = "4b7c1d2e9a01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(STATE_HISTORY_IMMUTABILITY_FUNCTION_SQL)
    op.execute(STATE_HISTORY_IMMUTABILITY_TRIGGER_SQL)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS qcore_state_history_immutable "
        "ON qcore_state_history"
    )
    op.execute("DROP FUNCTION IF EXISTS qcore_block_state_history_mutation()")
