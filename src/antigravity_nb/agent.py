from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .kernel import AttachedKernelSession, KernelSession, find_running_kernels
from .notebook import NotebookAdapter
from .runner import NotebookRunner

_AnyKernel = KernelSession | AttachedKernelSession


@dataclass
class NotebookContext:
    notebook: NotebookAdapter
    kernel: _AnyKernel
    runner: NotebookRunner


class NotebookToolManager:
    def __init__(self, workspace_root: str | Path = ".", default_kernel: str = "python3") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.default_kernel = default_kernel
        self._contexts: dict[Path, NotebookContext] = {}

    def _resolve_notebook(self, notebook_path: str | Path) -> Path:
        s_path = str(notebook_path)
        if "${workspaceFolder}" in s_path:
            s_path = s_path.replace("${workspaceFolder}", str(self.workspace_root))

        raw = Path(s_path)
        path = raw if raw.is_absolute() else (self.workspace_root / raw)
        resolved = path.resolve()
        if self.workspace_root not in resolved.parents and resolved != self.workspace_root:
            raise PermissionError(f"Notebook path outside workspace: {resolved}")
        if resolved.suffix != ".ipynb":
            raise ValueError(f"Only .ipynb files are allowed: {resolved}")
        return resolved

    def _get_context(self, notebook_path: str | Path, kernel_name: str | None = None) -> NotebookContext:
        path = self._resolve_notebook(notebook_path)
        
        if path in self._contexts:
            ctx = self._contexts[path]
            if ctx.notebook.is_stale():
                ctx.notebook.reload()
                
        if path not in self._contexts:
            notebook = NotebookAdapter(path)
            kernel = KernelSession(notebook, kernel_name=kernel_name or self.default_kernel)
            runner = NotebookRunner(notebook, kernel)
            self._contexts[path] = NotebookContext(notebook=notebook, kernel=kernel, runner=runner)
            
        return self._contexts[path]

    def list_kernels(self) -> dict[str, Any]:
        """Return all running Jupyter kernels found in the runtime directory."""
        kernels = find_running_kernels()
        for k in kernels:
            k.pop("last_modified", None)  # not JSON-serializable as-is
        return {"kernels": kernels}

    def attach_kernel(self, notebook_path: str, kernel_id: str) -> dict[str, Any]:
        """Wire a notebook context to an existing running kernel by its ID.

        After this call, run_cell / run_range will execute on the IDE's kernel,
        sharing all in-memory state (variables, imports, etc.).
        """
        path = self._resolve_notebook(notebook_path)
        kernels = find_running_kernels()
        match = next((k for k in kernels if k["kernel_id"] == kernel_id), None)
        if match is None:
            available = [k["kernel_id"] for k in kernels]
            raise ValueError(
                f"No running kernel with id {kernel_id!r}. "
                f"Call list_kernels to see what is available. "
                f"Found: {available}"
            )

        if path in self._contexts:
            old_kernel = self._contexts[path].kernel
            already_attached = (
                isinstance(old_kernel, AttachedKernelSession)
                and old_kernel.kernel_id == kernel_id
            )
            if not already_attached:
                old_kernel.shutdown()
                notebook = self._contexts[path].notebook
                attached = AttachedKernelSession(match["connection_file"], notebook)
                self._contexts[path] = NotebookContext(
                    notebook=notebook,
                    kernel=attached,
                    runner=NotebookRunner(notebook, attached),
                )
        else:
            notebook = NotebookAdapter(path)
            attached = AttachedKernelSession(match["connection_file"], notebook)
            self._contexts[path] = NotebookContext(
                notebook=notebook,
                kernel=attached,
                runner=NotebookRunner(notebook, attached),
            )

        return {
            "path": str(path),
            "kernel_id": kernel_id,
            "connection_file": match["connection_file"],
            "status": "attached",
        }

    def shutdown_all(self) -> None:
        for ctx in self._contexts.values():
            ctx.kernel.shutdown()
        self._contexts.clear()

    def open_notebook(self, notebook_path: str) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        return {
            "path": str(ctx.notebook.path),
            "cell_count": len(ctx.notebook.cells),
            "stages": ctx.notebook.stage_map_from_tags(),
        }

    def list_cells(self, notebook_path: str, include_source: bool = False, preview_chars: int = 120) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        cells = []
        for i, cell in enumerate(ctx.notebook.cells):
            source = ctx.notebook.get_cell_source(i)
            entry: dict[str, Any] = {
                "index": i,
                "cell_type": cell.get("cell_type"),
                "tags": cell.get("metadata", {}).get("tags", []),
                "preview": source[:preview_chars],
            }
            if include_source:
                entry["source"] = source
            cells.append(entry)
        return {"path": str(ctx.notebook.path), "cells": cells}

    def read_cell(self, notebook_path: str, index: int) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        cell = ctx.notebook.get_cell(index)
        return {
            "path": str(ctx.notebook.path),
            "index": index,
            "cell_type": cell.get("cell_type"),
            "tags": cell.get("metadata", {}).get("tags", []),
            "source": ctx.notebook.get_cell_source(index),
            "execution_count": cell.get("execution_count"),
            "outputs": cell.get("outputs", []),
        }

    def edit_cell(
        self,
        notebook_path: str,
        index: int,
        source: str,
        save: bool = True,
        checkpoint: bool = True,
    ) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        checkpoint_path = None
        if False:#checkpoint:
            checkpoint_path = str(ctx.notebook.checkpoint())
        ctx.notebook.update_cell(index, source)
        if save:
            ctx.notebook.save()
        return {
            "path": str(ctx.notebook.path),
            "index": index,
            "saved": save,
            "checkpoint": checkpoint_path,
        }

    def run_cell(
        self,
        notebook_path: str,
        index: int,
        timeout: int = 120,
        save: bool = True,
        kernel_name: str | None = None,
    ) -> dict[str, Any]:
        ctx = self._get_context(notebook_path, kernel_name=kernel_name)
        ctx.kernel.start()
        result = ctx.runner.run_cell(index, timeout=timeout)
        if save:
            ctx.notebook.save()
        return {
            "path": str(ctx.notebook.path),
            "index": index,
            "execution_count": result.execution_count,
            "error": result.error,
            "outputs": result.outputs,
        }

    def run_range(
        self,
        notebook_path: str,
        start: int,
        end: int,
        timeout: int = 120,
        stop_on_error: bool = True,
        save: bool = True,
        kernel_name: str | None = None,
    ) -> dict[str, Any]:
        ctx = self._get_context(notebook_path, kernel_name=kernel_name)
        ctx.kernel.start()
        summary = ctx.runner.run_range(start, end, timeout=timeout, stop_on_error=stop_on_error)
        if save:
            ctx.notebook.save()
        return {
            "path": str(ctx.notebook.path),
            "executed": summary.executed,
            "failed": summary.failed,
        }

    def run_pipeline(
        self,
        notebook_path: str,
        stage_order: list[str] | None = None,
        timeout: int = 120,
        stop_on_error: bool = True,
        save: bool = True,
        kernel_name: str | None = None,
    ) -> dict[str, Any]:
        ctx = self._get_context(notebook_path, kernel_name=kernel_name)
        ctx.kernel.start()
        summary = ctx.runner.run_pipeline(stage_order=stage_order, timeout=timeout, stop_on_error=stop_on_error)
        if save:
            ctx.notebook.save()
        return {
            "path": str(ctx.notebook.path),
            "stages": {
                name: {"executed": stage.executed, "failed": stage.failed}
                for name, stage in summary.items()
            },
        }

    def insert_cell(
        self,
        notebook_path: str,
        index: int,
        cell_type: str = "code",
        source: str = "",
        save: bool = True,
        checkpoint: bool = False,
    ) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        checkpoint_path = None
        if False:#checkpoint:
            checkpoint_path = str(ctx.notebook.checkpoint())
        ctx.notebook.insert_cell(index, cell_type=cell_type, source=source)
        if save:
            ctx.notebook.save()
        return {
            "path": str(ctx.notebook.path),
            "index": index,
            "cell_type": cell_type,
            "cell_count": len(ctx.notebook.cells),
            "saved": save,
            "checkpoint": checkpoint_path,
        }

    def delete_cell(
        self,
        notebook_path: str,
        index: int,
        save: bool = True,
        checkpoint: bool = True,
    ) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        checkpoint_path = None
        if False:#checkpoint:
            checkpoint_path = str(ctx.notebook.checkpoint())
        ctx.notebook.delete_cell(index)
        if save:
            ctx.notebook.save()
        return {
            "path": str(ctx.notebook.path),
            "index": index,
            "cell_count": len(ctx.notebook.cells),
            "saved": save,
            "checkpoint": checkpoint_path,
        }

    def restart_kernel(self, notebook_path: str) -> dict[str, Any]:
        ctx = self._get_context(notebook_path)
        ctx.kernel.restart()
        return {"path": str(ctx.notebook.path), "status": "restarted"}
