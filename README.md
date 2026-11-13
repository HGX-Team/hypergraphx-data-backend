# Hypergraphx-data backend

This repository is the source of truth for the Hypergraphx-data dataset catalog.
It contains dataset metadata, reproducibility material, static-site templates, and
the build/deploy scripts that publish the generated GitHub Pages website.

## What lives here
- `resources/datasets_config/`: dataset configs (`config_<name>.json`) and optional `<name>.bib` files.
- `resources/datasets_statistics/`: compact per-dataset chart distributions (`distributions.json`).
- `reproducibility/`: per-dataset reproducibility guides and script references.
- `site_config.json`: site configuration (set `github_repo_url_base` to link reproducibility pages to GitHub).
- `dist/`: local generated site output (ignored by git).
- `templates/`: HTML templates used to build the site.
- `static/`: source static assets used by the site (CSS, JS, images, figures).
- `scripts/`: build helpers for site generation.
- `scripts/maintenance/`: optional local maintenance, audit, download, compression, and verification tools.
- `data/`: local raw datasets (ignored; may be a symlink to a remote server mount).

## Deployment / build steps
Prereqs: Python 3.12 or newer.

- Building and deploying the site (`make build`, `scripts/deploy_pages.sh`) uses
  only the Python standard library. If `matplotlib` is installed, the statistics
  step also writes optional PDF figures to `static/figures/`; without it, the step
  prints a warning and skips them. No published page links to these figures.
- The dataset tools (`scripts/generate_dataset_distributions.py`,
  `scripts/regenerate_hgx_from_json.py`, `scripts/maintenance/verify_local_dataset_loads.py`)
  need `hypergraphx`. Use the `data-hgx` Conda environment from `environment.yml`,
  which pins `hypergraphx` and the scientific stack. `requirements.txt` is a
  lighter pip list and does not include `hypergraphx`.

From the repo root:

```bash
make build
```

This runs, in order:
1) `scripts/populate_with_links.py resources/datasets_config` to ensure download URLs are present in dataset configs.
2) `scripts/generate_statistics.py` to generate `dist/statistics.html` (and optional `dist/static/figures/*.pdf` if matplotlib is available).
3) `scripts/generate_pages.py` to generate `dist/index.html`, `dist/static/js/related-data.js`, and `dist/datasets/*.html`.

The build also copies static root templates such as `templates/about_template.html` to their published filenames in `dist/`.
Note that `make build` is not strictly read-only: `populate_with_links.py` can
update dataset config files if download links are missing.

- To add or refresh distribution charts for one dataset, generate the compact chart payload from the local dataset file:

```bash
python3 scripts/generate_dataset_distributions.py <dataset> --overwrite
```

Use `--prefer json` if the JSON file should be treated as the source instead of the HGX file.

Notes:
- `resources/datasets_statistics/<dataset>/distributions.json` is the source for dataset detail-page charts. The build will still run if a dataset has no distributions file, but charts will be empty.
- If you want deterministic builds, keep `FETCH_REMOTE_SIZES` unset in the environment; the default is off.
- Set `SITE_DIST_DIR` to change the output directory (default: `dist/`).
- When building into a Pages repo, the build also ensures a minimal `DIST_DIR/.gitignore` (currently ignores `.DS_Store`).

## Download-link checks
Before publishing, check that all configured dataset download URLs are reachable
without downloading or loading the dataset files:

```bash
python3 scripts/maintenance/check_dataset_downloads.py
```

The default checks all datasets. Useful variants:

```bash
# Check only selected datasets
python3 scripts/maintenance/check_dataset_downloads.py --only pokemon-moves zoo

# Print every checked URL and result
python3 scripts/maintenance/check_dataset_downloads.py --verbose

# Check every configured version entry
python3 scripts/maintenance/check_dataset_downloads.py --all-versions
```

The dataset host's TLS certificate verifies normally. If the check fails with
certificate errors, `--insecure` disables verification as a temporary workaround,
but the same errors will also affect users downloading from the site.

## Publishing
This backend repository publishes the generated site to the public GitHub Pages repository `HGX-Team/hypergraphx-data`.
The Pages repository is generated output, while this backend repository is the
source of truth. The Pages repository receives the built static files plus the
public `reproducibility/` directory.

First clone the Pages repository next to this backend repository:

```bash
git clone git@github.com:HGX-Team/hypergraphx-data.git ../hypergraphx-data
```

Before deploying, make sure this backend checkout contains exactly the changes
you want to publish. `deploy_pages.sh` checks whether the Pages checkout is
dirty, but it builds from the current backend working tree.

Then deploy:

```bash
scripts/deploy_pages.sh --push
```

Useful options:

```bash
# Copy/build into the Pages repo but do not commit
scripts/deploy_pages.sh --no-commit

# Use a non-default local checkout path
scripts/deploy_pages.sh --pages-dir ../hypergraphx-data

# Commit with a custom message
scripts/deploy_pages.sh --message "Update dataset website" --push
```

Optional local preview:

```bash
cd ../hypergraphx-data
python3 -m http.server 8000
```
