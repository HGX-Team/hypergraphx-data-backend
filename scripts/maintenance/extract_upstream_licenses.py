#!/usr/bin/env python3
"""
Extract upstream license evidence for datasets.

Strategy (best effort):
- Read local reproducibility README (if present) for license mentions.
- Parse dataset config `source` field for URLs.
- For GitHub sources, fetch raw LICENSE/README (tries main/master, plus branch from URL).
- For generic web sources, fetch HTML and search for recognizable license markers.

Outputs a JSON report with evidence URLs and inferred license IDs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urlparse, urljoin, parse_qs, urlencode


REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "resources" / "datasets_config"
REPRO_DIR = REPO_ROOT / "reproducibility"


URL_RE = re.compile(r"https?://[^\s)\"'>]+", re.IGNORECASE)
HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


LICENSE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("CC0-1.0", re.compile(r"creativecommons\.org/publicdomain/zero/1\.0", re.I)),
    ("CC-BY-4.0", re.compile(r"creativecommons\.org/licenses/by/4\.0", re.I)),
    ("CC-BY-3.0", re.compile(r"creativecommons\.org/licenses/by/3\.0", re.I)),
    ("CC-BY-SA-4.0", re.compile(r"creativecommons\.org/licenses/by-sa/4\.0", re.I)),
    ("CC-BY-NC-4.0", re.compile(r"creativecommons\.org/licenses/by-nc/4\.0", re.I)),
    ("CC-BY-NC-SA-3.0", re.compile(r"creativecommons\.org/licenses/by-nc-sa/3\.0", re.I)),
    ("CC-BY-NC-SA-4.0", re.compile(r"creativecommons\.org/licenses/by-nc-sa/4\.0", re.I)),
    ("MIT", re.compile(r"\bmit license\b", re.I)),
    ("Apache-2.0", re.compile(r"apache license\s*,?\s*version\s*2\.0", re.I)),
    ("GPL-3.0-only", re.compile(r"gnu (?:general public license|gpl)\s*(?:version\s*)?3", re.I)),
    # SPDX-ish markers
    ("MIT", re.compile(r"SPDX-License-Identifier:\\s*MIT", re.I)),
    ("Apache-2.0", re.compile(r"SPDX-License-Identifier:\\s*Apache-2\\.0", re.I)),
    ("GPL-3.0-only", re.compile(r"SPDX-License-Identifier:\\s*GPL-3\\.0-only", re.I)),
    ("GPL-3.0-or-later", re.compile(r"SPDX-License-Identifier:\\s*GPL-3\\.0-or-later", re.I)),
]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _urls_from_source(source: str) -> list[str]:
    if not source:
        return []
    urls = []
    for u in URL_RE.findall(source):
        urls.append(u.rstrip(".,;]"))
    # De-dup preserving order
    return list(dict.fromkeys(urls))


def _fetch(url: str, timeout: float) -> Optional[str]:
    if not hasattr(_fetch, "_cache"):
        _fetch._cache = {}  # type: ignore[attr-defined]
    cache: dict[str, Optional[str]] = _fetch._cache  # type: ignore[attr-defined]
    if url in cache:
        return cache[url]

    req = urllib.request.Request(url, headers={"User-Agent": "hypergraphx-data-license-audit/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
    except urllib.error.HTTPError as e:
        cache[url] = None
        return None
    except urllib.error.URLError:
        cache[url] = None
        return None
    except Exception:
        cache[url] = None
        return None

    try:
        # Default to utf-8; tolerate replacement.
        text = raw.decode("utf-8", errors="replace")
    except Exception:
        cache[url] = None
        return None

    if "text" in content_type or "json" in content_type or "xml" in content_type or not content_type:
        cache[url] = text
        return text
    cache[url] = text
    return text


def _guess_license_ids(text: str) -> list[str]:
    if not text:
        return []
    hits: list[str] = []
    for lic, pattern in LICENSE_PATTERNS:
        if pattern.search(text):
            hits.append(lic)
    # De-dup preserving order
    out: list[str] = []
    for h in hits:
        if h not in out:
            out.append(h)
    return out


def _extract_links_from_html(html: str, base_url: str) -> list[str]:
    if not html:
        return []
    links: list[str] = []
    for raw in HREF_RE.findall(html):
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        abs_url = urljoin(base_url, raw)
        if abs_url.startswith("http://") or abs_url.startswith("https://"):
            parsed = urlparse(abs_url)
            path_lower = (parsed.path or "").lower()
            if path_lower.endswith((".css", ".js", ".ico", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".woff2")):
                continue
            links.append(abs_url)
    # De-dup preserving order
    return list(dict.fromkeys(links))


def _drive_file_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in ("drive.google.com", "docs.google.com"):
        return None

    qs = parse_qs(parsed.query or "")
    if "id" in qs and qs["id"]:
        return qs["id"][0]

    parts = [p for p in parsed.path.split("/") if p]
    # /file/d/<id>/view
    if len(parts) >= 3 and parts[0] == "file" and parts[1] == "d":
        return parts[2]
    return None


def _download_drive_file(
    file_id: str, timeout: float, max_bytes: int, sleep_s: float
) -> Optional[Path]:
    """
    Best-effort public Google Drive download. Returns a local filepath, or None.
    """
    base = "https://drive.google.com/uc?export=download&id=" + file_id
    jar = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def open_url(url: str) -> tuple[Optional[bytes], Optional[str]]:
        req = urllib.request.Request(url, headers={"User-Agent": "hypergraphx-data-license-audit/1.0"})
        try:
            with opener.open(req, timeout=timeout) as resp:
                content_type = resp.headers.get("Content-Type", "")
                # Read a small probe first.
                probe = resp.read(8192)
                if probe.startswith(b"PK"):
                    return probe, content_type
                # If it's HTML, keep reading (small) to search for confirm token.
                if b"<html" in probe.lower() or b"<!doctype html" in probe.lower() or "text/html" in content_type:
                    rest = resp.read(256_000)
                    return probe + rest, content_type
                return probe, content_type
        except Exception:
            return None, None

    probe, ctype = open_url(base)
    time.sleep(sleep_s)
    if probe is None:
        return None

    download_url = base
    if not probe.startswith(b"PK"):
        html = probe.decode("utf-8", errors="replace")

        # Virus scan warning pages embed a form with confirm + uuid.
        form_action_match = re.search(r'<form[^>]+id="download-form"[^>]+action="([^"]+)"', html)
        if form_action_match:
            action = form_action_match.group(1)
            hidden = dict(re.findall(r'<input[^>]+type="hidden"[^>]+name="([^"]+)"[^>]+value="([^"]*)"', html))
            if hidden:
                # Ensure required fields.
                hidden.setdefault("id", file_id)
                hidden.setdefault("export", "download")
                download_url = action + "?" + urlencode(hidden)
            else:
                return None
        else:
            # Sometimes Drive serves HTML interstitial with a confirm token in URL.
            confirm_match = re.search(r"confirm=([0-9A-Za-z_-]+)", html)
            token: Optional[str] = confirm_match.group(1) if confirm_match else None
            if not token:
                # Sometimes token is stored in cookies (download_warning).
                for cookie in jar:
                    if cookie.name.startswith("download_warning") and cookie.value:
                        token = cookie.value
                        break
            if token:
                download_url = f"https://drive.google.com/uc?export=download&confirm={token}&id={file_id}"
            else:
                return None

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".bin")
    tmp_path = Path(tmp.name)
    tmp.close()

    req = urllib.request.Request(download_url, headers={"User-Agent": "hypergraphx-data-license-audit/1.0"})
    try:
        with opener.open(req, timeout=timeout) as resp, open(tmp_path, "wb") as f:
            read = 0
            while True:
                chunk = resp.read(1024 * 64)
                if not chunk:
                    break
                read += len(chunk)
                if read > max_bytes:
                    try:
                        tmp_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return None
                f.write(chunk)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    # Verify it's actually a ZIP; Drive sometimes returns HTML interstitials.
    try:
        head = tmp_path.read_bytes()[:8]
    except Exception:
        head = b""
    if not head.startswith(b"PK"):
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None
    return tmp_path


@dataclass
class ZipInspection:
    license_ids: list[str]
    matched_filenames: list[str]
    error: Optional[str] = None


def _inspect_zip_for_license(path: Path, max_file_bytes: int = 512_000) -> ZipInspection:
    ids: list[str] = []
    matched: list[str] = []
    try:
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                basename = Path(info.filename).name.upper()
                if not any(k in basename for k in ("LICENSE", "COPYING", "NOTICE", "TERMS", "README")):
                    continue
                matched.append(info.filename)
                if info.file_size > max_file_bytes:
                    continue
                with zf.open(info) as f:
                    content = f.read(max_file_bytes).decode("utf-8", errors="replace")
                for lid in _guess_license_ids(content):
                    if lid not in ids:
                        ids.append(lid)
    except Exception as e:
        return ZipInspection(license_ids=[], matched_filenames=[], error=str(e))
    return ZipInspection(license_ids=ids, matched_filenames=matched)


def _parse_github_repo(url: str) -> Optional[tuple[str, str, Optional[str]]]:
    """
    Returns (owner, repo, branch) if URL is github.com/{owner}/{repo}[...].
    """
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    owner, repo = parts[0], parts[1]
    branch: Optional[str] = None
    if len(parts) >= 4 and parts[2] in ("tree", "blob"):
        branch = parts[3]
    return owner, repo, branch


def _github_raw(owner: str, repo: str, branch: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path.lstrip('/')}"


def _github_candidate_files() -> list[str]:
    return [
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "COPYING",
        "COPYING.txt",
        "README.md",
        "README",
    ]


@dataclass
class Evidence:
    url: str
    kind: str  # "local-readme" | "github-raw" | "html"
    sha256: Optional[str] = None
    license_ids: list[str] = None  # type: ignore[assignment]
    note: Optional[str] = None


@dataclass
class DatasetReport:
    dataset: str
    config_path: str
    source: str
    config_license: str
    inferred_license_ids: list[str]
    evidence: list[Evidence]
    status: str  # "ok" | "no-evidence" | "ambiguous" | "mismatch"


def _local_repro_license_evidence(dataset: str) -> Optional[Evidence]:
    readme = REPRO_DIR / dataset / "README.md"
    text = _read_text(readme)
    if not text:
        return None
    ids = _guess_license_ids(text)
    if not ids:
        return None
    return Evidence(url=str(readme), kind="local-readme", sha256=_sha256(text), license_ids=ids)


def _fetch_github_evidence(urls: list[str], timeout: float, sleep_s: float) -> list[Evidence]:
    evidence: list[Evidence] = []
    seen = set()

    for url in urls:
        parsed = _parse_github_repo(url)
        if not parsed:
            continue
        owner, repo, url_branch = parsed
        branches = [b for b in [url_branch, "main", "master"] if b]
        for branch in branches:
            for path in _github_candidate_files():
                raw_url = _github_raw(owner, repo, branch, path)
                key = (raw_url,)
                if key in seen:
                    continue
                seen.add(key)
                text = _fetch(raw_url, timeout=timeout)
                time.sleep(sleep_s)
                if not text:
                    continue
                ids = _guess_license_ids(text)
                if not ids:
                    # Keep LICENSE/README evidence even if we fail to detect;
                    # the report still helps humans inspect.
                    evidence.append(
                        Evidence(
                            url=raw_url,
                            kind="github-raw",
                            sha256=_sha256(text),
                            license_ids=[],
                            note="fetched but no license markers detected",
                        )
                    )
                    continue
                evidence.append(Evidence(url=raw_url, kind="github-raw", sha256=_sha256(text), license_ids=ids))
    return evidence


def _fetch_html_evidence(
    urls: list[str],
    timeout: float,
    sleep_s: float,
    max_pages: int,
    follow_drive: bool,
    max_download_bytes: int,
) -> list[Evidence]:
    evidence: list[Evidence] = []
    seen: set[str] = set()
    fetched_pages = 0
    queue = list(urls)
    while queue and fetched_pages < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)

        text = _fetch(url, timeout=timeout)
        time.sleep(sleep_s)
        fetched_pages += 1
        if not text:
            continue

        ids = _guess_license_ids(text)
        if not ids:
            evidence.append(
                Evidence(
                    url=url,
                    kind="html",
                    sha256=_sha256(text),
                    license_ids=[],
                    note="fetched but no license markers detected",
                )
            )
        else:
            evidence.append(Evidence(url=url, kind="html", sha256=_sha256(text), license_ids=ids))
            break

        # Discover links to follow (helps Benson pages that link out to Kaggle/Drive).
        for link in _extract_links_from_html(text, base_url=url):
            netloc = urlparse(link).netloc.lower()
            if "kaggle.com" in netloc:
                queue.append(link)
            if follow_drive and netloc in ("drive.google.com", "docs.google.com"):
                file_id = _drive_file_id(link)
                if not file_id:
                    continue
                local = _download_drive_file(
                    file_id, timeout=timeout, max_bytes=max_download_bytes, sleep_s=sleep_s
                )
                if not local:
                    evidence.append(
                        Evidence(
                            url=link,
                            kind="drive-zip",
                            sha256=None,
                            license_ids=[],
                            note="could not download as a zip (blocked/too large/unavailable or non-zip response)",
                        )
                    )
                    continue
                try:
                    inspection = _inspect_zip_for_license(local)
                finally:
                    try:
                        local.unlink(missing_ok=True)
                    except Exception:
                        pass
                evidence.append(
                    Evidence(
                        url=link,
                        kind="drive-zip",
                        sha256=None,
                        license_ids=inspection.license_ids,
                        note=(
                            ("zip error: " + inspection.error + "; " if inspection.error else "")
                            + "matched files: "
                            + (", ".join(inspection.matched_filenames[:20]) if inspection.matched_filenames else "(none)")
                        ),
                    )
                )
                if inspection.license_ids:
                    break
        if evidence and evidence[-1].kind == "drive-zip" and evidence[-1].license_ids:
            break
    return evidence


def _aggregate_inferred_ids(evidence: Iterable[Evidence]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for ev in evidence:
        for lid in ev.license_ids or []:
            if lid not in seen:
                seen.add(lid)
                out.append(lid)
    return out


def _iter_configs() -> Iterable[tuple[str, Path]]:
    for d in sorted(CONFIG_DIR.iterdir()):
        if not d.is_dir():
            continue
        p = d / f"config_{d.name}.json"
        if p.exists():
            yield d.name, p


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract upstream license evidence for datasets.")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--sleep", type=float, default=0.2, help="Sleep between requests (seconds).")
    parser.add_argument("--max-html-pages", type=int, default=2, help="Max non-GitHub pages fetched per dataset.")
    parser.add_argument("--follow-drive", action="store_true", help="Try downloading public Google Drive archives and inspect for LICENSE/README.")
    parser.add_argument("--max-download-mb", type=int, default=25, help="Max size to download from Google Drive (MB).")
    parser.add_argument("--only-populated", action="store_true", help="Only datasets with `license` set in config.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of datasets (0 = no limit).")
    parser.add_argument("--dataset", action="append", default=[], help="Only run for a specific dataset name (repeatable).")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "resources" / "licenses_report.json")
    args = parser.parse_args()

    wanted = set(args.dataset or [])
    max_download_bytes = int(args.max_download_mb) * 1024 * 1024

    reports: list[DatasetReport] = []
    for dataset, config_path in _iter_configs():
        if wanted and dataset not in wanted:
            continue
        config = json.loads(config_path.read_text(encoding="utf-8"))
        source = (config.get("source") or "").strip()
        config_license = (config.get("license") or "").strip()
        if args.only_populated and not config_license:
            continue

        urls = _urls_from_source(source)

        evidence: list[Evidence] = []
        local_ev = _local_repro_license_evidence(dataset)
        if local_ev:
            evidence.append(local_ev)

        evidence.extend(_fetch_github_evidence(urls, timeout=args.timeout, sleep_s=args.sleep))
        evidence.extend(
            _fetch_html_evidence(
                urls,
                timeout=args.timeout,
                sleep_s=args.sleep,
                max_pages=args.max_html_pages,
                follow_drive=args.follow_drive,
                max_download_bytes=max_download_bytes,
            )
        )

        inferred = _aggregate_inferred_ids(evidence)

        status = "ok"
        if not evidence:
            status = "no-evidence"
        elif not inferred:
            status = "unknown"
        elif len(inferred) > 1:
            status = "ambiguous"
        elif config_license and config_license not in inferred:
            status = "mismatch"

        reports.append(
            DatasetReport(
                dataset=dataset,
                config_path=str(config_path.relative_to(REPO_ROOT)),
                source=source,
                config_license=config_license,
                inferred_license_ids=inferred,
                evidence=evidence,
                status=status,
            )
        )

        if args.limit and len(reports) >= args.limit:
            break

    args.out.write_text(
        json.dumps([asdict(r) for r in reports], indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    counts: dict[str, int] = {}
    for r in reports:
        counts[r.status] = counts.get(r.status, 0) + 1

    print(f"Wrote: {args.out}")
    print("Status counts:", counts)

    mismatches = [r for r in reports if r.status == "mismatch"]
    ambiguous = [r for r in reports if r.status == "ambiguous"]
    no_ev = [r for r in reports if r.status == "no-evidence"]
    if mismatches:
        print("\nMismatches:")
        for r in mismatches[:25]:
            print(f"- {r.dataset}: config={r.config_license!r} inferred={r.inferred_license_ids}")
    if ambiguous:
        print("\nAmbiguous:")
        for r in ambiguous[:25]:
            print(f"- {r.dataset}: inferred={r.inferred_license_ids}")
    if no_ev:
        print("\nNo evidence (sample):")
        for r in no_ev[:25]:
            print(f"- {r.dataset}: source={r.source[:80]!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
