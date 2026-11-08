"""Persistence-layer errors for Question Core.

Every failure mode the persistence layer can produce has a dedicated class so
callers (and tests) can distinguish configuration problems, connectivity
problems, idempotency/duplicate boundaries and contract re-validation
failures without parsing message strings.
"""

from __future__ import annotations


class PersistenceError(Exception):
    """Base class for every persistence-layer error."""


class ConfigurationError(PersistenceError):
    """Environment configuration is missing or refuses to run."""


class DatabaseConnectionError(PersistenceError):
    """The PostgreSQL server could not be reached or refused the login."""


class ContractViolationError(PersistenceError):
    """A payload read back from the database failed contract re-validation.

    The stored document is not a valid contract object any more (manual edit,
    corruption, or a contract change). The original exception is chained.
    """


class DuplicateCandidateError(PersistenceError):
    """A candidate with the same candidate_id or idempotency key exists."""


class DuplicateQuestionError(PersistenceError):
    """A question with the same question_id exists."""


class DuplicateRevisionError(PersistenceError):
    """A revision with the same revision_id or revision_number exists."""


class DuplicateInstanceError(PersistenceError):
    """An instance with the same instance_id or the same occurrence slot
    (question_id, source_document_id, ordinal) exists."""


class NotFoundError(PersistenceError):
    """The requested object does not exist."""


class RevisionImmutabilityError(PersistenceError):
    """An UPDATE/DELETE on stored revision content was rejected.

    Raised by the database trigger and translated by the repository.
    """
