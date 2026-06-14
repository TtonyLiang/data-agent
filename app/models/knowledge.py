from pydantic import BaseModel
from datetime import datetime


class SemanticModel(BaseModel):
    id: int | None = None
    agent_id: int
    table_name: str
    column_name: str
    business_name: str
    synonyms: str | None = ""
    description: str | None = ""
    data_type: str | None = None


class BusinessKnowledge(BaseModel):
    id: int | None = None
    agent_id: int
    title: str
    content: str
    knowledge_type: str = "definition"
    synonyms: str | None = ""
    is_recall: bool = True


class AgentKnowledge(BaseModel):
    id: int | None = None
    agent_id: int
    title: str
    content: str
    knowledge_type: str = "document"
    chunk_count: int = 0
    created_at: datetime | None = None
