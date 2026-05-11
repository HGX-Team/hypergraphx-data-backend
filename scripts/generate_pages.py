import os
import json
import urllib.request
import ssl
import html
from datetime import date
from pathlib import Path
from urllib.parse import urlparse, quote

# Paths
REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = (REPO_ROOT / os.getenv("SITE_DIST_DIR", "dist")).resolve()
DIST_DIR.mkdir(parents=True, exist_ok=True)
DATASETS_DIR = REPO_ROOT / 'resources' / 'datasets_config'
DATASETS_STATS_DIR = REPO_ROOT / 'resources' / 'datasets_statistics'
OUTPUT_DIR = DIST_DIR / 'datasets'
OUTPUT_DIR_NAME = 'datasets'
INDEX_TEMPLATE = REPO_ROOT / 'templates' / 'index_template.html'
INDEX_FILE = DIST_DIR / 'index.html'
DATASET_TEMPLATE = REPO_ROOT / 'templates' / 'dataset_template.html'
RELATED_DATA_FILE = DIST_DIR / 'static' / 'js' / 'related-data.js'
RECENT_LIMIT = 5
RECENT_DAYS = 90
REPRODUCIBILITY_DIR = REPO_ROOT / 'reproducibility'
SITE_CONFIG_FILE = REPO_ROOT / 'site_config.json'

FETCH_REMOTE_SIZES = os.getenv("FETCH_REMOTE_SIZES") == "1"
FETCH_REMOTE_SIZES_TIMEOUT = float(os.getenv("FETCH_REMOTE_SIZES_TIMEOUT", "2"))
FETCH_REMOTE_SIZES_MAX = int(os.getenv("FETCH_REMOTE_SIZES_MAX", "0"))
FETCH_REMOTE_SIZES_INSECURE = os.getenv("FETCH_REMOTE_SIZES_INSECURE") == "1"
FETCH_REMOTE_SIZES_WRITE = os.getenv("FETCH_REMOTE_SIZES_WRITE") == "1"

def _as_str(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)

def _escape_html_text(value):
    return html.escape(_as_str(value), quote=False)

def _escape_html_attr(value):
    return html.escape(_as_str(value), quote=True)

def _escape_stat(value):
    return _escape_html_text(value)

def _safe_external_href(url):
    parsed = urlparse(url)
    if parsed.scheme in ("http", "https"):
        return url
    return ""

# Load datasets from the datasets directory
def load_datasets():
    datasets = []
    for directory in sorted(os.listdir(DATASETS_DIR)):
        dir_path = os.path.join(DATASETS_DIR, directory)
        
        # Ensure we're only looking at directories
        if os.path.isdir(dir_path):
            json_file = os.path.join(dir_path, f"config_{directory}.json")
            print(json_file)
            # Check if the expected .json file exists in the directory
            if os.path.isfile(json_file):
                with open(json_file, 'r') as f:
                    dataset = json.load(f)
                    dataset['filename'] = directory  # Add directory name for links
                    dataset['_mtime'] = os.path.getmtime(json_file)
                    dataset['_config_path'] = json_file

                bibtex_file = os.path.join(dir_path, f"{directory}.bib")
                if os.path.isfile(bibtex_file):
                    with open(bibtex_file, 'r') as f:
                        dataset['bibtex'] = f.read()
                datasets.append(dataset)
        
    return datasets

# Generate a row for the table in index.html
def _status_badge_class(status):
    normalized = _as_str(status).strip().lower()
    if normalized == "new":
        return "bg-success"
    if normalized == "updated":
        return "bg-warning text-dark"
    return "bg-secondary"

def _parse_iso_date(value):
    text = _as_str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None

def _recent_window_days():
    try:
        return int(SITE_CONFIG.get("recent_dataset_days", RECENT_DAYS))
    except (TypeError, ValueError):
        return RECENT_DAYS

