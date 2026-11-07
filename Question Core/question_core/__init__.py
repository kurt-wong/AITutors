"""Question Core — independent formal question bank domain.

This package holds the Question Core data contracts and domain models. It
is deliberately independent of DeepTutor: DeepTutor consumes Question Core
via its API contract, not by importing its persistence models.
"""

from __future__ import annotations

__all__ = ["contracts"]
