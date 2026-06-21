"""Python 安全执行器 —— 受限环境执行统计分析脚本。

PythonExecutor 负责 Phase 3 深度分析阶段的 Python 脚本执行。

安全边界:
- ``RestrictedLocalPythonExecutor``:开发模式,子进程执行 + AST 校验 + 资源限制。
- ``WorkerPythonExecutor``:轻量 worker 后端,通过 HTTP 调用隔离执行。
- ``HighIsolationPythonExecutor``:高安全后端,支持 Docker/containerd/Firecracker。

AST 校验(``_validate_code``):
- 只允许白名单模块(json/math/statistics/pandas 等)。
- 禁止 open/exec/eval/compile/__import__ 等危险调用。
- 禁止 __xxx 属性和 system/popen/kill 等危险属性。

资源限制:
- 超时:默认 15 秒(python_executor_timeout_seconds)。
- 内存:默认 512MB(python_executor_memory_mb)。
- 工作目录:临时目录,执行完自动清理。

执行器选择由 ``python_executor_backend`` 配置决定:
- ``local``:RestrictedLocalPythonExecutor(开发默认)
- ``worker``:WorkerPythonExecutor
- ``docker``/``containerd``/``firecracker``/``container``:HighIsolationPythonExecutor
"""

from __future__ import annotations

import ast
import json
import logging
import os
import resource
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class PythonExecutionError(RuntimeError):
    """Python 执行器异常。"""


@dataclass
class PythonExecutionResult:
    """执行结果 —— ok=True 表示成功,payload 为 JSON 输出。"""

    ok: bool
    stdout: str
    stderr: str
    payload: dict[str, Any]


class PythonExecutor(Protocol):
    """执行器协议 —— 所有后端必须实现 execute 方法。"""

    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult: ...


