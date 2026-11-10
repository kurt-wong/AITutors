"""Content blocks: text, formulae, tables, assets and composite structure.

The direction document requires that real exam structure survives storage:
shared materials, parent/child composite questions, table row/column
relationships including merged cells, and image/chart assets with their
provenance. Display layers may flatten; the stored form must not.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field, TypeAdapter, model_validator

from .common import (
    ContractModel,
    JsonPointer,
    NoteText,
    QuestionType,
    Sha256Hex,
    UnitType,
)

# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


class BBox(ContractModel):
    """Axis-aligned region in a page's coordinate space."""

    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox must have x1>=x0 and y1>=y0")
        return self


class Asset(ContractModel):
    """An image, chart, formula-render or other binary/content artifact.

    ``target_path`` links the asset to the field it illustrates; several
    assets may share a target (multi-figure material) and one asset may be
    referenced from several targets (shared material).
    """

    asset_id: Annotated[str, Field(min_length=1, max_length=200)]
    asset_role: Literal[
        "figure",
        "chart",
        "photo",
        "diagram",
        "formula_render",
        "table_render",
        "answer_image",
        "other",
    ] = "figure"
    target_path: JsonPointer | None = None
    source_id: Annotated[str, Field(max_length=300)] | None = None
    page: int | None = Field(default=None, ge=1)
    bbox: BBox | None = None
    storage_path: Annotated[str, Field(max_length=1000)]
    content_hash: Sha256Hex | None = None
    mime_type: Annotated[str, Field(max_length=100)] = "image/png"
    width: int | None = Field(default=None, ge=1)
    height: int | None = Field(default=None, ge=1)
    note: NoteText | None = None


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class TableCell(ContractModel):
    """One table cell.

    Merged cells are expressed on the *anchor* cell via ``rowspan`` /
    ``colspan``; the covered positions must be omitted from the row arrays.
    A cell may carry rich content, not only plain text.
    """

    row_index: int = Field(ge=0)
    col_index: int = Field(ge=0)
    content: str = ""
    rowspan: int = Field(default=1, ge=1)
    colspan: int = Field(default=1, ge=1)
    is_header: bool = False


class TableBlock(ContractModel):
    """A table with explicit row/column structure.

    ``cells`` is the authoritative representation; ``rows`` is the plain-text
    projection (row → column → text) kept for cheap consumers. The two must
    agree: every non-merged position appears exactly once.
    """

    kind: Literal["table"] = "table"
    table_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    n_rows: int = Field(ge=1)
    n_cols: int = Field(ge=1)
    cells: Annotated[tuple[TableCell, ...], Field(min_length=1)]
    caption: str | None = None

    @model_validator(mode="after")
    def _check_grid(self) -> "TableBlock":
        occupied: set[tuple[int, int]] = set()
        for cell in self.cells:
            if cell.row_index >= self.n_rows or cell.col_index >= self.n_cols:
                raise ValueError(
                    f"cell ({cell.row_index},{cell.col_index}) outside "
                    f"{self.n_rows}x{self.n_cols} grid"
                )
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    pos = (cell.row_index + dr, cell.col_index + dc)
                    if pos[0] >= self.n_rows or pos[1] >= self.n_cols:
                        raise ValueError(
                            f"cell span at {cell.row_index},{cell.col_index} "
                            f"overflows grid"
                        )
                    if pos in occupied:
                        raise ValueError(f"overlapping cells at {pos}")
                    occupied.add(pos)
        return self

    def to_rows(self) -> list[list[str]]:
        grid = [["" for _ in range(self.n_cols)] for _ in range(self.n_rows)]
        for cell in self.cells:
            for dr in range(cell.rowspan):
                for dc in range(cell.colspan):
                    grid[cell.row_index + dr][cell.col_index + dc] = cell.content
        return grid


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


class TextBlock(ContractModel):
    kind: Literal["text"] = "text"
    text: str
    #: Optional source line range this text was read from (1-based inclusive).
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class MathBlock(ContractModel):
    kind: Literal["math"] = "math"
    latex: Annotated[str, Field(min_length=1)]
    display: bool = False


class ChemicalBlock(ContractModel):
    kind: Literal["chemical"] = "chemical"
    formula: Annotated[str, Field(min_length=1)]
    notation: Literal["plain", "latex"] = "plain"


class ImageBlock(ContractModel):
    kind: Literal["image"] = "image"
    asset_id: Annotated[str, Field(min_length=1, max_length=200)]
    alt_text: str | None = None


class MaterialRef(ContractModel):
    """Pointer to shared material used by one or more questions."""

    kind: Literal["material_ref"] = "material_ref"
    material_id: Annotated[str, Field(min_length=1, max_length=200)]
    label: str | None = None


ContentBlock = Annotated[
    Union[TextBlock, MathBlock, ChemicalBlock, ImageBlock, TableBlock, MaterialRef],
    Field(discriminator="kind"),
]

