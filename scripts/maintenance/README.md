# Maintenance Scripts

These scripts are not part of the normal static-site build. They are local
maintenance and release-check tools for dataset downloads, compression,
license audits, raw-data extraction, and load verification.

- `get_pokemon_csvs.py`: downloads PokéAPI resources and writes the shared CSV
  inputs consumed by the Pokemon reproducibility scripts.
- `check_dataset_downloads.py`: checks configured dataset download URLs with
  HTTP metadata requests. It does not write dataset files and does not load
  them with HypergraphX. By default it checks all datasets; use `--only` for a
  subset and `--verbose` to print every checked URL.

Run the download-link check from the repository root:

```bash
python3 scripts/maintenance/check_dataset_downloads.py --insecure
```

Useful variants:

```bash
python3 scripts/maintenance/check_dataset_downloads.py --only pokemon-moves zoo --insecure
python3 scripts/maintenance/check_dataset_downloads.py --verbose --insecure
python3 scripts/maintenance/check_dataset_downloads.py --all-versions --insecure
```

Keep the top-level `scripts/` directory focused on the build/deploy path.
