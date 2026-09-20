r"""
NekoCore client patcher -- one window, one button: turns a stock WoW 3.3.5a
install into a NekoCore-ready client without the player needing Python.

    Camera fix      patch_camera_bug.py applied to Wow.exe (backup kept)
    NekoCore patch  Data\patch-Z.mpq + Interface\AddOns\* from the server's
                    nekocore-patch.zip (downloaded, or a local copy)
    Realmlist       Data\<locale>\realmlist.wtf -> wow1.nekos.farm

Shipped as NekoCorePatcher.exe (see build_gui.py / the release workflow);
also runs headless for scripting:

    python nekocore_patcher.py --cli --wotlk-root "D:\Games\World of Warcraft 3.3.5a"

The patch zip is fetched from PATCH_URL unless --patch-zip points at a
local file. A small marker (Data\nekocore-patch.json) records the
Content-Length/Last-Modified of the last install so a rerun with nothing
new on the server skips the 200 MB download.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

from patch_camera_bug import patch as apply_camera_patch
from set_realmlist import detect_locale

APP_NAME = "NekoCore Patcher"
REALM = "wow1.nekos.farm"
PATCH_URL = "https://wow.nekos.farm/downloads/nekocore-patch.zip"
MARKER = "nekocore-patch.json"

COMMON_ROOTS = [
    r"D:\Games\World of Warcraft 3.3.5a",
    r"C:\Games\World of Warcraft 3.3.5a",
    r"C:\Program Files (x86)\World of Warcraft",
    r"C:\Program Files\World of Warcraft",
    r"C:\Users\Public\Games\World of Warcraft",
]


def find_client() -> Path | None:
    for r in COMMON_ROOTS:
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


def remote_info(url: str) -> dict:
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=20) as r:
        return {"length": r.headers.get("Content-Length"), "modified": r.headers.get("Last-Modified"), "url": url}


def download(url: str, log, progress) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        total = int(r.headers.get("Content-Length") or 0)
        buf = io.BytesIO()
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            buf.write(chunk)
            done += len(chunk)
            progress(done, total)
    log(f"downloaded {done / 2**20:.0f} MB")
    return buf.getvalue()


def install_patch_zip(root: Path, data: bytes, log) -> None:
    r"""Extracts only the two things the client can use: Data\*.mpq and Interface\AddOns\*."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        n = 0
        for name in names:
            parts = Path(name).parts
            if not parts or name.endswith("/"):
                continue
            ok = (len(parts) == 2 and parts[0] == "Data" and parts[1].lower().endswith(".mpq")) or \
                 (len(parts) >= 4 and parts[0] == "Interface" and parts[1] == "AddOns")
            if not ok:
                log(f"  skipping unexpected entry {name}")
                continue
            dest = root.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(name))
            n += 1
        addons = sorted({p.parts[2] for p in map(Path, names) if len(p.parts) >= 4 and p.parts[0] == "Interface"})
        mpqs = sorted(p.name for p in map(Path, names) if len(p.parts) == 2 and p.parts[0] == "Data")
    log(f"installed {n} files: {', '.join(mpqs)}; addons {', '.join(addons)}")


def write_realmlist(root: Path, realm: str, log) -> None:
    locale = detect_locale(root / "Data")
    target = root / "Data" / locale / "realmlist.wtf"
    new = f"set realmlist {realm}\n"
    if target.exists() and target.read_text(errors="replace") == new:
        log(f"realmlist already {realm}")
        return
    if target.exists():
        bak = target.with_suffix(".wtf.bak")
        if not bak.exists():
            shutil.copyfile(target, bak)
    target.write_text(new)
    log(f"realmlist -> {realm} ({target.relative_to(root)})")


def run(root: Path, *, camera: bool, patch: bool, realmlist: bool, patch_zip: Path | None,
        url: str, log, progress=lambda d, t: None) -> None:
    err = check_root(root)
    if err:
        raise SystemExit(err)
    check_writable(root)

    if camera:
        log("== camera fix")
        apply_camera_patch(root / "Wow.exe")

    if patch:
        log("== NekoCore patch")
        marker = root / "Data" / MARKER
        if patch_zip:
            data = patch_zip.read_bytes()
            log(f"using local {patch_zip}")
            install_patch_zip(root, data, log)
            marker.write_text(json.dumps({"source": str(patch_zip), "length": str(len(data))}))
        else:
            info = remote_info(url)
            prev = json.loads(marker.read_text()) if marker.exists() else {}
            have = (root / "Data" / "patch-Z.mpq").exists()
            if have and prev.get("length") == info["length"] and prev.get("modified") == info["modified"]:
                log("patch already up to date, skipping download")
            else:
                log(f"downloading {url} ({int(info['length'] or 0) / 2**20:.0f} MB)")
                data = download(url, log, progress)
                install_patch_zip(root, data, log)
                marker.write_text(json.dumps(info))

    if realmlist:
        log("== realmlist")
        write_realmlist(root, REALM, log)

    log("\nDone. Start Wow.exe and log in.")