content_block_adapter: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)


class Material(ContractModel):
    """Shared reading material / stimulus used by a composite question."""

    material_id: Annotated[str, Field(min_length=1, max_length=200)]
    title: str | None = None
    blocks: Annotated[tuple[ContentBlock, ...], Field(min_length=1)]
    #: Source line range of the material body, when it came from a paper.
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    note: NoteText | None = None


# ---------------------------------------------------------------------------
# Question body
# ---------------------------------------------------------------------------


class OptionItem(ContractModel):
    """A single choice option."""

    label: Annotated[str, Field(min_length=1, max_length=4)]
    blocks: Annotated[tuple[ContentBlock, ...], Field(min_length=1)]
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class QuestionBody(ContractModel):
    """The stem / options / materials of one question (or sub-question).

    ``parent_question_ref`` is the structural link for composite questions:
    a sub-question points at its parent's ``local_id``. Cycles and
    self-references are rejected.
    """

    local_id: Annotated[str, Field(min_length=1, max_length=100)]
    question_type: QuestionType
    printed_number: Annotated[str, Field(max_length=20)] | None = None
    stem_blocks: Annotated[tuple[ContentBlock, ...], Field(min_length=1)]
    options: tuple[OptionItem, ...] = Field(default_factory=tuple)
    material_ids: tuple[Annotated[str, Field(max_length=200)], ...] = Field(default_factory=tuple)
    #: Composite parent link. ``None`` for a top-level question.
    parent_question_ref: Annotated[str, Field(max_length=100)] | None = None
    #: Sub-question labels this body owns, when it is a composite parent.
    sub_question_ids: tuple[Annotated[str, Field(max_length=100)], ...] = Field(default_factory=tuple)
    unit_type: UnitType = UnitType.STANDALONE_QUESTION
    note: NoteText | None = None


class QuestionContent(ContractModel):
    """A full question payload: bodies + materials + assets.

    The composite tree lives in ``bodies`` via ``parent_question_ref`` /
    ``sub_question_ids``. Flattening for display is a view concern; the
    stored form keeps the tree.
    """

    bodies: Annotated[tuple[QuestionBody, ...], Field(min_length=1)]
    materials: tuple[Material, ...] = Field(default_factory=tuple)
    assets: tuple[Asset, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _check_tree(self) -> "QuestionContent":
        ids = [b.local_id for b in self.bodies]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate local_id in bodies")
        known = set(ids)
        material_ids = {m.material_id for m in self.materials}
        if len(material_ids) != len(self.materials):
            raise ValueError("duplicate material_id")
        asset_ids = [a.asset_id for a in self.assets]
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("duplicate asset_id")

        by_id = {b.local_id: b for b in self.bodies}
        for body in self.bodies:
            if body.parent_question_ref is not None:
                if body.parent_question_ref not in known:
                    raise ValueError(
                        f"body {body.local_id} references unknown parent "
                        f"{body.parent_question_ref}"
                    )
                if body.parent_question_ref == body.local_id:
                    raise ValueError(f"body {body.local_id} is its own parent")
            for sub in body.sub_question_ids:
                if sub not in known:
                    raise ValueError(
                        f"body {body.local_id} references unknown sub {sub}"
                    )
                if sub == body.local_id:
                    raise ValueError(f"body {body.local_id} lists itself as sub")
            for mid in body.material_ids:
                if mid not in material_ids:
                    raise ValueError(
                        f"body {body.local_id} references unknown material {mid}"
                    )

        # Cycle check on parent links.
        for body in self.bodies:
            seen = {body.local_id}
            cursor: str | None = body.parent_question_ref
            while cursor is not None:
                if cursor in seen:
                    raise ValueError(f"parent cycle involving {body.local_id}")
                seen.add(cursor)
                cursor = by_id[cursor].parent_question_ref

        # Parent/child consistency: if A lists B as sub, B must point back.
        for body in self.bodies:
            for sub in body.sub_question_ids:
                child = by_id[sub]
                if child.parent_question_ref != body.local_id:
                    raise ValueError(
                        f"body {body.local_id} lists {sub} as sub, but "
                        f"{sub} parent is {child.parent_question_ref}"
                    )
        return self

    def tree(self) -> dict[str, list[str]]:
        """Return parent → sub-question ids for composite bodies."""
        return {
            b.local_id: list(b.sub_question_ids)
            for b in self.bodies
            if b.sub_question_ids
        }


__all__ = [
    "Asset",
    "BBox",
    "ChemicalBlock",
    "ContentBlock",
    "ImageBlock",
    "Material",
    "MaterialRef",
    "MathBlock",
    "OptionItem",
    "QuestionBody",
    "QuestionContent",
    "TableCell",
    "TableBlock",
    "TextBlock",
    "content_block_adapter",
]
