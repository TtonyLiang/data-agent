"""用户反馈 API —— 问数结果的用户评分与备注提交。"""

import json
import logging

from fastapi import APIRouter

from app.db.mysql import get_management_db
from app.models.feedback import FeedbackCreate

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("")
async def submit_feedback(request: FeedbackCreate):
    """提交用户反馈。payload 为上下文快照,供后续评估与迭代。"""
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
    logger.info("feedback submit agent_id=%s rating=%s trace_id=%s",
                request.agent_id, request.rating, request.trace_id)
    return {"id": feedback_id, "message": "反馈已记录"}