def _recent_limit():
    try:
        return int(SITE_CONFIG.get("recent_dataset_limit", RECENT_LIMIT))
    except (TypeError, ValueError):
        return RECENT_LIMIT

def _dataset_recent_status(dataset, today):
    created_at = _parse_iso_date(dataset.get("created_at"))
    updated_at = _parse_iso_date(dataset.get("updated_at"))
    window_days = _recent_window_days()

    if created_at and 0 <= (today - created_at).days <= window_days:
        return "New", created_at

    if updated_at and 0 <= (today - updated_at).days <= window_days:
        if not created_at or updated_at > created_at:
            return "Updated", updated_at

    return None, None

def _recent_dataset_entries(datasets):
    by_name = {dataset.get("name"): dataset for dataset in datasets}
    by_filename = {dataset.get("filename"): dataset for dataset in datasets}
    today = date.today()
    entries = []

    for dataset in datasets:
        status, status_date = _dataset_recent_status(dataset, today)
        if status and status_date:
            entries.append({"dataset": dataset, "status": status, "date": status_date})

    overrides = SITE_CONFIG.get("recent_dataset_overrides") or []
    for item in overrides:
        if isinstance(item, str):
            name = item
            status = "New"
            status_date = today
        elif isinstance(item, dict):
            name = item.get("name") or item.get("dataset") or item.get("filename")
            status = item.get("status") or item.get("label") or "New"
            status_date = _parse_iso_date(item.get("date")) or today
        else:
            continue

        dataset = by_name.get(name) or by_filename.get(name)
        if dataset:
            entries = [entry for entry in entries if entry["dataset"] is not dataset]
            entries.append({
                "dataset": dataset,
                "status": _as_str(status).strip() or "New",
                "date": status_date,
            })

    def sort_key(entry):
        status_priority = 1 if _as_str(entry["status"]).strip().lower() == "new" else 0
        return (entry["date"], status_priority, entry["dataset"]["name"])

    return sorted(entries, key=sort_key, reverse=True)

# Generate a row for the table in index.html
def generate_table_row(dataset, recent_statuses):
    tags_html = ' '.join([
        f'<span class="tag">{_escape_html_text(_as_str(tag).capitalize())}</span>'
        for tag in dataset['tags']
    ])
    recent_badge = ''
    recent_status = recent_statuses.get(dataset['name'])
    if recent_status:
        badge_class = _status_badge_class(recent_status)
        escaped_status = _escape_html_text(recent_status)
        aria_label = "Newly added dataset" if recent_status.lower() == "new" else f"Recently {recent_status.lower()} dataset"
        recent_badge = (
            f' <span class="badge {badge_class} ms-2" '
            f'aria-label="{_escape_html_attr(aria_label)}">{escaped_status}</span>'
        )
    def meta_count(value):
        return len(value) if isinstance(value, dict) else 0
    total_meta = (
        meta_count(dataset.get('nodes_metadata')) +
        meta_count(dataset.get('edges_metadata')) +
        meta_count(dataset.get('hypergraph_metadata'))
    )
    meta_badge = ''
    if total_meta >= 6:
        meta_badge = ' <span class="badge bg-info ms-2" aria-label="Metadata rich dataset">Metadata-rich</span>'
    data_tags = ', '.join(_as_str(tag) for tag in dataset['tags'])
    data_license = _as_str(dataset.get("license") or "").strip()
    data_search = " ".join(
        part for part in [
            _as_str(dataset.get("name")),
            " ".join(_as_str(tag) for tag in dataset.get("tags", [])),
        ]
        if part
    )
    return f'''
    <tr data-tags="{_escape_html_attr(data_tags)}" data-license="{_escape_html_attr(data_license)}" data-name="{_escape_html_attr(dataset['name'])}" data-search="{_escape_html_attr(data_search)}">
        <td><a href="{OUTPUT_DIR_NAME}/{_escape_html_attr(dataset['filename'])}.html">{_escape_html_text(dataset['name'])}</a>{recent_badge}{meta_badge}</td>
        <td>{tags_html}</td>
        <td>{_escape_stat(dataset['vertices'])}</td>
        <td>{_escape_stat(dataset['edges'])}</td>
        <td>{_escape_stat(dataset['unique_edges'])}</td>
    </tr>
    '''

