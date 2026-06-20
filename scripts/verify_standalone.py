from __future__ import annotations

import os
import py_compile
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
ASSET_DIR = PROJECT_ROOT / "static" / "soundbank_assets"


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main() -> None:
    os.environ.setdefault("SOUNDBANK_ENABLED", "true")
    os.environ.setdefault("SOUNDBANK_SHOW_STARTER_DEMOS", "true")
    os.environ.setdefault("SOUNDBANK_INIT_DB", "false")
    os.environ.setdefault("SOUNDBANK_ALLOW_PUBLIC_MASTER_URLS", "false")

    for path in (SRC_DIR / "app.py", SRC_DIR / "soundbank.py"):
        py_compile.compile(str(path), doraise=True)
    print("PASS: Python compile")

    if not ASSET_DIR.exists():
        fail(f"asset directory not found: {ASSET_DIR}")

    masters = list(ASSET_DIR.glob("*-master.wav"))
    if masters:
        fail(f"public master WAV files are blocked: {len(masters)} found")
    print("PASS: no public master WAV files")

    previews = list(ASSET_DIR.glob("*-preview.wav"))
    rights = list(ASSET_DIR.glob("*-rights.txt"))
    images = list(ASSET_DIR.glob("*.png"))
    if not previews:
        fail("no preview WAV files found")
    if not rights:
        fail("no rights TXT files found")
    print(
        "PASS: asset counts "
        f"images={len(images)} previews={len(previews)} rights={len(rights)}"
    )

    sys.path.insert(0, str(SRC_DIR))
    from app import app  # noqa: WPS433

    client = app.test_client()
    routes = (
        "/healthz",
        "/",
        "/soundbank",
        "/soundbank/tracks",
        "/soundbank/license",
        "/soundbank.webmanifest",
        "/soundbank-sw.js",
    )
    for route in routes:
        response = client.get(route)
        if response.status_code != 200:
            fail(f"{route} returned {response.status_code}")
        print(f"PASS: {route} {response.status_code} {len(response.data)} bytes")


if __name__ == "__main__":
    main()
