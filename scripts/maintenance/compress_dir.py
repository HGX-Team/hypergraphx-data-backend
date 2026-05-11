#!/usr/bin/env python3
"""
Recursively gzip all files under a directory, deleting originals.
Usage:
  python compress_tree.py /path/to/dir
"""

import argparse
import gzip
import os
import shutil
import stat
import sys
from pathlib import Path


def compress_file(path: Path):
    """Compress a single file to file.gz next to it, then remove the original."""
    if not path.is_file():
        return False, "skip (not a regular file)"
    if path.name.endswith(".gz"):
        return False, "skip (.gz already)"
    out = path.with_name(path.name + ".gz")
    if out.exists():
        try:
            out.unlink()
        except Exception as e:
            return False, f"error removing existing dest: {e}"

    st = path.stat()

    try:
        with open(path, "rb") as fin, gzip.open(out, "wb") as fout:
            shutil.copyfileobj(fin, fout)

        # Preserve permissions and times on the output file
        os.chmod(out, stat.S_IMODE(st.st_mode))
        os.utime(out, (st.st_atime, st.st_mtime))

        # Remove original
        path.unlink()
        return True, f"ok -> {out}"
    except Exception as e:
        # Best-effort cleanup on failure
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        return False, f"error: {e}"


def main():
    ap = argparse.ArgumentParser(description="Recursively gzip all files under a directory, deleting originals.")
    ap.add_argument("root", type=Path, help="Directory to process")
    args = ap.parse_args()

    if not args.root.exists() or not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        sys.exit(2)

    total = compressed = skipped = errors = 0

    # Walk the tree; include files in the root directory and all subdirectories
    for p in args.root.rglob("*"):
        if p.is_file():
            total += 1
            ok, msg = compress_file(p)
            if ok:
                compressed += 1
            else:
                if msg.startswith("skip"):
                    skipped += 1
                else:
                    errors += 1
            print(f"{p}: {msg}")

    print(f"\nSummary: visited {total} files, compressed {compressed}, skipped {skipped}, errors {errors}")


if __name__ == "__main__":
    main()