def generate_metadata_table(metadata, title):
    """Generates an HTML table for a given metadata dictionary with enhanced styling."""
    if not metadata:
        return ""  # Return empty string if metadata doesn't exist

    icon_map = {
        "Hypergraph metadata": "fa-table",
        "Node metadata": "fa-table",
        "Hyperedge metadata": "fa-table",
    }
    icon_class = icon_map.get(title, "fa-table")

    table_html = f"""
    <div class="mb-4">
        <h4 class="metadata-title"><i class="fa-solid {icon_class} section-title-icon"></i> {title}</h4>
        <table class="table table-hover custom-metadata-table">
            <thead>
                <tr><th>Property</th><th>Description</th></tr>
            </thead>
            <tbody>
    """
    
    for key, description in metadata.items():
        table_html += (
            f"<tr><td><b>{_escape_html_text(key)}</b></td>"
            f"<td>{_escape_html_text(description)}</td></tr>"
        )

    table_html += "</tbody></table></div>"
    return table_html

def generate_versions_section(dataset):
    """Generates the HTML for dataset versions dynamically."""
    versions = normalize_dataset_versions(dataset)

    versions_html = '<div class="mb-3">\n<h4><i class="fa-solid fa-download section-title-icon"></i> Download</h4>\n<ul class="versions-list">\n'

    def format_size(value):
        try:
            size = float(value)
        except (TypeError, ValueError):
            return ''
        suffixes = ['B', 'KB', 'MB', 'GB', 'TB']
        idx = 0
        while size >= 1024 and idx < len(suffixes) - 1:
            size /= 1024.0
            idx += 1
        return f"{size:.1f} {suffixes[idx]}"

    for entry in versions:
        bin_size = format_size(entry.get("binary_download_size"))
        json_size = format_size(entry.get("json_download_size"))
        bin_label = f'Binary <span class="download-size">({bin_size})</span>' if bin_size else "Binary"
        json_label = f'JSON <span class="download-size">({json_size})</span>' if json_size else "JSON"
        binary_href = _escape_html_attr(_safe_external_href(_as_str(entry.get("binary_download"))))
        json_href = _escape_html_attr(_safe_external_href(_as_str(entry.get("json_download"))))
        version_label = _escape_html_text(entry.get("version") or "1.0.0")
        versions_html += f'''
        <li>
            <span class="version-label">Version {version_label}</span>
            <a href="{binary_href}" target="_blank" rel="noopener noreferrer">
                <i class="fa-solid fa-file-zipper"></i> {bin_label}
            </a>
            <a href="{json_href}" target="_blank" rel="noopener noreferrer">
                <i class="fa-solid fa-file-alt"></i> {json_label}
            </a>
        </li>
        '''

    versions_html += '</ul>\n</div>\n'
    return versions_html

