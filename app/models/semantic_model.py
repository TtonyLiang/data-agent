from pydantic import BaseModel


class SemanticModelEntry(BaseModel):
    agent_id: int
    table_name: str
    column_name: str
    business_name: str
    synonyms: str = ""
    description: str = ""
    data_type: str | None = None
