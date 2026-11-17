# -*- coding: utf-8 -*-
"""测试夹具迁移（G3-B B2 / P-07 契约）：旧 manifest → 结构声明注入。

Mapper 主路径已退出二次识别（split_sub_segments 降 audit-only，无正则兜底），
历史 manifest 映射会显式 ``input_contract_gap``。既有回归测试使用封存旧 manifest，
其被测行为是答案/归属/冲突等，与结构声明来源无关——本模块在**夹具侧**把已退役
正则路径的切点合成进 ``sub_questions``/``materials`` 声明（形态=旧 mapper 消费
的同一份切分），使断言原样保留。

只允许测试夹具调用；生产 mapper **不得** import 本模块。
"""

from __future__ import annotations


def inject_legacy_structure(manifest: dict, lines: list[str]) -> dict:
    """为缺 ``sub_questions`` 的 composite 单元合成结构声明（原地修改并返回）。

    合成口径 = 已退役正则路径（``split_sub_segments``）的切点：
    - ``materials[]``：material_lines → 单材料实体（id 同旧 ``{base}-material``）；
    - ``sub_questions[]``：逐正则切段（id 同旧 local_id ``{base}-s{i}``），层级平铺，
      ``materials_used`` = 全部材料（复现旧「统一挂载」的可见结果）。
    已有声明的单元不触碰。
    """
    from strict_adapter.extract import split_sub_segments

    for u in manifest.get("units") or []:
        if u.get("unit_type") != "composite_question":
            continue
        if u.get("sub_questions") is not None:
            continue
        base = str(u.get("unit_id", "u")).lower()
        qrange = u.get("questions_lines")
        if not qrange:
            continue  # 交由 mapper 的既有错误路径处理
        mrange = u.get("material_lines")
        mats = []
        if mrange:
            mats.append({
                "material_id": f"{base}-material",
                "label": None,
                "line_start": mrange[0],
                "line_end": mrange[1],
            })
        u["materials"] = mats
        skip = [tuple(mrange)] if mrange else []
        try:
            segs, _leads = split_sub_segments(lines, qrange[0], qrange[1], skip)
        except Exception:
            segs = []
        u["sub_questions"] = [
            {
                "sub_id": f"{base}-s{i + 1}",
                "label": lb,
                "label_kind": "sub_label",
                "parent_sub_id": None,
                "order": i + 1,
                "line_start": s,
                "line_end": e,
                "materials_used": [m["material_id"] for m in mats],
                "answer_refs": [],
                "figure_refs": [],
                "answer_entry_count": 1,
                "uncertainty": None,
            }
            for i, (lb, s, e) in enumerate(segs)
        ]
    return manifest
