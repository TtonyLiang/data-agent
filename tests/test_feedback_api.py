import json

import pytest
from pydantic import ValidationError

from app.api import feedback as feedback_api
from app.models.feedback import FeedbackCreate
from app.models.user import PublicUser


ADMIN_USER = PublicUser(id=1, username="admin", role="admin", status="active")


class RecordingFeedbackDB:
    def __init__(self):
        self.inserts: list[tuple[str, dict | None]] = []

    async def execute_insert(self, sql: str, params: dict | None = None):
        self.inserts.append((sql, params))
        return 12


@pytest.mark.asyncio
async def test_submit_feedback_records_validated_payload(monkeypatch):
    db = RecordingFeedbackDB()
    monkeypatch.setattr(feedback_api, "get_management_db", lambda: db)

    response = await feedback_api.submit_feedback(
        FeedbackCreate(
            agent_id=3,
            session_id="session-1",
            trace_id="trace-1",
            rating="negative",
            comment="答案口径不对",
            payload={"question": "前五呢", "expected": "按笔数排序"},
        ),
        current_user=ADMIN_USER,
    )

    _, params = db.inserts[0]
    assert response == {"id": 12, "message": "反馈已记录"}
    assert params["user_id"] == 1
    assert params["agent_id"] == 3
    assert params["session_id"] == "session-1"
    assert params["trace_id"] == "trace-1"
    assert params["rating"] == "negative"
    assert params["comment"] == "答案口径不对"
    assert json.loads(params["payload"]) == {"question": "前五呢", "expected": "按笔数排序"}


def test_feedback_rating_is_restricted():
    with pytest.raises(ValidationError):
        FeedbackCreate(agent_id=1, rating="confused")
