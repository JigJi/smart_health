"""Migrate single-user parquet files into per-user subdirectory.

Before:
    backend/data/parquet/*.parquet

After:
    backend/data/parquet/users/default/*.parquet

Usage:
    cd backend
    # in-place migrate (source == target root)
    python -m scripts.migrate_to_multiuser
    python -m scripts.migrate_to_multiuser --user alice

    # cross-project: copy old smart_watch parquet into smart_health/users/default/
    python -m scripts.migrate_to_multiuser \\
        --src D:/0_jig_dev/smart_watch/backend/data/parquet --copy
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def migrate(src: Path, dest_root: Path, target_user: str = "default", copy: bool = False) -> int:
    parquets = sorted(p for p in src.glob("*.parquet") if p.is_file())
    if not parquets:
        print(f"[migrate] no root-level *.parquet found in {src} — nothing to do")
        return 0

    dest = dest_root / "users" / target_user
    dest.mkdir(parents=True, exist_ok=True)

    action = shutil.copy2 if copy else shutil.move
    for p in parquets:
        target = dest / p.name
        if target.exists():
            print(f"[migrate] skip (already exists): {target}")
            continue
        action(str(p), str(target))
        print(f"[migrate] {'copied' if copy else 'moved'}: {p.name} -> {dest}")
    return len(parquets)


def main() -> None:
    ap = argparse.ArgumentParser()
    default_root = Path(__file__).resolve().parent.parent / "data" / "parquet"
    ap.add_argument("--src", type=Path, default=default_root,
                    help="source dir holding *.parquet (default: this backend's data/parquet)")
    ap.add_argument("--dest", type=Path, default=default_root,
                    help="destination parquet root (default: this backend's data/parquet). "
                         "users/<user_id>/ is created underneath.")
    ap.add_argument("--user", default="default",
                    help="target user_id (default: 'default')")
    ap.add_argument("--copy", action="store_true",
                    help="copy instead of move (safer for cross-project migration)")
    args = ap.parse_args()

    src = args.src.resolve()
    dest_root = args.dest.resolve()
    if not src.exists():
        raise SystemExit(f"src not found: {src}")

    n = migrate(src, dest_root, args.user, copy=args.copy)
    print(f"[migrate] done — processed {n} files into {dest_root}/users/{args.user}/")


if __name__ == "__main__":
    main()
