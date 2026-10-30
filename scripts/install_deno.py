#!/usr/bin/env python3
"""Install a pinned official Deno release with SHA256 verification; no curl|sh."""
from __future__ import annotations
import hashlib
import io
import os
from pathlib import Path
import platform
import sys
import zipfile
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions.config import DATA

VERSION = "v2.9.8"


def main():
    machine = platform.machine().lower()
    arch = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(machine)
    system = {"Linux": "unknown-linux-gnu", "Darwin": "apple-darwin"}.get(platform.system())
    if not arch or not system:
        raise SystemExit("Installer ini untuk Linux/macOS x86_64/ARM64. Windows: instal Deno resmi lalu masukkan ke PATH.")
    name = f"deno-{arch}-{system}.zip"
    base = f"https://github.com/denoland/deno/releases/download/{VERSION}/"
    print(f"Mengunduh Deno {VERSION} ({arch})…", flush=True)
    r = requests.get(base+name, timeout=(15, 180))
    r.raise_for_status()
    if len(r.content) > 160*1024**2:
        raise SystemExit("Ukuran rilis tidak wajar.")
    checksum = requests.get(base+name+".sha256sum", timeout=30)
    checksum.raise_for_status()
    expected = checksum.text.split()[0].lower()
    actual = hashlib.sha256(r.content).hexdigest()
    if len(expected) != 64 or actual != expected:
        raise SystemExit("Checksum tidak cocok; instalasi dibatalkan.")
    target_dir = DATA/"bin"
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        if z.namelist() != ["deno"]:
            raise SystemExit("Arsip tidak sesuai (hanya binary deno yang diizinkan).")
        tmp = target_dir/"deno.new"
        tmp.write_bytes(z.read("deno"))
        tmp.chmod(0o755)
        os.replace(tmp, target_dir/"deno")
    print(f"Terpasang: {target_dir/'deno'}\nSHA256: {actual}")


if __name__ == "__main__":
    main()