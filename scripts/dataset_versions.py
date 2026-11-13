"""Shared helpers for dataset versioning.

Layout on the download server (mirrored from the local ``data/`` directory):

    <name>/<name>.hgx.gz            latest release (moving alias)
    <name>/<name>.json.gz
    <name>/<version>/<name>.hgx.gz  one immutable folder per released version
    <name>/<version>/<name>.json.gz

Each entry in a dataset config's ``versions`` list (newest first) records the
version label, release date, changelog, download URLs, file sizes, and SHA-256
checksums of the compressed files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_DIR = REPO_ROOT / "resources" / "datasets_config"
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_SITE_CONFIG = REPO_ROOT / "site_config.json"

BASE_URL = "https://cricca.disi.unitn.it/datasets/hypergraphx-data"

# Config key prefix -> file extension (before ".gz").
FORMATS = {"binary": "hgx", "json": "json"}

_VERSION_RE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def parse_version(label: object) -> tuple[int, int, int]:
    """Parse a MAJOR.MINOR.PATCH label, raising ValueError if invalid."""
    match = _VERSION_RE.fullmatch(str(label))
    if not match:
        raise ValueError(f"invalid version {label!r}; expected MAJOR.MINOR.PATCH, e.g. 1.0.0")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def file_name(name: str, fmt: str) -> str:
    return f"{name}.{FORMATS[fmt]}.gz"


def latest_url(name: str, fmt: str) -> str:
    return f"{BASE_URL}/{name}/{file_name(name, fmt)}"


def version_url(name: str, version: str, fmt: str) -> str:
    return f"{BASE_URL}/{name}/{version}/{file_name(name, fmt)}"


def latest_path(data_dir: Path, name: str, fmt: str) -> Path:
    return data_dir / name / file_name(name, fmt)


def version_path(data_dir: Path, name: str, version: str, fmt: str) -> Path:
    return data_dir / name / version / file_name(name, fmt)


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_atomic(src: Path, dst: Path) -> None:
    """Copy src to dst via a temporary file, so dst is never left half-written."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{dst.name}.", dir=dst.parent)
    os.close(fd)
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def iter_config_paths(config_dir: Path) -> Iterator[Path]:
    for entry in sorted(config_dir.iterdir()):
        config_path = entry / f"config_{entry.name}.json"
        if entry.is_dir() and config_path.exists():
            yield config_path


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_config(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def versioned_downloads_enabled(site_config: Path = DEFAULT_SITE_CONFIG) -> bool:
    """Whether the latest version should also link to its immutable version folder.

    While False, the newest entry keeps linking to the latest alias path; set it
    to True once every current release has been frozen into a version folder
    on the server.
    """
    if not site_config.exists():
        return False
    return bool(json.loads(site_config.read_text(encoding="utf-8")).get("versioned_downloads", False))
