r"""
NekoCore launcher -- keeps a WoW 3.3.5a install patched for NekoCore and
starts the game. One window: it checks the server for a newer patch when
it opens, and Play installs whatever is missing before starting Wow.exe.

    Camera fix      patch_camera_bug.py applied to Wow.exe (backup kept)
    NekoCore patch  Data\patch-Z.mpq + Interface\AddOns\* from the server's
                    nekocore-patch.zip, checked against nekocore-patch.json
    Realmlist       Data\<locale>\realmlist.wtf -> wow1.nekos.farm

The server publishes nekocore-patch.json beside the zip (written by
nekocore's install_client.py): the patch version, and the zip's size and
SHA-256. The installed version is read back from the patch itself, the
NekoPatchCheck addon's Version.lua -- the same file the addon reports to the
realm in game -- so a patch extracted by hand counts as installed too.

Shipped as NekoCoreLauncher.exe (see build_gui.py / the release workflow);
also runs headless for scripting:

    python nekocore_launcher.py --cli --wotlk-root "D:\Games\World of Warcraft 3.3.5a"
    python nekocore_launcher.py --cli --wotlk-root ... --patch-zip nekocore-patch.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

from patch_camera_bug import patch as apply_camera_patch
from set_realmlist import detect_locale

__version__ = "0.2.0"

APP_NAME = "NekoCore Launcher"
REALM = "wow1.nekos.farm"
SITE_URL = "https://wow.nekos.farm"
MANIFEST_URL = f"{SITE_URL}/downloads/nekocore-patch.json"
RELEASES_API = "https://api.github.com/repos/m0nnnna/wotlk-client-tools/releases/latest"
RELEASES_PAGE = "https://github.com/m0nnnna/wotlk-client-tools/releases/latest"
USER_AGENT = f"NekoCoreLauncher/{__version__}"
VERSION_LUA = Path("Interface", "AddOns", "NekoPatchCheck", "Version.lua")
IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    SETTINGS = Path(os.environ.get("APPDATA", Path.home())) / "NekoCore" / "launcher.json"
else:
    SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nekocore" / "launcher.json"
    # Wow.exe runs under Wine in its own prefix (a self-contained fake C:).
    WINEPREFIX = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "nekocore" / "prefix"

COMMON_ROOTS = [
    r"D:\Games\World of Warcraft 3.3.5a",
    r"C:\Games\World of Warcraft 3.3.5a",
    r"C:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files\World of Warcraft",
    r"C:\Users\Public\Games\World of Warcraft",
]


# ---------------------------------------------------------------- settings

def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    try:
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    except OSError:
        pass  # a launcher that cannot remember the folder still works


def linux_candidates() -> list[str]:
    """Wow.exe folders up to two levels under ~/Games and ~/Downloads."""
    out = []
    for base in (Path.home() / "Games", Path.home() / "Downloads", Path.home()):
        if not base.is_dir():
            continue
        for pattern in ("*/Wow.exe", "*/*/Wow.exe"):
            try:
                out += [str(p.parent) for p in sorted(base.glob(pattern))]
            except OSError:
                pass
    return out


def find_client() -> Path | None:
    saved = load_settings().get("wotlk_root")
    roots = COMMON_ROOTS if IS_WINDOWS else linux_candidates()
    for r in ([saved] if saved else []) + roots:
        p = Path(r)
        if (p / "Wow.exe").is_file():
            return p
    return None


def check_root(root: Path) -> str | None:
    """None if this looks like a 3.3.5a client root, else why not."""
    if not root.is_dir():
        return f"{root} is not a folder"
    if not (root / "Wow.exe").is_file():
        return f"no Wow.exe in {root} -- pick the folder Wow.exe lives in"
    if not (root / "Data").is_dir():
        return f"no Data folder in {root}"
    return None


def check_writable(root: Path) -> None:
    """The client locks its MPQs while running; fail before doing half a job."""
    probe = root / "Data" / "patch-Z.mpq"
    if probe.exists():
        try:
            with open(probe, "ab"):
                pass
        except PermissionError:
            raise SystemExit("Data\\patch-Z.mpq is locked -- close World of Warcraft and try again.")


# ---------------------------------------------------------------- versions

def installed_version(root: Path) -> str | None:
    """The patch version this client has, from the NekoPatchCheck addon the
    patch ships. None when there is no patch, or one from before the addon
    existed -- both of which need the update."""
    if not (root / "Data" / "patch-Z.mpq").is_file():
        return None
    try:
        text = (root / VERSION_LUA).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'NEKO_PATCH_VERSION\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else None


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_manifest() -> dict:
    # The query string defeats any cache between here and the site.
    with _get(f"{MANIFEST_URL}?t={int(time.time())}") as r:
        manifest = json.loads(r.read().decode("utf-8"))
    for key in ("version", "file", "sha256", "size"):
        if key not in manifest:
            raise ValueError(f"the server's patch manifest has no '{key}'")
    return manifest


def latest_launcher() -> str | None:
    """The newest launcher release's version, or None if GitHub can't say."""
    try:
        with _get(RELEASES_API, timeout=10) as r:
            tag = json.loads(r.read().decode("utf-8")).get("tag_name", "")
    except (OSError, ValueError):
        return None
    return tag.lstrip("v") or None


def newer(a: str, b: str) -> bool:
    """Whether version a is newer than b (dotted numbers)."""
    def parts(v: str) -> tuple:
        return tuple(int(x) for x in re.findall(r"\d+", v))
    return parts(a) > parts(b)


# ---------------------------------------------------------------- install

def download(url: str, dest: Path, progress) -> None:
    with _get(url, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        with open(dest, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                done += len(chunk)
                progress(done, total)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def install_patch_zip(root: Path, zip_path: Path, log) -> None:
    r"""Extracts only the two things the client can use: Data\*.mpq and
    Interface\AddOns\*. Each file is written beside its target and then
    swapped in, so a failure never leaves half an MPQ behind."""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        n = 0
        for name in names:
            parts = Path(name).parts
            if not parts or name.endswith("/"):
                continue
            ok = (len(parts) == 2 and parts[0] == "Data" and parts[1].lower().endswith(".mpq")) or \
                 (len(parts) >= 4 and parts[0] == "Interface" and parts[1] == "AddOns")
            if not ok:
                continue
            dest = root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            with z.open(name) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            os.replace(tmp, dest)
            n += 1
        addons = sorted({p.parts[2] for p in map(Path, names) if len(p.parts) >= 4 and p.parts[0] == "Interface"})
        mpqs = sorted(p.name for p in map(Path, names) if len(p.parts) == 2 and p.parts[0] == "Data")
    log(f"installed {n} files: {', '.join(mpqs)}; addons {', '.join(addons)}")


def update_patch(root: Path, manifest: dict, log, progress) -> None:
    url = f"{MANIFEST_URL.rsplit('/', 1)[0]}/{manifest['file']}"
    log(f"downloading patch {manifest['version']} ({manifest['size'] / 2**20:.1f} MB)")
    with tempfile.TemporaryDirectory(prefix="nekocore-") as tmp:
        zip_path = Path(tmp) / manifest["file"]
        download(url, zip_path, progress)
        if sha256_of(zip_path) != manifest["sha256"]:
            raise SystemExit("The downloaded patch is damaged (checksum mismatch). Try again in a minute -- "
                             "the server may be in the middle of an update.")
        install_patch_zip(root, zip_path, log)


def write_realmlist(root: Path, realm: str, log) -> None:
    locale = detect_locale(root / "Data")
    target = root / "Data" / locale / "realmlist.wtf"
    new = f"set realmlist {realm}\n"
    if target.exists() and target.read_text(errors="replace") == new:
        return
    if target.exists():
        bak = target.with_suffix(".wtf.bak")
        if not bak.exists():
            shutil.copyfile(target, bak)
    target.write_text(new)
    log(f"realmlist -> {realm}")


def camera_fix(root: Path, log) -> None:
    """Best effort: an exe this tool does not recognise (another server's
    patched client, say) is left alone rather than blocking the game."""
    try:
        apply_camera_patch(root / "Wow.exe")
    except SystemExit as e:
        log(f"camera fix skipped: {e}")


def prepare(root: Path, *, manifest: dict | None, patch_zip: Path | None = None, force: bool = False,
            camera: bool = True, log=print, progress=lambda d, t: None) -> None:
    """Brings the client up to date: camera fix, patch, realmlist."""
    err = check_root(root)
    if err:
        raise SystemExit(err)
    check_writable(root)

    if camera:
        camera_fix(root, log)

    if patch_zip:
        log(f"installing local {patch_zip}")
        install_patch_zip(root, patch_zip, log)
    elif manifest is None:
        log("could not reach the server -- keeping the patch you have")
    elif force or installed_version(root) != manifest["version"]:
        update_patch(root, manifest, log, progress)
    else:
        log(f"patch {manifest['version']} is up to date")

    write_realmlist(root, REALM, log)


def launch(root: Path, log=print) -> None:
    if IS_WINDOWS:
        subprocess.Popen([str(root / "Wow.exe")], cwd=str(root),
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        return
    launch_wine(root, log)


# ---------------------------------------------------------------- Linux (Wine)

# 32-bit DXVK d3d9 (Wow.exe 3.3.5a is a 32-bit Direct3D 9 game): Debian's
# dxvk-wine32 package, or a copy dropped next to the launcher.
DXVK32_CANDIDATES = [
    "/usr/lib/i386-linux-gnu/dxvk/wine32-development/d3d9.dll",
    "/usr/lib/i386-linux-gnu/dxvk/wine32/d3d9.dll",
    "/usr/lib/dxvk/wine32/d3d9.dll",
    "/usr/share/dxvk/x32/d3d9.dll",
]


def _has_nvidia() -> bool:
    return shutil.which("nvidia-smi") is not None or Path("/proc/driver/nvidia/version").exists()


def wine_env() -> dict:
    env = dict(os.environ)
    env["WINEPREFIX"] = str(WINEPREFIX)
    env.setdefault("WINEDEBUG", "-all")
    env.setdefault("DXVK_LOG_LEVEL", "none")
    gpu = load_settings().get("gpu", "discrete")
    if gpu == "discrete" and _has_nvidia():
        # Hybrid laptops: render on the NVIDIA GPU (PRIME render offload).
        env.update({"__NV_PRIME_RENDER_OFFLOAD": "1", "__GLX_VENDOR_LIBRARY_NAME": "nvidia",
                    "__VK_LAYER_NV_optimus": "NVIDIA_only", "DXVK_FILTER_DEVICE_NAME": "NVIDIA"})
    return env


def ensure_prefix(log=print) -> None:
    """Create the Wine prefix on first run and put 32-bit DXVK in it."""
    env = wine_env()
    if not (WINEPREFIX / "system.reg").exists():
        log("setting up Wine (first run, takes a minute)...")
        WINEPREFIX.mkdir(parents=True, exist_ok=True)
        subprocess.run(["wineboot", "-u"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    syswow = WINEPREFIX / "drive_c" / "windows" / "syswow64"
    target = (syswow if syswow.is_dir() else WINEPREFIX / "drive_c" / "windows" / "system32") / "d3d9.dll"
    src = next((Path(c) for c in DXVK32_CANDIDATES if Path(c).is_file()), None)
    if src and (not target.exists() or target.stat().st_size != src.stat().st_size):
        shutil.copyfile(src, target)
        log(f"DXVK enabled ({src})")
    elif not src:
        log("DXVK not found; using Wine's own Direct3D (slower)")


def launch_wine(root: Path, log=print) -> None:
    if not shutil.which("wine"):
        raise RuntimeError("Wine is not installed (sudo apt install wine wine32:i386)")
    ensure_prefix(log)
    env = wine_env()
    if any(Path(c).is_file() for c in DXVK32_CANDIDATES):
        env["WINEDLLOVERRIDES"] = "d3d9=n,b"
    cmd = ["wine", str(root / "Wow.exe")]
    if shutil.which("gamemoderun"):
        cmd = ["gamemoderun"] + cmd
    subprocess.Popen(cmd, cwd=str(root), env=env, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- GUI

def gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    win = tk.Tk()
    win.title(f"{APP_NAME} {__version__}")
    win.resizable(False, False)
    pad = {"padx": 10, "pady": 4}

    frm = ttk.Frame(win, padding=12)
    frm.grid()

    ttk.Label(frm, text="NekoCore", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")
    ttk.Label(frm, text=f"Realm: {REALM}").grid(row=1, column=0, columnspan=3, sticky="w")

    ttk.Label(frm, text="World of Warcraft 3.3.5a folder:").grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
    root_var = tk.StringVar(value=str(find_client() or ""))
    ttk.Entry(frm, textvariable=root_var, width=60).grid(row=3, column=0, columnspan=2, sticky="we", **pad)

    status_var = tk.StringVar(value="Checking for updates...")
    ttk.Label(frm, textvariable=status_var, font=("Segoe UI", 10, "bold")).grid(
        row=4, column=0, columnspan=3, sticky="w", **pad)

    launcher_var = tk.StringVar(value="")
    launcher_link = ttk.Label(frm, textvariable=launcher_var, foreground="#1a5fb4", cursor="hand2")
    launcher_link.grid(row=5, column=0, columnspan=3, sticky="w", padx=10)
    launcher_link.bind("<Button-1>", lambda _e: webbrowser.open(RELEASES_PAGE))

    bar = ttk.Progressbar(frm, length=520, mode="determinate")
    bar.grid(row=6, column=0, columnspan=3, sticky="we", **pad)

    out = tk.Text(frm, width=72, height=8, state="disabled", wrap="word", font=("Consolas", 9))
    out.grid(row=7, column=0, columnspan=3, **pad)

    buttons = ttk.Frame(frm)
    buttons.grid(row=8, column=0, columnspan=3, pady=(8, 0), sticky="we")
    play = ttk.Button(buttons, text="Play", width=18)
    play.pack(side="right")
    repair = ttk.Button(buttons, text="Repair")
    repair.pack(side="left")
    recheck = ttk.Button(buttons, text="Check for updates")
    recheck.pack(side="left", padx=6)
    ttk.Button(buttons, text="Website", command=lambda: webbrowser.open(SITE_URL)).pack(side="left")

    state = {"manifest": None}

    # Workers never touch Tk themselves: they queue callables, and the main
    # thread runs them. Tk is not thread-safe.
    pending: queue.Queue = queue.Queue()

    def ui(fn):
        pending.put(fn)

    def drain():
        while True:
            try:
                fn = pending.get_nowait()
            except queue.Empty:
                break
            fn()
        try:
            win.after(50, drain)
        except tk.TclError:
            pass  # the window is gone (Play closes it)

    def log(msg: str) -> None:
        def _():
            out.configure(state="normal")
            out.insert("end", msg + "\n")
            out.see("end")
            out.configure(state="disabled")
        ui(_)

    def progress(done: int, total: int) -> None:
        ui(lambda: bar.configure(maximum=max(total, 1), value=done))

    def set_busy(busy: bool) -> None:
        for b in (play, repair, recheck):
            b.configure(state="disabled" if busy else "normal")

    def root_path() -> Path:
        return Path(root_var.get().strip('" '))

    def show_status() -> None:
        root = root_path()
        manifest = state["manifest"]
        if check_root(root):
            status_var.set("Pick your WoW 3.3.5a folder to continue.")
            play.configure(text="Play")
            return
        have = installed_version(root)
        if manifest is None:
            status_var.set("Couldn't reach the NekoCore server -- you can still play with the patch you have."
                           if have else "Couldn't reach the NekoCore server, and no patch is installed yet.")
            play.configure(text="Play")
        elif have == manifest["version"]:
            status_var.set(f"Up to date (patch {have}).")
            play.configure(text="Play")
        elif have is None:
            status_var.set(f"The NekoCore patch needs installing ({manifest['size'] / 2**20:.1f} MB).")
            play.configure(text="Install and play")
        else:
            status_var.set(f"Update available: patch {manifest['version']} (you have {have}).")
            play.configure(text="Update and play")

    def refresh() -> None:
        set_busy(True)
        status_var.set("Checking for updates...")

        def worker():
            try:
                state["manifest"] = fetch_manifest()
            except (OSError, ValueError) as e:
                state["manifest"] = None
                log(f"update check failed: {e}")
            newest = latest_launcher()
            if newest and newer(newest, __version__):
                ui(lambda: launcher_var.set(f"A new launcher ({newest}) is available -- click to download it."))
            ui(show_status)
            ui(lambda: set_busy(False))
        threading.Thread(target=worker, daemon=True).start()

    def browse():
        d = filedialog.askdirectory(title="Pick your WoW 3.3.5a folder (the one with Wow.exe)",
                                    initialdir=root_var.get() or "C:/")
        if d:
            root_var.set(d.replace("/", "\\"))
            show_status()
    ttk.Button(frm, text="Browse...", command=browse).grid(row=3, column=2, **pad)

    def run(force: bool, then_play: bool) -> None:
        root = root_path()
        err = check_root(root)
        if err:
            messagebox.showerror(APP_NAME, err)
            return
        settings = load_settings()
        settings["wotlk_root"] = str(root)
        save_settings(settings)
        set_busy(True)
        bar.configure(value=0)

        def worker():
            try:
                prepare(root, manifest=state["manifest"], force=force, log=log, progress=progress)
                if then_play:
                    log("starting World of Warcraft...")
                    launch(root, log)
                    ui(win.destroy)
                    return
                ui(lambda: messagebox.showinfo(APP_NAME, "Your client is ready."))
            except SystemExit as e:
                msg = str(e)
                log(f"STOPPED: {msg}")
                ui(lambda: messagebox.showerror(APP_NAME, msg))
            except Exception as e:  # noqa: BLE001 -- show the player something, not a silent hang
                msg = repr(e)
                log(f"ERROR: {msg}")
                ui(lambda: messagebox.showerror(APP_NAME, msg))
            ui(show_status)
            ui(lambda: set_busy(False))
        threading.Thread(target=worker, daemon=True).start()

    play.configure(command=lambda: run(force=False, then_play=True))
    repair.configure(command=lambda: run(force=True, then_play=False))
    recheck.configure(command=refresh)

    drain()
    refresh()
    win.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", action="store_true", help="no window; needs --wotlk-root")
    ap.add_argument("--wotlk-root", type=Path)
    ap.add_argument("--patch-zip", type=Path, help="local nekocore-patch.zip instead of downloading")
    ap.add_argument("--force", action="store_true", help="reinstall the patch even if it is up to date")
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--play", action="store_true", help="start Wow.exe when done")
    args = ap.parse_args()

    if not args.cli:
        return gui()
    if not args.wotlk_root:
        raise SystemExit("--cli needs --wotlk-root")

    def progress(done, total):
        if total:
            print(f"\r  {done * 100 // total:3d}%", end="", flush=True)
            if done >= total:
                print()

    manifest = None
    if not args.patch_zip:
        try:
            manifest = fetch_manifest()
        except (OSError, ValueError) as e:
            print(f"update check failed: {e}")
    prepare(args.wotlk_root, manifest=manifest, patch_zip=args.patch_zip, force=args.force,
            camera=not args.no_camera, progress=progress)
    if args.play:
        launch(args.wotlk_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
