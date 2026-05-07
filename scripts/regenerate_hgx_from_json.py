#!/usr/bin/env python3
"""Regenerate compressed HGX artifacts from local JSON datasets.

This script treats JSON as the source of truth and rewrites each dataset's
``.hgx.gz`` file using the currently installed HypergraphX API.
"""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from hypergraphx.readwrite import load_hypergraph, save_hypergraph
from hypergraphx.readwrite.io_json import _parse_json_bytes_to_hypergraph


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"


@dataclass(frozen=True)
class Job:
    dataset: str
    json_path: Path
    output_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Load each local JSON dataset, then regenerate the compressed "
            ".hgx.gz artifact with the currently installed HypergraphX."
        )
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Directory containing one subdirectory per dataset.",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=[],
        help="Optional dataset directory names to regenerate.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process at most this many datasets. Useful for smoke tests.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List planned work without loading or writing datasets.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the intermediate uncompressed .hgx file next to the output.",
    )
    return parser.parse_args()


def find_json_source(dataset_dir: Path) -> Path | None:
    dataset = dataset_dir.name
    candidates = [
        dataset_dir / f"{dataset}.json.gz",
        dataset_dir / f"{dataset}.json",
    ]
    for path in candidates:
        if path.exists():
            return path

    matches = sorted(dataset_dir.glob("*.json.gz")) + sorted(dataset_dir.glob("*.json"))
    return matches[0] if matches else None


def discover_jobs(data_dir: Path, only: set[str], limit: int) -> list[Job]:
    jobs: list[Job] = []
    for dataset_dir in sorted(path for path in data_dir.iterdir() if path.is_dir()):
        dataset = dataset_dir.name
        if only and dataset not in only:
            continue
        json_path = find_json_source(dataset_dir)
        if json_path is None:
            continue
        jobs.append(
            Job(
                dataset=dataset,
                json_path=json_path,
                output_path=dataset_dir / f"{dataset}.hgx.gz",
            )
        )
    if limit:
        return jobs[:limit]
    return jobs


def load_json_hypergraph(path: Path):
    if path.name.endswith(".gz"):
        return _parse_json_bytes_to_hypergraph(gzip.decompress(path.read_bytes()))
    return load_hypergraph(str(path), fmt="json")


def gzip_file(source: Path, destination: Path) -> None:
    with source.open("rb") as src, gzip.open(destination, "wb") as dst:
        shutil.copyfileobj(src, dst)


def regenerate(job: Job, keep_temp: bool) -> dict[str, object]:
    started = time.perf_counter()
    temp_dir = job.output_path.parent
    temp_hgx = temp_dir / f".{job.output_path.stem}.{os.getpid()}.tmp.hgx"
    temp_gz = temp_dir / f".{job.output_path.name}.{os.getpid()}.tmp"

    result: dict[str, object] = {
        "dataset": job.dataset,
        "json": str(job.json_path),
        "output": str(job.output_path),
        "ok": False,
    }

    try:
        hypergraph = load_json_hypergraph(job.json_path)
        save_hypergraph(hypergraph, str(temp_hgx), fmt="pickle")
        gzip_file(temp_hgx, temp_gz)
        temp_gz.replace(job.output_path)
        if keep_temp:
            final_hgx = job.output_path.with_suffix("")
            temp_hgx.replace(final_hgx)
            result["intermediate_hgx"] = str(final_hgx)
        else:
            temp_hgx.unlink(missing_ok=True)
        result["ok"] = True
        result["bytes"] = job.output_path.stat().st_size
    except Exception as exc:
        result["error_type"] = type(exc).__name__
        result["error"] = str(exc)
        result["traceback"] = traceback.format_exc(limit=8)
        temp_hgx.unlink(missing_ok=True)
        temp_gz.unlink(missing_ok=True)
    finally:
        result["seconds"] = round(time.perf_counter() - started, 3)

    return result


def render_progress(done: int, total: int, width: int = 32) -> str:
    if total <= 0:
        return ""
    filled = int(width * done / total)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {done}/{total}"


def print_progress(done: int, total: int, *, end: str = "\r") -> None:
    print(render_progress(done, total), end=end, flush=True)


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser()
    if not data_dir.exists():
        raise SystemExit(f"Data directory not found: {data_dir}")
    only = {item.strip() for item in args.only if item.strip()}
    jobs = discover_jobs(data_dir, only, args.limit)
    if not jobs:
        print("No JSON datasets found.")
        return 0

    if args.dry_run:
        for job in jobs:
            print(f"{job.dataset}: {job.json_path} -> {job.output_path}")
        print(f"Planned: {len(jobs)} dataset(s)")
        return 0

    results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    started = time.perf_counter()

    print(f"Regenerating {len(jobs)} dataset(s)")
    print_progress(0, len(jobs))

    for job in jobs:
        result = regenerate(job, args.keep_temp)
        results.append(result)
        if not result["ok"]:
            failures.append(result)
        print_progress(len(results), len(jobs))

    print()
    elapsed = round(time.perf_counter() - started, 3)
    print(f"Done in {elapsed}s")
    print(f"Passed: {len(results) - len(failures)}")
    print(f"Failed: {len(failures)}")

    for result in sorted(results, key=lambda item: str(item["dataset"])):
        status = "OK" if result["ok"] else "FAIL"
        print(f"{status} {result['dataset']} {result['seconds']}s")
        if not result["ok"]:
            print(f"  {result.get('error_type')}: {result.get('error')}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
