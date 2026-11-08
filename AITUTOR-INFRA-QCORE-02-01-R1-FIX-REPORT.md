# AITUTOR-INFRA-QCORE-02-01-R1-FIX 执行报告

执行方：MIMO ｜ 独立审查方：DSH ｜ 任务性质：基础设施重建 + 已有持久化实现定点修复

## 最终裁决（先给结论）

**PASS**

十项完成定义逐条达成：旧三容器及专属 Volume 已按授权清除（实际名称对账见 A）；三个新容器以固定版本镜像、精确 Volume 名、仅 127.0.0.1 端口部署且全部 healthy；PostgreSQL 为独立实例 + 非超级用户应用角色；四项核心缺陷全部修复且由数据库约束/触发器直接保证；测试连接零注册表、零隐式回退、零建库删库；377 项测试全部通过（279 契约 + 29 单元 + 69 集成）；Schema Hash 与 Golden 零变化；未修改 DeepTutor/Preprocessing；未提交/推送/清理 Git。

---

## A. 基础设施重建

### A.1 旧资源清理（名称对账）

旧三容器同属旧 V3 的 `backend` Compose 项目（`com.docker.compose.project.config_files = D:\Project\AITutors-v3\backend\docker-compose.yml`）。
**注意任务书中的 `postgres_data`/`minio_data` 是 Compose 逻辑名，实际 Docker Volume 带项目前缀**：

| 旧资源 | 实际名称 | 实际 ID | 镜像 | 挂载 Volume（实际名） | 处置 |
|---|---|---|---|---|---|
| 旧 PostgreSQL 容器 | `aitutor-postgres` | `3e6925d691a8f532…` | `pgvector/pgvector:pg16` | `backend_postgres_data` → `/var/lib/postgresql/data` | 已停止并删除 |
| 旧 MinIO 容器 | `aitutor-minio` | `82740e2cdbe5c328…` | `quay.io/minio/minio:latest`（实际 RELEASE.2025-09-07T16-13-09Z） | `backend_minio_data` → `/data` | 已停止并删除 |
| 旧 Redis 容器 | `aitutor-redis` | `0402bfa7c9692bbd…` | `redis:alpine`（Redis v8.10.1） | **无任何 Volume（Mounts=[]）** | 已停止并删除 |
| 旧 PostgreSQL Volume | **`backend_postgres_data`** | created 2026-09-15，label project=backend | — | 仅 `aitutor-postgres` 使用 | 已删除 |
| 旧 MinIO Volume | **`backend_minio_data`** | created 2026-09-15，label project=backend | — | 仅 `aitutor-minio` 使用 | 已删除 |
| 旧 Redis Volume | **不存在**（旧 Redis 无专属 Volume，无删除对象） | — | — | — | 不适用 |

**Volume 归属核查（删除前）**：`docker ps -a --filter volume=backend_postgres_data` → 仅 `aitutor-postgres`；
`--filter volume=backend_minio_data` → 仅 `aitutor-minio`。均为旧 V3 专属，无其他项目引用，按 Owner 授权删除。

**旧 PostgreSQL 数据库清单（删除前记录，仅确认清理范围）**：共 392 个库——107 个 `aitutors%`、`b2verify_*`/`ml_*`/`t*` 等历史测试库、`qcore_dev_test`、`postgres`、`template0/1`。Owner 已授权随旧 Volume 全部删除，未做备份/迁移。

**删除后复查**：`docker ps -a` 仅剩 `hermes`（`68138842c882`，nousresearch/hermes-agent，**未触碰**）；`docker volume ls` 中 `backend_postgres_data`/`backend_minio_data` 已消失；未执行任何 `docker system prune`/`docker volume prune`/无差别删除。

### A.2 新资源部署

