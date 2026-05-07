#!/usr/bin/env python3
"""Generate compact chart distributions directly from local datasets."""

from __future__ import annotations

import argparse
import bisect
import gzip
import json
import math
import os
import tempfile
from pathlib import Path

from hypergraphx.readwrite import load_hypergraph
from hypergraphx.readwrite.io_json import _parse_json_bytes_to_hypergraph


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "resources" / "datasets_statistics"


def histogram(values: list[float], edges: list[float]) -> list[int]:
    if len(edges) < 2:
        return []
    counts = [0 for _ in range(len(edges) - 1)]
    for value in values:
        idx = bisect.bisect_right(edges, value) - 1
        if 0 <= idx < len(counts) and value < edges[idx + 1]:
            counts[idx] += 1
    return counts


def make_log_edges(min_value: int, max_value: int, *, num: int = 20) -> list[int]:
    if min_value <= 0 or max_value <= 0:
        raise ValueError("log edges require positive min/max")
    if min_value > max_value:
        raise ValueError("min_value must be <= max_value")
    if min_value == max_value:
        return [min_value, max_value + 1]

    log_min = math.log10(min_value)
    log_max = math.log10(max_value)
    raw = []
    for i in range(num):
        t = i / (num - 1) if num > 1 else 0
        raw.append(int(round(10 ** (log_min + (log_max - log_min) * t))))

    edges = sorted({v for v in raw if min_value <= v <= max_value})
    edges = sorted(set(edges + [min_value, max_value + 1]))
    if len(edges) < 2:
        edges = [min_value, max_value + 1]
    if edges[0] != min_value:
        edges = [min_value] + edges
    if edges[-1] != max_value + 1:
        edges = edges + [max_value + 1]
    return sorted(set(edges))


def make_linear_edges(min_value: int, max_value: int) -> list[int]:
    if min_value > max_value:
        raise ValueError("min_value must be <= max_value")
    if min_value == max_value:
        return [min_value, max_value + 1]
    edges = list(range(min_value, max_value + 2))
    if len(edges) < 2:
        edges = [min_value, max_value + 1]
    return edges


def bin_labels_from_edges(edges: list[int]) -> list[str]:
    labels = []
    for i in range(max(0, len(edges) - 1)):
        left = int(edges[i])
        right_inclusive = int(edges[i + 1]) - 1
        if right_inclusive < left:
            right_inclusive = left
        labels.append(f"{left}" if left == right_inclusive else f"{left}\u2013{right_inclusive}")
    return labels


def bin_positions_from_edges(edges: list[int]) -> list[int]:
    return [int(edges[i]) for i in range(max(0, len(edges) - 1))]


def binned_integer_distribution(values: list[int]) -> dict[str, list[int] | list[str]]:
    if not values:
        return {"bins": [], "labels": [], "frequencies": []}

    min_value, max_value = min(values), max(values)
    if max_value > 10 and min_value > 0:
        edges = make_log_edges(min_value, max_value, num=20)
    else:
        edges = make_linear_edges(min_value, max_value)

    frequencies = histogram([float(v) for v in values], [float(v) for v in edges])
    bins = bin_positions_from_edges(edges)
    labels = bin_labels_from_edges(edges)

    if len(bins) == len(frequencies) == len(labels):
        keep = [count > 0 for count in frequencies]
        frequencies = [count for count, ok in zip(frequencies, keep) if ok]
        bins = [item for item, ok in zip(bins, keep) if ok]
        labels = [item for item, ok in zip(labels, keep) if ok]

    return {"bins": bins, "labels": labels, "frequencies": frequencies}


def empty_time_distribution() -> dict[str, object]:
    return {
        "x": [],
        "y": [],
        "start": [],
        "end": [],
        "is_epoch": False,
        "bucket_seconds": 0,
        "granularity": "unit",
    }


