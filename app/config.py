from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3:14b"

    # Embedding
    embedding_base_url: str = "https://api.deepseek.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-3"

    # MySQL 业务数据库
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "root"
    mysql_database: str = "business_db"

    # MySQL 管理数据库
    management_mysql_host: str = "127.0.0.1"
    management_mysql_port: int = 3306
    management_mysql_user: str = "root"
    management_mysql_password: str = "root"
    management_mysql_database: str = "dataquery_agent"

    # Milvus
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_uri: str = "./data/milvus.db"
    milvus_collection: str = "dataquery_knowledge"

    # RAG
    embedding_dimension: int = 1024
    rag_top_k: int = 5
    rag_score_threshold: float = 0.3
    schema_recall_max_tables: int = 6
    schema_recall_max_columns: int = 24
    nl2sql_schema_context_max_tables: int = 6
    nl2sql_schema_context_max_columns: int = 32

    # LLM runtime controls
    llm_cache_enabled: bool = True
    llm_cache_ttl_seconds: int = 300
    llm_cache_max_items: int = 256
    max_llm_prompt_log_chars: int = 8000
    max_reasoning_trace_chars: int = 12000
    max_stream_text_trace_chars: int = 24000
    max_sse_log_value_chars: int = 1200
    detailed_data_logging_enabled: bool = False
    llm_prompt_logging_enabled: bool = True
    sql_sample_logging_enabled: bool = False

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 4400
    debug: bool = True

    # Phase 3 Python executor
    python_executor_backend: str = "local"  # local / worker / container
    python_worker_url: str = ""
    allow_local_python_executor_in_production: bool = False
    python_executor_timeout_seconds: int = 15
    python_executor_memory_mb: int = 512
    python_container_image: str = "python:3.12-slim"
    python_container_cpus: str = "1"
    python_container_command: str = ""
    python_firecracker_runner: str = ""
    python_repair_enabled: bool = True
    python_repair_max_attempts: int = 2
    python_repair_error_chars: int = 2400

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def business_db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def management_db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.management_mysql_user}:{self.management_mysql_password}"
            f"@{self.management_mysql_host}:{self.management_mysql_port}"
            f"/{self.management_mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
