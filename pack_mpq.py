r"""
Packs a folder into a patch MPQ the 3.3.5a client will load from Data\.

    python pack_mpq.py --src ./my-patch --out "D:\Games\WoW 3.3.5a\Data\patch-Z.mpq"

Every file under --src goes in at its path relative to --src, with forward
slashes turned into the backslashes MPQ paths use -- so
./my-patch/DBFilesClient/Talent.dbc becomes DBFilesClient\Talent.dbc inside
the archive, which is exactly where the client looks for it.

Why an MPQ at all: the client only reads DBC/texture/model overrides from
inside an archive under Data\ -- loose files on disk are ignored. Addon
Lua/.toc files are the opposite (loose under Interface\AddOns\ only), so
don't put addons in here.

Naming: the client loads Data\patch-*.mpq in alphabetical order and later
archives override earlier ones, so a letter near the end of the alphabet
(patch-Z.mpq) wins over anything else on the box. Files are stored
uncompressed -- fine for a handful of DBCs, not meant for a 4 GB asset dump.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mpq_writer import write_archive


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", required=True, type=Path, help="folder whose contents become the archive")
    ap.add_argument("--out", required=True, type=Path, help="archive to write (e.g. <client>/Data/patch-Z.mpq)")
    args = ap.parse_args()

    if not args.src.is_dir():
        raise SystemExit(f"--src is not a folder: {args.src}")
    paths = sorted(p for p in args.src.rglob("*") if p.is_file())
    if not paths:
        raise SystemExit(f"nothing to pack under {args.src}")

    files = {p.relative_to(args.src).as_posix().replace("/", "\\"): p.read_bytes() for p in paths}
    for name in files:
        print(f"  {name}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_archive(args.out, files)
    except PermissionError:
        raise SystemExit(
            f"Could not write {args.out} -- it's locked, almost certainly because "
            "the WoW client currently has it open. Close the client and rerun."
        )
    print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes, {len(files)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