| 检查项 | 结果 | 证据 |
|---|---|---|
| 旧 PostgreSQL 容器清理 | ✅ 已删除 | ID `3e6925d691a8…` 已不存在（`docker ps -a`） |
| 旧 PostgreSQL Volume 清理 | ✅ 已删除 | `backend_postgres_data` 不在 `docker volume ls` |
| 旧 MinIO 容器清理 | ✅ 已删除 | ID `82740e2cdbe5…` 已不存在 |
| 旧 MinIO Volume 清理 | ✅ 已删除 | `backend_minio_data` 不在 `docker volume ls` |
| 旧 Redis 容器清理 | ✅ 已删除 | ID `0402bfa7c969…` 已不存在 |
| 旧 Redis Volume 清理 | 无对象 | 旧 Redis 无 Volume（inspect `Mounts=[]`） |
| 新 PostgreSQL 容器 | ✅ `Aitutor-postgresql` | ID `13880d91727fe816…`，镜像 `postgres:16.15`，healthy |
| 新 PostgreSQL Volume | ✅ `aitutor_postgresql_data` | inspect Name 精确匹配（compose `name:` 固定，无项目前缀） |
| 新 MinIO 容器 | ✅ `Aitutor-minio` | ID `7a1de49da875…`，镜像 `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`，healthy |
| 新 MinIO Volume | ✅ `aitutor_minio_data` | inspect `/data` ← `aitutor_minio_data` |
| 新 Redis 容器 | ✅ `Aitutor-redis` | ID `3a667b682356…`，镜像 `redis:8.10.1-alpine`，healthy |
| 新 Redis Volume | ✅ `aitutor_redis_data` | inspect `/data` ← `aitutor_redis_data` |
| 三项服务健康检查 | ✅ 全部 healthy | `docker inspect … {{.State.Health.Status}}` = healthy×3；PG `pg_isready -U qcore_app -d qcore_dev_test`、MinIO `curl -f http://localhost:9000/minio/health/live`（实测镜像内有 `/usr/bin/curl`）、Redis `PING`→`PONG` |
| 端口绑定 | ✅ 仅 127.0.0.1 | PG `127.0.0.1:55432->5432`、MinIO `127.0.0.1:59000->9000` + `127.0.0.1:59001->9001`、Redis `127.0.0.1:56379->6379`（docker ps/inspect HostIp 均为 `127.0.0.1`；旧容器均为 `0.0.0.0`，为明确差异） |
| 密钥安全 | ✅ | 全部来自 `Infrastructure/.env`（生成后不入 Git、不出报告）；`.env.example` 仅占位值；Redis 密码经容器环境变量传入 `exec redis-server --requirepass "$REDIS_PASSWORD"`，不落在命令行字面量 |

**固定镜像版本**（旧栈为 `latest`/`alpine` 浮动标签，新栈全部钉死）：

- PostgreSQL：`postgres:16.15`（Docker Hub 官方，已实际拉取）。
- MinIO：`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`（官方镜像的确定 Release）。
  本机网络下 quay.io 不可重新拉取（unauthorized），该固定 tag 指向本机已验证可运行的同一镜像
  （ID `69b2ec208575`，release 标签经镜像 label 确认），README 已记录该维护状态；不使用浮动 `latest`。
- Redis：`redis:8.10.1-alpine`（已实际拉取，`redis-server --version` = 8.10.1）。

**环境事件（透明披露）**：任务固定端口 55432 落入 Windows WinNAT 动态保留区间（55374–55473），
Docker 初始绑定失败。经 Owner 批准 UAC 提权执行 `net stop winnat` → 绑定成功 → `net start winnat`
（可逆、影响系统 NAT 数秒，已恢复）。端口最终保持任务书固定值 55432，未做任何变通。

**Compose 统一管理**：`Infrastructure/docker-compose.yml`（项目 `aitutor-infra`）管理三服务；
Volume 以 `name:` 精确固定；统一网络 `aitutor_net`；`restart: unless-stopped`；三项 HEALTHCHECK；
`.env.example` 变量名+占位值；根 `.gitignore` 增加 `!Infrastructure/.env.example` 反忽略
（修复既有 `.env.*` 连带忽略问题——已验证 `git status` 中 `.env.example` 可见、`.env` 被忽略）。

## B. PostgreSQL 权限和隔离

