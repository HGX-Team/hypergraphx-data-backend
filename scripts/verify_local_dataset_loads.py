#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import multiprocessing
import time
import traceback
from pathlib import Path

from hypergraphx.readwrite import load_hypergraph


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_REPORT = REPO_ROOT / "reports" / "local_dataset_loads.json"


def iter_dataset_files(data_dir: Path) -> list[tuple[str, str, Path]]:
    files: list[tuple[str, str, Path]] = []
    for dataset_dir in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        for suffix in ("json", "hgx"):
            matches = sorted(dataset_dir.glob(f"*.{suffix}"))
            for path in matches:
                files.append((dataset_dir.name, suffix, path))
    return files


def object_summary(obj) -> dict[str, object]:
    summary: dict[str, object] = {"class": type(obj).__name__}

    if hasattr(obj, "_node_metadata"):
        summary["nodes"] = len(obj._node_metadata)
    else:
        method = getattr(obj, "num_nodes", None)
        if callable(method):
            summary["nodes"] = method()

    method = getattr(obj, "num_edges", None)
    if callable(method):
        summary["edges"] = method()
    elif hasattr(obj, "_edge_list"):
        summary["edges"] = len(obj._edge_list)

    if hasattr(obj, "_weights"):
        summary["weights"] = len(obj._weights)

    method = getattr(obj, "get_hypergraph_metadata", None)
    if callable(method):
        try:
            value = method()
            summary["hypergraph_metadata"] = value if isinstance(value, dict) else str(value)
        except Exception as exc:
            summary["hypergraph_metadata_error"] = f"{type(exc).__name__}: {exc}"

    return summary


def check_file(dataset: str, fmt: str, path: Path) -> dict[str, object]:
    started = time.perf_counter()
    result: dict[str, object] = {
        "dataset": dataset,
        "format": fmt,
        "path": str(path),
        "ok": False,
    }

    try:
        loaded = load_hypergraph(str(path), fmt=fmt)
        result["ok"] = True
        result["summary"] = object_summary(loaded)
        del loaded
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc(limit=8)
    finally:
        result["seconds"] = round(time.perf_counter() - started, 3)
        gc.collect()

    return result


def check_file_worker(dataset: str, fmt: str, path: str, queue: multiprocessing.Queue) -> None:
    queue.put(check_file(dataset, fmt, Path(path)))


def check_file_with_timeout(
    dataset: str,
    fmt: str,
    path: Path,
    timeout_seconds: int,
) -> dict[str, object]:
    if timeout_seconds <= 0:
        return check_file(dataset, fmt, path)

    started = time.perf_counter()
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=check_file_worker, args=(dataset, fmt, str(path), queue))
    process.start()
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(5)
        return {
            "dataset": dataset,
            "format": fmt,
            "path": str(path),
            "ok": False,
            "error_type": "TimeoutError",
            "error": f"Timed out after {timeout_seconds}s",
            "seconds": round(time.perf_counter() - started, 3),
        }

    if not queue.empty():
        return queue.get()

    return {
        "dataset": dataset,
        "format": fmt,
        "path": str(path),
        "ok": False,
        "error_type": "ProcessError",
        "error": f"Loader process exited with code {process.exitcode} without returning a result",
        "seconds": round(time.perf_counter() - started, 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify that local Hypergraphx datasets load with hypergraphx.readwrite.load_hypergraph."
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--only", nargs="*", default=[], help="Dataset directory names to check.")
    parser.add_argument(
        "--formats",
        nargs="*",
        choices=("json", "hgx"),
        default=["json", "hgx"],
        help="Formats to check.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Limit number of files checked.")
    parser.add_argument("--resume", action="store_true", help="Skip entries already present in the report.")
    parser.add_argument("--timeout", type=int, default=0, help="Per-file timeout in seconds; 0 disables timeouts.")
    args = parser.parse_args()

    data_dir = args.data_dir
    if not data_dir.exists():
        raise SystemExit(f"Data directory not found: {data_dir}")

    only = {item.strip() for item in args.only if item.strip()}
    files = iter_dataset_files(data_dir)
    if only:
        files = [item for item in files if item[0] in only]
    formats = set(args.formats)
    files = [item for item in files if item[1] in formats]
    if args.limit:
        files = files[: args.limit]

    if args.resume and args.report.exists():
        previous = json.loads(args.report.read_text(encoding="utf-8"))
        results = list(previous.get("results", []))
        seen = {
            (Path(item["path"]).resolve(), item["format"])
            for item in results
            if "path" in item and "format" in item
        }
        files = [
            item
            for item in files
            if (item[2].resolve(), item[1]) not in seen
        ]
    else:
        results = []
    args.report.parent.mkdir(parents=True, exist_ok=True)

    def write_report() -> None:
        failures = [item for item in results if not item["ok"]]
        payload = {
            "data_dir": str(data_dir),
            "checked": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "results": results,
        }
        args.report.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for index, (dataset, fmt, path) in enumerate(files, start=1):
        print(f"[{index}/{len(files)}] loading {dataset} ({fmt})", flush=True)
        result = check_file_with_timeout(dataset, fmt, path, args.timeout)
        status = "OK" if result["ok"] else "FAIL"
        print(f"    {status} {result['seconds']}s", flush=True)
        results.append(result)
        write_report()

    failures = [item for item in results if not item["ok"]]
    write_report()

    print()
    print(f"Checked: {len(results)}")
    print(f"Passed:  {len(results) - len(failures)}")
    print(f"Failed:  {len(failures)}")
    print(f"Report:  {args.report}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
