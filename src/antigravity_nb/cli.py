from __future__ import annotations

import argparse
from pathlib import Path

from .agent_server import run_stdio_server
from .kernel import KernelSession
from .notebook import NotebookAdapter
from .runner import NotebookRunner


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="antigravity-nb")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cell = sub.add_parser("run-cell", help="Run one code cell")
    run_cell.add_argument("notebook", type=Path)
    run_cell.add_argument("index", type=int)
    run_cell.add_argument("--kernel", default="python3")
    run_cell.add_argument("--timeout", type=int, default=120)

    run_range = sub.add_parser("run-range", help="Run code cells in [start, end]")
    run_range.add_argument("notebook", type=Path)
    run_range.add_argument("start", type=int)
    run_range.add_argument("end", type=int)
    run_range.add_argument("--kernel", default="python3")
    run_range.add_argument("--timeout", type=int, default=120)
    run_range.add_argument("--continue-on-error", action="store_true")

    run_pipeline = sub.add_parser("run-pipeline", help="Run tag-based pipeline stages")
    run_pipeline.add_argument("notebook", type=Path)
    run_pipeline.add_argument("--kernel", default="python3")
    run_pipeline.add_argument("--timeout", type=int, default=120)
    run_pipeline.add_argument("--continue-on-error", action="store_true")
    run_pipeline.add_argument(
        "--stage",
        action="append",
        default=[],
        help="Stage/tag to run in order; repeat for multiple stages",
    )

    edit_cell = sub.add_parser("edit-cell", help="Edit one cell")
    edit_cell.add_argument("notebook", type=Path)
    edit_cell.add_argument("index", type=int)
    edit_cell.add_argument("--source-file", type=Path, required=True)

    list_stages = sub.add_parser("list-stages", help="List tag-based stages")
    list_stages.add_argument("notebook", type=Path)

    serve_agent = sub.add_parser("serve-agent", help="Run stdio JSON-RPC tool server for Antigravity")
    serve_agent.add_argument("--workspace-root", type=Path, default=Path("."))
    serve_agent.add_argument("--kernel", default="python3")

    return parser


def _run_cell(args: argparse.Namespace) -> int:
    nb = NotebookAdapter(args.notebook)
    ks = KernelSession(nb, kernel_name=args.kernel)
    runner = NotebookRunner(nb, ks)
    try:
        ks.start()
        result = runner.run_cell(args.index, timeout=args.timeout)
        nb.save()
        status = "error" if result.error else "ok"
        print(f"cell={args.index} status={status} execution_count={result.execution_count}")
        return 1 if result.error else 0
    finally:
        ks.shutdown()


def _run_range(args: argparse.Namespace) -> int:
    nb = NotebookAdapter(args.notebook)
    ks = KernelSession(nb, kernel_name=args.kernel)
    runner = NotebookRunner(nb, ks)
    try:
        ks.start()
        summary = runner.run_range(
            args.start,
            args.end,
            timeout=args.timeout,
            stop_on_error=not args.continue_on_error,
        )
        nb.save()
        print(f"executed={summary.executed} failed={summary.failed}")
        return 1 if summary.failed is not None else 0
    finally:
        ks.shutdown()


def _run_pipeline(args: argparse.Namespace) -> int:
    nb = NotebookAdapter(args.notebook)
    ks = KernelSession(nb, kernel_name=args.kernel)
    runner = NotebookRunner(nb, ks)
    try:
        ks.start()
        order = args.stage if args.stage else None
        summary = runner.run_pipeline(
            stage_order=order,
            timeout=args.timeout,
            stop_on_error=not args.continue_on_error,
        )
        nb.save()
        failed_any = False
        for stage_name, stage_summary in summary.items():
            print(f"{stage_name}: executed={stage_summary.executed} failed={stage_summary.failed}")
            if stage_summary.failed is not None:
                failed_any = True
        return 1 if failed_any else 0
    finally:
        ks.shutdown()


def _edit_cell(args: argparse.Namespace) -> int:
    nb = NotebookAdapter(args.notebook)
    source = args.source_file.read_text(encoding="utf-8")
    nb.update_cell(args.index, source)
    nb.save()
    print(f"updated cell {args.index}")
    return 0


def _list_stages(args: argparse.Namespace) -> int:
    nb = NotebookAdapter(args.notebook)
    stage_map = nb.stage_map_from_tags()
    for name, indices in stage_map.items():
        print(f"{name}: {indices}")
    return 0


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "run-cell":
        return _run_cell(args)
    if args.command == "run-range":
        return _run_range(args)
    if args.command == "run-pipeline":
        return _run_pipeline(args)
    if args.command == "edit-cell":
        return _edit_cell(args)
    if args.command == "list-stages":
        return _list_stages(args)
    if args.command == "serve-agent":
        return run_stdio_server(workspace_root=str(args.workspace_root), default_kernel=args.kernel)

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
