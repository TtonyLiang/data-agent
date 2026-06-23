"""应用配置 —— Pydantic Settings 集中管理所有环境变量和默认值。

Settings 类通过 pydantic-settings 从 .env 文件和环境变量读取配置。
所有配置都有合理的默认值,开发环境开箱即用。

配置分组:
- LLM:大语言模型连接(Base URL / API Key / Model)。
- Embedding:向量模型连接。
- MySQL:业务数据库和管理数据库连接。
- Milvus:向量数据库连接。
- RAG/召回:数据定位阈值、向量召回参数。
- LLM 运行时:缓存开关、日志截断长度。
- App:应用主机/端口、鉴权、CORS、限流。
- Phase3:Python 执行器后端和资源限制。

生产安全校验(``validate_startup_safety``):
debug=False 时,缺少 ADMIN_API_KEY、SECRET_ENCRYPTION_KEY 或仍使用默认 MySQL 密码
会拒绝启动。
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用全局配置 —— 从 .env 文件和环境变量读取。"""

    # ============================================================
    # LLM 大语言模型
    # ============================================================
    llm_provider: str = "ollama"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "qwen3:14b"

    # ============================================================
    # Embedding 向量模型
    # ============================================================
    embedding_base_url: str = "https://api.deepseek.com/v1"
    embedding_api_key: str = ""
    embedding_model: str = "embedding-3"

    # ============================================================
    # MySQL 业务数据库(存放业务数据)
    # ============================================================
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = "root"
    mysql_database: str = "business_db"

    # ============================================================
    # MySQL 管理数据库(存放配置、元数据、会话历史)
    # ============================================================
    management_mysql_host: str = "127.0.0.1"
    management_mysql_port: int = 3306
    management_mysql_user: str = "root"
    management_mysql_password: str = "root"
    management_mysql_database: str = "dataquery_agent"

    # ============================================================
    # Milvus 向量数据库
    # ============================================================
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19530
    milvus_uri: str = "./data/milvus.db"
    milvus_collection: str = "dataquery_knowledge"

    # ============================================================
    # RAG / 数据定位召回参数
    # ============================================================
    embedding_dimension: int = 1024
    rag_top_k: int = 5
    rag_score_threshold: float = 0.3
    schema_recall_max_tables: int = 6
    schema_recall_required_score_ratio: float = 0.35
    schema_recall_optional_score_ratio: float = 0.15
    schema_recall_max_columns: int = 24
    nl2sql_schema_context_max_tables: int = 6
    nl2sql_schema_context_max_columns: int = 32

    # ============================================================
    # LLM 运行时控制
    # ============================================================
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

    # ============================================================
    # 应用配置
    # ============================================================
    app_host: str = "0.0.0.0"
    app_port: int = 4400
    debug: bool = True
    admin_api_key: str = ""
    jwt_secret_key: str = ""
    secret_encryption_key: str = ""
    initial_admin_username: str = ""
    initial_admin_password: str = ""
    initial_admin_password_hash: str = ""
    cors_allowed_origins: list[str] = [
        "http://localhost:4399",
        "http://127.0.0.1:4399",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    api_rate_limit_per_minute: int = 120
    chat_stream_max_concurrent: int = 8
    mysql_connect_timeout_seconds: int = 10
    mysql_query_timeout_seconds: int = 30

    # ============================================================
    # Phase 3 Python 执行器
    # ============================================================
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

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_allowed_origins(cls, value):
        """支持逗号分隔的字符串形式(兼容 .env 文件和环境变量)。"""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def validate_startup_safety(self) -> None:
        """生产模式启动安全校验:缺少关键配置时拒绝启动。

        检查项:
        - JWT_SECRET_KEY:用户登录 JWT 密钥。
        - SECRET_ENCRYPTION_KEY:密钥加密密钥。
        - MySQL 密码:不能使用默认 root。
        """
        if self.debug:
            return
        errors = []
        if len(self.jwt_secret_key.strip().encode("utf-8")) < 32:
            errors.append("JWT_SECRET_KEY >= 32 bytes")
        if not self.secret_encryption_key.strip():
            errors.append("SECRET_ENCRYPTION_KEY")
        if self.mysql_password == "root" or self.management_mysql_password == "root":
            errors.append("non-default MySQL passwords")
        if errors:
            raise RuntimeError(
                "生产模式缺少安全配置: " + ", ".join(errors)
            )

    @property
    def business_db_url(self) -> str:
        """业务数据库连接 URL(pymysql 格式,异步时替换为 aiomysql)。"""
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset=utf8mb4"
        )

    @property
    def management_db_url(self) -> str:
        """管理数据库连接 URL(pymysql 格式)。"""
        return (
            f"mysql+pymysql://{self.management_mysql_user}:{self.management_mysql_password}"
            f"@{self.management_mysql_host}:{self.management_mysql_port}"
            f"/{self.management_mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    """返回进程级配置单例(带 lru_cache,进程生命周期内只读取一次)。"""
    return Settings()