| 项 | 结果 | 证据 |
|---|---|---|
| 新容器 ID | `13880d91727fe8169261be74f733ee74c58057077fbec9426fb37fe65dec6346` | docker inspect（≠ 旧 `3e6925d…`） |
| PostgreSQL 版本 | `PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2)` | `SELECT version()` |
| Volume 名 | `aitutor_postgresql_data` | inspect Mounts（≠ 旧 `backend_postgres_data`） |
| 端口映射 | `{"5432/tcp":[{"HostIp":"127.0.0.1","HostPort":"55432"}]}` | inspect HostConfig.PortBindings |
| 数据库名称 | `current_database() = qcore_dev_test`（另有预创建 `qcore_dev_test_migrate`） | SQL |
| 应用用户 | `current_user = qcore_app` | SQL |
| SUPERUSER | **false** | `SELECT rolsuper FROM pg_roles WHERE rolname='qcore_app'` |
| CREATEDB | **false** | `rolcreatedb` |
| CREATEROLE | **false** | `rolcreaterole` |
| 新旧隔离 | 新实例仅含 `postgres/qcore_dev_test/qcore_dev_test_migrate/template0/1`；**`aitutors%` 库计数 = 0**（旧 V3 指纹为 392 库） | SQL |
| 是否连接旧 V3 实例 | **否**。旧实例已随旧 Volume 删除；测试侧 `safety.verify_test_target` 强制校验 端口=55432、用户=qcore_app、库名白名单、PG 16.x、服务端零 `aitutors*` 库，任一不符即失败 | tests/persistence/integration/safety.py |

初始化设计：`initdb/01-init-qcore.sh` 由 bootstrap 超级用户（`POSTGRES_USER=postgres`，仅初始化用、不入仓库、不作应用连接账号）创建 `qcore_app`
（`NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`）及两个数据库（OWNER `qcore_app`）。Migration 权限经**数据库所有权**解决，未授予任何特权。

## C. 四项核心缺陷修复

### C.1 Candidate 幂等键（P0-2）

**设计**：唯一约束由 `UNIQUE(idempotency_key)` 改为 **`UNIQUE(idempotency_key, adapter_version)`**（`uq_candidate_key_version`）；
查询接口改为 `get_candidate_by_key(idempotency_key, adapter_version)`（版本参数必填）。

**adapter_version IS NULL 的明确处理**：该列在 0001 即为 `NOT NULL`（契约 `IngestionIdentity.adapter_version`
要求 `min_length=1`），NULL 版本**无法进入唯一键**——PostgreSQL "NULL 互不相等" 的默认语义被 NOT NULL 约束整体消除，
不依赖也不留下歧义。有专门测试证明 NULL 插入被数据库直接拒绝。

**测试结果**（tests/persistence/integration/test_pg_idempotency.py，7 项全过）：

1. 相同 key+相同 version → `DuplicateCandidateError` ✅（仅 1 行落库）
2. 相同 key+不同 version → 两条共存 ✅
3. 两条记录 ingestion_run_id 不同 ✅
4. 新版本不覆盖旧版本（旧记录逐字段不变）✅
5. 查询按版本精确区分（含错误版本 → NotFoundError）✅
6. NULL 版本 → 数据库 NOT NULL 拒绝 ✅
7. 唯一约束与 Repository 行为一致（raw SQL 同样被 `uq_candidate_key_version` 拒绝）✅

### C.2 Revision 内容不可变与 State History（P1）

**设计**：Revision 内容不可变维持全列 UPDATE/DELETE 触发器（`qcore_revisions_immutable`）；
**当前生命周期状态唯一权威为追加式 `qcore_state_history`**，由最新有效 StateSnapshot 派生。
`qcore_revisions` 上的 `review_state`/`publication_state`/`completeness` 仅为创建时快照投影，不冒充当前状态、不作为当前状态读取依据。

**新增受控方法**（repository.py）：`append_state_snapshot`（追加，位置递增，校验 revision 归属）、
`get_current_state`（仅读 history）、`get_revision_current_state`（仅读 history，无记录时回退创建时快照并文档化）、`list_state_history`。

**测试结果**（test_pg_state_history.py，7 项全过）：

