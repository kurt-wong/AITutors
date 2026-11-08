"""学生 API 可见性控制测试（合成聚合，不连库）。"""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from question_core.contracts.v1 import (  # noqa: E402
    Completeness,
    PublicationState,
    QuestionAggregate,
    QuestionContent,
    QuestionBody,
    QuestionIdentity,
    QuestionInstance,
    Revision,
    SingleChoiceAnswer,
    StateSnapshot,
    TextBlock,
    Visibility,
    publish_revision,
    approve_revision,
)
from strict_adapter.student_api import (  # noqa: E402
    build_student_detail,
    build_student_list,
    create_student_app,
    field_visible,
)


def _aggregate(answer_vis: str, published: bool):
    qid, rid = uuid4(), uuid4()
    content = QuestionContent(
        bodies=(
            QuestionBody(
                local_id="q",
                question_type="single_choice",
                stem_blocks=(TextBlock(text="题干内容"),),
            ),
        )
    )
    ans = SingleChoiceAnswer(
        answer_value="A",
        answer_display="A",
        completeness="full",
        evidence_kind="answer_lines",
        visibility=answer_vis,
    )
    from question_core.contracts.v1 import canonical_content_hash

    expl = (TextBlock(text="解析内容"),)
    ch = canonical_content_hash(content, ans, *expl)
    snap = StateSnapshot(
        revision_id=rid,
        content_hash=ch,
        completeness=Completeness.COMPLETE,
        review="pending_review",
        publication="unpublished",
    )
    if published:
        snap = approve_revision(snap, approved_by="t", content_hash=ch)
        snap = publish_revision(snap, acted_by="t", content_hash=ch)
    rev = Revision.create(
        question_id=qid,
        revision_id=rid,
        revision_number=1,
        question_type="single_choice",
        content=content,
        answers=(ans,),
        explanation_blocks=expl,
        answer_visibility=answer_vis,
        explanation_visibility="review_only",
        state=snap,
    )
    inst = QuestionInstance(
        question_id=qid, revision_id=rid, source_document_id="paper", ordinal=1
    )
    return QuestionAggregate(
        identity=QuestionIdentity(question_id=qid),
        revisions=(rev,),
        instances=(inst,),
        state_history=(snap,),
    )


class TestFieldVisible:
    def test_matrix(self):
        assert field_visible("review_only", False) is False
        assert field_visible("review_only", True) is False
        assert field_visible("student_after_submit", False) is False
        assert field_visible("student_after_submit", True) is True
        assert field_visible("public", False) is True
        assert field_visible("public", True) is True


class TestStudentViews:
    def test_unpublished_invisible(self):
        agg = _aggregate("review_only", published=False)
        assert build_student_detail(agg, submitted=False) is None
        assert build_student_list([agg]) == []

    def test_published_review_only_hides_answers(self):
        agg = _aggregate("review_only", published=True)
        detail = build_student_detail(agg, submitted=False)
        assert detail is not None
        assert detail["content"]["bodies"][0]["stem_blocks"][0]["text"] == "题干内容"
        assert detail["answer_visible"] is False
        assert detail["answers"] == []
        assert detail["explanation_blocks"] == []
        assert detail["explanation_visible"] is False

    def test_after_submit_reveals_answer_only_after_submit(self):
        agg = _aggregate("student_after_submit", published=True)
        before = build_student_detail(agg, submitted=False)
        after = build_student_detail(agg, submitted=True)
        assert before["answers"] == []
        assert after["answer_visible"] is True
        assert after["answers"][0]["answer_value"] == "A"

    def test_public_answer_visible_immediately(self):
        agg = _aggregate("public", published=True)
        detail = build_student_detail(agg, submitted=False)
        assert detail["answer_visible"] is True
        assert detail["answers"][0]["answer_value"] == "A"

    def test_no_internal_fields_in_detail(self):
        agg = _aggregate("public", published=True)
        detail = build_student_detail(agg, submitted=True)
        blob = str(detail)
        for token in ("idempotency", "ingestion", "raw_value", "identity_fingerprint"):
            assert token not in blob


class TestStudentApp:
    def test_list_and_detail_routes(self):
        from fastapi.testclient import TestClient

        pub = _aggregate("review_only", published=True)
        unpub = _aggregate("review_only", published=False)
        app = create_student_app(lambda: [pub, unpub])
        client = TestClient(app)

        r = client.get("/student/questions")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1

        pid = body["questions"][0]["question_id"]
        r = client.get(f"/student/questions/{pid}")
        assert r.status_code == 200
        assert r.json()["answers"] == []

        uid = str(unpub.identity.question_id)
        r = client.get(f"/student/questions/{uid}")
        assert r.status_code == 404

        r = client.get(f"/student/questions/{pid}?submitted=true")
        assert r.status_code == 200
        assert r.json()["answers"] == []
