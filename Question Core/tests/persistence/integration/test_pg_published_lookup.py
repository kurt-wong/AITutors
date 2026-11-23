# -*- coding: utf-8 -*-
"""Regression: published_revision() must consult state_history, not the
revision's creation-time embedded snapshot.

背景（QCORE-DEEPTUTOR-STUDENT-INTEGRATION-01）：Revision.state 是创建时快照，
因 qcore_revisions 不可变而永不更新；当前生命周期状态的唯一权威是
append-only 的 qcore_state_history（见 persistence.repository 注释）。
修复前 published_revision() 只读 rev.state，合法 approve→publish 的问题
永远无法被 Student API 服务；该路径此前零测试覆盖。

本用例按真实导入流构造：revision 随写入携带 unpublished 创建快照 →
append_state_snapshot 追加 approved/published → 重新 get_question_aggregate()
→ published_revision() 必须命中。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from question_core.contracts.v1 import (
    ApprovalRecord,
    Completeness,
    PublicationRecord,
    PublicationState,
    QuestionAggregate,
    ReviewState,
    StateSnapshot,
)
from question_core.persistence import QuestionCoreRepository, session_scope
from question_core.persistence.serialize import restore_revision

from tests.persistence.synthetic import (
    make_identity,
    make_instance,
    make_rich_revision,
)

pytestmark = pytest.mark.pg

QID = UUID("00000000-0000-4000-8000-000000000a11")
RID = UUID("00000000-0000-4000-8000-000000000b22")


def _published_snapshot(revision) -> StateSnapshot:
    content_hash = revision.content_hash
    approval = ApprovalRecord(
        revision_id=revision.revision_id,
        content_hash=content_hash,
        approved_by="Kurtw",
        approved_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
        confirmed_fields=("content",),
    )
    publication = PublicationRecord(
        revision_id=revision.revision_id,
        content_hash=content_hash,
        state=PublicationState.PUBLISHED,
        acted_by="Kurtw",
        acted_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    return StateSnapshot(
        revision_id=revision.revision_id,
        content_hash=content_hash,
        completeness=Completeness.COMPLETE,
        review=ReviewState.APPROVED,
        publication=PublicationState.PUBLISHED,
        approval=approval,
        publication_record=publication,
    )


class TestPublishedRevisionLookupFromHistory:
    def test_published_revision_found_after_history_publish(self, engine, clean_db):
        revision = make_rich_revision(QID, revision_number=1, revision_id=RID)
        # 随导入写入的创建快照：complete + pending_review + unpublished
        initial = StateSnapshot(
            revision_id=revision.revision_id,
            content_hash=revision.content_hash,
            completeness=Completeness.COMPLETE,
            review=ReviewState.PENDING_REVIEW,
            publication=PublicationState.UNPUBLISHED,
        )
        # 经持久化重水化路径注入创建快照（explanation_blocks 需重水化，
        # 不能裸 model_validate —— 与真实入库路径一致）
        payload = revision.model_dump(mode="json")
        payload["state"] = initial.model_dump(mode="json")
        revision = restore_revision(payload)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(initial,),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        published = _published_snapshot(revision)
        with session_scope(engine) as session:
            QuestionCoreRepository(session).append_state_snapshot(QID, published)

        with session_scope(engine) as session:
            agg = QuestionCoreRepository(session).get_question_aggregate(QID)

        # 重建出的 aggregate：内嵌创建快照仍是 unpublished（不可变事实）
        assert agg.revisions[0].state is not None
        assert agg.revisions[0].state.publication == PublicationState.UNPUBLISHED
        # 但 published_revision() 必须经 state_history 命中
        found = agg.published_revision()
        assert found is not None
        assert found.revision_id == revision.revision_id

    def test_unpublished_question_still_hidden(self, engine, clean_db):
        """负向：只有未发布历史快照的题不得命中（防止修复过宽）。"""
        revision = make_rich_revision(QID, revision_number=1, revision_id=RID)
        initial = StateSnapshot(
            revision_id=revision.revision_id,
            content_hash=revision.content_hash,
            completeness=Completeness.COMPLETE,
            review=ReviewState.PENDING_REVIEW,
            publication=PublicationState.UNPUBLISHED,
        )
        payload = revision.model_dump(mode="json")
        payload["state"] = initial.model_dump(mode="json")
        revision = restore_revision(payload)
        aggregate = QuestionAggregate(
            identity=make_identity(QID),
            revisions=(revision,),
            instances=(make_instance(QID, revision.revision_id),),
            state_history=(initial,),
        )
        with session_scope(engine) as session:
            QuestionCoreRepository(session).save_question_aggregate(aggregate)

        with session_scope(engine) as session:
            agg = QuestionCoreRepository(session).get_question_aggregate(QID)
        assert agg.published_revision() is None
