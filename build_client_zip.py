r"""
Packs a patched 3.3.5a client into a player-facing zip: an explicit
ALLOWLIST of what a player needs and nothing else -- no Cache/WTF/Logs,
no stray addons, no launcher leftovers, no editor backups.

    python build_client_zip.py --wotlk-root "D:\Games\WoW 3.3.5a" \
        --out "D:\Games\MyServer.zip" --realm logon.example.com \
        --patch patch-Z.mpq --addon MyServerUI --zip-root MyServer

What goes in:

  Wow.exe                 whatever exe is in the client root (patched or not).
  AwesomeWotlkLib.dll     only if present -- an AwesomeWotlk-patched Wow.exe
                          imports it, so it must ride along. AwesomeWotlkPatch.exe
                          (the one-time patcher) and Wow.exe.bak do not.
  DivxDecoder.dll, msvcr80.dll   stock runtime deps.
  Data/*.MPQ              the stock archives plus every --patch you name.
                          Anything else in Data/ (other servers' lettered
                          patches, test builds) stays out unless listed.
  Data/<locale>/          stock locale archives. If patch-<locale>.MPQ.bak
                          exists it is preferred over the live file (a
                          pristine copy some launchers leave behind after
                          modifying the real one). realmlist.wtf is written
                          fresh pointing at --realm.
  Interface/AddOns/       Blizzard_* signature stubs (stock) + every --addon.

MPQs are stored uncompressed inside the zip (they're already compressed --
deflating 17 GB of them would take an hour for a few percent).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT_FILES = ["Wow.exe", "DivxDecoder.dll", "msvcr80.dll"]
OPTIONAL_ROOT_FILES = ["AwesomeWotlkLib.dll"]

DATA_MPQS = [
    "common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ",
    "patch.MPQ", "patch-2.MPQ", "patch-3.MPQ",
]

LOCALE_MPQS = [
    "backup-{L}.MPQ", "base-{L}.MPQ", "locale-{L}.MPQ", "speech-{L}.MPQ",
    "expansion-locale-{L}.MPQ", "expansion-speech-{L}.MPQ",
    "lichking-locale-{L}.MPQ", "lichking-speech-{L}.MPQ",
    "patch-{L}-2.MPQ", "patch-{L}-3.MPQ",
]
LOCALE_EXTRAS = ["AccountBilling.url", "TechSupport.url", "Credits.html", "Credits_BC.html", "Credits_LK.html",
                 "connection-help.html", "eula.html", "tos.html"]
LOCALE_DIRS = ["Documentation", "Interface"]

LOCALE_RE = re.compile(r"^[a-z]{2}[A-Z]{2}$")


def detect_locale(data_dir: Path) -> str:
    found = sorted(p.name for p in data_dir.iterdir() if p.is_dir() and LOCALE_RE.match(p.name))
    if len(found) != 1:
        raise SystemExit(f"expected exactly one locale folder under {data_dir}, found {found or 'none'} -- use --locale")
    return found[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path, help="the patched client install to pack")
    ap.add_argument("--out", required=True, type=Path, help="zip to write")
    ap.add_argument("--realm", required=True, help="logon host written into realmlist.wtf")
    ap.add_argument("--patch", action="append", default=[], metavar="NAME",
                    help="extra Data/*.mpq to include (repeatable), e.g. --patch patch-Z.mpq")
    ap.add_argument("--addon", action="append", default=[], metavar="NAME",
                    help="Interface/AddOns/<NAME> folder to include (repeatable); Blizzard_* stubs are always included")
    ap.add_argument("--zip-root", default="WoW", help="top-level folder name inside the zip (default WoW)")
    ap.add_argument("--locale", help="client locale, e.g. enUS (default: auto-detect)")
    args = ap.parse_args()

    root: Path = args.wotlk_root
    data = root / "Data"
    if not data.is_dir():
        raise SystemExit(f"no Data folder under {root}")
    locale = args.locale or detect_locale(data)
    loc = data / locale
    zip_root = args.zip_root.strip("/\\")

    plan: list[tuple[Path, str, bool]] = []   # (source, archive path, stored)
    for name in ROOT_FILES:
        plan.append((root / name, name, False))
    for name in OPTIONAL_ROOT_FILES:
        if (root / name).is_file():
            plan.append((root / name, name, False))
    for name in DATA_MPQS + args.patch:
        plan.append((data / name, f"Data/{name}", True))
    for tmpl in LOCALE_MPQS:
        name = tmpl.format(L=locale)
        plan.append((loc / name, f"Data/{locale}/{name}", True))
    main_locale = loc / f"patch-{locale}.MPQ"
    pristine = main_locale.with_suffix(".MPQ.bak")
    plan.append((pristine if pristine.is_file() else main_locale, f"Data/{locale}/patch-{locale}.MPQ", True))
    for name in LOCALE_EXTRAS:
        if (loc / name).is_file():
            plan.append((loc / name, f"Data/{locale}/{name}", False))

    missing = [str(p) for p, _, _ in plan if not p.is_file()]
    if missing:
        raise SystemExit("missing from the client:\n  " + "\n  ".join(missing))
    addons_dir = root / "Interface" / "AddOns"
    for addon in args.addon:
        if not (addons_dir / addon).is_dir():
            raise SystemExit(f"addon folder not in the client: {addons_dir / addon}")

    def add_file(z: zipfile.ZipFile, src: Path, arc: str, stored: bool) -> int:
        z.write(src, f"{zip_root}/{arc}", compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        return src.stat().st_size

    def add_tree(z: zipfile.ZipFile, src: Path, arc: str) -> int:
        n = 0
        for f in sorted(src.rglob("*")):
            if f.is_file():
                n += add_file(z, f, f"{arc}/{f.relative_to(src).as_posix()}", f.suffix.lower() == ".mpq")
        return n

    args.out.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    t0 = time.time()
    with zipfile.ZipFile(args.out, "w", allowZip64=True) as z:
        for src, arc, stored in plan:
            print(f"  {arc}", flush=True)
            total += add_file(z, src, arc, stored)
        for d in LOCALE_DIRS:
            if (loc / d).is_dir():
                total += add_tree(z, loc / d, f"Data/{locale}/{d}")
        z.writestr(f"{zip_root}/Data/{locale}/realmlist.wtf", f"set realmlist {args.realm}\n")
        if addons_dir.is_dir():
            for d in sorted(addons_dir.iterdir()):
                if d.is_dir() and (d.name.startswith("Blizzard_") or d.name in args.addon):
                    print(f"  Interface/AddOns/{d.name}", flush=True)
                    total += add_tree(z, d, f"Interface/AddOns/{d.name}")

    print(f"wrote {args.out} ({args.out.stat().st_size / 2**30:.2f} GiB, {total / 2**30:.2f} GiB of input) in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