def normalize_dataset_versions(dataset):
    """Return download versions in canonical order, most recent first."""
    versions = dataset.get("versions")
    if isinstance(versions, list):
        normalized = []
        for entry in versions:
            if not isinstance(entry, dict):
                continue
            binary_url = entry.get("binary_download") or entry.get("hgx_download")
            json_url = entry.get("json_download")
            if not binary_url and not json_url:
                continue
            normalized.append({
                "version": entry.get("version") or "1.0.0",
                "binary_download": binary_url,
                "json_download": json_url,
                "binary_download_size": entry.get("binary_download_size") or entry.get("hgx_download_size"),
                "json_download_size": entry.get("json_download_size"),
            })
        if normalized:
            return normalized

    binary_links = dataset.get("binary_download", [])
    json_links = dataset.get("json_download", [])
    binary_sizes = dataset.get("binary_download_size", dataset.get("binary_download_sizes", []))
    json_sizes = dataset.get("json_download_size", dataset.get("json_download_sizes", []))
    num_versions = min(len(binary_links), len(json_links))
    fallback_versions = []
    for i in range(num_versions):
        fallback_versions.append({
            "version": f"{num_versions - i}.0.0",
            "binary_download": binary_links[i],
            "json_download": json_links[i],
            "binary_download_size": binary_sizes[i] if i < len(binary_sizes) else None,
            "json_download_size": json_sizes[i] if i < len(json_sizes) else None,
        })
    return fallback_versions

def load_site_config():
    if not SITE_CONFIG_FILE.exists():
        return {}
    try:
        with open(SITE_CONFIG_FILE, "r") as handle:
            return json.load(handle)
    except Exception:
        return {}

SITE_CONFIG = load_site_config()
REPO_URL_BASE = (SITE_CONFIG.get("github_repo_url_base") or "").strip().rstrip("/")
REPO_ISSUES_URL = (SITE_CONFIG.get("github_repo_issues_url") or "").strip() or (
    f"{REPO_URL_BASE}/issues" if REPO_URL_BASE else "https://github.com/HGX-Team/hypergraphx-data/issues"
)

# License badge styling: license_id -> (display_text, bootstrap_class)
LICENSE_BADGES = {
    "CC0-1.0": ("CC0 Public Domain", "bg-success"),
    "CC-BY-3.0": ("CC BY 3.0", "bg-success"),
    "CC-BY-4.0": ("CC BY 4.0", "bg-success"),
    "CC-BY-SA-4.0": ("CC BY-SA 4.0", "bg-success"),
    "CC-BY-NC-4.0": ("CC BY-NC 4.0", "bg-warning text-dark"),
    "CC-BY-NC-SA-3.0": ("CC BY-NC-SA 3.0", "bg-warning text-dark"),
    "CC-BY-NC-SA-4.0": ("CC BY-NC-SA 4.0", "bg-warning text-dark"),
    "MIT": ("MIT", "bg-success"),
    "BSD-3-Clause": ("BSD 3-Clause", "bg-success"),
    "GPL-3.0": ("GPL 3.0", "bg-info text-dark"),
    "GPL-3.0-only": ("GPL 3.0 (only)", "bg-info text-dark"),
    "Apache-2.0": ("Apache 2.0", "bg-success"),
    "ODC-BY": ("ODC-BY", "bg-success"),
    "ODbL": ("ODbL", "bg-success"),
    "Research-only": ("Research Only", "bg-warning text-dark"),
    "Unknown": ("Unknown", "bg-secondary"),
    "Custom": ("Custom", "bg-info text-dark"),
}

