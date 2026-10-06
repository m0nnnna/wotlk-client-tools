"""Builds dist/NekoCoreLauncher.exe with PyInstaller (pip install pyinstaller)."""
import subprocess
import sys

subprocess.run([
    sys.executable, "-m", "PyInstaller", "--onefile", "--noconsole", "--clean", "--noconfirm",
    "--name", "NekoCoreLauncher", "nekocore_launcher.py",
], check=True)
