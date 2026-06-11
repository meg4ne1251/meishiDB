"""監査ログ append-only 記録 audit.record。"""

import uuid

from sqlalchemy import select

from app.models.audit import AuditLog
from app.services import audit


class _FakeClient:
    host = "203.0.113.7"


class _FakeRequest:
    client = _FakeClient()
    headers = {"user-agent": "pytest-agent/1.0"}


async def test_record_persists_with_request_metadata(db):
    target = uuid.uuid4()
    await audit.record(
        db,
        user_id=None,
        action="test.action",
        request=_FakeRequest(),
        target_type="card",
        target_id=target,
        metadata={"k": "v"},
    )
    await db.commit()

    row = await db.scalar(select(AuditLog).where(AuditLog.action == "test.action"))
    assert row is not None
    assert row.user_id is None
    # target_id は文字列化される
    assert row.target_id == str(target)
    assert row.target_type == "card"
    assert str(row.ip) == "203.0.113.7"
    assert row.user_agent == "pytest-agent/1.0"
    assert row.audit_metadata == {"k": "v"}


async def test_record_without_request_has_no_ip(db):
    await audit.record(db, user_id=None, action="no.request")
    await db.commit()
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "no.request"))
    assert row.ip is None
    assert row.user_agent is None
    assert row.target_id is None


async def test_record_does_not_commit_on_its_own(db):
    # record は commit しない（呼び出し元のトランザクションに乗る）
    await audit.record(db, user_id=None, action="uncommitted")
    # まだ flush/commit していないので別問い合わせでは見えない想定。
    # ここでは rollback して消えることを確認する。
    await db.rollback()
    row = await db.scalar(select(AuditLog).where(AuditLog.action == "uncommitted"))
    assert row is None
