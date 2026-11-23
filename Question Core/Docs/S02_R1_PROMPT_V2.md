# S02 R1 · Prompt v2 版本锚点（可追溯）

本文件记录 S02 R1「LLM 结构约束最小修复」所用的 Prompt 版本关系。
**不包含试卷原文**：封存 Prompt（含 OCR 试卷文本）按 `.gitignore` 策略不入库，
因此这里只保存“基线指纹 + 最小补丁 + 复现步骤”。

## 版本链

| 项 | 值 |
| --- | --- |
| 基线（封存 v1） | 本地封存文件 `_dsh_tmp/s02_replay/run1/_llm_raw/2023全国II卷新高考真题语文（教师版）(1).20261120-161537.attempt1.prompt.txt` |
| v1 字符数 / 文本口径 SHA-256 | 53,276 字符 / `fcaf04c54273e1eb160a3818769cbb242ecc2bc204cf78b95902abbb72792398` |
| v1 磁盘字节 SHA-256（CRLF） | `dd9ef2960ac82ae96e5b689b02823ece772946e35fc3d41ae3c6fee12458ed27` |
| 补丁 | `S02_R1_PROMPT_V2.diff`（2 处插入、+9 行 / +517 字符，无删除） |
| v2 字符数 / 文本口径 SHA-256 | 53,793 字符 / `4f11d8c1d8c2e6d611520047d537ba48ccf8eadd2ee5cd769c706f5060cce725` |
| v2 磁盘字节 SHA-256（CRLF） | `6b28dcfaaa7e9e1ba9159795ad476e03b846f3f77abbc49a0322573cdeb9b590` |
| 生成参数 | `deepseek-flash`，temperature 0.1，max_tokens 120000，reasoning_effort low，stream+usage |
| 验收证据 | 5/5 生成满足契约（`_dsh/s02_r1_01/r1_llm_runs.json`） |

## 补丁内容（两处约束）

1. **basis 取值收口**：composite 的 basis 默认只写 `["A"]`；只有 `grouping_statements` 中
   `triage=explicit_grouping` 且 `covered_range` 非 null 时，才允许追加 `"B"`。
2. **子问引用必须带子问标签**：`answer_refs` 写成 `(1)#1` 或 `13(1)#1`，禁止只写父题号
   `13#1`；每条 ref 必须与对应 `answers[].slot_id` 逐字相同。

## 复现步骤

1. 取本地封存 v1 Prompt（路径见上；不回填入库）。
2. `git apply` 或按 `S02_R1_PROMPT_V2.diff` 应用补丁。
3. 校验 v2 文本 SHA-256 = `4f11d8c1…c725`。
4. 以表中参数生成，核对 `_dsh/s02_r1_01/r1_llm_runs.json` 的 5 次结果。

## 与代码的关系

- Mapper/选项/图片声明修复见同仓 `Question Core/strict_adapter/mapper.py`
  （提交信息标注 S02 R1）。
- 本 Prompt 版本与 Mapper 修复**共同构成** S02 R1 的可复现版本基线；两者需一并检出。
