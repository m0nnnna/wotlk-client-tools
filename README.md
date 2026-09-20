# NekoCore client patcher + WotLK 3.3.5a client tools

Everything needed to turn a stock **World of Warcraft 3.3.5a (build 12340)**
client into a NekoCore-ready one -- as a single-file Windows app for players,
and as the plain Python scripts behind it for anyone running their own server.

Everything here works against a client install **you already own**. Nothing in
this repo contains or downloads any Blizzard data.

## Players: NekoCorePatcher.exe (no Python needed)

1. Grab `NekoCorePatcher.exe` from the
   [latest release](https://github.com/m0nnnna/wotlk-client-tools/releases/latest).
2. Run it. It looks for your WoW 3.3.5a folder in the usual places; if it
   doesn't find it, click **Browse...** and pick the folder that contains
   `Wow.exe`. Make sure the game is closed.
3. Click **Patch my client**. It will:
   - fix the right-click camera snap bug in `Wow.exe` (`Wow.exe.bak` is kept),
   - download the NekoCore patch (~200 MB: `Data\patch-Z.mpq` with the era
     talents and other DBC changes, plus the `Interface\AddOns\` addons), and
   - point `realmlist.wtf` at `wow1.nekos.farm`.
4. Start `Wow.exe` and log in.

Run it again any time -- it skips whatever is already done and only
re-downloads the patch when the server has a newer one. If you already have
`nekocore-patch.zip` (say, from the website), point the **Patch zip** field at
it to skip the download.

Windows SmartScreen will warn about an unknown publisher the first time; the
exe is unsigned. It is built by GitHub Actions straight from this repo
(`.github/workflows/release.yml`, PyInstaller over `nekocore_patcher.py`), so
you can compare it against the source or build your own with `python build_gui.py`.

Headless use of the same thing:

```
python nekocore_patcher.py --cli --wotlk-root "D:\Games\World of Warcraft 3.3.5a"
```

## The scripts

| Script | What it does |
| --- | --- |
| `nekocore_patcher.py` | The GUI/CLI above -- glues the three tools below together with the NekoCore defaults. |
| `patch_camera_bug.py` | Fixes the "camera snaps to straight up/down on right-click" bug in `Wow.exe`. Checks every byte before writing, backs up first. |
| `set_realmlist.py` | Rewrites `Data\<locale>ealmlist.wtf` to point at a server. |
| `pack_mpq.py` | Packs a folder (e.g. `DBFilesClient\*.dbc`) into a `patch-*.mpq`. |
| `mpq_writer.py` | The MPQ writer `pack_mpq.py` uses; import it if you'd rather build archives from your own script. |
| `build_client_zip.py` | Allowlist-packs a patched client into a distributable zip -- stock archives, your patch MPQ, your addons, a fresh `realmlist.wtf`, and nothing else. |

Requirements for the scripts: Python 3.10+, no pip packages. The exe needs nothing.

---

## Manual guide: connect an existing client to a server (any server)

You need a stock 3.3.5a client and the server's logon hostname (something like
`logon.example.com`). Open a terminal in this folder.

### 1. Fix the camera bug (optional, recommended)

The 3.3.5a executable has a well-known bug where right-click camera rotation
occasionally snaps the camera to look straight up or down. This applies the
community binary patch (documented on Warmane's forums, "How to apply the
jumpy mouse camera fix patch to WotLK").

```
python patch_camera_bug.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a" --dry-run
python patch_camera_bug.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a"
```

`--dry-run` checks compatibility without writing anything. The real run writes
`Wow.exe.bak` first, then applies four same-length byte patches. It is
all-or-nothing: if any offset holds bytes it doesn't recognise (a different
build, a differently-patched exe) it refuses and writes nothing.

It composes fine with [AwesomeWotlk](https://github.com/FrostAtom/awesome_wotlk):
run AwesomeWotlk's patcher first, then this -- the offsets it touches don't
overlap. Run it a second time and it reports "already fully patched".

### 2. Point the client at the server

```
python set_realmlist.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a" --realm logon.example.com
```

This writes `Data\enUS\realmlist.wtf` (the locale folder is auto-detected;
`--locale deDE` etc. to override). The root-level `realmlist.wtf` some guides
mention is a pre-2.x leftover that 3.3.5a ignores. The previous file is kept
as `realmlist.wtf.bak` the first time it's changed.

### 3. Install the server's patch, if it has one

Most servers with custom content hand out two kinds of files. They go in
different places and the client is strict about it:

- **`patch-*.mpq`** -> `Data\`. Custom DBCs, textures, models. The client only
  reads these from inside an archive; a loose `Talent.dbc` on disk is ignored.
- **Addons** (a folder with a `.toc` and `.lua` files) -> `Interface\AddOns\`.
  Loose files only; an addon inside an MPQ is invisible.

Fully log out and back in (not just `/reload`) after adding an MPQ.

---

## Server-owner guide: build and ship a patched client

### Pack custom DBCs into a patch MPQ

Lay out a folder mirroring the client's internal paths, then pack it:

```
my-patch/
  DBFilesClient/
    Talent.dbc
    TalentTab.dbc
```

```
python pack_mpq.py --src my-patch --out "D:\Games\World of Warcraft 3.3.5a\Data\patch-Z.mpq"
```

Paths inside the archive become `DBFilesClient\Talent.dbc` etc. The client
loads `Data\patch-*.mpq` alphabetically and later archives override earlier
ones, so `patch-Z.mpq` beats anything else on the box. Files are stored
uncompressed -- right for a handful of DBCs, not for a multi-GB asset dump.

To build archives from your own tooling, `mpq_writer.write_archive(path,
{"DBFilesClient\Talent.dbc": b"..."})` is the whole API.

### Ship a ready-to-play client zip

Once a client install is patched and tested (exe fixed, MPQ in `Data\`,
addons in `Interface\AddOns\`), pack it for players:

```
python build_client_zip.py --wotlk-root "D:\Games\World of Warcraft 3.3.5a" ^
    --out "D:\Games\MyServer.zip" --realm logon.example.com ^
    --patch patch-Z.mpq --addon MyServerUI --zip-root MyServer
```

This is an **allowlist**, not a copy of the folder. It takes: `Wow.exe` and its
runtime DLLs (`AwesomeWotlkLib.dll` rides along automatically if present), the
stock `Data\*.MPQ` and locale archives, each `--patch` you name, the
`Blizzard_*` addon stubs plus each `--addon` you name, and a fresh
`realmlist.wtf` pointing at `--realm`. It leaves behind `Cache\`, `WTF\`,
`Logs\`, other servers' lettered patches, `Wow.exe.bak`, the AwesomeWotlk
patcher, and any addons you didn't list. If `patch-<locale>.MPQ.bak` exists it
is preferred over the live file (some launchers modify the real one and leave
the pristine copy behind). MPQs are stored uncompressed inside the zip since
they're already compressed; expect ~17 GB and a few minutes.

Players extract the zip and run `Wow.exe` from the `--zip-root` folder.

### Why two delivery mechanisms?

The client draws the line, not us: DBC/model/texture overrides load **only**
from an MPQ under `Data\`, and addon Lua/XML/TOC files load **only** as loose
files under `Interface\AddOns\`. Every tool here respects that split.

---

## Licensing note

The scripts are MIT. They only ever read from and write into a client install
you already have -- no Blizzard files, DBCs, or MPQs are included here or
fetched from anywhere, and you shouldn't commit any either (`.gitignore`
already excludes `*.mpq`, `*.zip`, `*.bak`).

Credits: the camera patch bytes are the community patch from Warmane's forums;
the MPQ hash/crypt routines follow the format documented at
[wowdev.wiki/MPQ](https://wowdev.wiki/MPQ).