def generate_provenance_section(dataset):
    source = (dataset.get("source") or "").strip()
    reproducibility_link = (dataset.get("reproducibility_link") or "").strip()
    repro_readme = REPRODUCIBILITY_DIR / dataset["filename"] / "README.md"
    license_id = (dataset.get("license") or "").strip()
    license_url = (dataset.get("license_url") or "").strip()
    license_note = (dataset.get("license_note") or "").strip()

    if not reproducibility_link and REPO_URL_BASE:
        reproducibility_link = f"{REPO_URL_BASE}/tree/main/reproducibility/{dataset['filename']}"

    lines = []

    # Source
    if source:
        safe_source = _safe_external_href(source)
        if safe_source:
            href = _escape_html_attr(safe_source)
            label = _escape_html_text(safe_source)
            lines.append(
                f'<p><strong>Source:</strong> <a href="{href}" target="_blank" rel="noopener noreferrer">{label}</a></p>'
            )
        else:
            lines.append(f'<p><strong>Source:</strong> {_escape_html_text(source)}</p>')
    else:
        lines.append('<p><strong>Source:</strong> <span class="text-muted">Not provided.</span></p>')

    # License
    if license_id:
        badge_text, badge_class = LICENSE_BADGES.get(license_id, (license_id, "bg-secondary"))
        badge_html = f'<span class="badge {badge_class}">{_escape_html_text(badge_text)}</span>'
        if license_url:
            safe_license_url = _safe_external_href(license_url)
            if safe_license_url:
                badge_html = f'<a href="{_escape_html_attr(safe_license_url)}" target="_blank" rel="noopener noreferrer">{badge_html}</a>'
        lines.append(f'<p><strong>License:</strong> {badge_html}</p>')
        if license_note:
            lines.append(f'<p class="text-muted small mb-2">{_escape_html_text(license_note)}</p>')
    else:
        lines.append('<p><strong>License:</strong> <span class="text-muted">Not specified. Please refer to the original source for licensing terms.</span></p>')

    # Reproducibility
    if reproducibility_link:
        safe_repro = _safe_external_href(reproducibility_link)
        if safe_repro:
            repro_href = _escape_html_attr(safe_repro)
            lines.append(
                f'<p><strong>Reproducibility:</strong> <a href="{repro_href}" target="_blank" rel="noopener noreferrer">'
                'Instructions and scripts</a></p>'
            )
        else:
            lines.append(f'<p><strong>Reproducibility:</strong> {_escape_html_text(reproducibility_link)}</p>')
    elif repro_readme.exists():
        rel_link = f"../reproducibility/{dataset['filename']}/README.md"
        lines.append(
            f'<p><strong>Reproducibility:</strong> <a href="{_escape_html_attr(rel_link)}" target="_blank" rel="noopener noreferrer">'
            'Instructions and scripts</a></p>'
        )
    else:
        lines.append('<p><strong>Reproducibility:</strong> <span class="text-muted">Not provided.</span></p>')

    return "\n".join(lines)


_url_size_cache = {}
_url_fetch_count = 0

def fetch_url_size(url, timeout=10):
    global _url_fetch_count
    if not url:
        return None
    if url in _url_size_cache:
        return _url_size_cache[url]
    if FETCH_REMOTE_SIZES_MAX and _url_fetch_count >= FETCH_REMOTE_SIZES_MAX:
        return None
    ctx = ssl._create_unverified_context() if FETCH_REMOTE_SIZES_INSECURE else None
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
            length = response.headers.get("Content-Length")
            size = int(length) if length and length.isdigit() else None
    except Exception:
        size = None
    if size is None:
        try:
            req = urllib.request.Request(url, method="GET")
            req.add_header("Range", "bytes=0-0")
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                length = response.headers.get("Content-Range")
                if length and "/" in length:
                    size = int(length.split("/")[-1])
                else:
                    length = response.headers.get("Content-Length")
                    size = int(length) if length and length.isdigit() else None
        except Exception:
            size = None
    _url_fetch_count += 1
    _url_size_cache[url] = size
    return size

