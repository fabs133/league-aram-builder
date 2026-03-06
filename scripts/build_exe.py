#!/usr/bin/env python3
"""Build ARAM Oracle into a standalone Windows executable.

Usage:
    python scripts/build_exe.py          # directory bundle (recommended)
    python scripts/build_exe.py --onefile  # single .exe (slower startup)

Requirements:
    pip install pyinstaller
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = ROOT / "aram-oracle.spec"
DIST_DIR = ROOT / "dist"


def main():
    parser = argparse.ArgumentParser(description="Build ARAM Oracle EXE")
    parser.add_argument(
        "--onefile", action="store_true",
        help="Build a single .exe instead of a directory bundle",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Clean build artifacts before building",
    )
    args = parser.parse_args()

    if args.clean:
        for d in [ROOT / "build", DIST_DIR]:
            if d.exists():
                print(f"Cleaning {d}...")
                shutil.rmtree(d)

    if args.onefile:
        # Single-file build (slower startup but easier to distribute)
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            "--onefile",
            "--windowed",
            "--name", "aram-oracle",
            "--add-data", f"{ROOT / 'frontend'};frontend",
            "--add-data", f"{ROOT / 'data' / 'champions'};data/champions",
            "--add-data", f"{ROOT / 'data' / 'augments'};data/augments",
            "--hidden-import", "backend.api.server",
            "--hidden-import", "uvicorn.logging",
            "--hidden-import", "uvicorn.loops.auto",
            "--hidden-import", "uvicorn.protocols.http.auto",
            "--hidden-import", "uvicorn.protocols.websockets.auto",
            "--hidden-import", "uvicorn.lifespan.on",
            "--exclude-module", "tkinter",
            "--exclude-module", "matplotlib",
            str(ROOT / "backend" / "overlay" / "__main__.py"),
        ]
    else:
        # Directory bundle via spec file (recommended)
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm",
            str(SPEC_FILE),
        ]

    print(f"Running: {' '.join(cmd)}")

    # Run at below-normal priority so the build doesn't freeze the PC
    import platform
    creationflags = 0
    if platform.system() == "Windows":
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        creationflags = BELOW_NORMAL_PRIORITY_CLASS

    result = subprocess.run(cmd, cwd=str(ROOT), creationflags=creationflags)

    if result.returncode != 0:
        print("Build FAILED.", file=sys.stderr)
        sys.exit(1)

    output = DIST_DIR / "aram-oracle"
    if args.onefile:
        output = DIST_DIR / "aram-oracle.exe"

    print(f"\nBuild successful: {output}")
    print("To run: dist/aram-oracle/aram-oracle.exe")


if __name__ == "__main__":
    main()
