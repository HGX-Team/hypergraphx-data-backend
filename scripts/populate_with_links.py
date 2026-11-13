#!/usr/bin/env python3
"""
Update config_{dirname}.json files under a root directory to include dataset URLs.

For each immediate subdirectory of ROOT:
  - Expect a file: subdir/config_{subdir.name}.json
  - Read its "name" attribute.
  - Ensure a "versions" list exists (newest first, MAJOR.MINOR.PATCH labels).
  - Set every entry's download URLs from its version label:
      {BASE_URL}/{name}/{version}/{name}.json.gz and .hgx.gz
    except the newest entry while "versioned_downloads" is off in
    site_config.json: it keeps the latest alias path
      {BASE_URL}/{name}/{name}.json.gz and .hgx.gz

Usage:
    python scripts/populate_with_links.py resources/datasets_config
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from dataset_versions import (
    DEFAULT_SITE_CONFIG,
    latest_url,
    parse_version,
    version_url,
    versioned_downloads_enabled,
)

def clean_list(value: Any) -> List[str]:
    """Return a clean list of non-empty strings from value (list or scalar)."""
    if isinstance(value, list):
        items = []
        for x in value:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    items.append(s)
        return items
    return []

def normalize_versions(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    versions = data.get("versions")
    if isinstance(versions, list):
        cleaned = [item for item in versions if isinstance(item, dict)]
        if cleaned:
            return cleaned

    binary_downloads = clean_list(data.get("binary_download"))
    json_downloads = clean_list(data.get("json_download"))
    binary_sizes = data.get("binary_download_sizes") if isinstance(data.get("binary_download_sizes"), list) else []
    json_sizes = data.get("json_download_sizes") if isinstance(data.get("json_download_sizes"), list) else []
    count = max(len(binary_downloads), len(json_downloads))
    out = []
    for idx in range(count):
        entry: Dict[str, Any] = {"version": "1.0.0" if idx == 0 else f"{idx + 1}.0.0"}
        if idx < len(binary_downloads):
            entry["binary_download"] = binary_downloads[idx]
        if idx < len(json_downloads):
            entry["json_download"] = json_downloads[idx]
        if idx < len(binary_sizes):
            entry["binary_download_size"] = binary_sizes[idx]
        if idx < len(json_sizes):
            entry["json_download_size"] = json_sizes[idx]
        out.append(entry)
    return out

def ensure_url(lst: List[str], url: str) -> List[str]:
    """Append url if not already present, preserving order."""
    if url not in lst:
        lst.append(url)
    return lst

def check_version_order(versions: List[Dict[str, Any]]) -> None:
    """Raise ValueError unless labels are valid and strictly newest-first."""
    parsed = [parse_version(entry["version"]) for entry in versions]
    for newer, older in zip(parsed, parsed[1:]):
        if newer <= older:
            raise ValueError(
                "versions must be listed newest first without duplicates, got "
                + ", ".join(entry["version"] for entry in versions)
            )

def process_config_file(cfg_path: Path, versioned: bool = False) -> bool:
    """
    Update a single config JSON file.
    Returns True if the file was updated, False if unchanged.
    Raises ValueError if the version labels are invalid or out of order.
    """
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] Skipping invalid JSON: {cfg_path} ({e})")
        return False

    # Derive name: prefer explicit "name", otherwise fallback to directory name.
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        name = cfg_path.parent.name

    original = json.dumps(data, sort_keys=True)

    versions = normalize_versions(data)
    if not versions:
        versions = [{"version": "1.0.0"}]
    for entry in versions:
        entry.setdefault("version", "1.0.0")
    check_version_order(versions)

    for index, entry in enumerate(versions):
        if index == 0 and not versioned:
            # Latest release served from the moving alias path.
            entry["json_download"] = latest_url(name, "json")
            entry["binary_download"] = latest_url(name, "binary")
        else:
            entry["json_download"] = version_url(name, entry["version"], "json")
            entry["binary_download"] = version_url(name, entry["version"], "binary")
    data["versions"] = versions
    for legacy_key in (
        "json_download",
        "binary_download",
        "json_download_sizes",
        "binary_download_sizes",
        "json_download_size",
        "binary_download_size",
    ):
        data.pop(legacy_key, None)

    updated = json.dumps(data, sort_keys=True)
    if updated != original:
        # Write back with pretty formatting, newline at EOF
        cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True
    return False

def main():
    ap = argparse.ArgumentParser(description="Update config_{dirname}.json files with dataset URLs.")
    ap.add_argument("root", type=Path, help="Path to the root directory containing subdirectories.")
    ap.add_argument(
        "--site-config",
        type=Path,
        default=DEFAULT_SITE_CONFIG,
        help="site_config.json to read the versioned_downloads switch from.",
    )
    args = ap.parse_args()

    root: Path = args.root
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root path does not exist or is not a directory: {root}")

    versioned = versioned_downloads_enabled(args.site_config)
    processed = 0
    updated = 0
    skipped_missing = 0
    errors: List[str] = []

    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        cfg_path = sub / f"config_{sub.name}.json"
        if not cfg_path.exists():
            # Fallback: if the expected file name isn't present, optionally look for any config_*.json
            # (kept simple: count as missing and continue)
            print(f"[INFO] No config file found for {sub.name}: {cfg_path.name}")
            skipped_missing += 1
            continue

        processed += 1
        try:
            changed = process_config_file(cfg_path, versioned=versioned)
        except ValueError as e:
            errors.append(f"{cfg_path}: {e}")
            continue
        if changed:
            print(f"[OK] Updated: {cfg_path}")
            updated += 1
        else:
            print(f"[OK] No changes needed: {cfg_path}")

    print("\nSummary")
    print("-------")
    print(f"Processed configs: {processed}")
    print(f"Updated configs:   {updated}")
    print(f"Missing configs:   {skipped_missing}")
    print(f"Latest version links to: {'its version folder' if versioned else 'the latest alias path'}")

    if errors:
        print("\nInvalid version lists:")
        for error in errors:
            print(f"  [ERROR] {error}")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
