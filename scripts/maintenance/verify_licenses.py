#!/usr/bin/env python3
"""
Verify dataset config licensing fields for internal consistency.

This is a best-effort validator:
- It checks that `license` and `license_url` are consistent and supported by the site.
- It compares configs against URL-based inference rules (see `scripts/maintenance/license_rules.py`).

It does NOT automatically assert the upstream license terms unless you opt into
fetching remote pages (which may be unavailable in restricted environments).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from license_rules import first_matching_rule, normalize_license_id


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "resources" / "datasets_config"
GENERATE_PAGES_SCRIPT = REPO_ROOT / "scripts" / "generate_pages.py"


EXPECTED_LICENSE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-3.0": "https://creativecommons.org/licenses/by/3.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC-BY-NC-4.0": "https://creativecommons.org/licenses/by-nc/4.0/",
    "CC-BY-NC-SA-3.0": "https://creativecommons.org/licenses/by-nc-sa/3.0/",
    "CC-BY-NC-SA-4.0": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    "MIT": "https://opensource.org/licenses/MIT",
    "Apache-2.0": "https://www.apache.org/licenses/LICENSE-2.0",
    "GPL-3.0-only": "https://www.gnu.org/licenses/gpl-3.0.html",
    "Custom": "https://journals.aps.org/datasets",
}


@dataclass(frozen=True)
class Finding:
    level: str  # "error" | "warn"
    dataset: str
    message: str


def _iter_config_files(config_dir: Path) -> Iterable[Path]:
    for entry in sorted(config_dir.iterdir()):
        if not entry.is_dir():
            continue
        config_path = entry / f"config_{entry.name}.json"
        if config_path.exists():
            yield config_path


def _load_badge_license_ids(generate_pages_script: Path) -> set[str]:
    """
    Parse `LICENSE_BADGES = { ... }` keys from scripts/generate_pages.py without importing it.
    """
    try:
        tree = ast.parse(generate_pages_script.read_text(encoding="utf-8"))
    except Exception:
        return set()

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "LICENSE_BADGES":
            continue
        if not isinstance(node.value, ast.Dict):
            return set()
        keys: set[str] = set()
        for key_node in node.value.keys:
            if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str):
                keys.add(key_node.value)
        return keys

    return set()


def _norm_url(url: str) -> str:
    return (url or "").strip()


def verify_config(
    config_path: Path, badge_license_ids: set[str], check_rules: bool
) -> list[Finding]:
    findings: list[Finding] = []
    dataset = config_path.parent.name

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [Finding("error", dataset, f"invalid JSON: {e}")]

    license_id_raw = (config.get("license") or "").strip()
    license_id = normalize_license_id(license_id_raw)
    license_url = _norm_url(config.get("license_url") or "")
    source = (config.get("source") or "").strip()

    if license_id_raw and license_id != license_id_raw:
        findings.append(
            Finding("warn", dataset, f"`license` uses deprecated id {license_id_raw!r}; prefer {license_id!r}")
        )

    if license_id:
        if badge_license_ids and license_id not in badge_license_ids:
            findings.append(Finding("error", dataset, f"unsupported `license` for site badge mapping: {license_id!r}"))

        expected_url = EXPECTED_LICENSE_URLS.get(license_id)
        if expected_url:
            if not license_url:
                findings.append(Finding("warn", dataset, f"missing `license_url` (expected {expected_url})"))
            elif license_url != expected_url:
                findings.append(
                    Finding(
                        "error",
                        dataset,
                        f"`license_url` mismatch for {license_id!r}: got {license_url!r}, expected {expected_url!r}",
                    )
                )
        else:
            if license_url and not (license_url.startswith("http://") or license_url.startswith("https://")):
                findings.append(Finding("error", dataset, f"`license_url` is not http(s): {license_url!r}"))
    else:
        if license_url:
            findings.append(Finding("warn", dataset, "`license_url` present but `license` missing"))

    if check_rules and source:
        rule = first_matching_rule(source)
        if rule:
            rule_license = normalize_license_id(rule.license_id)
            if license_id and license_id != rule_license:
                findings.append(
                    Finding(
                        "error",
                        dataset,
                        f"`license` {license_id!r} does not match inferred rule for source ({rule.pattern!r} -> {rule_license!r})",
                    )
                )
            elif not license_id:
                findings.append(
                    Finding(
                        "warn",
                        dataset,
                        f"missing `license`; source matches rule ({rule.pattern!r} -> {rule_license!r}, confidence={rule.confidence})",
                    )
                )
            elif rule.confidence == "low":
                findings.append(
                    Finding(
                        "warn",
                        dataset,
                        f"license inferred from a low-confidence source rule ({rule.pattern!r}); verify upstream terms",
                    )
                )

            expected_rule_url = _norm_url(rule.license_url)
            if license_id and expected_rule_url and license_url and license_url != expected_rule_url:
                findings.append(
                    Finding(
                        "error",
                        dataset,
                        f"`license_url` {license_url!r} does not match rule URL {expected_rule_url!r} for source ({rule.pattern!r})",
                    )
                )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify dataset config license fields.")
    parser.add_argument("--configs-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--no-rules", action="store_true", help="Skip checks against URL-based inference rules.")
    args = parser.parse_args()

    badge_license_ids = _load_badge_license_ids(GENERATE_PAGES_SCRIPT)
    if not badge_license_ids:
        print(f"warning: could not parse LICENSE_BADGES from {GENERATE_PAGES_SCRIPT}", file=sys.stderr)

    findings: list[Finding] = []
    for config_path in _iter_config_files(args.configs_dir):
        findings.extend(verify_config(config_path, badge_license_ids, check_rules=not args.no_rules))

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warn"]

    if errors:
        print("\nErrors")
        print("=" * 60)
        for f in errors:
            print(f"- {f.dataset}: {f.message}")

    if warnings:
        print("\nWarnings")
        print("=" * 60)
        for f in warnings:
            print(f"- {f.dataset}: {f.message}")

    print("\nSummary")
    print("=" * 60)
    print(f"Checked: {len(list(_iter_config_files(args.configs_dir)))} configs")
    print(f"Errors:  {len(errors)}")
    print(f"Warnings:{len(warnings)}")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