def time_distribution(times: list[object]) -> dict[str, object]:
    cleaned = []
    for value in times:
        try:
            cleaned.append(int(value))
        except Exception:
            pass

    if not cleaned:
        return empty_time_distribution()

    cleaned.sort()
    raw_min, raw_max = cleaned[0], cleaned[-1]
    is_millis = raw_max >= 10_000_000_000
    min_seconds = (raw_min / 1000.0) if is_millis else float(raw_min)
    is_epoch = min_seconds >= 500_000_000

    times_seconds = [(t / 1000.0) if is_millis else float(t) for t in cleaned]
    if not is_epoch:
        base = times_seconds[0]
        times_seconds = [t - base for t in times_seconds]

    span = max(0.0, max(times_seconds) - min(times_seconds))
    if span <= 14 * 86400:
        bucket = 20 * 60
    elif span <= 90 * 86400:
        bucket = 3600
    elif span <= 2 * 365 * 86400:
        bucket = 86400
    else:
        bucket = 7 * 86400

    try:
        bucket_override = int(os.getenv("TIME_BUCKET_SECONDS", "0"))
    except ValueError:
        bucket_override = 0
    if bucket_override > 0:
        bucket = bucket_override

    max_points = 800
    if span > 0 and (span / bucket) > max_points:
        bucket = math.ceil(span / max_points)
    if bucket <= 0:
        bucket = 1

    start = math.floor(min(times_seconds) / bucket) * bucket
    end = math.ceil((max(times_seconds) + 1e-9) / bucket) * bucket
    if end <= start:
        end = start + bucket

    bucket_count = max(1, min(int(round((end - start) / bucket)), 20000))
    counts = [0 for _ in range(bucket_count)]
    for value in times_seconds:
        idx = int((value - start) // bucket)
        if idx < 0:
            idx = 0
        elif idx >= bucket_count:
            idx = bucket_count - 1
        counts[idx] += 1

    x_values = []
    starts = []
    ends = []
    for i in range(bucket_count):
        left = start + i * bucket
        right = left + bucket
        starts.append(left)
        ends.append(right)
        x_values.append((left + right) / 2.0)

    return {
        "x": x_values,
        "y": counts,
        "start": starts,
        "end": ends,
        "is_epoch": bool(is_epoch),
        "bucket_seconds": int(bucket),
        "granularity": "unit",
    }


def discover_dataset_names(data_dir: Path) -> list[str]:
    return sorted(path.name for path in data_dir.iterdir() if path.is_dir())


def find_dataset_file(data_dir: Path, dataset: str, prefer: str) -> Path:
    dataset_dir = data_dir / dataset
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    preferred_suffixes = {
        "hgx": [".hgx", ".hgx.gz", ".json", ".json.gz"],
        "json": [".json", ".json.gz", ".hgx", ".hgx.gz"],
    }[prefer]

    for suffix in preferred_suffixes:
        candidate = dataset_dir / f"{dataset}{suffix}"
        if candidate.exists():
            return candidate

    for suffix in preferred_suffixes:
        matches = sorted(dataset_dir.glob(f"*{suffix}"))
        if matches:
            return matches[0]

    raise FileNotFoundError(f"No .hgx/.json dataset file found in {dataset_dir}")


def load_dataset(path: Path):
    name = path.name
    if name.endswith(".json.gz"):
        return _parse_json_bytes_to_hypergraph(gzip.decompress(path.read_bytes()))
    if name.endswith(".hgx.gz"):
        with tempfile.NamedTemporaryFile(suffix=".hgx") as temp:
            temp.write(gzip.decompress(path.read_bytes()))
            temp.flush()
            return load_hypergraph(temp.name, fmt="pickle")
    if path.suffix == ".json":
        return load_hypergraph(str(path), fmt="json")
    if path.suffix == ".hgx":
        return load_hypergraph(str(path), fmt="pickle")
    return load_hypergraph(str(path))


def build_distribution(hypergraph) -> dict[str, object]:
    edge_sizes = [int(value) for value in hypergraph.get_sizes()]
    node_degrees = [
        int(value)
        for value in hypergraph.degree_sequence().values()
        if int(value) > 0
    ]
    get_times = getattr(hypergraph, "get_times", None)
    times = list(get_times()) if callable(get_times) else []

    return {
        "version": 1,
        "hyperedge_size": binned_integer_distribution(edge_sizes),
        "hyperdegree": binned_integer_distribution(node_degrees),
        "time": time_distribution(times),
    }


def write_distribution(distribution: dict[str, object], output_path: Path, overwrite: bool) -> None:
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(distribution, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datasets", nargs="*", help="Dataset directory names under --data-dir.")
    parser.add_argument("--all", action="store_true", help="Generate distributions for every dataset directory.")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--prefer", choices=("hgx", "json"), default="hgx")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_dir = args.data_dir.expanduser()
    output_dir = args.output_dir.expanduser()

    if args.all:
        datasets = discover_dataset_names(data_dir)
    else:
        datasets = [item.strip() for item in args.datasets if item.strip()]

    if not datasets:
        raise SystemExit("Pass at least one dataset name, or use --all.")

    failures = []
    for index, dataset in enumerate(datasets, start=1):
        try:
            source = find_dataset_file(data_dir, dataset, args.prefer)
            output = output_dir / dataset / "distributions.json"
            if args.dry_run:
                print(f"[{index}/{len(datasets)}] {dataset}: {source} -> {output}")
                continue
            hypergraph = load_dataset(source)
            distribution = build_distribution(hypergraph)
            write_distribution(distribution, output, args.overwrite)
            print(f"[{index}/{len(datasets)}] wrote {output} from {source}")
        except Exception as exc:
            failures.append((dataset, exc))
            print(f"[{index}/{len(datasets)}] FAIL {dataset}: {type(exc).__name__}: {exc}")

    if failures:
        print()
        print(f"Failed: {len(failures)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
