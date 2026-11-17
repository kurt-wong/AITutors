# -*- coding: utf-8 -*-
"""Deployment entrypoint for the existing Student API (Option A, QCORE-DEEPTUTOR-STUDENT-INTEGRATION-01).

职责仅限部署层：
    QuestionCoreRepository（只读聚合） → reader → create_student_app(reader) → uvicorn.run

不改 student_api.py / persistence / repository / state / mapper / schema / visibility /
Answer projection / Asset contract。repository 无 list_aggregates 方法（已核），
故聚合枚举在本入口文件内完成（select question_id + get_question_aggregate），
不向 repository 添加任何方法。

运行（须显式声明目标库：本机用户级 QCORE_DATABASE_URL 默认指向其他库，必须覆盖；
aitutors* 保护库由 config.py 拒绝连接）：
    QCORE_DATABASE_URL=postgresql+psycopg2://<user>:<pass>@127.0.0.1:55432/qcore_g4_final_01 \
        python strict_adapter/student_api_server.py

可选环境变量：QCORE_STUDENT_API_HOST（默认 127.0.0.1）、QCORE_STUDENT_API_PORT（默认 8801）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import UUID

_QC_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(_QC_ROOT), str(_QC_ROOT / "strict_adapter")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _list_question_ids(session) -> list[UUID]:
    from sqlalchemy import text

    rows = session.execute(text("select question_id from qcore_questions order by question_id"))
    return [UUID(str(r[0])) for r in rows]


def main() -> int:
    from question_core.persistence import (
        DatabaseSettings,
        QuestionCoreRepository,
        create_db_engine,
        session_scope,
    )
    from strict_adapter.student_api import create_student_app

    settings = DatabaseSettings.from_env()
    engine = create_db_engine(settings)

    def reader():
        out = []
        with session_scope(engine) as session:
            repo = QuestionCoreRepository(session)
            for qid in _list_question_ids(session):
                out.append(repo.get_question_aggregate(qid))
        return out

    app = create_student_app(reader)

    # 部署层跨源配置（供 DeepTutor web 本地开发源消费）；不触碰路由/响应契约。
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000",
                       "http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    import uvicorn

    host = os.environ.get("QCORE_STUDENT_API_HOST", "127.0.0.1")
    port = int(os.environ.get("QCORE_STUDENT_API_PORT", "8801"))
    print(f"qcore-student-api on http://{host}:{port}  db={settings.dbname}")
    uvicorn.run(app, host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
