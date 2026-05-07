import json
import os
import sys
from pathlib import Path

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _HAS_MATPLOTLIB = True
except ModuleNotFoundError:
    plt = None
    _HAS_MATPLOTLIB = False
    print(
        "Warning: matplotlib is not available; skipping PDF figure generation.",
        file=sys.stderr,
    )

# Paths
REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = (REPO_ROOT / os.getenv("SITE_DIST_DIR", "dist")).resolve()
DIST_DIR.mkdir(parents=True, exist_ok=True)
DATASETS_DIR = REPO_ROOT / 'resources' / 'datasets_config'
DATASET_TEMPLATE = 'dataset_template.html'
FIGURES_DIR = DIST_DIR / 'static' / 'figures'

# === Plotting config ===
if _HAS_MATPLOTLIB:
    plt.rcParams.update({
        "font.size": 10,
        "axes.labelsize": 12,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
    })

# Minimum count for a domain to be shown in the domain figure
MIN_DOMAIN_COUNT_FOR_FIG = 3   # adjust if needed
MAX_DOMAINS_IN_FIG = 25        # cap in case there are many domains


def load_datasets():
    counts = {}
    total_datasets = 0
    for directory in sorted(os.listdir(DATASETS_DIR)):
        dir_path = os.path.join(DATASETS_DIR, directory)

        # Ensure we're only looking at directories
        if os.path.isdir(dir_path):
            json_file = os.path.join(dir_path, f"config_{directory}.json")
            # Check if the expected .json file exists in the directory
            if os.path.isfile(json_file):
                with open(json_file, 'r') as f:
                    dataset = json.load(f)
                    total_datasets += 1
                    tags = dataset.get('tags', [])
                    for tag in tags:
                        counts[tag] = counts.get(tag, 0) + 1
                        if tag == "Undirected":
                            print(f"Dataset '{directory}' is tagged as 'Undirected'")

    return counts, total_datasets


def make_vertical_bar_figure(data, filename, x_label,
                             min_count=1, max_categories=None):
    """
    data: list of dicts with keys "name" and "count"
    """
    if not _HAS_MATPLOTLIB:
        return

    # Filter by minimum count
    filtered = [d for d in data if d["count"] >= min_count]

    # Sort by count (descending)
    filtered.sort(key=lambda x: x["count"], reverse=True)

    # Limit number of categories if requested
    if max_categories is not None:
        filtered = filtered[:max_categories]

    if not filtered:
        # Nothing to plot
        return

    names = [d["name"] for d in filtered]
    counts = [d["count"] for d in filtered]

    # Width depends on number of categories
    fig_width = max(4, 0.4 * len(names) + 1)
    fig_height = 4
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    x_pos = range(len(names))
    ax.bar(x_pos, counts)

    ax.set_xticks(x_pos)
    ax.set_xticklabels(names, rotation=45, ha="right")

    # Labels (no title as requested)
    ax.set_xlabel(x_label)
    ax.set_ylabel("Number of datasets")

    # Despine: remove top and right spines
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Optional: light horizontal grid on y-axis for readability
    ax.yaxis.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
    ax.set_axisbelow(True)

    fig.tight_layout()
    fig.savefig(filename, format="pdf", bbox_inches="tight")
    plt.close(fig)


FIGURES_DIR.mkdir(parents=True, exist_ok=True)

counts, total_datasets = load_datasets()

NETWORK_TYPES = [
    'Undirected', 'Directed', 'Weighted', 'Temporal', 'Multiplex',
    'Unweighted', 'Node attributed', 'Edge attributed'
]

network_type_data = []
domain_data = []

for tag, count in counts.items():
    if tag in NETWORK_TYPES:
        network_type_data.append({"name": tag, "count": count})
    else:
        domain_data.append({"name": tag, "count": count})

# === Sort by count for BOTH figures and HTML ===
network_type_data.sort(key=lambda x: x["count"], reverse=True)
domain_data.sort(key=lambda x: x["count"], reverse=True)

# === Create publication-ready figures in PDF ===

if _HAS_MATPLOTLIB:
    # Network types: show all that exist (no min_count filter)
    make_vertical_bar_figure(
        network_type_data,
        filename=str(FIGURES_DIR / "fig_network_types.pdf"),
        x_label="Hypergraph type",
        min_count=1,
        max_categories=None
    )

    # Domains: exclude very rare domains to keep the figure clean
    make_vertical_bar_figure(
        domain_data,
        filename=str(FIGURES_DIR / "fig_domains.pdf"),
        x_label="Hypergraph domain",
        min_count=MIN_DOMAIN_COUNT_FOR_FIG,
        max_categories=MAX_DOMAINS_IN_FIG
    )

# === Inject JSON into template for the HTML statistics page ===

network_type_js = f"const networkTypes = {json.dumps(network_type_data)};"
domain_js = f"const domains = {json.dumps(domain_data)};"
stats_totals_js = (
    f"const totalDatasets = {total_datasets};\n"
    f"const totalDomains = {len(domain_data)};\n"
    f"const totalTypes = {len(network_type_data)};"
)

with open(REPO_ROOT / "templates" / "statistics_template.html") as f:
    html_template = f.read()

html_output = (
    html_template
    .replace("{{network_type_js}}", network_type_js)
    .replace("{{domain_js}}", domain_js)
    .replace("{{stats_totals_js}}", stats_totals_js)
)

with open(DIST_DIR / "statistics.html", "w") as f:
    f.write(html_output)
