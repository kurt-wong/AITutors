"""Content blocks: tables, composite parent/child tree, cycles, assets."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestTableStructure:
    def test_round_trip_rows(self, contract):
        table = contract.TableBlock(
            n_rows=2,
            n_cols=2,
            cells=[
                contract.TableCell(row_index=0, col_index=0, content="a"),
                contract.TableCell(row_index=0, col_index=1, content="b"),
                contract.TableCell(row_index=1, col_index=0, content="c"),
                contract.TableCell(row_index=1, col_index=1, content="d"),
            ],
        )
        assert table.to_rows() == [["a", "b"], ["c", "d"]]

    def test_merged_cells_cover_grid(self, contract):
        table = contract.TableBlock(
            n_rows=2,
            n_cols=2,
            cells=[
                contract.TableCell(
                    row_index=0, col_index=0, content="wide", colspan=2
                ),
                contract.TableCell(row_index=1, col_index=0, content="c"),
                contract.TableCell(row_index=1, col_index=1, content="d"),
            ],
        )
        assert table.to_rows() == [["wide", "wide"], ["c", "d"]]

    def test_rowspan(self, contract):
        table = contract.TableBlock(
            n_rows=2,
            n_cols=2,
            cells=[
                contract.TableCell(row_index=0, col_index=0, content="tall", rowspan=2),
                contract.TableCell(row_index=0, col_index=1, content="b"),
                contract.TableCell(row_index=1, col_index=1, content="d"),
            ],
        )
        assert table.to_rows() == [["tall", "b"], ["tall", "d"]]

    def test_overlapping_cells_rejected(self, contract):
        with pytest.raises(ValidationError, match="overlapping"):
            contract.TableBlock(
                n_rows=2,
                n_cols=2,
                cells=[
                    contract.TableCell(row_index=0, col_index=0, content="x", colspan=2),
                    contract.TableCell(row_index=0, col_index=1, content="y"),
                ],
            )

    def test_out_of_grid_rejected(self, contract):
        with pytest.raises(ValidationError, match="outside"):
            contract.TableBlock(
                n_rows=1,
                n_cols=1,
                cells=[contract.TableCell(row_index=2, col_index=0, content="x")],
            )

    def test_span_overflow_rejected(self, contract):
        with pytest.raises(ValidationError, match="overflows"):
            contract.TableBlock(
                n_rows=1,
                n_cols=2,
                cells=[
                    contract.TableCell(row_index=0, col_index=1, content="x", colspan=2)
                ],
            )

    def test_table_serialization_round_trip(self, contract):
        table = contract.TableBlock(
            n_rows=2,
            n_cols=3,
            cells=[
                contract.TableCell(row_index=0, col_index=0, content="t/s", is_header=True),
                contract.TableCell(row_index=0, col_index=1, content="pH", is_header=True),
                contract.TableCell(row_index=0, col_index=2, content="c", is_header=True),
                contract.TableCell(row_index=1, col_index=0, content="0"),
                contract.TableCell(row_index=1, col_index=1, content="1.0"),
                contract.TableCell(row_index=1, col_index=2, content="0.10"),
            ],
        )
        dumped = table.model_dump(mode="json")
        again = contract.TableBlock.model_validate(dumped)
        assert again.to_rows() == table.to_rows()


class TestCompositeTree:
    def _tree(self, contract):
        return contract.QuestionContent(
            bodies=[
                contract.QuestionBody(
                    local_id="parent",
                    question_type="composite",
                    stem_blocks=[contract.TextBlock(text="材料")],
                    sub_question_ids=["sub1", "sub2"],
                    unit_type="composite_question",
                ),
                contract.QuestionBody(
                    local_id="sub1",
                    question_type="single_choice",
                    stem_blocks=[contract.TextBlock(text="(1)")],
                    parent_question_ref="parent",
                ),
                contract.QuestionBody(
                    local_id="sub2",
                    question_type="fill_blank",
                    stem_blocks=[contract.TextBlock(text="(2)")],
                    parent_question_ref="parent",
                ),
            ]
        )

    def test_parent_child_links_consistent(self, contract):
        content = self._tree(contract)
        assert content.tree() == {"parent": ["sub1", "sub2"]}

    def test_orphan_parent_rejected(self, contract):
        with pytest.raises(ValidationError, match="unknown parent"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="sub",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                        parent_question_ref="ghost",
                    )
                ]
            )

    def test_self_parent_rejected(self, contract):
        with pytest.raises(ValidationError, match="its own parent"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="q",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                        parent_question_ref="q",
                    )
                ]
            )

    def test_cycle_rejected(self, contract):
        with pytest.raises(ValidationError, match="cycle"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="a",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                        parent_question_ref="b",
                    ),
                    contract.QuestionBody(
                        local_id="b",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="y")],
                        parent_question_ref="a",
                    ),
                ]
            )

    def test_sub_must_point_back(self, contract):
        with pytest.raises(ValidationError, match="parent is"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="p",
                        question_type="composite",
                        stem_blocks=[contract.TextBlock(text="m")],
                        sub_question_ids=["s"],
                    ),
                    contract.QuestionBody(
                        local_id="s",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                        parent_question_ref=None,
                    ),
                ]
            )

    def test_duplicate_local_id_rejected(self, contract):
        with pytest.raises(ValidationError, match="duplicate local_id"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="q",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                    ),
                    contract.QuestionBody(
                        local_id="q",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="y")],
                    ),
                ]
            )

    def test_flattening_for_display_is_a_view_not_storage(self, contract):
        """Storage keeps the tree; flattening is a consumer-side concern."""
        content = self._tree(contract)
        flat_ids = [b.local_id for b in content.bodies]
        assert set(flat_ids) == {"parent", "sub1", "sub2"}
        # The tree relation survives serialization.
        dumped = content.model_dump(mode="json")
        again = contract.QuestionContent.model_validate(dumped)
        assert again.tree() == {"parent": ["sub1", "sub2"]}


class TestAssets:
    def test_asset_round_trip(self, contract):
        asset = contract.Asset(
            asset_id="img1",
            asset_role="figure",
            target_path="/bodies/0/stem_blocks/0",
            source_id="paper.md",
            page=2,
            bbox=contract.BBox(x0=0, y0=0, x1=10, y1=10),
            storage_path="_imgs/img1.jpg",
            content_hash="a" * 64,
            mime_type="image/jpeg",
        )
        dumped = asset.model_dump(mode="json")
        again = contract.Asset.model_validate(dumped)
        assert again.bbox.x1 == 10

    def test_bbox_order_validated(self, contract):
        with pytest.raises(ValidationError, match="x1>=x0"):
            contract.BBox(x0=10, y0=0, x1=0, y1=10)

    def test_duplicate_asset_id_rejected(self, contract):
        with pytest.raises(ValidationError, match="duplicate asset_id"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="q",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                    )
                ],
                assets=[
                    contract.Asset(asset_id="a", storage_path="p1.png"),
                    contract.Asset(asset_id="a", storage_path="p2.png"),
                ],
            )

    def test_unknown_material_ref_rejected(self, contract):
        with pytest.raises(ValidationError, match="unknown material"):
            contract.QuestionContent(
                bodies=[
                    contract.QuestionBody(
                        local_id="q",
                        question_type="single_choice",
                        stem_blocks=[contract.TextBlock(text="x")],
                        material_ids=["ghost"],
                    )
                ]
            )


class TestContentBlockUnion:
    def test_dispatch(self, contract):
        blk = contract.content_block_adapter.validate_python(
            {"kind": "math", "latex": "x^2"}
        )
        assert isinstance(blk, contract.MathBlock)

    def test_table_inside_content(self, contract):
        blk = contract.content_block_adapter.validate_python(
            {
                "kind": "table",
                "n_rows": 1,
                "n_cols": 1,
                "cells": [{"row_index": 0, "col_index": 0, "content": "x"}],
            }
        )
        assert isinstance(blk, contract.TableBlock)
        assert blk.to_rows() == [["x"]]