def maybe_fill_download_sizes(dataset):
    if not FETCH_REMOTE_SIZES:
        return
    if isinstance(dataset.get("versions"), list):
        changed = False
        for entry in dataset["versions"]:
            if not isinstance(entry, dict):
                continue
            binary_url = entry.get("binary_download") or entry.get("hgx_download")
            json_url = entry.get("json_download")
            if binary_url and entry.get("binary_download_size") is None:
                entry["binary_download_size"] = fetch_url_size(binary_url, timeout=FETCH_REMOTE_SIZES_TIMEOUT)
                changed = True
            if json_url and entry.get("json_download_size") is None:
                entry["json_download_size"] = fetch_url_size(json_url, timeout=FETCH_REMOTE_SIZES_TIMEOUT)
                changed = True

        if changed and FETCH_REMOTE_SIZES_WRITE:
            config_out = {}
            for key, value in dataset.items():
                if key.startswith('_') or key in ('filename', 'bibtex'):
                    continue
                config_out[key] = value
            try:
                with open(dataset["_config_path"], "w") as handle:
                    json.dump(config_out, handle, indent=2, ensure_ascii=True)
                    handle.write("\n")
            except Exception:
                pass
        return

    binary_links = dataset.get("binary_download", [])
    json_links = dataset.get("json_download", [])
    binary_sizes = list(dataset.get("binary_download_size", dataset.get("binary_download_sizes", [])) or [])
    json_sizes = list(dataset.get("json_download_size", dataset.get("json_download_sizes", [])) or [])
    if len(binary_sizes) < len(binary_links):
        for i in range(len(binary_links) - len(binary_sizes)):
            url = binary_links[len(binary_sizes) + i]
            binary_sizes.append(fetch_url_size(url, timeout=FETCH_REMOTE_SIZES_TIMEOUT))
    if len(json_sizes) < len(json_links):
        for i in range(len(json_links) - len(json_sizes)):
            url = json_links[len(json_sizes) + i]
            json_sizes.append(fetch_url_size(url, timeout=FETCH_REMOTE_SIZES_TIMEOUT))

    dataset["binary_download_sizes"] = binary_sizes
    dataset["json_download_sizes"] = json_sizes
    if FETCH_REMOTE_SIZES_WRITE:
        config_out = {}
        for key, value in dataset.items():
            if key.startswith('_') or key in ('filename', 'bibtex'):
                continue
            config_out[key] = value
        try:
            with open(dataset["_config_path"], "w") as handle:
                json.dump(config_out, handle, indent=2, ensure_ascii=True)
                handle.write("\n")
        except Exception:
            pass

def generate_related_data(datasets):
    related_items = []
    for dataset in datasets:
        related_items.append({
            "name": dataset["name"],
            "href": f"{OUTPUT_DIR_NAME}/{dataset['filename']}.html",
            "tags": dataset["tags"],
            "vertices": dataset.get("vertices"),
            "edges": dataset.get("edges"),
        })

    js_payload = "window.RELATED_DATASETS = " + json.dumps(related_items, ensure_ascii=True) + ";\n"
    RELATED_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RELATED_DATA_FILE, 'w') as related_file:
        related_file.write(js_payload)

def generate_recently_added_section(entries):
    if not entries:
        return '<div class="text-muted text-center">No recent datasets yet.</div>'

    cards = []
    for entry in entries:
        dataset = entry["dataset"]
        status = entry["status"]
        badge_class = _status_badge_class(status)
        tags_html = ' '.join([
            f'<span class="tag">{_escape_html_text(_as_str(tag).capitalize())}</span>'
            for tag in dataset['tags']
        ])
        cards.append(f'''
        <div class="recently-added-card">
            <div class="recently-added-title">
                <a href="{OUTPUT_DIR_NAME}/{_escape_html_attr(dataset['filename'])}.html">{_escape_html_text(dataset['name'])}</a>
                <span class="badge {badge_class} ms-2">{_escape_html_text(status)}</span>
            </div>
            <div class="recently-added-tags">{tags_html}</div>
        </div>
        ''')

    return f'''
    <div class="recently-added-grid horizontal-card-row">
        {''.join(cards)}
    </div>
    '''

def _empty_distribution_js():
    return (
        "const hyperedgeBins = [];\n"
        "const hyperedgeBinLabels = [];\n"
        "const hyperedgeFrequencies = [];",
        "const degreeBins = [];\n"
        "const degreeBinLabels = [];\n"
        "const degreeFrequencies = [];",
        "const timeSeriesX = [];\n"
        "const timeSeriesY = [];\n"
        "const timeSeriesStart = [];\n"
        "const timeSeriesEnd = [];\n"
        "const timeIsEpoch = false;\n"
        "const timeBucketSeconds = 0;\n"
        "const timeGranularity = 'unit';",
    )


