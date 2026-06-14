from app.services.llm_service import get_llm_service
from app.services.metadata_service import get_metadata_service

SCHEMA_RECALL_PROMPT = """你是一个数据库Schema匹配专家。根据用户的问题，从提供的数据库表和字段中，选出与问题最相关的表和字段。

## 数据库Schema信息
{schema_info}

## 用户问题
{question}

## 要求
1. 根据问题选择最相关的表和字段
2. 识别表之间的关联关系，填写 likely_joins
3. [PK] 标记的是主键，[FK → 表.字段] 标记的是外键
4. 字段后的"同义词"是用户可能使用的口语化表述

请返回JSON格式：
{{
    "tables": [
        {{
            "table_name": "表名",
            "reason": "选择原因",
            "columns": ["字段1", "字段2"]
        }}
    ],
    "likely_joins": [
        {{"left": "表1.字段", "right": "表2.字段", "reason": "关联原因"}}
    ]
}}
只返回JSON，不要其他内容。
"""


async def schema_recall_node(state: dict) -> dict:
    """Schema 召回节点：从元数据中召回相关表和字段."""
    llm = get_llm_service()
    meta_svc = get_metadata_service()
    question = state.get("enhanced_query") or state.get("question", "")
    datasource_id = state.get("datasource_id")
    agent_id = state.get("agent_id")

    if not datasource_id:
        return {"relevant_tables": [], "relevant_columns": [], "semantic_models": [], "likely_joins": []}

    # 获取全部表元数据
    tables = await meta_svc.get_tables(datasource_id)
    if not tables:
        return {"relevant_tables": [], "relevant_columns": [], "semantic_models": [], "likely_joins": []}

    # 构建 schema 信息 (包含 PK/FK/同义词)
    schema_parts = []
    all_columns = {}
    for t in tables:
        cols = await meta_svc.get_columns(t.id)
        all_columns[t.id] = cols
        col_desc = []
        for c in cols:
            desc = f"    {c.column_name} ({c.data_type})"
            # 主键/外键标注
            if c.is_primary_key:
                desc += " [PK]"
            if c.is_foreign_key and c.foreign_key_ref:
                desc += f" [FK → {c.foreign_key_ref}]"
            # 注释
            if c.column_comment:
                desc += f" - {c.column_comment}"
            # 业务名
            if c.business_name:
                desc += f" [业务名:{c.business_name}]"
            # 同义词
            if c.synonyms:
                desc += f" [同义词:{c.synonyms}]"
            col_desc.append(desc)
        table_desc = f"表名: {t.table_name}"
        if t.table_comment:
            table_desc += f" - {t.table_comment}"
        if t.business_name:
            table_desc += f" [业务名:{t.business_name}]"
        schema_parts.append(f"{table_desc}\n" + "\n".join(col_desc))

    schema_info = "\n\n".join(schema_parts)

    messages = [
        {"role": "system", "content": SCHEMA_RECALL_PROMPT.format(
            schema_info=schema_info, question=question
        )},
        {"role": "user", "content": question},
    ]

    response = await llm.achat(messages)

    import json

    try:
        result = json.loads(response.strip())
    except (json.JSONDecodeError, AttributeError):
        result = {"tables": [{"table_name": t.table_name, "reason": "", "columns": []} for t in tables[:3]]}

    # 收集相关表和字段
    relevant_tables = []
    relevant_columns = []
    table_name_map = {t.table_name: t for t in tables}

    for t_info in result.get("tables", []):
        tname = t_info.get("table_name", "")
        if tname in table_name_map:
            table_obj = table_name_map[tname]
            relevant_tables.append({
                "table_name": tname,
                "table_comment": table_obj.table_comment,
                "business_name": table_obj.business_name,
                "reason": t_info.get("reason", ""),
            })
            for col in all_columns.get(table_obj.id, []):
                if not t_info.get("columns") or col.column_name in t_info["columns"]:
                    relevant_columns.append({
                        "table_name": tname,
                        "column_name": col.column_name,
                        "data_type": col.data_type,
                        "column_comment": col.column_comment,
                        "business_name": col.business_name,
                    })

    # 获取语义模型
    semantic_models = []
    if agent_id:
        sm_list = await meta_svc.get_semantic_models(agent_id)
        relevant_table_names = {t["table_name"] for t in relevant_tables}
        for sm in sm_list:
            if sm.table_name in relevant_table_names:
                semantic_models.append({
                    "table_name": sm.table_name,
                    "column_name": sm.column_name,
                    "business_name": sm.business_name,
                    "synonyms": sm.synonyms,
                    "description": sm.description,
                })

    likely_joins = result.get("likely_joins", [])

    return {
        "relevant_tables": relevant_tables,
        "relevant_columns": relevant_columns,
        "semantic_models": semantic_models,
        "likely_joins": likely_joins,
    }
