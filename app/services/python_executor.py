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

import httpx

from app.config import get_settings


class PythonExecutionError(RuntimeError):
    pass


@dataclass
class PythonExecutionResult:
    ok: bool
    stdout: str
    stderr: str
    payload: dict[str, Any]


class PythonExecutor(Protocol):
    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult: ...


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
                if isinstance(node.func, ast.Name) and node.func.id in {
                    "open",
                    "exec",
                    "eval",
                    "compile",
                    "__import__",
                }:
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
            resource.setrlimit(
                resource.RLIMIT_CPU, (self.timeout_seconds, self.timeout_seconds + 1)
            )
        except (OSError, ValueError):
            pass


class WorkerPythonExecutor:
    """Production-oriented lightweight backend: delegate execution to an isolated worker."""

    def __init__(self, worker_url: str, timeout_seconds: int = 30):
        self.worker_url = worker_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        if not self.worker_url:
            raise PythonExecutionError("Python worker 后端未配置 python_worker_url")
        try:
            response = httpx.post(
                f"{self.worker_url}/execute",
                json={"code": code, "rows": rows},
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            raise PythonExecutionError(f"Python worker 调用失败: {exc}") from exc
        if response.status_code >= 400:
            raise PythonExecutionError(f"Python worker 返回错误: HTTP {response.status_code}")
        payload = response.json()
        return PythonExecutionResult(
            ok=bool(payload.get("ok", True)),
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
            payload=payload.get("payload") or {},
        )


class HighIsolationPythonExecutor:
    """High-isolation executor selected by deployment config.

    Docker/containerd can run directly with the configured image. Firecracker is
    exposed through a runner command so production can plug in its own worker
    wrapper without changing the application code.
    """

    def __init__(
        self,
        backend: str,
        image: str = "",
        timeout_seconds: int = 30,
        memory_mb: int = 512,
        cpus: str = "1",
        container_command: str = "",
        firecracker_runner: str = "",
    ):
        self.backend = backend
        self.image = image
        self.timeout_seconds = timeout_seconds
        self.memory_mb = memory_mb
        self.cpus = cpus
        self.container_command = container_command
        self.firecracker_runner = firecracker_runner

    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        if self.backend in {"docker", "containerd", "container"}:
            return self._execute_container(code, rows)
        if self.backend == "firecracker":
            return self._execute_firecracker(code, rows)
        raise PythonExecutionError(f"不支持的高安全执行后端: {self.backend}")

    def _execute_container(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        runtime = "docker" if self.backend in {"docker", "container"} else "nerdctl"
        if not self.image:
            raise PythonExecutionError(
                f"{self.backend} 高安全执行后端缺少 python_container_image 配置"
            )
        RestrictedLocalPythonExecutor()._validate_code(code)
        with tempfile.TemporaryDirectory(prefix="wenqu-container-analysis-") as tmpdir:
            input_path = os.path.join(tmpdir, "input.json")
            script_path = os.path.join(tmpdir, "analysis.py")
            with open(input_path, "w", encoding="utf-8") as fh:
                json.dump({"rows": rows}, fh, ensure_ascii=False)
            with open(script_path, "w", encoding="utf-8") as fh:
                fh.write(RestrictedLocalPythonExecutor()._wrap_code(code, "/work/input.json"))

            command = [
                runtime,
                "run",
                "--rm",
                "--network",
                "none",
                "--cpus",
                str(self.cpus),
                "--memory",
                f"{self.memory_mb}m",
                "--pids-limit",
                "128",
                "-v",
                f"{tmpdir}:/work:ro",
                "-w",
                "/work",
                self.image,
                *self._container_command(),
            ]
            try:
                proc = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise PythonExecutionError(
                    f"{runtime} 命令不存在，请安装或改用 worker 后端。"
                ) from exc
            except subprocess.TimeoutExpired as exc:
                raise PythonExecutionError(f"{self.backend} Python 执行超时") from exc
        return _python_process_result(proc)

    def _container_command(self) -> list[str]:
        if self.container_command:
            return self.container_command.split()
        return ["python", "-I", "/work/analysis.py"]

    def _execute_firecracker(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        if not self.firecracker_runner:
            raise PythonExecutionError(
                "firecracker 高安全执行后端缺少 python_firecracker_runner 配置"
            )
        RestrictedLocalPythonExecutor()._validate_code(code)
        try:
            proc = subprocess.run(
                [self.firecracker_runner],
                input=json.dumps({"code": code, "rows": rows}, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PythonExecutionError(
                "firecracker runner 命令不存在，请检查 python_firecracker_runner。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise PythonExecutionError("firecracker Python 执行超时") from exc
        return _python_process_result(proc)


_python_executor: PythonExecutor | None = None


def get_python_executor() -> PythonExecutor:
    global _python_executor
    if _python_executor is None:
        _python_executor = build_python_executor()
    return _python_executor


def build_python_executor() -> PythonExecutor:
    settings = get_settings()
    backend = (settings.python_executor_backend or "local").lower()
    if backend == "local":
        if not settings.debug and not settings.allow_local_python_executor_in_production:
            raise PythonExecutionError(
                "生产环境禁止使用本地 Python 执行器，请配置 worker/container 后端。"
            )
        return RestrictedLocalPythonExecutor(
            timeout_seconds=settings.python_executor_timeout_seconds,
            memory_mb=settings.python_executor_memory_mb,
        )
    if backend == "worker":
        return WorkerPythonExecutor(
            settings.python_worker_url,
            timeout_seconds=settings.python_executor_timeout_seconds,
        )
    if backend in {"docker", "containerd", "firecracker", "container"}:
        return HighIsolationPythonExecutor(
            backend,
            image=settings.python_container_image,
            timeout_seconds=settings.python_executor_timeout_seconds,
            memory_mb=settings.python_executor_memory_mb,
            cpus=settings.python_container_cpus,
            container_command=settings.python_container_command,
            firecracker_runner=settings.python_firecracker_runner,
        )
    raise PythonExecutionError(f"未知 Python 执行器后端: {backend}")


def reset_python_executor() -> None:
    global _python_executor
    _python_executor = None


def _python_process_result(proc: subprocess.CompletedProcess[str]) -> PythonExecutionResult:
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
