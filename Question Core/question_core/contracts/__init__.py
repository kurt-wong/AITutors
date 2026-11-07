"""Question Core data contracts.

``v1`` is the first formal contract version. The Pydantic v2 models in this
package are the single source of truth; the JSON Schema under
``integrations/question_core/schema/v1/`` is generated from them and must not
be hand-edited.
"""

from __future__ import annotations

__all__ = ["v1"]
