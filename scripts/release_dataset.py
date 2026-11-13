#!/usr/bin/env python3
"""Freeze, release, and verify dataset versions.

Commands
--------
freeze   Record the current latest files of a dataset as the newest version
         listed in its config: copy them into data/<name>/<version>/ and store
         their sizes and SHA-256 checksums in the config. Safe to re-run.
release  Publish new files as a new version: copy them into a new version
         folder, update the latest files, and add a version entry (release
         date and changelog) at the top of the config's "versions" list.
check    Verify local files against the recorded checksums, or with --remote
         the files served by the download server.

Typical workflow (see HOWTO.md, "Dataset versions"):

    python3 scripts/release_dataset.py freeze --all
    python3 scripts/release_dataset.py release zoo 1.1.0 \\
        --changes "Added node metadata" --hgx new/zoo.hgx.gz --json new/zoo.json.gz
    python3 scripts/release_dataset.py check
    scripts/upload_datasets.sh
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from dataset_versions import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_DATA_DIR,
    FORMATS,
    copy_atomic,
    iter_config_paths,
    latest_path,
    latest_url,
    load_config,
    parse_version,
    sha256_file,
    version_path,
    version_url,
    versioned_downloads_enabled,
    write_config,
)


class ReleaseError(Exception):
    pass


def _config_paths(config_dir: Path, names: list[str]) -> list[Path]:
    paths = {path.parent.name: path for path in iter_config_paths(config_dir)}
    missing = [name for name in names if name not in paths]
    if missing:
        raise ReleaseError(f"unknown dataset(s): {', '.join(missing)}")
    return [paths[name] for name in names] if names else list(paths.values())


def _require_data_dir(data_dir: Path) -> None:
    if not data_dir.is_dir():
        raise ReleaseError(
            f"data directory not found: {data_dir} (is the dataset drive mounted?)"
        )


def _versions(config: dict, name: str) -> list[dict]:
    versions = config.get("versions")
    if not isinstance(versions, list) or not versions or not isinstance(versions[0], dict):
        raise ReleaseError(f"{name}: config has no versions list (run the site build once first)")
    return versions


# --------------------------------------------------------------------------- freeze


def freeze_dataset(config_path: Path, data_dir: Path, *, dry_run: bool) -> str:
    name = config_path.parent.name
    config = load_config(config_path)
    entry = _versions(config, name)[0]
    label = entry.get("version", "")
    try:
        parse_version(label)
    except ValueError as exc:
        raise ReleaseError(f"{name}: {exc}") from None

    actions: list[str] = []
    notes: list[str] = []
    for fmt in FORMATS:
        frozen = version_path(data_dir, name, label, fmt)
        latest = latest_path(data_dir, name, fmt)
        recorded = entry.get(f"{fmt}_sha256")

        if frozen.exists():
            digest = sha256_file(frozen)
            if recorded and recorded != digest:
                raise ReleaseError(f"{name}: {frozen} does not match the checksum recorded for {label}")
            if latest.exists() and sha256_file(latest) != digest:
                notes.append(f"latest {fmt} file differs from {label} (release it as a new version)")
            size = frozen.stat().st_size
        else:
            if not latest.exists():
                raise ReleaseError(f"{name}: missing {latest}")
            digest = sha256_file(latest)
            if recorded and recorded != digest:
                raise ReleaseError(
                    f"{name}: {latest} changed after {label} was recorded; release it as a new version"
                )
            if not dry_run:
                copy_atomic(latest, frozen)
                if sha256_file(frozen) != digest:
                    raise ReleaseError(f"{name}: copy verification failed for {frozen}")
            actions.append(f"copy {fmt} -> {label}/")
            size = latest.stat().st_size

        if entry.get(f"{fmt}_sha256") != digest or entry.get(f"{fmt}_download_size") != size:
            entry[f"{fmt}_download_size"] = size
            entry[f"{fmt}_sha256"] = digest
            actions.append(f"record {fmt} checksum")

    if actions and not dry_run:
        write_config(config_path, config)
    status = ", ".join(actions) if actions else "already frozen"
    if notes:
        status += " | note: " + "; ".join(notes)
    return f"{label}: {status}"


def cmd_freeze(args: argparse.Namespace) -> int:
    if not args.names and not args.all:
        raise ReleaseError("name one or more datasets, or pass --all")
    _require_data_dir(args.data_dir)
    failures = 0
    for config_path in _config_paths(args.config_dir, args.names):
        name = config_path.parent.name
        try:
            print(f"[OK] {name}: {freeze_dataset(config_path, args.data_dir, dry_run=args.dry_run)}")
        except ReleaseError as exc:
            failures += 1
            print(f"[ERROR] {exc}")
    if args.dry_run:
        print("Dry run: no files copied and no configs written.")
    return 1 if failures else 0


# -------------------------------------------------------------------------- release


def cmd_release(args: argparse.Namespace) -> int:
    _require_data_dir(args.data_dir)
    (config_path,) = _config_paths(args.config_dir, [args.name])
    name = args.name
    config = load_config(config_path)
    versions = _versions(config, name)
    current = versions[0]
    current_label = current.get("version", "")

    try:
        new_version = parse_version(args.version)
        if new_version <= parse_version(current_label):
            raise ReleaseError(
                f"{name}: version {args.version} must be greater than the current {current_label}"
            )
        dt.date.fromisoformat(args.date)
    except ValueError as exc:
        raise ReleaseError(f"{name}: {exc}") from None
    if not args.changes.strip():
        raise ReleaseError("--changes must describe what changed")

    # The previous release must already live in its own folder, otherwise
    # replacing the latest files would lose it.
    for fmt in FORMATS:
        frozen = version_path(args.data_dir, name, current_label, fmt)
        recorded = current.get(f"{fmt}_sha256")
        if not recorded or not frozen.exists():
            raise ReleaseError(
                f"{name}: version {current_label} is not frozen yet; run "
                f"`release_dataset.py freeze {name}` before replacing its files"
            )
        if sha256_file(frozen) != recorded:
            raise ReleaseError(f"{name}: {frozen} does not match the checksum recorded for {current_label}")

    sources = {
        "binary": args.hgx or latest_path(args.data_dir, name, "binary"),
        "json": args.json or latest_path(args.data_dir, name, "json"),
    }
    digests = {}
    for fmt, src in sources.items():
        if not src.is_file():
            raise ReleaseError(f"{name}: missing source file {src}")
        digests[fmt] = sha256_file(src)
    if all(digests[fmt] == current.get(f"{fmt}_sha256") for fmt in FORMATS):
        raise ReleaseError(f"{name}: files are identical to version {current_label}; nothing to release")

    new_dir = args.data_dir / name / args.version
    if new_dir.exists():
        raise ReleaseError(f"{name}: {new_dir} already exists")

    entry = {
        "version": args.version,
        "released": args.date,
        "changes": args.changes.strip(),
        "binary_download": version_url(name, args.version, "binary"),
        "json_download": version_url(name, args.version, "json"),
        "binary_download_size": sources["binary"].stat().st_size,
        "json_download_size": sources["json"].stat().st_size,
        "binary_sha256": digests["binary"],
        "json_sha256": digests["json"],
    }

    if args.dry_run:
        print(f"Dry run: would release {name} {args.version} (current {current_label}):")
        for fmt, src in sources.items():
            print(f"  {fmt}: {src} -> {version_path(args.data_dir, name, args.version, fmt)}")
        return 0

    for fmt, src in sources.items():
        frozen = version_path(args.data_dir, name, args.version, fmt)
        copy_atomic(src, frozen)
        if sha256_file(frozen) != digests[fmt]:
            raise ReleaseError(f"{name}: copy verification failed for {frozen}")
        latest = latest_path(args.data_dir, name, fmt)
        if src.resolve() != latest.resolve():
            copy_atomic(src, latest)

    versions.insert(0, entry)
    # Same URL rules as populate_with_links.py: older versions link to their
    # folders; the newest links to the latest alias unless versioned_downloads is on.
    for older in versions[1:]:
        for fmt in FORMATS:
            older[f"{fmt}_download"] = version_url(name, older["version"], fmt)
    if not versioned_downloads_enabled():
        for fmt in FORMATS:
            entry[f"{fmt}_download"] = latest_url(name, fmt)
    config["updated_at"] = args.date
    write_config(config_path, config)
    print(f"[OK] Released {name} {args.version} (previous: {current_label}).")
    print("Next: run `release_dataset.py check`, upload with scripts/upload_datasets.sh, then deploy the site.")
    return 0


# ---------------------------------------------------------------------------- check


def _remote_sha256(url: str, timeout: int) -> str:
    digest = hashlib.sha256()
    with urlopen(Request(url, headers={"User-Agent": "hypergraphx-data-release-check"}), timeout=timeout) as response:
        for chunk in iter(lambda: response.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cmd_check(args: argparse.Namespace) -> int:
    if not args.remote:
        _require_data_dir(args.data_dir)
    errors: list[str] = []
    unfrozen: list[str] = []
    checked = 0

    for config_path in _config_paths(args.config_dir, args.names):
        name = config_path.parent.name
        try:
            versions = _versions(load_config(config_path), name)
            labels = [entry.get("version", "") for entry in versions]
            parsed = [parse_version(label) for label in labels]
        except (ReleaseError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        if any(newer <= older for newer, older in zip(parsed, parsed[1:])):
            errors.append(f"{name}: versions must be newest first without duplicates ({', '.join(labels)})")

        for index, entry in enumerate(versions):
            label = entry["version"]
            for fmt in FORMATS:
                recorded = entry.get(f"{fmt}_sha256")
                if not recorded:
                    if index == 0:
                        if name not in unfrozen:
                            unfrozen.append(name)
                    else:
                        errors.append(f"{name} {label}: no {fmt} checksum recorded")
                    continue

                targets = [("version folder", version_path(args.data_dir, name, label, fmt), version_url(name, label, fmt))]
                if index == 0:
                    targets.append(("latest alias", latest_path(args.data_dir, name, fmt), latest_url(name, fmt)))
                for where, path, url in targets:
                    checked += 1
                    try:
                        if args.remote:
                            actual = _remote_sha256(url, args.timeout)
                        elif path.exists():
                            actual = sha256_file(path)
                        else:
                            errors.append(f"{name} {label}: missing {where} {fmt} file {path}")
                            continue
                    except Exception as exc:  # network errors in --remote mode
                        errors.append(f"{name} {label}: cannot read {url} ({exc})")
                        continue
                    if actual != recorded:
                        hint = " (unreleased changes? release a new version)" if where == "latest alias" else ""
                        errors.append(f"{name} {label}: {where} {fmt} file does not match its checksum{hint}")
        if args.remote:
            print(f"  checked {name}", file=sys.stderr)

    print(f"Checked {checked} file(s) {'on the server' if args.remote else 'locally'}.")
    if unfrozen:
        print(f"{len(unfrozen)} dataset(s) have no recorded checksums yet (run `freeze`): "
              + ", ".join(unfrozen[:10]) + (" ..." if len(unfrozen) > 10 else ""))
    for error in errors:
        print(f"[ERROR] {error}")
    return 1 if errors else 0


# ----------------------------------------------------------------------------- main


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help="Local dataset directory mirrored to the server (default: data/).")
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze", help="Archive the current files as their recorded version.")
    freeze.add_argument("names", nargs="*", help="Dataset names.")
    freeze.add_argument("--all", action="store_true", help="Freeze every dataset.")
    freeze.add_argument("--dry-run", action="store_true")
    freeze.set_defaults(func=cmd_freeze)

    release = sub.add_parser("release", help="Publish new files as a new version.")
    release.add_argument("name")
    release.add_argument("version", help="New MAJOR.MINOR.PATCH version.")
    release.add_argument("--changes", required=True, help="Short changelog for this version.")
    release.add_argument("--hgx", type=Path, help="New .hgx.gz file (default: the current latest file).")
    release.add_argument("--json", type=Path, help="New .json.gz file (default: the current latest file).")
    release.add_argument("--date", default=dt.date.today().isoformat(), help="Release date (YYYY-MM-DD).")
    release.add_argument("--dry-run", action="store_true")
    release.set_defaults(func=cmd_release)

    check = sub.add_parser("check", help="Verify files against recorded checksums.")
    check.add_argument("names", nargs="*", help="Dataset names (default: all).")
    check.add_argument("--remote", action="store_true", help="Download and verify the server's files instead.")
    check.add_argument("--timeout", type=int, default=60)
    check.set_defaults(func=cmd_check)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return args.func(args)
    except ReleaseError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
