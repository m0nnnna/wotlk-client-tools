r"""
Points a 3.3.5a client at a server by rewriting Data\<locale>\realmlist.wtf.

    python set_realmlist.py --wotlk-root "D:\Games\WoW 3.3.5a" --realm logon.example.com

The file is one line, `set realmlist <host>`, and lives under the locale
folder (Data\enUS\ for an English client), not in the client root -- the
root-level realmlist.wtf some guides mention is a pre-2.x leftover that
3.3.5a ignores. The locale is auto-detected from whichever Data\<xxYY>\
folder exists; pass --locale to override. A .bak of the previous file is
kept the first time it's changed.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

LOCALE_RE = re.compile(r"^[a-z]{2}[A-Z]{2}$")


def detect_locale(data_dir: Path) -> str:
    found = sorted(p.name for p in data_dir.iterdir() if p.is_dir() and LOCALE_RE.match(p.name))
    if not found:
        raise SystemExit(f"no locale folder (e.g. enUS) under {data_dir} -- is --wotlk-root the client root?")
    if len(found) > 1:
        raise SystemExit(f"several locale folders under {data_dir}: {', '.join(found)} -- pick one with --locale")
    return found[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path, help="the client install")
    ap.add_argument("--realm", required=True, help="logon server hostname or IP")
    ap.add_argument("--locale", help="client locale folder, e.g. enUS (default: auto-detect)")
    args = ap.parse_args()

    data_dir = args.wotlk_root / "Data"
    if not data_dir.is_dir():
        raise SystemExit(f"no Data folder under {args.wotlk_root}")
    locale = args.locale or detect_locale(data_dir)
    target = data_dir / locale / "realmlist.wtf"
    new = f"set realmlist {args.realm}\n"

    if target.exists():
        old = target.read_text(errors="replace")
        if old == new:
            print(f"{target} already points at {args.realm}")
            return 0
        backup = target.with_suffix(".wtf.bak")
        if not backup.exists():
            shutil.copyfile(target, backup)
            print(f"backed up previous realmlist -> {backup}")
        print(f"was: {old.strip() or '(empty)'}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new)
    print(f"now: {new.strip()}  ({target})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
