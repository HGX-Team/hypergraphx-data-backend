- Download datasets
- Load the dataset in a hypergraphx object, keeping all the available metadata
- Dump the hypergraphx object with save_hypergraph both in json and hgx format
- Create `resources/datasets_config/<dataset>/config_<dataset>.json` with the dataset metadata and download links
- Generate the detail-page chart distributions from the local dataset file:

```bash
/Users/francesco/hgx-dev/hgx-installation/bin/python scripts/generate_dataset_distributions.py <dataset> --overwrite
```

- This writes `resources/datasets_statistics/<dataset>/distributions.json`
- You can update config with the correct missing information
- Add `created_at` and `updated_at` dates in `YYYY-MM-DD` format to the dataset config. The website automatically shows `New` when `created_at` is recent, and `Updated` when only `updated_at` is recent.
- Push the changes
- In `reproducibility/<dataset>/` keep the self-contained script that rebuilds the dataset from the original source

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
