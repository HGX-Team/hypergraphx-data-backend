# Hypergraphx-data site

This repository contains datasets and a static website that documents and links them.

## What lives here
- `resources/datasets_config/`: dataset configs (`config_<name>.json`) and optional `<name>.bib` files.
- `resources/datasets_statistics/`: compact per-dataset chart distributions (`distributions.json`).
- `reproducibility/`: per-dataset reproducibility guides and script references.
- `site_config.json`: site configuration (set `github_repo_url_base` to link reproducibility pages to GitHub).
- `dist/index.html`, `dist/about.html`, `dist/statistics.html`: built site entry pages.
- `dist/datasets/*.html`: built dataset pages.
- `dist/static/`: built static assets (CSS/JS/images).
- `templates/`: HTML templates used to build the site.
- `static/`: source static assets used by the site (CSS, JS, images, figures).
- `scripts/`: build helpers for site generation.
- `data/`: local raw datasets (ignored; may be a symlink to a remote server mount).

## Deployment / build steps
Prereqs: Python 3.12 and dependencies from `environment.yml` (Conda recommended).

From the repo root:

```bash
make build
```

This runs, in order:
1) `scripts/populate_with_links.py resources/datasets_config` to ensure download URLs are present in dataset configs.
2) `scripts/generate_statistics.py` to generate `dist/statistics.html` (and optional `dist/static/figures/*.pdf` if matplotlib is available).
3) `scripts/generate_pages.py` to generate `dist/index.html`, `dist/static/js/related-data.js`, and `dist/datasets/*.html`.

The build also copies static root templates such as `templates/about_template.html` to their published filenames in `dist/`.

- To add or refresh distribution charts for one dataset, generate the compact chart payload from the local dataset file:

```bash
/Users/francesco/hgx-dev/hgx-installation/bin/python scripts/generate_dataset_distributions.py <dataset> --overwrite
```

Use `--prefer json` if the JSON file should be treated as the source instead of the HGX file.

Notes:
- `resources/datasets_statistics/<dataset>/distributions.json` is the source for dataset detail-page charts. The build will still run if a dataset has no distributions file, but charts will be empty.
- If you want deterministic builds, keep `FETCH_REMOTE_SIZES` unset in the environment; the default is off.
- Set `SITE_DIST_DIR` to change the output directory (default: `dist/`).
- When building into a Pages repo, the build also ensures a minimal `DIST_DIR/.gitignore` (currently ignores `.DS_Store`).

## Publishing
This backend repository publishes the generated site to the public GitHub Pages repository `HGX-Team/hypergraphx-data`.
The Pages repository receives the built static files plus the public `reproducibility/` directory.

First clone the Pages repository next to this backend repository:

```bash
git clone git@github.com:HGX-Team/hypergraphx-data.git ../hypergraphx-data
```

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
