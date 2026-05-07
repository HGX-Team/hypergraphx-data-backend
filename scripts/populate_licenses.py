#!/usr/bin/env python3
"""
Populate license fields in dataset configs based on known source URL patterns.

Only applies licenses that can be reliably inferred from the source URL.
Datasets with unknown licenses are left unchanged (will show default message).
"""

import json
from pathlib import Path

from license_rules import first_matching_rule, normalize_license_id

CONFIG_DIR = Path(__file__).parent.parent / "resources" / "datasets_config"

def get_license_for_source(source_url):
    """Return license info if source URL matches a known pattern."""
    if not source_url:
        return None

    rule = first_matching_rule(source_url)
    if not rule:
        return None
    return {
        "license": normalize_license_id(rule.license_id),
        "license_url": rule.license_url,
        "license_note": rule.license_note,
        "confidence": rule.confidence,
    }


def update_config(config_path, dry_run=False, min_confidence="high"):
    """Update a single config file with license info if applicable."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # Skip if license already set
    if config.get("license"):
        return None, "already has license"

    source = config.get("source", "")
    license_info = get_license_for_source(source)

    if not license_info:
        return None, "no matching license pattern"

    order = {"high": 3, "medium": 2, "low": 1}
    if order.get(license_info.get("confidence", "low"), 1) < order[min_confidence]:
        return None, f"match below confidence ({license_info.get('confidence')})"

    # Update config
    config["license"] = license_info["license"]
    if license_info["license_url"]:
        config["license_url"] = license_info["license_url"]
    if license_info["license_note"]:
        config["license_note"] = license_info["license_note"]

    if not dry_run:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
            f.write("\n")

    return license_info["license"], "updated"


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Populate license fields in dataset configs")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying files")
    parser.add_argument(
        "--min-confidence",
        choices=("high", "medium", "low"),
        default="high",
        help="Minimum confidence required to infer a license from the source URL (default: high).",
    )
    args = parser.parse_args()

    updated = []
    skipped_has_license = []
    skipped_no_match = []

    for config_dir in sorted(CONFIG_DIR.iterdir()):
        if not config_dir.is_dir():
            continue

        config_file = config_dir / f"config_{config_dir.name}.json"
        if not config_file.exists():
            continue

        license_id, status = update_config(
            config_file, dry_run=args.dry_run, min_confidence=args.min_confidence
        )

        if status == "updated":
            updated.append((config_dir.name, license_id))
        elif status == "already has license":
            skipped_has_license.append(config_dir.name)
        else:
            skipped_no_match.append(config_dir.name)

    # Print summary
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}License Population Summary")
    print("=" * 50)

    if updated:
        print(f"\nUpdated ({len(updated)} datasets):")
        for name, license_id in updated:
            print(f"  {name}: {license_id}")

    if skipped_has_license:
        print(f"\nSkipped - already has license ({len(skipped_has_license)} datasets):")
        for name in skipped_has_license:
            print(f"  {name}")

    print(f"\nSkipped - no matching / insufficient confidence ({len(skipped_no_match)} datasets)")
    print(f"  These will show 'License not specified' message")

    print(
        f"\nTotal: {len(updated)} updated, {len(skipped_has_license)} already set, {len(skipped_no_match)} skipped"
    )


if __name__ == "__main__":
    main()
