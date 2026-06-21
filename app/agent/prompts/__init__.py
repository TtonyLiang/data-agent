"""Prompt 文件加载器 —— 从 prompts/ 目录读取 Markdown 格式的系统提示词。

本模块是 prompt 文件的唯一入口。所有节点通过 ``load_prompt("xxx.system.md")``
加载提示词,再通过 ``PromptService.resolve`` 渲染变量后送入 LLM。

设计要点:
- 提示词以 .md 文件形式存放在与本文件同级的 prompts/ 目录下。
- ``lru_cache(maxsize=64)`` 缓存已读取的文件内容,避免重复磁盘 IO;
  若需要热更新(如开发调试),调用 ``load_prompt.cache_clear()`` 清缓存。
- 文件编码统一为 utf-8。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 提示词文件目录:与本 __init__.py 同级的 prompts/ 目录
PROMPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class PromptCatalogItem:
    """Metadata for one default prompt template exposed to the admin console."""

    filename: str
    prompt_key: str
    name: str
    description: str
    node: str


PROMPT_CATALOG: tuple[PromptCatalogItem, ...] = (
    PromptCatalogItem(
        "intent_recognition.system.md",
        "intent_recognition.system",
        "意图识别系统提示词",
        "判断用户是在问数、闲聊还是查询元数据。",
        "intent_recognition",
    ),
    PromptCatalogItem(
        "semantic_enhance.system.md",
        "semantic_enhance.system",
        "语义增强系统提示词",
        "把用户原问改写成更完整、更适合知识召回和查询生成的自然语言问题。",
        "semantic_enhance",
    ),
    PromptCatalogItem(
        "nl2lf_generate.system.md",
        "nl2lf_generate.system",
        "LogicForm 生成系统提示词",
        "将自然语言问题转换为 LogicForm JSON，禁止直接生成 SQL。",
        "nl2lf_generate",
    ),
    PromptCatalogItem(
        "nl2sql_fallback.system.md",
        "nl2sql_fallback.system",
        "NL2SQL 兜底系统提示词",
        "语义层未命中可执行指标时，基于已采集 schema 生成安全 SELECT。",
        "nl2sql_fallback",
    ),
    PromptCatalogItem(
        "phase3_python_generate.system.md",
        "phase3_python_generate.system",
        "Python 分析脚本生成系统提示词",
        "基于 SQL 结果样例、字段画像和分析计划生成受限 Python 分析脚本。",
        "python_generate",
    ),
    PromptCatalogItem(
        "phase3_python_generate.user.md",
        "phase3_python_generate.user",
        "Python 分析脚本生成用户提示词",
        "约束模型只输出可执行 Python 代码。",
        "python_generate",
    ),
    PromptCatalogItem(
        "phase3_python_analyze.system.md",
        "phase3_python_analyze.system",
        "Python 分析结果解释提示词",
        "约束 Python 分析结果应服务于最终报告；当前作为可配置预留模板。",
        "python_analyze",
    ),
    PromptCatalogItem(
        "phase3_report_generator.system.md",
        "phase3_report_generator.system",
        "深度分析报告生成系统提示词",
        "基于用户问题、SQL、Python 分析结果和样例数据生成 Markdown 分析报告。",
        "report_generator",
    ),
    PromptCatalogItem(
        "phase3_report_generator.user.md",
        "phase3_report_generator.user",
        "深度分析报告生成用户提示词",
        "要求模型流式输出完整 Markdown 分析报告。",
        "report_generator",
    ),
)


@lru_cache(maxsize=64)
def load_prompt(filename: str) -> str:
    """读取并缓存一个 prompt 文件的内容。

    参数:
        filename:文件名(不含路径前缀),如 ``"intent_recognition.system.md"``

    返回:
        文件内容(字符串)

    异常:
        FileNotFoundError:文件不存在时抛出
    """
    return (PROMPT_DIR / filename).read_text(encoding="utf-8")


def default_prompt_templates() -> list[dict[str, str]]:
    """Return default prompt templates that should be visible in admin UI."""

    return [
        {
            "prompt_key": item.prompt_key,
            "filename": item.filename,
            "name": item.name,
            "description": item.description,
            "node": item.node,
            "template_text": load_prompt(item.filename),
        }
        for item in PROMPT_CATALOG
    ]
