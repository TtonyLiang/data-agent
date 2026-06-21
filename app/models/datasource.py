"""数据源数据模型 —— 定义业务库连接配置与采集到的表/字段元数据。

WenQu 中"数据源"特指业务数据库(MySQL)的连接配置,不含语义层信息。
语义层资产(SemanticDomain)会绑定到一个数据源,用于校验物理表/字段是否已采集。

本模块包含两类模型:
1. ``DatasourceConfig`` / ``DatasourceCreate`` / ``DatasourceUpdate``:连接配置。
2. ``TableMeta`` / ``ColumnMeta``:采集到的表与字段元数据,供数据定位与 NL2SQL 使用。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class DatasourceConfig(BaseModel):
    """数据源完整配置 —— 对应 datasource 表的完整行。

    ``password`` 在数据库中以 ``enc:v1:`` 密文存储,读取时由 service 层解密;
    API 出参时会显式 exclude=password,不会把明文密码返回给前端。
    """

    id: int | None = None
    agent_id: int | None = Field(
        default=None,
        description="创建该数据源的智能体(旧字段,新链路通过 agent_datasource 关联表绑定)",
    )
    name: str = Field(description="数据源名称")
    db_type: str = Field(default="mysql", description="数据库类型,当前仅支持 mysql")
    host: str = Field(description="数据库主机地址")
    port: int = Field(default=3306, description="数据库端口")
    username: str = Field(description="数据库用户名")
    password: str = Field(description="数据库密码(密文存储,service 层负责加解密)")
    database_name: str = Field(description="数据库名/schema 名")
    status: str = Field(default="active", description="状态:active/inactive")
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasourceCreate(BaseModel):
    """数据源创建入参 —— 用于 POST /api/datasource/create。

    创建时会自动把 password 加密落盘,并把该数据源绑定到 agent_id 指定的智能体。
    """

    agent_id: int | None = Field(default=None, description="创建后绑定到的智能体")
    name: str = Field(description="数据源名称")
    db_type: str = Field(default="mysql", description="数据库类型")
    host: str = Field(description="数据库主机地址")
    port: int = Field(default=3306, description="数据库端口")
    username: str = Field(description="数据库用户名")
    password: str = Field(description="数据库明文密码,入库前加密")
    database_name: str = Field(description="数据库名")


class DatasourceUpdate(BaseModel):
    """数据源更新入参 —— 用于 PUT /api/datasource/{id}。

    ``password`` 为可选:不传(或传掩码)时保留原密钥,传新值才覆盖。
    这样前端编辑其他字段时不会误清空密码。
    """

    agent_id: int | None = Field(default=None, description="重新绑定到的智能体")
    name: str = Field(description="数据源名称")
    db_type: str = Field(default="mysql", description="数据库类型")
    host: str = Field(description="数据库主机地址")
    port: int = Field(default=3306, description="数据库端口")
    username: str = Field(description="数据库用户名")
    password: str | None = Field(
        default=None,
        description="新密码(明文);为空或掩码时保留原密钥",
    )
    database_name: str = Field(description="数据库名")
    status: str = Field(default="active", description="状态")


class TableMeta(BaseModel):
    """采集到的表元数据 —— 对应 meta_table 表的一行。

    由 ``MetadataService.collect_schema`` 从业务库 information_schema 采集而来,
    作为数据定位与 NL2SQL 兜底的候选表来源。
    """

    id: int | None = None
    datasource_id: int = Field(description="所属数据源")
    table_name: str = Field(description="物理表名")
    table_comment: str | None = Field(default="", description="表注释,提升召回命中率")


class ColumnMeta(BaseModel):
    """采集到的字段元数据 —— 对应 meta_column 表的一行。

    外键信息(``is_foreign_key`` / ``foreign_key_ref``)由数据定位阶段用于
    推导 JOIN Hint,辅助模型理解表间关联。
    """

    id: int | None = None
    table_id: int = Field(description="所属 meta_table 的 id")
    column_name: str = Field(description="物理字段名")
    data_type: str = Field(description="字段数据类型,如 varchar/bigint")
    column_comment: str | None = Field(default="", description="字段注释,提升召回命中率")
    is_primary_key: bool = Field(default=False, description="是否主键")
    is_foreign_key: bool = Field(default=False, description="是否外键")
    foreign_key_ref: str | None = Field(
        default=None,
        description="外键引用,格式 'referenced_table.referenced_column',用于推导 JOIN Hint",
    )
