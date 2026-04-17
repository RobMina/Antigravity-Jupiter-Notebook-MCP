from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from queue import Empty
from typing import Any

from jupyter_client import KernelManager

from .notebook import NotebookAdapter


def find_running_kernels() -> list[dict[str, Any]]:
    """Return metadata for all running kernels found in the Jupyter runtime directory."""
    from jupyter_core.paths import jupyter_runtime_dir
    runtime_dir = Path(jupyter_runtime_dir())
    if not runtime_dir.exists():
        return []
    kernels: list[dict[str, Any]] = []
    for cf in sorted(runtime_dir.glob("kernel-*.json"), key=os.path.getmtime, reverse=True):
        try:
            data = json.loads(cf.read_text())
            kernel_id = cf.stem.removeprefix("kernel-")
            kernels.append({
                "kernel_id": kernel_id,
                "connection_file": str(cf),
                "last_modified": cf.stat().st_mtime,
                "transport": data.get("transport", "tcp"),
                "ip": data.get("ip", ""),
                "kernel_name": data.get("kernel_name", ""),
            })
        except Exception:
            pass
    return kernels


@dataclass
class ExecutionResult:
    outputs: list[dict[str, Any]]
    execution_count: int | None
    error: dict[str, Any] | None = None


class KernelSession:
    def __init__(self, notebook: NotebookAdapter, kernel_name: str = "python3") -> None:
        self.notebook = notebook
        self.kernel_name = kernel_name
        self.km: KernelManager | None = None
        self.kc = None

    def _discover_venv(self) -> Path | None:
        import os
        from pathlib import Path
        
        current = self.notebook.path.parent.resolve()
        while True:
            venv_path = current / ".venv"
            if venv_path.is_dir():
                return venv_path
            if current.parent == current:
                break
            current = current.parent
        return None

    def start(self) -> None:
        if self.km is not None:
            return
            
        import os
        venv = self._discover_venv()
        env = os.environ.copy()
        if venv:
            # Add venv/share/jupyter to JUPYTER_PATH
            # We set it in os.environ because KernelManager/KernelSpecManager reads it during init
            jupyter_path = venv / "share" / "jupyter"
            if jupyter_path.exists():
                old_jpath = os.environ.get("JUPYTER_PATH", "")
                new_jpath = str(jupyter_path) + (os.pathsep + old_jpath if old_jpath else "")
                os.environ["JUPYTER_PATH"] = new_jpath
                env["JUPYTER_PATH"] = new_jpath
            
            # Add venv/bin to PATH so jupyter can find the kernel executables
            venv_bin = venv / "bin"
            if venv_bin.exists():
                env["PATH"] = str(venv_bin) + os.pathsep + env.get("PATH", "")

        self.km = KernelManager(kernel_name=self.kernel_name)
        
        # Surgically update the kernel's argv to use the absolute path of the discovered venv's python
        if venv and self.km.kernel_spec:
            spec = self.km.kernel_spec
            if spec.argv and (spec.argv[0] == "python" or spec.argv[0] == "python3"):
                python_exe = venv / "bin" / "python"
                if not python_exe.exists():
                    python_exe = venv / "bin" / "python3"
                if python_exe.exists():
                    spec.argv[0] = str(python_exe)

        self.km.start_kernel(env=env, cwd=str(self.notebook.path.parent.resolve()))
        self.kc = self.km.blocking_client()
        self.kc.start_channels()
        try:
            self.kc.wait_for_ready(timeout=30)
        except RuntimeError as exc:
            self.shutdown()
            raise RuntimeError(
                f"Kernel '{self.kernel_name}' failed to start. "
                "Is a matching Jupyter kernel installed? "
                f"(Original error: {exc})"
            ) from exc

    def restart(self) -> None:
        if self.km is None:
            self.start()
            return
        if self.kc is not None:
            self.kc.stop_channels()
        self.km.restart_kernel(now=True)
        self.kc = self.km.blocking_client()
        self.kc.start_channels()
        try:
            self.kc.wait_for_ready(timeout=30)
        except RuntimeError as exc:
            self.shutdown()
            raise RuntimeError(
                f"Kernel '{self.kernel_name}' failed to restart: {exc}"
            ) from exc

    def shutdown(self) -> None:
        if self.kc is not None:
            try:
                self.kc.stop_channels()
            except Exception:
                pass
            self.kc = None
        if self.km is not None:
            try:
                self.km.shutdown_kernel(now=True)
            except Exception:
                pass
            self.km = None

    def execute_cell(self, index: int, timeout: int = 120) -> ExecutionResult:
        cell = self.notebook.get_cell(index)
        if cell.get("cell_type") != "code":
            raise ValueError(f"Cell {index} is not a code cell")

        if self.kc is None:
            self.start()
        assert self.kc is not None

        source = self.notebook.get_cell_source(index)
        msg_id = self.kc.execute(source, store_history=True, allow_stdin=False)
        outputs: list[dict[str, Any]] = []
        execution_count: int | None = None
        error_payload: dict[str, Any] | None = None

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=timeout)
            except Empty as exc:
                raise TimeoutError(f"Timed out while executing cell {index}") from exc

            if msg["parent_header"].get("msg_id") != msg_id:
                continue

            msg_type = msg["msg_type"]
            content = msg["content"]

            if msg_type == "status" and content.get("execution_state") == "idle":
                break
            if msg_type == "execute_input":
                execution_count = content.get("execution_count")
            elif msg_type == "stream":
                outputs.append(
                    {
                        "output_type": "stream",
                        "name": content.get("name", "stdout"),
                        "text": content.get("text", ""),
                    }
                )
            elif msg_type in {"display_data", "execute_result"}:
                payload: dict[str, Any] = {
                    "output_type": msg_type,
                    "data": content.get("data", {}),
                    "metadata": content.get("metadata", {}),
                }
                if msg_type == "execute_result":
                    payload["execution_count"] = content.get("execution_count")
                    execution_count = content.get("execution_count", execution_count)
                outputs.append(payload)
            elif msg_type == "error":
                error_payload = {
                    "output_type": "error",
                    "ename": content.get("ename", ""),
                    "evalue": content.get("evalue", ""),
                    "traceback": content.get("traceback", []),
                }
                outputs.append(error_payload)

        self.notebook.set_cell_outputs(index, outputs, execution_count)
        return ExecutionResult(outputs=outputs, execution_count=execution_count, error=error_payload)


