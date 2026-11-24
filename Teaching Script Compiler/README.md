# Teaching Script Compiler

EULER-STYLE-INTERACTIVE-LESSON-PILOT-01 · **Question/Revision → TeachingScript**

本目录是讲题闭环的**教学化层**：只读消费 Question Core 的 published Revision，产出
可验证、可追溯、可按 Revision 版本化的 `TeachingScript`，供 Interactive Lesson 播放。

## 边界（不可越）

| 允许 | 禁止 |
| --- | --- |
| 读取 QCore published Revision（只读事务） | 修改 Question / Revision / 答案 / 解析 / 发布状态 |
| 从官方解析派生教学步骤 | 让 LLM 补造题目条件、答案、公式、图形 |
| 把每个步骤绑定到 source refs | 把教学化内容写回 Question Core |
| 按 revision 缓存并保留旧脚本 | 覆盖旧 Revision 的脚本 |
| 图片 OCR 作为**检索证据** | 用 OCR 结果反向修改题目事实 |

事实源优先级：`Question Core revision payload` > 教学脚本。脚本永远不能成为事实源。

## 结构

```
tsc_compiler/
  config.py       环境与路径（.env.local，本地私有）
  models.py       固定常量 / 缓存键 / 语言与版本
  normalize.py    文本规范化、数学片段切分、数字/LaTeX token、时长估算
  qcore_source.py 只读快照构建（QuestionCoreRepository + read-only txn）
  compiler.py     revision payload → TeachingScript（确定性派生）
  validator.py    schema / refs / targets / assets / answer / 事实新增 校验
  cache.py        revision 隔离的脚本缓存与索引
  photo/          OCR 客户端 + 候选检索 + 分层排序 + fail-closed 决策
  api.py          FastAPI：/api/search/photo、/api/teaching-bundles/...
  cli.py          快照 / 编译 / 校验 / 服务
schema/
  teaching_script.schema.json
tests/
docs/
```

## 快速开始

```powershell
cd "D:\Project\AITutors\Teaching Script Compiler"
python -X utf8 -m tsc_compiler.cli snapshot          # 只读导出 QCore 快照
python -X utf8 -m tsc_compiler.cli compile --all     # 编译 + 校验全部已发布数学题
python -X utf8 -m tsc_compiler.cli serve --port 8820 # 检索/讲题 API
```

依赖：系统 Python 3.12（已有 fastapi / uvicorn / sqlalchemy / psycopg2 / requests /
PyMuPDF / jsonschema）。`requirements.txt` 仅作记录。

## 输出

`data/`（gitignored，含试题内容，绝不提交）：

```
data/qcore/catalog.json          已发布题目目录（检索用）
data/qcore/bundles/<qid>.json    每题 revision 快照（含答案/解析/资产）
data/scripts/<qid>/<rid>/...     按 revision 隔离的 TeachingScript 缓存
data/photo/<search_id>/          拍照检索原始 OCR 与候选证据
```

## 数据安全

- 连接串只来自 `QCORE_DATABASE_URL` / `.env.local`，不进仓库、不进报告。
- 快照构建使用 `default_transaction_read_only=on`，任何写入由 PostgreSQL 直接拒绝。
- 本目录不写生产库；`data/` 全部为 pilot 派生数据。
