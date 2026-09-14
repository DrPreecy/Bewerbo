from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import WorkflowEngine
from .executors import ExecutorRegistry
from .service import WorkflowService
from .spec_loader import load_workflow_spec
from .storage import JsonStateStore


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a config-driven workflow")
    parser.add_argument("--spec", required=True, help="Path to workflow spec JSON")
    parser.add_argument("--state", required=True, help="Path to state storage JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start")
    start.add_argument("--input", required=True, help="Path to run input JSON")
    start.add_argument("--idempotency-key")
    start.add_argument("--wait", action="store_true", help="Accepted for compatibility; command waits before exiting")
    start.add_argument("--timeout", type=float, default=None, help="Optional wait timeout in seconds")
    for command in ("pause", "cancel", "resume"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("--run-id", required=True)
    rerun = sub.add_parser("rerun-failed")
    rerun.add_argument("--run-id", required=True)
    rerun.add_argument("--wait", action="store_true", help="Accepted for compatibility; command waits before exiting")
    rerun.add_argument("--timeout", type=float, default=None, help="Optional wait timeout in seconds")
    status = sub.add_parser("status")
    status.add_argument("--run-id", required=True)
    sub.add_parser("metrics")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    spec = load_workflow_spec(args.spec)
    store = JsonStateStore(args.state)
    engine = WorkflowEngine(store=store, registry=ExecutorRegistry())
    service = WorkflowService(engine=engine)

    if args.command == "start":
        run = service.start(spec, _read_json(args.input), idempotency_key=args.idempotency_key)
        run = service.wait(run.run_id, timeout=args.timeout)
        print(json.dumps({"run_id": run.run_id, "status": run.status.value}, indent=2))
        return
    if args.command == "pause":
        run = service.pause(args.run_id)
        print(json.dumps({"run_id": run.run_id, "requested_action": run.requested_action}, indent=2))
        return
    if args.command == "cancel":
        run = service.cancel(args.run_id)
        print(json.dumps({"run_id": run.run_id, "requested_action": run.requested_action}, indent=2))
        return
    if args.command == "resume":
        run = service.resume(spec, args.run_id)
        print(json.dumps({"run_id": run.run_id, "status": run.status.value}, indent=2))
        return
    if args.command == "rerun-failed":
        run = service.rerun_failed_step(spec, args.run_id)
        run = service.wait(run.run_id, timeout=args.timeout)
        print(json.dumps({"run_id": run.run_id, "status": run.status.value}, indent=2))
        return
    if args.command == "status":
        run = store.get_run(args.run_id)
        if not run:
            raise SystemExit("Run not found")
        print(json.dumps(run.to_dict(), indent=2))
        return
    if args.command == "metrics":
        print(json.dumps(engine.metrics(), indent=2))
        return
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
