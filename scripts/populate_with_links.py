#!/usr/bin/env python3
"""
Update config_{dirname}.json files under a root directory to include dataset URLs.

For each immediate subdirectory of ROOT:
  - Expect a file: subdir/config_{subdir.name}.json
  - Read its "name" attribute.
  - Ensure:
      json_download  includes "https://cricca.disi.unitn.it/datasets/hypergraphx-data/{name}/{name}.json.gz"
      binary_download includes "https://cricca.disi.unitn.it/datasets/hypergraphx-data/{name}/{name}.hgx.gz"
  - The script creates the lists if they don't exist, removes empty-string placeholders,
    and avoids duplicates.

Usage:
    python update_configs.py /path/to/root
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

BASE = "https://cricca.disi.unitn.it/datasets/hypergraphx-data"

def clean_list(value: Any) -> List[str]:
    """Return a clean list of non-empty strings from value (list or other)."""
    if isinstance(value, list):
        items = []
        for x in value:
            if isinstance(x, str):
                s = x.strip()
                if s:
                    items.append(s)
        return items
    return []

def ensure_url(lst: List[str], url: str) -> List[str]:
    """Append url if not already present, preserving order."""
    if url not in lst:
        lst.append(url)
    return lst

def process_config_file(cfg_path: Path) -> bool:
    """
    Update a single config JSON file.
    Returns True if the file was updated, False if unchanged.
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

    json_url   = f"{BASE}/{name}/{name}.json.gz"
    binary_url = f"{BASE}/{name}/{name}.hgx.gz"

    original = json.dumps(data, sort_keys=True)

    # Normalize and update lists
    data["json_download"]   = ensure_url(clean_list(data.get("json_download")), json_url)
    data["binary_download"] = ensure_url(clean_list(data.get("binary_download")), binary_url)

    updated = json.dumps(data, sort_keys=True)
    if updated != original:
        # Write back with pretty formatting, newline at EOF
        cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True
    return False

def main():
    ap = argparse.ArgumentParser(description="Update config_{dirname}.json files with dataset URLs.")
    ap.add_argument("root", type=Path, help="Path to the root directory containing subdirectories.")
    args = ap.parse_args()

    root: Path = args.root
    if not root.exists() or not root.is_dir():
        raise SystemExit(f"Root path does not exist or is not a directory: {root}")

    processed = 0
    updated = 0
    skipped_missing = 0

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
        changed = process_config_file(cfg_path)
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

if __name__ == "__main__":
    main()