# ---------------------------------------------------------------- GUI

def gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    win = tk.Tk()
    win.title(APP_NAME)
    win.resizable(False, False)
    pad = {"padx": 10, "pady": 4}

    frm = ttk.Frame(win, padding=10)
    frm.grid()

    ttk.Label(frm, text="World of Warcraft 3.3.5a folder (the one with Wow.exe):").grid(row=0, column=0, columnspan=3, sticky="w")
    root_var = tk.StringVar(value=str(find_client() or ""))
    ttk.Entry(frm, textvariable=root_var, width=64).grid(row=1, column=0, columnspan=2, sticky="we", **pad)

    def browse():
        d = filedialog.askdirectory(title="Pick your WoW 3.3.5a folder", initialdir=root_var.get() or "C:/")
        if d:
            root_var.set(d.replace("/", "\\"))
    ttk.Button(frm, text="Browse...", command=browse).grid(row=1, column=2, **pad)

    cam = tk.BooleanVar(value=True)
    pat = tk.BooleanVar(value=True)
    rlm = tk.BooleanVar(value=True)
    ttk.Checkbutton(frm, text="Fix the right-click camera snap bug in Wow.exe (backup kept as Wow.exe.bak)", variable=cam).grid(row=2, column=0, columnspan=3, sticky="w", **pad)
    ttk.Checkbutton(frm, text="Install the NekoCore patch (Data\\patch-Z.mpq + addons) -- ~200 MB download", variable=pat).grid(row=3, column=0, columnspan=3, sticky="w", **pad)
    ttk.Checkbutton(frm, text=f"Point the client at {REALM}", variable=rlm).grid(row=4, column=0, columnspan=3, sticky="w", **pad)

    local_var = tk.StringVar(value="")
    ttk.Label(frm, text="Patch zip (leave empty to download):").grid(row=5, column=0, sticky="w", **pad)
    ttk.Entry(frm, textvariable=local_var, width=40).grid(row=5, column=1, sticky="we", **pad)

    def browse_zip():
        f = filedialog.askopenfilename(title="nekocore-patch.zip", filetypes=[("Zip", "*.zip")])
        if f:
            local_var.set(f.replace("/", "\\"))
    ttk.Button(frm, text="Browse...", command=browse_zip).grid(row=5, column=2, **pad)

    bar = ttk.Progressbar(frm, length=520, mode="determinate")
    bar.grid(row=6, column=0, columnspan=3, sticky="we", **pad)

    out = tk.Text(frm, width=76, height=16, state="disabled", wrap="word", font=("Consolas", 9))
    out.grid(row=7, column=0, columnspan=3, **pad)

    def log(msg: str) -> None:
        def _():
            out.configure(state="normal")
            out.insert("end", msg + "\n")
            out.see("end")
            out.configure(state="disabled")
        win.after(0, _)

    def progress(done: int, total: int) -> None:
        win.after(0, lambda: bar.configure(maximum=max(total, 1), value=done))

    btn = ttk.Button(frm, text="Patch my client")
    btn.grid(row=8, column=0, columnspan=3, pady=(6, 0))

    def worker():
        try:
            run(Path(root_var.get().strip('" ')), camera=cam.get(), patch=pat.get(), realmlist=rlm.get(),
                patch_zip=Path(local_var.get()) if local_var.get().strip() else None,
                url=PATCH_URL, log=log, progress=progress)
            win.after(0, lambda: messagebox.showinfo(APP_NAME, "All done -- start Wow.exe and log in."))
        except SystemExit as e:
            log(f"\nSTOPPED: {e}")
            win.after(0, lambda: messagebox.showerror(APP_NAME, str(e)))
        except Exception as e:  # noqa: BLE001 -- show the player something, not a silent hang
            log(f"\nERROR: {e!r}")
            win.after(0, lambda: messagebox.showerror(APP_NAME, f"{e!r}"))
        finally:
            win.after(0, lambda: btn.configure(state="normal"))

    def start():
        out.configure(state="normal")
        out.delete("1.0", "end")
        out.configure(state="disabled")
        bar.configure(value=0)
        btn.configure(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    btn.configure(command=start)
    win.mainloop()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cli", action="store_true", help="no window; needs --wotlk-root")
    ap.add_argument("--wotlk-root", type=Path)
    ap.add_argument("--patch-zip", type=Path, help="local nekocore-patch.zip instead of downloading")
    ap.add_argument("--url", default=PATCH_URL)
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--no-patch", action="store_true")
    ap.add_argument("--no-realmlist", action="store_true")
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
    run(args.wotlk_root, camera=not args.no_camera, patch=not args.no_patch, realmlist=not args.no_realmlist,
        patch_zip=args.patch_zip, url=args.url, log=print, progress=progress)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
