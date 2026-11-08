"""Question Core persistence layer (PostgreSQL).

Public surface: configuration, engine/session helpers, the repository and
the error types.  The contract models under
``question_core.contracts.v1`` remain the single source of truth; this
package only stores and restores them.
"""

from __future__ import annotations

from .config import DatabaseSettings
from .engine import create_db_engine, health_check, session_scope
from .exceptions import (
    ConfigurationError,
    ContractViolationError,
    DatabaseConnectionError,
    DuplicateCandidateError,
    DuplicateInstanceError,
    DuplicateQuestionError,
    DuplicateRevisionError,
    NotFoundError,
    PersistenceError,
    RevisionImmutabilityError,
)
from .repository import QuestionCoreRepository

__all__ = [
    "ConfigurationError",
    "ContractViolationError",
    "DatabaseConnectionError",
    "DatabaseSettings",
    "DuplicateCandidateError",
    "DuplicateInstanceError",
    "DuplicateQuestionError",
    "DuplicateRevisionError",
    "NotFoundError",
    "PersistenceError",
    "QuestionCoreRepository",
    "RevisionImmutabilityError",
    "create_db_engine",
    "health_check",
    "session_scope",
]