class RestrictedLocalPythonExecutor:
    """开发模式安全执行器 —— 子进程执行 + AST 校验 + 资源限制。

    安全措施:
    1. AST 校验:只允许白名单模块和安全函数。
    2. 子进程执行:python -I(隔离模式),工作目录为临时目录。
    3. 资源限制(RLIMIT_AS/RLIMIT_CPU):防止内存溢出和 CPU 无限占用。
    4. 输入/输出通过 JSON 文件传递,脚本必须 print(json.dumps(...)) 输出。
    """

    # 模块白名单:只允许标准库中安全的模块和 pandas/numpy
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
        """在受限子进程中执行 Python 分析脚本。

        流程:AST 校验 → 写入临时文件 → 子进程执行 → 解析 JSON 输出。
        """
        logger.info("python executor execute rows=%s code_chars=%s", len(rows), len(code or ""))
        self._validate_code(code)

        with tempfile.TemporaryDirectory(prefix="wenqu-analysis-") as tmpdir:
            input_path = os.path.join(tmpdir, "input.json")
            script_path = os.path.join(tmpdir, "analysis.py")
            with open(input_path, "w", encoding="utf-8") as fh:
                json.dump({"rows": rows}, fh, ensure_ascii=False)
            with open(script_path, "w", encoding="utf-8") as fh:
                fh.write(self._wrap_code(code, input_path))

            try:
                proc = subprocess.run(
                    [sys.executable, "-I", script_path],
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    preexec_fn=self._limit_resources if hasattr(os, "fork") else None,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                logger.warning("python executor TIMEOUT after %ss", self.timeout_seconds)
                raise PythonExecutionError(f"Python 分析超时({self.timeout_seconds}秒)")

        payload: dict[str, Any] = {}
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                logger.warning("python executor output not valid JSON: %s", exc)
                raise PythonExecutionError(f"Python 分析输出不是合法 JSON: {exc}") from exc

        logger.info(
            "python executor done ok=%s returncode=%s stderr_chars=%s",
            proc.returncode == 0,
            proc.returncode,
            len(proc.stderr or ""),
        )
        return PythonExecutionResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=proc.stderr,
            payload=payload,
        )

    def _validate_code(self, code: str) -> None:
        """AST 校验:只允许白名单模块和安全函数,禁止危险调用。"""
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError) as exc:
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
                if node.attr.startswith("__") or node.attr in {
                    "system",
                    "popen",
                    "remove",
                    "unlink",
                    "rmdir",
                    "mkdir",
                    "getenv",
                    "putenv",
                    "spawn",
                    "fork",
                    "kill",
                }:
                    raise PythonExecutionError(f"Python 分析代码禁止访问危险属性 {node.attr}")

    def _assert_allowed_module(self, module: str) -> None:
        """校验模块是否在白名单内,不在则抛异常。"""
        root = module.split(".", 1)[0]
        if root not in self.ALLOWED_MODULES:
            raise PythonExecutionError(f"Python 分析代码禁止导入模块: {module}")

    def _wrap_code(self, code: str, input_path: str) -> str:
        """把用户代码包装为完整的可执行脚本(注入 JSON 输入读取逻辑)。"""
        return (
            "import json\n"
            f"with open({input_path!r}, 'r', encoding='utf-8') as _fh:\n"
            "    _input = json.load(_fh)\n"
            "rows = _input.get('rows', [])\n"
            f"{code}\n"
        )

    def _limit_resources(self) -> None:
        """设置子进程资源限制(仅 Linux/macOS),防止内存和 CPU 溢出。"""
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
    """轻量 worker 后端 —— 通过 HTTP 调用隔离的 Python 执行服务。"""

    def __init__(self, worker_url: str, timeout_seconds: int = 30):
        self.worker_url = worker_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def execute(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        """通过 HTTP POST 调用 worker 执行脚本。"""
        if not self.worker_url:
            raise PythonExecutionError("Python worker 后端未配置 python_worker_url")
        try:
            response = httpx.post(
                f"{self.worker_url}/execute",
                json={"code": code, "rows": rows},
                timeout=self.timeout_seconds,
            )
        except Exception as exc:
            logger.exception("python worker call failed")
            raise PythonExecutionError(f"Python worker 调用失败: {exc}") from exc
        if response.status_code >= 400:
            logger.warning("python worker error status=%s", response.status_code)
            raise PythonExecutionError(f"Python worker 返回错误: HTTP {response.status_code}")
        payload = response.json()
        return PythonExecutionResult(
            ok=bool(payload.get("ok", True)),
            stdout=str(payload.get("stdout", "")),
            stderr=str(payload.get("stderr", "")),
            payload=payload.get("payload") or {},
        )


class HighIsolationPythonExecutor:
    """高安全执行器 —— 支持 Docker/containerd/Firecracker 三种容器后端。

    每种后端都实现:
    1. 代码写入临时文件(只读挂载到容器)。
    2. 输入通过 JSON 文件传递。
    3. 输出通过 stdout JSON 解析。
    4. 资源限制(内存/CPU/PID)通过容器参数控制。
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
        """根据 backend 类型分发到对应的容器执行逻辑。"""
        if self.backend in {"docker", "containerd", "container"}:
            return self._execute_container(code, rows)
        if self.backend == "firecracker":
            return self._execute_firecracker(code, rows)
        raise PythonExecutionError(f"不支持的高安全执行后端: {self.backend}")

    def _execute_container(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        """Docker/containerd 执行:代码+输入写入临时目录,只读挂载到容器。"""
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
                logger.warning("python container TIMEOUT after %ss", self.timeout_seconds)
                raise PythonExecutionError(f"{self.backend} Python 执行超时") from exc
        return _python_process_result(proc)

    def _container_command(self) -> list[str]:
        """返回容器内执行命令,可自定义。"""
        if self.container_command:
            return self.container_command.split()
        return ["python", "-I", "/work/analysis.py"]

    def _execute_firecracker(self, code: str, rows: list[dict[str, Any]]) -> PythonExecutionResult:
        """Firecracker 执行:代码+输入通过 stdin 传递给 runner。"""
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
            logger.warning("python firecracker TIMEOUT after %ss", self.timeout_seconds)
            raise PythonExecutionError("firecracker Python 执行超时") from exc
        return _python_process_result(proc)


# 全局单例
_python_executor: PythonExecutor | None = None


def get_python_executor() -> PythonExecutor:
    """返回进程级 Python 执行器单例。"""
    global _python_executor
    if _python_executor is None:
        _python_executor = build_python_executor()
    return _python_executor


def build_python_executor() -> PythonExecutor:
    """根据配置构建对应的 Python 执行器。"""
    settings = get_settings()
    backend = (settings.python_executor_backend or "local").lower()

    if backend == "local":
        # 生产环境禁止本地执行器(除非显式允许)
        if not settings.debug and not settings.allow_local_python_executor_in_production:
            raise PythonExecutionError(
                "生产环境禁止使用本地 Python 执行器，请配置 worker/container 后端。"
            )
        logger.info("python executor backend=local timeout=%ss memory=%smb",
                     settings.python_executor_timeout_seconds, settings.python_executor_memory_mb)
        return RestrictedLocalPythonExecutor(
            timeout_seconds=settings.python_executor_timeout_seconds,
            memory_mb=settings.python_executor_memory_mb,
        )

    if backend == "worker":
        logger.info("python executor backend=worker url=%s timeout=%ss",
                     settings.python_worker_url, settings.python_executor_timeout_seconds)
        return WorkerPythonExecutor(
            settings.python_worker_url,
            timeout_seconds=settings.python_executor_timeout_seconds,
        )

    if backend in {"docker", "containerd", "firecracker", "container"}:
        logger.info("python executor backend=%s image=%s timeout=%ss",
                     backend, settings.python_container_image, settings.python_executor_timeout_seconds)
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
    """重置单例(测试用)。"""
    global _python_executor
    _python_executor = None


def _python_process_result(proc: subprocess.CompletedProcess[str]) -> PythonExecutionResult:
    """解析子进程输出为 PythonExecutionResult。"""
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