1. 创建初始 `not_ready` StateSnapshot ✅  2. 追加 `approved` StateSnapshot ✅
3. 当前状态读取 = `approved` ✅  4. 历史仍保留 `not_ready`（[not_ready, approved]，position 0,1）✅
5. Revision payload 不变 ✅  6. content_hash 不变 ✅  7. 答案/解析/证据/内容全字段不变 ✅
8. 直接 UPDATE 被数据库拒绝 ✅  9. 直接 DELETE 被数据库拒绝 ✅

**权威来源证明**：history 追加 approved 后，`qcore_revisions` 行上 `review_state` 仍为 `not_ready`（创建快照），
而 `get_current_state` 返回 `approved`——当前状态确由 history 派生，而非投影列。

### C.3 Question / Revision 复合外键（P1）

**设计**：`qcore_revisions` 增加 `UNIQUE(question_id, revision_id)`（`uq_revision_question_ref`）；
`qcore_question_instances` 增加复合外键 `fk_instance_revision_pair (question_id, revision_id) → qcore_revisions(question_id, revision_id)`。
非法组合（Question A + Question B 的 Revision）由**数据库约束直接拒绝**，不依赖 Python 校验。

**测试结果**（test_pg_pairing_fk.py，8 项全过）：

1. Q_A+rev_A 允许 ✅  2. Q_B+rev_B 允许 ✅
3. Q_A+rev_B：**raw SQL 直插被 `fk_instance_revision_pair` 拒绝**（绕过全部 Python 检查的证明）✅
4. 非法组合写入失败后整事务回滚（组合写中第三个问题的聚合连同非法 Instance 全部回滚，预存两题不受影响）✅
5. Repository 正常聚合读写不受影响 ✅

**Instance occurrence**（8.4）：自然键 `uq_instance_slot (question_id, source_document_id, ordinal)` 保留；
`printed_number` 仅为展示信息（改 printed_number 重插同样被拒）；相同位置重复导入不产生重复 Instance（专门测试）✅；
本轮未实现 Instance 修订历史/自动合并/自动重关联。

### C.4 Migration 链路

**0001 未做任何修改**；四项修复位于新增 **`4b7c1d2e9a01`（0002, head）**，保留 `1230cc4692f1 → 4b7c1d2e9a01` 可审计链路
（含 downgrade 对称回收）。0002 内容：幂等唯一键替换（含旧约束 `qcore_candidates_idempotency_key_key` 的显式删除）、
`uq_revision_question_ref`、`fk_instance_revision_pair`。

## D. 可复现性

- **`requirements-persistence.txt`**（新增）：`SQLAlchemy==2.0.50`、`alembic==1.18.4`、`psycopg2-binary==2.9.12`、
  `pytest==9.0.3`、`pydantic==2.13.4`、`jsonschema==4.26.0`（Python 3.12，纯同步栈，**未引入 asyncpg**）。
  实际运行环境即上述版本（pip list 核对一致）。
- **测试环境变量**：集成测试只读 `QCORE_TEST_DATABASE_URL`；Migration 测试只读 `QCORE_MIGRATION_TEST_DATABASE_URL`
  （指向预创建的 `qcore_dev_test_migrate`）。两者已在用户级环境持久化（值含密码，不在此展示），缺失即 `pytest.fail`。
- **Windows 注册表依赖**：**已彻底移除**。`tests/persistence/**` 全文检索 `winreg|HKEY|registry` 仅剩 conftest
  docstring 的"不读注册表"声明；无任何读取代码、无 `QCORE_PG_*` 回退（config 单元测试中的 `QCORE_PG_*` 是
  显式传入 `from_env(dict)` 的夹具数据，不读环境、不连接）。
- **隐式回退**：零。无默认连接、无自动推断、无 template1（迁移测试源码含专项断言扫描：无 `CREATE DATABASE`/
  `DROP DATABASE`/`template1`，本文件自身除外）。
- **误连旧库**：不可能。旧实例已物理删除；`safety.verify_test_target` 在任何 Migration/DDL/写入**之前**校验
  端口 55432 / 用户 qcore_app / 库名白名单 / PG 16 / 服务端零 `aitutors*` 库；测试进程零建库/删库能力
  （`qcore_app` 无 CREATEDB）。

## E. 完整测试结果

