"""Builds dist/NekoCorePatcher.exe with PyInstaller (pip install pyinstaller)."""
import subprocess
import sys

subprocess.run([
    sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--clean", "--noconfirm",
    "--name", "NekoCorePatcher", "nekocore_patcher.py",
], check=True)