class AttachedKernelSession:
    """Attaches to an already-running Jupyter kernel via its ZMQ connection file.

    Use this to share the kernel that VSCode (or any other client) has already started.
    Does NOT start or stop the kernel — only the original owner should do that.
    """

    def __init__(self, connection_file: str | Path, notebook: NotebookAdapter) -> None:
        self.connection_file = str(connection_file)
        self.notebook = notebook
        self.kc = None
        self._kernel_id: str = Path(connection_file).stem.removeprefix("kernel-")

    @property
    def kernel_id(self) -> str:
        return self._kernel_id

    def start(self) -> None:
        if self.kc is not None:
            return
        from jupyter_client import BlockingKernelClient
        kc = BlockingKernelClient()
        kc.load_connection_file(self.connection_file)
        kc.start_channels()
        try:
            kc.wait_for_ready(timeout=10)
        except RuntimeError as exc:
            kc.stop_channels()
            raise RuntimeError(
                f"Cannot attach to kernel {self._kernel_id}: {exc}. "
                "Is the kernel still running in the IDE?"
            ) from exc
        self.kc = kc

    def restart(self) -> None:
        raise RuntimeError(
            "Cannot restart an attached kernel — restart it from the IDE and then call attach_kernel again."
        )

    def shutdown(self) -> None:
        if self.kc is not None:
            try:
                self.kc.stop_channels()
            except Exception:
                pass
            self.kc = None

    def execute_cell(self, index: int, timeout: int = 120) -> ExecutionResult:
        cell = self.notebook.get_cell(index)
        if cell.get("cell_type") != "code":
            raise ValueError(f"Cell {index} is not a code cell")
        if self.kc is None:
            self.start()
        assert self.kc is not None

        source = self.notebook.get_cell_source(index)
        msg_id = self.kc.execute(source, store_history=True, allow_stdin=False)
        outputs: list[dict[str, Any]] = []
        execution_count: int | None = None
        error_payload: dict[str, Any] | None = None

        while True:
            try:
                msg = self.kc.get_iopub_msg(timeout=timeout)
            except Empty as exc:
                raise TimeoutError(f"Timed out while executing cell {index}") from exc

            if msg["parent_header"].get("msg_id") != msg_id:
                continue

            msg_type = msg["msg_type"]
            content = msg["content"]

            if msg_type == "status" and content.get("execution_state") == "idle":
                break
            if msg_type == "execute_input":
                execution_count = content.get("execution_count")
            elif msg_type == "stream":
                outputs.append({
                    "output_type": "stream",
                    "name": content.get("name", "stdout"),
                    "text": content.get("text", ""),
                })
            elif msg_type in {"display_data", "execute_result"}:
                payload: dict[str, Any] = {
                    "output_type": msg_type,
                    "data": content.get("data", {}),
                    "metadata": content.get("metadata", {}),
                }
                if msg_type == "execute_result":
                    payload["execution_count"] = content.get("execution_count")
                    execution_count = content.get("execution_count", execution_count)
                outputs.append(payload)
            elif msg_type == "error":
                error_payload = {
                    "output_type": "error",
                    "ename": content.get("ename", ""),
                    "evalue": content.get("evalue", ""),
                    "traceback": content.get("traceback", []),
                }
                outputs.append(error_payload)

        self.notebook.set_cell_outputs(index, outputs, execution_count)
        return ExecutionResult(outputs=outputs, execution_count=execution_count, error=error_payload)