| 测试类别 | 通过 | 失败 | 错误 |
|---|---|---|---|
| QCORE-01 契约测试 | 279 | 0 | 0 |
| 持久化单元测试 | 29 | 0 | 0 |
| PostgreSQL 集成测试（不含 Migration） | 63 | 0 | 0 |
| Migration 测试 | 6 | 0 | 0 |
| **合计** | **377** | **0** | **0** |

- 命令与原始输出：`python -m pytest tests -q --junitxml=results_r1fix_full.xml`（377 passed in 30.68s）、
  `python -m pytest tests --ignore=tests/persistence -q --junitxml=results_r1fix_contract.xml`（279 passed）。
  JUnit 产物位于 `Question Core/results_r1fix_*.xml`（保留完整原始输出）。
- 任务 11.2 清单 21 项全部有对应测试，含：空库 Migration、重复执行保数据、Candidate 双入口、版本幂等、NULL 规则、
  Revision 不可变、State History 追加、当前状态读取、复合外键、聚合读写、9 种 Typed Answer、Evidence、
  EvidenceConflict、Composite、Table、Asset、Material、事务回滚、Engine 重建后数据仍在（11.3 持久性验证：
  写入完整聚合 → `engine.dispose()` → 新建 Engine → 重读 → 与原对象全等且 content_hash 一致）。
- 全部为真实 PostgreSQL 集成测试，无 SQLite/Mock 替代。

## F. 契约完整性

- **Schema Hash**：`0cba7f5a0c0f85bb024bbb99fda381f2a20e0e4a783390a1e4b3710a601a4f14`，与基线完全一致。
- **Golden snapshots**：零变化（`git status` 中 `question_core/golden/**`、`schema/**`、`contracts/**` 无任何 M 条目）。
- **契约目录 diff**：无。45 个契约模型、JSON Schema、Contract Manifest 原样未动。
- **原有 279 项测试**：全部通过，预期结果未因持久化修改。

## G. Git 与文件状态（未提交、未推送）

| 范围 | 状态 |
|---|---|
| AITutors 根仓库 | `M .gitignore`（本轮唯一根仓库改动：+`!Infrastructure/.env.example`）；`?? Infrastructure/`（4 个交付文件+initdb）；`?? Question Core/{QCORA-02-01-REPORT.md, alembic.ini, migrations/, pytest.ini, question_core/persistence/, requirements-persistence.txt, tests/persistence/}` |
| Question Core 文件变化 | 新增 `question_core/persistence/`（7 文件）、`migrations/`（0001 未改 + 新增 0002 + env.py 严格化 + 模板）、`tests/persistence/`（含重写的 integration conftest/迁移测试与三个新增修复测试文件）、`requirements-persistence.txt`；修改 `models.py`/`repository.py`（定点修复）；**contracts/golden/schema 零变化** |
| Infrastructure 文件变化 | 全新：`docker-compose.yml`、`.env.example`（可追踪）、`README.md`、`initdb/01-init-qcore.sh`；`.env`（本地生成、被忽略、不入 Git） |
| DeepTutor Submodule | 指针未动（`e774c891f…` 与索引一致）；工作区仅遗留 lock/pytest 临时目录（先前轮次产物，本轮未触碰） |
| Preprocessing Submodule | 指针未动（`fb21cf780…`）；工作区存在**先前 SECURITY-01 轮次**的未提交改动（.gitignore/log.md/bugs.md/prd.md/ocr_service/batch_convert_pdf.py/scripts/pac_ocr_runner.py 等），**非本轮产生**，按 Git 保护规则原样保留 |
| 自动提交/推送/清理 | 无。全部仅工作区变更，等待 Owner/DSH 验收后再决定处置 |

## H. 未实施（按任务书暂缓，不包装为已完成）

RevisionImmutabilityError 分类优化、health_check 异常体系重构、asyncpg、Instance 修订历史、
Candidate DB 级不可变触发器、身份去重、Embedding、FastAPI、Adapter、DeepTutor 集成、
Approval/Publication 服务、前端、V3 迁移、MinIO Asset 业务适配器、Redis 业务集成。
本轮结束即停止，不自动启动 QCORE-02-02。
