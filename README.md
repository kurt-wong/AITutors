# AITutors

AI 考试辅导统一项目仓库。通过 Git Submodule 整合三个子项目，Question Core 作为普通目录纳入根仓库管理。

## 仓库结构

| 目录 | 管理方式 | 远端 | 说明 |
|---|---|---|---|
| `DeepTutor/` | Submodule | [kurt-wong/DeepTutor](https://github.com/kurt-wong/DeepTutor) (Fork) | 学习产品；集成分支 `aitutor/deeptutor-integration` 消费 Preprocessing 产出 |
| `Preprocessing/` | Submodule | [kurt-wong/Aitutors-preprocessing](https://github.com/kurt-wong/Aitutors-preprocessing) | 考试数据生产流水线 |
| `Question Core/` | 普通目录 | 本仓库 | 正式题库核心（契约、Schema、Golden Snapshots、测试） |
| `ARCHIVE/` | 排除 | — | V1/V2/V3 历史项目归档，不入库 |
| `_dsh_review/` | 排除 | — | DSH 审查材料，不入库 |

## Submodule 使用

```bash
# 克隆时包含子模块
git clone --recurse-submodules https://github.com/kurt-wong/AITutors.git

# 或克隆后初始化
git submodule init
git submodule update
```

## 数据安全约束

**考试相关材料（PDF、OCR Markdown、Manifest、试卷图片等）绝不推送 GitHub。**

- Preprocessing 仓库中已有的历史样本文件不再新增。
- Question Core 的 Golden Snapshots 为合成测试数据，不含真实试卷。
- 新增任何文件前请确认不含考试数据。

## 子项目职责

- **DeepTutor** — AI 一对一学习辅导产品，消费 Preprocessing 审核后的 Markdown/Manifest。
- **Preprocessing** — 试卷 OCR、切分、标注、质检、生产 Manifest 的完整数据生产管线。
- **Question Core** — 题库契约层：Schema 定义、候选数据模型、Golden Snapshot 测试。纯 Pydantic v2 + 标准库，无外部依赖。
