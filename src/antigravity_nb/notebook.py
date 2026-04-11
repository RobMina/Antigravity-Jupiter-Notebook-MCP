from __future__ import annotations

import copy
import datetime
import json
from pathlib import Path
from typing import Any


def _as_lines(source: str | list[str]) -> list[str]:
    if isinstance(source, list):
        return source
    if not source:
        return []
    lines = source.splitlines(keepends=True)
    if source and not lines:
        return [source]
    return lines


def _as_text(source: str | list[str]) -> str:
    if isinstance(source, str):
        return source
    return "".join(source)


class NotebookAdapter:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Notebook not found: {self.path}")
        with self.path.open("r", encoding="utf-8") as f:
            self.data: dict[str, Any] = json.load(f)
        if "cells" not in self.data:
            raise ValueError(f"Not a valid notebook (missing 'cells' key): {self.path}")
        self._original = copy.deepcopy(self.data)
        self._dirty = False
        self._last_mtime = self.path.stat().st_mtime

    def is_stale(self) -> bool:
        if not self.path.exists():
            return False
        return self.path.stat().st_mtime > self._last_mtime

    @property
    def cells(self) -> list[dict[str, Any]]:
        return self.data.get("cells", [])

    @property
    def dirty(self) -> bool:
        return self._dirty or self.data != self._original

    def save(self, path: str | Path | None = None) -> None:
        out_path = Path(path) if path else self.path
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=1, ensure_ascii=False)
            f.write("\n")
        if out_path.resolve() == self.path.resolve():
            self._original = copy.deepcopy(self.data)
            self._dirty = False
            self._last_mtime = self.path.stat().st_mtime

    def checkpoint(self) -> Path:
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_path = self.path.with_name(f"{self.path.stem}.checkpoint_{ts}.ipynb")
        self.save(checkpoint_path)
        return checkpoint_path

    def validate_index(self, index: int) -> None:
        if index < 0 or index >= len(self.cells):
            raise IndexError(f"Cell index {index} out of range 0..{len(self.cells) - 1}")

    def get_cell(self, index: int) -> dict[str, Any]:
        self.validate_index(index)
        return self.cells[index]

    def get_cell_source(self, index: int) -> str:
        return _as_text(self.get_cell(index).get("source", []))

    def update_cell(self, index: int, source: str | list[str]) -> None:
        self.validate_index(index)
        self.cells[index]["source"] = _as_lines(source)
        self._dirty = True

    def insert_cell(self, index: int, cell_type: str = "code", source: str = "") -> None:
        if index < 0 or index > len(self.cells):
            raise IndexError(f"Insert index {index} out of range 0..{len(self.cells)}")
        if cell_type not in {"code", "markdown", "raw"}:
            raise ValueError("cell_type must be one of: code, markdown, raw")

        import uuid
        cell: dict[str, Any] = {
            "id": uuid.uuid4().hex[:8],
            "cell_type": cell_type,
            "metadata": {},
            "source": _as_lines(source),
        }
        if cell_type == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        self.cells.insert(index, cell)
        self._dirty = True

    def delete_cell(self, index: int) -> None:
        self.validate_index(index)
        del self.cells[index]
        self._dirty = True

    def set_cell_outputs(self, index: int, outputs: list[dict[str, Any]], execution_count: int | None) -> None:
        cell = self.get_cell(index)
        if cell.get("cell_type") != "code":
            raise ValueError(f"Cell {index} is not a code cell")
        cell["outputs"] = outputs
        cell["execution_count"] = execution_count
        self._dirty = True

    def clear_outputs(self) -> None:
        for cell in self.cells:
            if cell.get("cell_type") == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
        self._dirty = True

    def stage_map_from_tags(self) -> dict[str, list[int]]:
        stages: dict[str, list[int]] = {}
        for idx, cell in enumerate(self.cells):
            tags = cell.get("metadata", {}).get("tags", [])
            for tag in tags:
                stages.setdefault(tag, []).append(idx)
        return stages
