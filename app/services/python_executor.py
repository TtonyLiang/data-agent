from __future__ import annotations

import ast
import json
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol


class PythonExecutionError(RuntimeError):
    pass


@dataclass
class PythonExecutionResult:
    ok: bool
    stdout: str
    stderr: str
    payload: dict[str, Any]


class PythonExecutor(Protocol):
    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        ...


class RestrictedLocalPythonExecutor:
    """开发模式安全执行器：只读输入、临时目录、超时、内存限制和导入白名单。"""

    ALLOWED_MODULES = {
        "json",
        "math",
        "statistics",
        "collections",
        "datetime",
        "decimal",
        "itertools",
        "numpy",
        "pandas",
    }

    def __init__(self, timeout_seconds: int = 15, memory_mb: int = 512):
        self.timeout_seconds = timeout_seconds
        self.memory_bytes = memory_mb * 1024 * 1024

    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        self._validate_code(code)
        with tempfile.TemporaryDirectory(prefix="wenqu-analysis-") as tmpdir:
            input_path = os.path.join(tmpdir, "input.json")
            script_path = os.path.join(tmpdir, "analysis.py")
            with open(input_path, "w", encoding="utf-8") as fh:
                json.dump({"rows": rows}, fh, ensure_ascii=False)
            with open(script_path, "w", encoding="utf-8") as fh:
                fh.write(self._wrap_code(code, input_path))

            proc = subprocess.run(
                [sys.executable, "-I", script_path],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                preexec_fn=self._limit_resources if hasattr(os, "fork") else None,
                check=False,
            )

        payload: dict[str, Any] = {}
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise PythonExecutionError(f"Python 分析输出不是合法 JSON: {exc}") from exc
        return PythonExecutionResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            payload=payload,
        )

    def _validate_code(self, code: str) -> None:
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise PythonExecutionError(f"Python 代码语法错误: {exc}") from exc

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._assert_allowed_module(alias.name)
            elif isinstance(node, ast.ImportFrom):
                self._assert_allowed_module(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in {"open", "exec", "eval", "compile", "__import__"}:
                    raise PythonExecutionError(f"Python 分析代码禁止调用 {node.func.id}")
            elif isinstance(node, ast.Attribute):
                if node.attr in {"system", "popen", "remove", "unlink", "rmdir", "mkdir"}:
                    raise PythonExecutionError(f"Python 分析代码禁止访问危险属性 {node.attr}")

    def _assert_allowed_module(self, module: str) -> None:
        root = module.split(".", 1)[0]
        if root not in self.ALLOWED_MODULES:
            raise PythonExecutionError(f"Python 分析代码禁止导入模块: {module}")

    def _wrap_code(self, code: str, input_path: str) -> str:
        return (
            "import json\n"
            f"with open({input_path!r}, 'r', encoding='utf-8') as _fh:\n"
            "    _input = json.load(_fh)\n"
            "rows = _input.get('rows', [])\n"
            f"{code}\n"
        )

    def _limit_resources(self) -> None:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (self.memory_bytes, self.memory_bytes))
        except (OSError, ValueError):
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (self.timeout_seconds, self.timeout_seconds + 1))
        except (OSError, ValueError):
            pass


_python_executor: PythonExecutor | None = None


def get_python_executor() -> PythonExecutor:
    global _python_executor
    if _python_executor is None:
        _python_executor = RestrictedLocalPythonExecutor()
    return _python_executor
