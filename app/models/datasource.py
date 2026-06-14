from pydantic import BaseModel
from datetime import datetime


class DatasourceConfig(BaseModel):
    id: int | None = None
    agent_id: int
    name: str
    db_type: str = "mysql"
    host: str
    port: int = 3306
    username: str
    password: str
    database_name: str
    status: str = "active"
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasourceCreate(BaseModel):
    agent_id: int
    name: str
    db_type: str = "mysql"
    host: str
    port: int = 3306
    username: str
    password: str
    database_name: str


class TableMeta(BaseModel):
    id: int | None = None
    datasource_id: int
    table_name: str
    table_comment: str | None = ""
    business_name: str | None = ""


class ColumnMeta(BaseModel):
    id: int | None = None
    table_id: int
    column_name: str
    data_type: str
    column_comment: str | None = ""
    business_name: str | None = ""
    synonyms: str | None = ""
    is_primary_key: bool = False
    is_foreign_key: bool = False
    foreign_key_ref: str | None = None
