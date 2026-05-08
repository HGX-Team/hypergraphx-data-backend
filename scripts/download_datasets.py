#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import shutil
import ssl
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse
from urllib.error import HTTPError
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_DIR = REPO_ROOT / "resources" / "datasets_config"
DEFAULT_DATA_DIR = REPO_ROOT / "data"


def _iter_dataset_config_paths(config_dir: Path) -> Iterable[Path]:
    for entry in sorted(config_dir.iterdir()):
        if not entry.is_dir():
            continue
        config_path = entry / f"config_{entry.name}.json"
        if config_path.exists():
            yield config_path


def _urls(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


def _version_download_urls(cfg: dict, *, all_versions: bool) -> list[str]:
    versions = cfg.get("versions")
    if isinstance(versions, list):
        selected = versions if all_versions else versions[:1]
        urls: list[str] = []
        for entry in selected:
            if not isinstance(entry, dict):
                continue
            for key in ("binary_download", "hgx_download", "json_download"):
                url = entry.get(key)
                if url:
                    urls.append(str(url))
        return urls

    binary_urls = _urls(cfg.get("binary_download"))
    json_urls = _urls(cfg.get("json_download"))
    if not all_versions:
        binary_urls = binary_urls[:1]
        json_urls = json_urls[:1]
    return binary_urls + json_urls


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or "download.bin"


def _download(url: str, dest: Path, *, overwrite: bool, insecure: bool) -> None:
    if dest.exists() and not overwrite:
        print(f"[SKIP] exists: {dest}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")

    if insecure:
        context = ssl._create_unverified_context()  # noqa: SLF001
    else:
        context = ssl.create_default_context()
    try:
        import certifi  # type: ignore

        if not insecure:
            context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass

    print(f"[GET] {url}")
    with urlopen(url, context=context) as response, open(tmp, "wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(dest)
    print(f"[OK]  {dest}")


def _decompress_gzip(path: Path, *, keep: bool) -> Path:
    out = path.with_suffix("")
    print(f"[GZ]  {path.name} -> {out.name}")
    tmp = out.with_suffix(out.suffix + ".part")
    with gzip.open(path, "rb") as src, open(tmp, "wb") as dst:
        shutil.copyfileobj(src, dst)
    tmp.replace(out)
    if not keep:
        path.unlink(missing_ok=True)
    return out


def _extract_zip(path: Path, dest_dir: Path, *, keep: bool) -> None:
    print(f"[ZIP] {path.name} -> {dest_dir}")
    with zipfile.ZipFile(path) as zf:
        zf.extractall(dest_dir)
    if not keep:
        path.unlink(missing_ok=True)


def _extract_tar(path: Path, dest_dir: Path, *, keep: bool) -> None:
    print(f"[TAR] {path.name} -> {dest_dir}")
    with tarfile.open(path) as tf:
        tf.extractall(dest_dir)
    if not keep:
        path.unlink(missing_ok=True)


def _maybe_unpack(path: Path, dest_dir: Path, *, keep_archives: bool) -> None:
    lower = path.name.lower()
    if lower.endswith(".gz") and not lower.endswith(".tar.gz"):
        decompressed = _decompress_gzip(path, keep=keep_archives)
        _maybe_unpack(decompressed, dest_dir, keep_archives=keep_archives)
        return
    if lower.endswith(".zip"):
        _extract_zip(path, dest_dir, keep=keep_archives)
        return
    if lower.endswith(".tar") or lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        _extract_tar(path, dest_dir, keep=keep_archives)
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and unpack dataset files into ./data/<dataset>/")
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--only", nargs="*", default=[], help="Only download these dataset ids (directory names).")
    parser.add_argument("--all-versions", action="store_true", help="Download all versions, not just the first link.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files.")
    parser.add_argument("--keep-archives", action="store_true", help="Keep downloaded archives after unpacking.")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (use only if you trust the download host).",
    )
    args = parser.parse_args()

    config_dir: Path = args.config_dir
    data_dir: Path = args.data_dir
    only: set[str] = {item.strip() for item in args.only if item.strip()}

    if not config_dir.exists():
        print(f"Config dir not found: {config_dir}", file=sys.stderr)
        return 2

    if data_dir.exists() and not data_dir.is_dir():
        print(f"Data dir exists but is not a directory: {data_dir}", file=sys.stderr)
        return 2
    data_dir.mkdir(parents=True, exist_ok=True)

    import json

    configs = list(_iter_dataset_config_paths(config_dir))
    if only:
        configs = [p for p in configs if p.parent.name in only]

    if not configs:
        print("No dataset configs found.")
        return 0

    failures: list[str] = []
    for config_path in configs:
        dataset_id = config_path.parent.name
        dataset_dir = data_dir / dataset_id
        dataset_dir.mkdir(parents=True, exist_ok=True)

        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            failures.append(f"{dataset_id}: failed to read config ({exc})")
            continue

        download_urls = _version_download_urls(cfg, all_versions=args.all_versions)

        if not download_urls:
            print(f"[SKIP] {dataset_id}: no download links")
            continue

        for url in download_urls:
            filename = _filename_from_url(url)
            dest = dataset_dir / filename
            try:
                _download(url, dest, overwrite=args.overwrite, insecure=args.insecure)
                _maybe_unpack(dest, dataset_dir, keep_archives=args.keep_archives)
            except HTTPError as exc:
                if exc.code == 404 and url.lower().endswith(".gz"):
                    alt_url = url[:-3]
                    alt_dest = dataset_dir / _filename_from_url(alt_url)
                    try:
                        _download(
                            alt_url,
                            alt_dest,
                            overwrite=args.overwrite,
                            insecure=args.insecure,
                        )
                        _maybe_unpack(alt_dest, dataset_dir, keep_archives=args.keep_archives)
                        continue
                    except Exception as alt_exc:
                        failures.append(f"{dataset_id}: {url} ({exc}); retry {alt_url} ({alt_exc})")
                        continue
                failures.append(f"{dataset_id}: {url} ({exc})")
            except Exception as exc:
                failures.append(f"{dataset_id}: {url} ({exc})")

    if failures:
        print("\nFailures:", file=sys.stderr)
        for item in failures:
            print(f"- {item}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
