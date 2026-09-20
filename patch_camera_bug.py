"""
Fixes a real, well-known 3.3.5a client bug: right-click camera rotation
can snap the camera to looking straight up or straight down, forcing the
player to manually correct it every time it happens. This is a bug in the
client executable itself (Wow.exe), not something fixable via DBC/Lua/
addon/MPQ -- every other tool in this repo works at the data layer; this
is the one exception that edits the executable's own code.

Patch source: a community-maintained binary patch documented on Warmane's
forums (https://forum.warmane.com/showthread.php?t=474289, "How to apply
the jumpy mouse camera fix patch to WotLK") -- the same category of fix as
brndd/vanilla-tweaks' equivalent for the 1.12.1 client (confirmed that
project exists and does the same kind of thing for Vanilla, though the
byte offsets there are naturally different -- different client build
entirely). Four same-length byte patches (no file-size change) at fixed
file offsets.

Every patch entry is applied ONLY after confirming the bytes already at
that offset exactly match what this specific patch expects there --
this is what makes it safe to run against a DIFFERENT Wow.exe build than
whichever one the original guide was written against: a build mismatch
shows up as a byte mismatch and this tool refuses to touch the file at
all (all-or-nothing, not a partial patch) rather than writing whatever a
different build's code happens to have at that same file offset. Verified
against this project's own 3.3.5a client before ever writing anything:
all 4 offsets matched the expected "before" bytes exactly.

A .bak copy of the untouched exe is always written first (never
overwritten by a later run -- if one already exists, this tool assumes
it's the genuine original and leaves it alone).
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# (offset, original bytes, patched bytes) -- same length each, confirmed
# programmatically below (ASSERT, not assumed) before this module is used
# for anything.
PATCHES: list[tuple[int, bytes, bytes]] = [
    (0x4691B1,
     bytes.fromhex("8BEC83EC108D45F0506A00E8DF28000083C40450FF150CF69D008B45F8992BC28BC88B45FC992BC2D1F8D1F95051890DEC13D400A3F013D400E881EEFFFF83C4088BE55DC3CCCCCCCCCCCCCCCCCCCC"),
     bytes.fromhex("89E58B05FC13D4008B0DF813D400EBC27D0383C10183C03283C1323B0DECBCCA007E0383E9013B05F0BCCA007E0383E80183E93283E832890DF813D4008905FC13D40089EC5DE9B4F7FFFFEC5DC3C3")),
    (0x469183,
     bytes.fromhex("CCCCCCCCCCCCCCCCCCCCCCCCCC"),
     bytes.fromhex("83F8327D0383C00183F932EB31")),
    (0x469A2C,
     bytes.fromhex("8B45F08B15EC13D4008B1DF0"),
     bytes.fromhex("E971F00B00F813D4008B1DFC")),
    (0x528AA2,
     bytes.fromhex("CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC"),
     bytes.fromhex("8D4DF05157FF15DCF59D008B45F08B15F813D400E97A0FF4FF")),
]

for _off, _orig, _patched in PATCHES:
    assert len(_orig) == len(_patched), f"offset {_off:X}: original/patched length mismatch"


def _hex(b: bytes) -> str:
    return b.hex(" ").upper()


def patch(exe_path: Path, *, dry_run: bool = False) -> int:
    data = bytearray(exe_path.read_bytes())

    to_apply: list[tuple[int, bytes, bytes]] = []
    for off, orig, patched in PATCHES:
        current = bytes(data[off:off + len(orig)])
        if current == patched:
            print(f"{off:#08x}: already patched, skipping")
        elif current == orig:
            print(f"{off:#08x}: original bytes confirmed, will patch")
            to_apply.append((off, orig, patched))
        else:
            print(f"{off:#08x}: MISMATCH -- neither original nor patched bytes found")
            print(f"  expected original: {_hex(orig)}")
            print(f"  expected patched:  {_hex(patched)}")
            print(f"  actually found:    {_hex(current)}")
            raise SystemExit(
                "\nRefusing to touch this file: at least one offset doesn't match "
                "either the expected original or already-patched bytes. This almost "
                "certainly means this Wow.exe is a different build than the one this "
                "patch was written for -- applying it anyway could corrupt the "
                "executable. No bytes have been written."
            )

    if not to_apply:
        print("\nNothing to do -- already fully patched.")
        return 0

    if dry_run:
        print(f"\n--dry-run: would apply {len(to_apply)} patch(es), nothing written.")
        return 0

    backup = exe_path.with_suffix(exe_path.suffix + ".bak")
    if not backup.exists():
        shutil.copyfile(exe_path, backup)
        print(f"\nBacked up untouched exe -> {backup}")
    else:
        print(f"\nBackup already exists, leaving it alone -> {backup}")

    for off, orig, patched in to_apply:
        data[off:off + len(patched)] = patched
    exe_path.write_bytes(data)
    print(f"Applied {len(to_apply)} patch(es) -> {exe_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wotlk-root", required=True, type=Path, help="the client install containing Wow.exe")
    ap.add_argument("--dry-run", action="store_true", help="check compatibility without writing anything")
    args = ap.parse_args()

    exe_path = args.wotlk_root / "Wow.exe"
    if not exe_path.is_file():
        raise SystemExit(f"not found: {exe_path}")

    return patch(exe_path, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
