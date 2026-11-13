- Download datasets
- Load the dataset in a hypergraphx object, keeping all the available metadata
- Dump the hypergraphx object with save_hypergraph both in json and hgx format
- Create `resources/datasets_config/<dataset>/config_<dataset>.json` with the dataset metadata and download links
- Generate the detail-page chart distributions from the local dataset file, using a Python environment with `hypergraphx` installed (e.g. the `data-hgx` Conda environment from `environment.yml`):

```bash
python scripts/generate_dataset_distributions.py <dataset> --overwrite
```

- This writes `resources/datasets_statistics/<dataset>/distributions.json`
- You can update config with the correct missing information
- Add `created_at` and `updated_at` dates in `YYYY-MM-DD` format to the dataset config. The website automatically shows `New` when `created_at` is recent, and `Updated` when only `updated_at` is recent.
- Push the changes
- In `reproducibility/<dataset>/` keep the self-contained script that rebuilds the dataset from the original source
- If several datasets share one reproducibility folder (e.g. `reproducibility/movies-cast-by-genre/`), set `reproducibility_link` in each dataset config to that folder's GitHub URL; otherwise the page links to `reproducibility/<dataset>/`, which would not exist

## Recent dataset labels

The homepage labels are generated from dates in each dataset config:

```json
"created_at": "2026-05-07",
"updated_at": "2026-05-07"
```

By default, datasets changed in the last `recent_dataset_days` configured in
`site_config.json` are eligible. Newly created datasets are labeled `New`;
older datasets with a recent `updated_at` are labeled `Updated`. Use
`recent_dataset_limit` in `site_config.json` to control how many recent cards
are shown.

## Regenerate compressed HGX files from JSON

When the HypergraphX serialization/API changes, the `.hgx` files can become
outdated. The JSON files should be treated as the source of truth. To regenerate
compressed `.hgx.gz` files dataset by dataset, run:

```bash
python scripts/regenerate_hgx_from_json.py --data-dir data
```

The script accepts both uncompressed `.json` files and compressed `.json.gz`
files. It writes `{dataset}/{dataset}.hgx.gz` atomically after successfully
loading the JSON and serializing with the currently installed HypergraphX.

Useful options:

```bash
# Show what would be regenerated without writing files
python scripts/regenerate_hgx_from_json.py --data-dir data --dry-run

# Regenerate selected datasets only
python scripts/regenerate_hgx_from_json.py --data-dir data --only zoo DAWN

# Smoke test on the first 5 datasets
python scripts/regenerate_hgx_from_json.py --data-dir data --limit 5
```

## Dataset versions

Every dataset has a `versions` list in its config, newest first. Each entry
records the version label, release date, changelog, download URLs, file sizes,
and SHA-256 checksums of the compressed files.

On the download server (mirrored from the local `data/` directory):

```text
<name>/<name>.hgx.gz             latest release (moving alias, used by existing links
<name>/<name>.json.gz            and by hypergraphx's load_hypergraph_from_server)
<name>/<version>/<name>.hgx.gz   one folder per released version, never modified
<name>/<version>/<name>.json.gz
```

Version numbers are `MAJOR.MINOR.PATCH`:

- `MAJOR`: the hypergraph changes (nodes or edges added/removed, different construction rule).
- `MINOR`: metadata added or changed; same hypergraph.
- `PATCH`: same content re-serialized, e.g. `.hgx` regenerated for a new HypergraphX format.

### Freeze the current files (once per dataset)

Before a dataset's files are ever replaced, archive the current release into
its version folder and record its checksums:

```bash
python3 scripts/release_dataset.py freeze --all --dry-run   # preview
python3 scripts/release_dataset.py freeze --all
```

`freeze` is safe to re-run; it refuses to continue if a recorded checksum no
longer matches the files.

### Release a new version

```bash
python3 scripts/release_dataset.py release zoo 1.1.0 \
    --changes "Added node metadata" \
    --hgx path/to/new/zoo.hgx.gz --json path/to/new/zoo.json.gz
```

This copies the new files into `data/zoo/1.1.0/`, replaces the latest files,
adds the version entry at the top of the config, and sets `updated_at` (so the
site shows the `Updated` label). Without `--hgx`/`--json` it releases the files
already placed at the latest paths. It refuses if the previous version is not
frozen, the version number is not greater than the current one, or the files
are unchanged.

### Verify and upload

```bash
python3 scripts/release_dataset.py check            # local files vs recorded checksums
REMOTE_HOST=user@cricca.disi.unitn.it scripts/upload_datasets.sh --dry-run
REMOTE_HOST=user@cricca.disi.unitn.it scripts/upload_datasets.sh
python3 scripts/release_dataset.py check --remote   # server files vs recorded checksums
```

`upload_datasets.sh` runs the local check first, then uploads without ever
overwriting or deleting anything in a version folder on the server. Commit the
config changes and deploy the site afterwards.

### Linking the latest version to its folder

While `versioned_downloads` is `false` in `site_config.json`, the newest version
links to the latest alias path and older versions link to their folders. Once
every dataset is frozen and uploaded (`check --remote` passes), set it to `true`
so every version, including the newest, links to its own permanent folder.
