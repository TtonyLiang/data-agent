# Agent Prompts

这个目录管理问数链路中固定的默认提示词种子。应用启动迁移会把这里登记在 `PROMPT_CATALOG` 中的模板播种到管理库 `prompt_template`，管理台「系统参数 / Prompt 模板」会展示这些默认值，管理员可以直接修改。

运行时仍通过 `PromptService.resolve(prompt_key, default_template, ...)` 解析：优先使用管理库中最匹配的 active 模板；管理库缺失或模板变量渲染失败时，才回退到本目录文件默认值。

## Prompt 清单

| 文件 | Prompt Key | 使用节点 | 说明 |
| --- | --- | --- | --- |
| `intent_recognition.system.md` | `intent_recognition.system` | `intent_recognition` | 识别数据问答、闲聊、元数据查询 |
| `semantic_enhance.system.md` | `semantic_enhance.system` | `semantic_enhance` | 将用户原问改写成更完整的业务自然语言 |
| `nl2lf_generate.system.md` | `nl2lf_generate.system` | `nl2lf_generate` | 将自然语言转换成 LogicForm JSON |
| `nl2sql_fallback.system.md` | `nl2sql_fallback.system` | `nl2sql_fallback` | 语义层未命中时基于已采集 schema 生成安全 SQL |
| `phase3_python_generate.system.md` | `phase3_python_generate.system` | `python_generate` | 生成只处理 SQL 结果集的安全 Python 分析脚本 |
| `phase3_python_generate.user.md` | `phase3_python_generate.user` | `python_generate` | 约束模型只输出可执行 Python 代码 |
| `phase3_python_analyze.system.md` | `phase3_python_analyze.system` | `python_analyze` | 记录 Python 分析结果语义约束，当前节点不直接调用模型 |
| `phase3_report_generator.system.md` | `phase3_report_generator.system` | `report_generator` | 基于 SQL 与 Python 分析生成 Markdown 报告 |
| `phase3_report_generator.user.md` | `phase3_report_generator.user` | `report_generator` | 要求模型流式输出完整 Markdown 报告 |

## 维护约定

- 新增会调用大模型的节点时，默认提示词优先放在本目录，不在节点代码里写大段字符串。
- 新增 prompt 文件后，同步在 `app/agent/prompts/__init__.py` 的 `PROMPT_CATALOG` 登记，否则不会自动出现在管理台默认列表。
- system prompt 文件名建议和 `prompt_key` 对齐，例如 `xxx.system.md` 对应 `xxx.system`。
- 需要动态变量的模板使用 Python `str.format` 语法；JSON 示例中的 `{` 和 `}` 需要写成 `{{` 和 `}}`。
- 代码里可以保留短小的业务文案、错误提示和确定性规则，但大模型角色、任务、输出格式约束应放在这里。
- Python 兜底分析脚本不放在节点代码或 prompt 目录中，统一维护在 `app/agent/python_templates/`。