def _load_distribution(dataset_dir: str) -> dict:
    path = DATASETS_STATS_DIR / dataset_dir / "distributions.json"
    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, ValueError):
        return {}


def _distribution_js(dataset_dir: str) -> tuple[str, str, str]:
    empty_hyperedge, empty_degree, empty_time = _empty_distribution_js()
    distribution = _load_distribution(dataset_dir)

    hyperedge = distribution.get("hyperedge_size")
    if isinstance(hyperedge, dict):
        hyperedge_js = (
            f"const hyperedgeBins = {json.dumps(hyperedge.get('bins', []))};\n"
            f"const hyperedgeBinLabels = {json.dumps(hyperedge.get('labels', []), ensure_ascii=True)};\n"
            f"const hyperedgeFrequencies = {json.dumps(hyperedge.get('frequencies', []))};"
        )
    else:
        hyperedge_js = empty_hyperedge

    degree = distribution.get("hyperdegree")
    if isinstance(degree, dict):
        degree_js = (
            f"const degreeBins = {json.dumps(degree.get('bins', []))};\n"
            f"const degreeBinLabels = {json.dumps(degree.get('labels', []), ensure_ascii=True)};\n"
            f"const degreeFrequencies = {json.dumps(degree.get('frequencies', []))};"
        )
    else:
        degree_js = empty_degree

    time = distribution.get("time")
    if isinstance(time, dict):
        time_js = (
            f"const timeSeriesX = {json.dumps(time.get('x', []))};\n"
            f"const timeSeriesY = {json.dumps(time.get('y', []))};\n"
            f"const timeSeriesStart = {json.dumps(time.get('start', []))};\n"
            f"const timeSeriesEnd = {json.dumps(time.get('end', []))};\n"
            f"const timeIsEpoch = {json.dumps(bool(time.get('is_epoch', False)))};\n"
            f"const timeBucketSeconds = {json.dumps(int(time.get('bucket_seconds', 0) or 0))};\n"
            f"const timeGranularity = {json.dumps(str(time.get('granularity', 'unit')))};"
        )
    else:
        time_js = empty_time

    return hyperedge_js, degree_js, time_js

def _dataset_bibtex_text(dataset):
    bibtex = _as_str(dataset.get("bibtex")).strip()
    if bibtex:
        return bibtex

    source = _as_str(dataset.get("source")).strip()
    if source:
        return f"No BibTeX entry is currently available. Please refer to the original source: {source}"
    return "No BibTeX entry is currently available. Please refer to the original data source listed in the provenance section."

