import json

from fastapi import APIRouter

from app.db.mysql import get_management_db
from app.models.feedback import FeedbackCreate

router = APIRouter()


@router.post("")
async def submit_feedback(request: FeedbackCreate):
    feedback_id = await get_management_db().execute_insert(
        "INSERT INTO user_feedback (agent_id, session_id, trace_id, rating, comment, payload) "
        "VALUES (:agent_id, :session_id, :trace_id, :rating, :comment, :payload)",
        {
            "agent_id": request.agent_id,
            "session_id": request.session_id,
            "trace_id": request.trace_id,
            "rating": request.rating,
            "comment": request.comment or "",
            "payload": json.dumps(request.payload or {}, ensure_ascii=False),
        },
    )
    return {"id": feedback_id, "message": "反馈已记录"}
