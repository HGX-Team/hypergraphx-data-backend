import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = (REPO_ROOT / os.getenv("SITE_DIST_DIR", "dist")).resolve()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=True)


def sync_static_assets() -> None:
    src = REPO_ROOT / "static"
    dst = DIST_DIR / "static"
    if not src.exists():
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)


def sync_root_pages() -> None:
    pages = {
        "about_template.html": "about.html",
    }
    for template_name, output_name in pages.items():
        src = REPO_ROOT / "templates" / template_name
        dst = DIST_DIR / output_name
        if src.exists():
            shutil.copy2(src, dst)


def ensure_pages_settings() -> None:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    (DIST_DIR / ".nojekyll").write_text("", encoding="utf-8")


def ensure_pages_repo_gitignore() -> None:
    gitignore = DIST_DIR / ".gitignore"
    entries = [
        ".DS_Store",
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
    ]

    if not gitignore.exists():
        gitignore.write_text("\n".join(entries) + "\n", encoding="utf-8")
        return

    existing = gitignore.read_text(encoding="utf-8")
    lines = existing.splitlines()
    missing = [entry for entry in entries if entry not in lines]
    if missing:
        suffix = "" if existing.endswith("\n") or existing == "" else "\n"
        gitignore.write_text(f"{existing}{suffix}" + "\n".join(missing) + "\n", encoding="utf-8")


def main() -> None:
    ensure_pages_settings()
    ensure_pages_repo_gitignore()
    sync_static_assets()
    sync_root_pages()

    run(["python3", "scripts/populate_with_links.py", "resources/datasets_config"])
    run(["python3", "scripts/generate_statistics.py"])
    run(["python3", "scripts/generate_pages.py"])

    print(f"Built site into: {DIST_DIR}")


if __name__ == "__main__":
    main()