def generate_dataset_page(dataset):
    with open(DATASET_TEMPLATE, 'r') as template_file:
        template = template_file.read()

    directory = dataset['filename']
    hyperedge_bins_js, degree_bins_js, time_bins_js = _distribution_js(directory)

    maybe_fill_download_sizes(dataset)
    versions_section = generate_versions_section(dataset)


    # Replace placeholders in the template
    page_content = template.replace('{{name}}', _escape_html_attr(dataset['name']))
    page_content = page_content.replace('{{description_attr}}', _escape_html_attr(dataset['description']))
    tags_html_parts = []
    for raw_tag in dataset.get('tags', []):
        tag_value = _as_str(raw_tag).strip()
        if not tag_value:
            continue
        tag_label = _escape_html_text(tag_value.capitalize())
        tag_param = quote(tag_value, safe='')
        tags_html_parts.append(
            f'<a class="tag tag-link" href="../index.html?tags={tag_param}" aria-label="Filter catalog by tag {tag_label}">{tag_label}</a>'
        )
    tags_html = ' '.join(tags_html_parts)
    page_content = page_content.replace('{{tags}}', tags_html)
    page_content = page_content.replace('{{description}}', _escape_html_text(dataset['description']))
    provenance_html = generate_provenance_section(dataset)
    page_content = page_content.replace('{{provenance}}', provenance_html)
    page_content = page_content.replace('{{bibtex}}', _escape_html_text(_dataset_bibtex_text(dataset)))
    page_content = page_content.replace('{{hyperedge_bins_js}}', hyperedge_bins_js)
    page_content = page_content.replace('{{degree_bins_js}}', degree_bins_js)
    page_content = page_content.replace('{{time_bins_js}}', time_bins_js)

    page_content = page_content.replace('{{vertices}}', _escape_stat(dataset['vertices']))
    page_content = page_content.replace('{{edges}}', _escape_stat(dataset['edges']))
    page_content = page_content.replace('{{unique_edges}}', _escape_stat(dataset['unique_edges']))
    page_content = page_content.replace('{{max_size_edge}}', _escape_stat(dataset.get('max_size_edge', '—')))

    # Generate metadata tables only if they exist
    hypergraph_metadata_html = generate_metadata_table(dataset.get("hypergraph_metadata"), "Hypergraph metadata")
    nodes_metadata_html = generate_metadata_table(dataset.get("nodes_metadata"), "Node metadata")
    edges_metadata_html = generate_metadata_table(dataset.get("edges_metadata"), "Hyperedge metadata")

    # Insert the tables into the page
    page_content = page_content.replace('{{hypergraph_metadata}}', hypergraph_metadata_html)
    page_content = page_content.replace('{{nodes_metadata}}', nodes_metadata_html)
    page_content = page_content.replace('{{edges_metadata}}', edges_metadata_html)
    page_content = page_content.replace('{{versions}}', versions_section)  # Inject versions HTML


    # Write to the output directory
    with open(OUTPUT_DIR / f'{dataset["filename"]}.html', 'w') as output_file:
        output_file.write(page_content)



# Main function to populate the table in index.html and create dataset pages
def generate_pages():
    # Load datasets
    datasets = load_datasets()
    print(f"Found {len(datasets)} datasets.")
    print([dataset['name'] for dataset in datasets])

    only_datasets_env = os.getenv("ONLY_DATASETS", "").strip()
    if only_datasets_env:
        only = {name.strip() for name in only_datasets_env.split(",") if name.strip()}
        datasets = [d for d in datasets if d.get("filename") in only or d.get("name") in only]
        print(f"Generating only selected datasets: {sorted(only)}")

        # Generate only dataset pages to keep output minimal.
        if not OUTPUT_DIR.exists():
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for dataset in datasets:
            generate_dataset_page(dataset)
        return

    # Generate table rows
    recent_entries = _recent_dataset_entries(datasets)
    recent_statuses = {
        entry["dataset"]["name"]: entry["status"]
        for entry in recent_entries
    }
    table_rows = '\n'.join([generate_table_row(dataset, recent_statuses) for dataset in datasets])

    # Read the index.html and populate the table
    with open(INDEX_TEMPLATE, 'r') as index_file:
        index_content = index_file.read()

    # Insert table rows into the index file (assuming a placeholder {{table_rows}} exists in the HTML)
    recently_added_html = generate_recently_added_section(recent_entries[:_recent_limit()])
    updated_index_content = index_content.replace('{{table_rows}}', table_rows)
    updated_index_content = updated_index_content.replace('{{recently_added}}', recently_added_html)
    safe_issues_url = _safe_external_href(REPO_ISSUES_URL)
    updated_index_content = updated_index_content.replace('{{repo_issues_url}}', _escape_html_attr(safe_issues_url))

    # Write updated index.html
    with open(INDEX_FILE, 'w') as index_file:
        index_file.write(updated_index_content)

    generate_related_data(datasets)

    # Create output directory if it doesn't exist
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Generate individual dataset pages
    for dataset in datasets:
        generate_dataset_page(dataset)

# Run the script
if __name__ == '__main__':
    generate_pages()
