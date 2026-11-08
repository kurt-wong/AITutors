# AITutor Infrastructure

统一管理 AITutor 项目的三项基础设施：PostgreSQL、MinIO、Redis。
所有服务只绑定本机（127.0.0.1），敏感配置来自本地 `.env`（不入 Git）。

## 服务与固定配置

| 服务 | 容器名 | 镜像（固定版本） | 端口（仅本机） | Volume（固定名） |
|---|---|---|---|---|
| PostgreSQL | `Aitutor-postgresql` | `postgres:16.15` | `127.0.0.1:55432:5432` | `aitutor_postgresql_data` |
| MinIO | `Aitutor-minio` | `quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z` | `127.0.0.1:59000:9000`（API）、`127.0.0.1:59001:9001`（Console） | `aitutor_minio_data` |
| Redis | `Aitutor-redis` | `redis:8.10.1-alpine` | `127.0.0.1:56379:6379` | `aitutor_redis_data` |

- Volume 名在 `docker-compose.yml` 中以 `name:` 固定，不会被加 compose 项目前缀。
- 三个服务同属 Docker 网络 `aitutor_net`。
- 容器重启策略：`unless-stopped`。
- 三个服务均配置 Docker HEALTHCHECK（PG `pg_isready`、MinIO `/minio/health/live`、Redis `PING`）。

### 镜像版本说明

- PostgreSQL 使用官方 `postgres:16.15`（固定补丁版本，不用 `latest`）。
- MinIO 固定为 `RELEASE.2025-09-07T16-13-09Z`（MinIO 官方 quay.io 镜像，与本机已验证可运行的版本一致）。
  该镜像内自带 `/usr/bin/curl`，健康检查用 `curl -f http://localhost:9000/minio/health/live`
  （已对该镜像实测；镜像本身不带 HEALTHCHECK，由 compose 显式配置）。
  注意：当前网络环境下 `quay.io` 无法重新拉取（unauthorized），该固定 tag 指向本机已验证的同一镜像层。
- Redis 使用 `redis:8.10.1-alpine`（固定版本，不用浮动 `alpine`/`latest`）。

## 配置密钥

1. 复制 `.env.example` 为 `.env`，替换全部占位值。
2. `.env` 已被根 `.gitignore` 排除，禁止提交。
3. `.env.example` 只含变量名与占位值，被 `!Infrastructure/.env.example` 显式保留追踪。

变量：

| 变量 | 用途 |
|---|---|
| `POSTGRES_BOOTSTRAP_PASSWORD` | PG 容器初始化超级用户（仅初始化用，不是应用账号，不入仓库） |
| `QCORE_APP_PASSWORD` | 应用角色 `qcore_app` 的密码 |
| `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` | MinIO 根凭据 |
| `REDIS_PASSWORD` | Redis `requirepass` |

## PostgreSQL 数据库与权限

初始化脚本 `initdb/01-init-qcore.sh`（仅在空数据卷首次启动时执行）创建：

- 角色 `qcore_app`：`NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT`（应用连接账号）。
- 数据库 `qcore_dev_test`：业务/测试库，OWNER `qcore_app`。
- 数据库 `qcore_dev_test_migrate`：Migration 专用测试库，OWNER `qcore_app`（预创建，测试不建库/删库）。

迁移权限通过数据库所有权解决；**不给应用账号 SUPERUSER/CREATEDB**。
`postgres` 超级用户仅用于容器初始化，不出现在应用连接串中。

## 部署与管理

```bash
cd D:\Project\AITutors\Infrastructure
docker compose up -d
docker compose ps          # 三个服务应为 healthy
docker compose logs -f
docker compose down        # 停止（保留 Volume）
```

验证健康：

```bash
docker inspect Aitutor-postgresql Aitutor-minio Aitutor-redis --format "{{.Name}} {{.State.Health.Status}}"
```

## Question Core 测试环境变量

`Question Core` 的集成测试只读取以下两个环境变量（缺一明确失败，无隐式回退）：

| 变量 | 指向 |
|---|---|
| `QCORE_TEST_DATABASE_URL` | `postgresql+psycopg2://qcore_app:<密码>@127.0.0.1:55432/qcore_dev_test` |
| `QCORE_MIGRATION_TEST_DATABASE_URL` | `postgresql+psycopg2://qcore_app:<密码>@127.0.0.1:55432/qcore_dev_test_migrate` |

密码取自 `Infrastructure/.env` 的 `QCORE_APP_PASSWORD`，不要写入任何提交文件。
