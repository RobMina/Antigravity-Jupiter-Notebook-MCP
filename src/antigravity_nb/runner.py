from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

from .kernel import ExecutionResult, KernelSession
from .notebook import NotebookAdapter

if TYPE_CHECKING:
    from .kernel import AttachedKernelSession


@dataclass
class RunSummary:
    executed: list[int]
    failed: int | None = None


class NotebookRunner:
    def __init__(self, notebook: NotebookAdapter, kernel: KernelSession | AttachedKernelSession) -> None:
        self.notebook = notebook
        self.kernel = kernel

    def run_cell(self, index: int, timeout: int = 120) -> ExecutionResult:
        return self.kernel.execute_cell(index, timeout=timeout)

    def run_range(self, start: int, end: int, timeout: int = 120, stop_on_error: bool = True) -> RunSummary:
        if start > end:
            raise ValueError("start must be <= end")
        executed: list[int] = []
        failed: int | None = None
        for idx in range(start, end + 1):
            cell = self.notebook.get_cell(idx)
            if cell.get("cell_type") != "code":
                continue
            result = self.run_cell(idx, timeout=timeout)
            executed.append(idx)
            if result.error:
                failed = idx
                if stop_on_error:
                    break
        return RunSummary(executed=executed, failed=failed)

    def run_all(self, timeout: int = 120, stop_on_error: bool = True) -> RunSummary:
        if not self.notebook.cells:
            return RunSummary(executed=[])
        return self.run_range(0, len(self.notebook.cells) - 1, timeout=timeout, stop_on_error=stop_on_error)

    def run_pipeline(
        self,
        stages: dict[str, Iterable[int]] | None = None,
        stage_order: list[str] | None = None,
        timeout: int = 120,
        stop_on_error: bool = True,
    ) -> dict[str, RunSummary]:
        stage_map = stages or self.notebook.stage_map_from_tags()
        if not stage_map:
            return {}

        order = stage_order or list(stage_map.keys())
        summary: dict[str, RunSummary] = {}

        for stage_name in order:
            indices = list(stage_map.get(stage_name, []))
            executed: list[int] = []
            failed: int | None = None
            for idx in indices:
                cell = self.notebook.get_cell(idx)
                if cell.get("cell_type") != "code":
                    continue
                result = self.run_cell(idx, timeout=timeout)
                executed.append(idx)
                if result.error:
                    failed = idx
                    if stop_on_error:
                        break
            summary[stage_name] = RunSummary(executed=executed, failed=failed)
            if stop_on_error and failed is not None:
                break

        return summary
