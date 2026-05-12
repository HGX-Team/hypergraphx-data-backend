# Maintenance Scripts

These scripts are not part of the normal static-site build. They are local
maintenance and release-check tools for dataset downloads, compression,
license audits, raw-data extraction, and load verification.

- `get_pokemon_csvs.py`: downloads PokéAPI resources and writes the shared CSV
  inputs consumed by the Pokemon reproducibility scripts.

Keep the top-level `scripts/` directory focused on the build/deploy path.
