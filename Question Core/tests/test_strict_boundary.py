"""Strict Adapter boundary: the three shared-answer-table cases.

The contract must encode (and refuse to blur) the distinction between:

1. Manifest declares the unit's answer evidence → direct map.
2. Structured answer table with explicit number→answer mapping →
   deterministic conversion allowed, table-row evidence kept.
3. Only a whole answer table or prose explanation → ``incomplete``, no
   inference.

Strict may perform deterministic *structural* conversion, never new
*semantic* judgment. The adapter is not built this round; this module pins
the data contract the future adapter must obey.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestThreeCases:
    def test_declared_case(self, contract):
        dec = contract.StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value="B",
            completeness="complete",
        )
        assert dec.attribution == "declared"
        assert dec.declared_value == "B"

    def test_table_row_case(self, contract):
        dec = contract.StrictAnswerDeclaration(
            attribution="table_row",
            evidence_kind="answer_table",
            declared_value="C",
            table_row_locator="table:row=3,col=2",
            completeness="complete",
        )
        assert dec.table_row_locator is not None

    def test_not_attributable_case_must_be_incomplete(self, contract):
        dec = contract.StrictAnswerDeclaration(
            attribution="not_attributable",
            evidence_kind="explanation_prose",
            completeness="incomplete",
        )
        assert dec.completeness.value == "incomplete"

    def test_not_attributable_refuses_complete(self, contract):
        with pytest.raises(ValidationError, match="must be marked incomplete"):
            contract.StrictAnswerDeclaration(
                attribution="not_attributable",
                evidence_kind="explanation_prose",
                completeness="complete",
            )

    def test_declared_requires_value(self, contract):
        with pytest.raises(ValidationError, match="requires declared_value"):
            contract.StrictAnswerDeclaration(
                attribution="declared",
                evidence_kind="answer_lines",
                completeness="complete",
            )


class TestCompletenessMapping:
    def test_only_not_attributable_maps_to_incomplete(self, contract):
        assert contract.strict_completeness_for("not_attributable").value == "incomplete"
        assert contract.strict_completeness_for("declared").value == "complete"
        assert contract.strict_completeness_for("table_row").value == "complete"

    def test_rules_table_is_documented(self, contract):
        rules = contract.STRICT_BOUNDARY_RULES
        assert set(rules) == {"declared", "table_row", "not_attributable"}
        assert "do not infer" in rules["not_attributable"]


class TestNoNewSemanticJudgment:
    def test_declared_value_is_verbatim_not_reinterpreted(self, contract):
        """A declared value like ``=VO2+ +Mn2+`` must survive untouched."""
        raw = "=VO$_2^+$ +Mn$^{2+}$"
        dec = contract.StrictAnswerDeclaration(
            attribution="declared",
            evidence_kind="answer_lines",
            declared_value=raw,
            completeness="complete",
        )
        assert dec.declared_value == raw

    def test_unattributable_keeps_no_invented_answer(self, contract):
        dec = contract.StrictAnswerDeclaration(
            attribution="not_attributable",
            evidence_kind="answer_table",
            completeness="incomplete",
        )
        # No declared_value may be smuggled in as "the answer".
        assert dec.declared_value is None

    def test_end_to_end_candidate_with_unattributable_answer(self, contract):
        """A candidate whose answer cannot be attributed must land as
        incomplete, so the review workflow sees it as unresolved."""
        cand = contract.PreprocessingCandidate(
            core=contract.CandidateCore(
                question_type="short_answer",
                content=contract.QuestionContent(
                    bodies=[
                        contract.QuestionBody(
                            local_id="q",
                            question_type="short_answer",
                            stem_blocks=[contract.TextBlock(text="简述…")],
                        )
                    ]
                ),
                answers=[],
                completeness=contract.Completeness.INCOMPLETE,
                ingestion=contract.IngestionIdentity(
                    candidate_idempotency_key="k" * 20,
                    adapter_version="a/1",
                    input_hashes=contract.InputHashes(manifest_hash="a" * 64),
                ),
            ),
            source=contract.PreprocessingSource(
                source_document_id="doc/1",
                manifest_ref=contract.SourceDocumentRef(
                    doc_role="manifest", content_hash="a" * 64
                ),
                unit=contract.PreprocessingUnitRef(
                    unit_id="Q7", unit_type="standalone_question"
                ),
                answer_declaration=contract.StrictAnswerDeclaration(
                    attribution="not_attributable",
                    evidence_kind="explanation_prose",
                    completeness="incomplete",
                ),
            ),
        )
        assert cand.source.answer_declaration.completeness.value == "incomplete"
        assert cand.core.completeness.value == "incomplete"


class TestRealAnswerEvidenceKinds:
    """The kinds observed in real Preprocessing manifests must all be
    expressible (847 units across 46 packages: answer_lines 653,
    inline_in_explanation 128, absent 49, range_string 17)."""

    @pytest.mark.parametrize(
        "kind,attribution",
        [
            ("answer_lines", "declared"),
            ("inline_in_explanation", "not_attributable"),
            ("absent", "not_attributable"),
            ("range_string", "not_attributable"),
            ("answer_table", "table_row"),
        ],
    )
    def test_kind_expressible(self, contract, kind, attribution):
        declared_value = None
        table_row_locator = None
        if attribution == "declared":
            declared_value = "B"
        elif attribution == "table_row":
            declared_value = "C"
            table_row_locator = "table:row=3,col=2"
        dec = contract.StrictAnswerDeclaration(
            attribution=attribution,
            evidence_kind=kind,
            declared_value=declared_value,
            table_row_locator=table_row_locator,
            completeness=contract.strict_completeness_for(attribution).value,
        )
        assert dec.evidence_kind == kind
