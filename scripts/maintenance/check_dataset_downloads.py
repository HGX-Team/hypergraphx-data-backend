#!/usr/bin/env python3
"""Check dataset download links without downloading or loading datasets."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_DIR = REPO_ROOT / "resources" / "datasets_config"

DOWNLOAD_KEYS = (
    "binary_download",
    "hgx_download",
    "json_download",
)
SIZE_KEYS = {
    "binary_download": "binary_download_size",
    "hgx_download": "binary_download_size",
    "json_download": "json_download_size",
}


@dataclass(frozen=True)
class DownloadLink:
    dataset: str
    key: str
    url: str
    expected_size: int | None = None


@dataclass(frozen=True)
class Finding:
    level: str
    dataset: str
    url: str
    message: str


def _supports_progress() -> bool:
    return sys.stderr.isatty()


def _print_progress(current: int, total: int, *, width: int = 32) -> None:
    if total <= 0:
        return
    filled = int(width * current / total)
    bar = "#" * filled + "-" * (width - filled)
    percent = int(100 * current / total)
    end = "\n" if current == total else "\r"
    print(f"[{bar}] {current}/{total} ({percent:3d}%)", end=end, file=sys.stderr, flush=True)


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


def _positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _links_from_config(config_path: Path, *, all_versions: bool) -> list[DownloadLink]:
    dataset = config_path.parent.name
    config = json.loads(config_path.read_text(encoding="utf-8"))
    links: list[DownloadLink] = []

    versions = config.get("versions")
    if isinstance(versions, list):
        selected = versions if all_versions else versions[:1]
        for entry in selected:
            if not isinstance(entry, dict):
                continue
            for key in DOWNLOAD_KEYS:
                for url in _urls(entry.get(key)):
                    links.append(
                        DownloadLink(
                            dataset=dataset,
                            key=key,
                            url=url,
                            expected_size=_positive_int(entry.get(SIZE_KEYS[key])),
                        )
                    )
        return links

    for key in DOWNLOAD_KEYS:
        urls = _urls(config.get(key))
        if not all_versions:
            urls = urls[:1]
        for url in urls:
            links.append(
                DownloadLink(
                    dataset=dataset,
                    key=key,
                    url=url,
                    expected_size=_positive_int(config.get(SIZE_KEYS[key])),
                )
            )
    return links


def _ssl_context(insecure: bool):
    if insecure:
        return ssl._create_unverified_context()  # noqa: SLF001
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _request(url: str, *, method: str, timeout: int, insecure: bool):
    request = Request(url, method=method, headers={"User-Agent": "hypergraphx-data-checker/1.0"})
    return urlopen(request, timeout=timeout, context=_ssl_context(insecure))


def _content_length(headers) -> int | None:
    raw = headers.get("Content-Length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _check_link(link: DownloadLink, *, timeout: int, insecure: bool, allow_range_get: bool) -> list[Finding]:
    findings: list[Finding] = []
    parsed = urlparse(link.url)
    if parsed.scheme not in {"http", "https"}:
        return [
            Finding(
                "error",
                link.dataset,
                link.url,
                "download URL is not HTTP(S)",
            )
        ]

    try:
        with _request(link.url, method="HEAD", timeout=timeout, insecure=insecure) as response:
            status = response.status
            headers = response.headers
            method = "HEAD"
    except HTTPError as exc:
        if exc.code in {403, 405} and allow_range_get:
            try:
                request = Request(
                    link.url,
                    method="GET",
                    headers={
                        "Range": "bytes=0-0",
                        "User-Agent": "hypergraphx-data-checker/1.0",
                    },
                )
                with urlopen(request, timeout=timeout, context=_ssl_context(insecure)) as response:
                    status = response.status
                    headers = response.headers
                    method = "GET range"
            except Exception as range_exc:
                return [Finding("error", link.dataset, link.url, f"HEAD failed ({exc}); range GET failed ({range_exc})")]
        else:
            return [Finding("error", link.dataset, link.url, f"HTTP {exc.code}: {exc.reason}")]
    except URLError as exc:
        return [Finding("error", link.dataset, link.url, f"network error: {exc.reason}")]
    except Exception as exc:
        return [Finding("error", link.dataset, link.url, str(exc))]

    if status >= 400:
        findings.append(Finding("error", link.dataset, link.url, f"{method} returned HTTP {status}"))

    remote_size = _content_length(headers)
    if link.expected_size is not None and remote_size is not None and remote_size != link.expected_size:
        findings.append(
            Finding(
                "warn",
                link.dataset,
                link.url,
                f"Content-Length {remote_size} differs from configured {link.expected_size}",
            )
        )
    elif link.expected_size is not None and remote_size is None:
        findings.append(Finding("warn", link.dataset, link.url, "Content-Length is missing; configured size could not be checked"))

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check dataset download links without downloading files or loading them in HypergraphX."
    )
    parser.add_argument("--config-dir", type=Path, default=DEFAULT_CONFIG_DIR)
    parser.add_argument("--only", nargs="*", default=[], help="Only check these dataset ids.")
    parser.add_argument("--all-versions", action="store_true", help="Check all configured versions, not just the first.")
    parser.add_argument("--timeout", type=int, default=20, help="Per-request timeout in seconds.")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS certificate verification.")
    parser.add_argument(
        "--no-range-get",
        action="store_true",
        help="Do not fall back to a one-byte range GET when HEAD is blocked.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print each checked URL and its result.")
    parser.add_argument("--no-progress", action="store_true", help="Disable the progress bar.")
    args = parser.parse_args()

    if not args.config_dir.exists():
        print(f"Config dir not found: {args.config_dir}", file=sys.stderr)
        return 2

    only: set[str] = {item.strip() for item in args.only if item.strip()}
    config_paths = list(_iter_dataset_config_paths(args.config_dir))
    if only:
        config_paths = [path for path in config_paths if path.parent.name in only]

    if not config_paths:
        print("No dataset configs found.")
        return 0

    links: list[DownloadLink] = []
    findings: list[Finding] = []
    for config_path in config_paths:
        try:
            config_links = _links_from_config(config_path, all_versions=args.all_versions)
        except Exception as exc:
            findings.append(Finding("error", config_path.parent.name, str(config_path), f"invalid config: {exc}"))
            continue
        if not config_links:
            findings.append(Finding("warn", config_path.parent.name, str(config_path), "no download links configured"))
        links.extend(config_links)

    show_progress = not args.no_progress and not args.verbose and _supports_progress()
    if show_progress:
        _print_progress(0, len(links))

    for index, link in enumerate(links, start=1):
        if args.verbose:
            print(f"[{index}/{len(links)}] {link.dataset} {link.key}: {link.url}")
        link_findings = _check_link(
            link,
            timeout=args.timeout,
            insecure=args.insecure,
            allow_range_get=not args.no_range_get,
        )
        if args.verbose and not link_findings:
            print("  OK")
        elif args.verbose:
            for finding in link_findings:
                print(f"  {finding.level.upper()}: {finding.message}")
        findings.extend(link_findings)
        if show_progress:
            _print_progress(index, len(links))

    errors = [finding for finding in findings if finding.level == "error"]
    warnings = [finding for finding in findings if finding.level == "warn"]

    print("\nSummary")
    print("-------")
    print(f"Configs checked: {len(config_paths)}")
    print(f"Links checked:   {len(links)}")
    print(f"Errors:          {len(errors)}")
    print(f"Warnings:        {len(warnings)}")

    if findings:
        print("\nFindings:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding.level.upper()} {finding.dataset}: {finding.message} ({finding.url})", file=sys.stderr)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
