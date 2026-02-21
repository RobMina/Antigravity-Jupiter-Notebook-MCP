from __future__ import annotations

from dataclasses import dataclass
from queue import Empty
from typing import Any

from jupyter_client import KernelManager

from .notebook import NotebookAdapter


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

    def start(self) -> None:
        if self.km is not None:
            return
        self.km = KernelManager(kernel_name=self.kernel_name)
        self.km.start_kernel()
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
