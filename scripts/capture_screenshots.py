"""Capture the demo site's screenshots with headless Chrome.

Reproducible rather than hand-taken, so the images in `docs/screenshots/` can be
regenerated when the site changes instead of quietly showing a version of the
page that no longer exists.

It serves `site/` on a free port, drives an already-installed Chrome or Edge in
headless mode, and writes PNGs. No new dependency: the browser is the one on the
machine, and nothing is downloaded.

    uv run python scripts/capture_screenshots.py

Whole pages rather than sections. Headless Chrome honours a URL fragment
unreliably when the screenshot fires, which produced half-blank section shots,
and a full page is better documentation anyway: it shows the order things are
said in, which is most of the argument.

The theme rides in on the query string, which the page supports for its own sake
so that a link can carry one. Nothing here is a mode that exists for cameras.
"""

from __future__ import annotations

import http.server
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = ROOT / "docs" / "screenshots"

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


@dataclass(frozen=True)
class Shot:
    name: str
    width: int
    theme: str
    description: str


# Heights are set from the measured page height at each width, with headroom.
# A page that grows past one of these loses its tail silently, so
# `test_site_data.py` checks the captures still cover the whole document.
HEIGHTS: dict[int, int] = {1440: 10600, 390: 20000}

SHOTS: tuple[Shot, ...] = (
    Shot("01-full-light", 1440, "light", "The whole page, light"),
    Shot("02-full-dark", 1440, "dark", "The whole page, dark"),
    Shot("03-full-mobile", 390, "light", "The whole page at 390px"),
)


def find_browser() -> str:
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    found = shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")
    if found:
        return found
    msg = (
        "no Chrome or Edge found. Screenshots need a Chromium-family browser "
        "that is already installed; nothing is downloaded."
    )
    raise RuntimeError(msg)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    return port


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(SITE), **kwargs)  # type: ignore[arg-type]

    def log_message(self, *args: object) -> None:
        """Quiet. The interesting output is which files were written."""


def capture(
    browser: str, url: str, shot: Shot, profile: Path, cache_buster: int
) -> Path:
    """One screenshot, with the theme applied before the page paints.

    Chrome's `--screenshot` cannot run script first, so the theme rides in on
    the URL fragment and the page's own toggle reads it. Anything cleverer would
    be capturing a mode a visitor never sees.
    """
    target = OUT / f"{shot.name}.png"
    subprocess.run(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-color-profile=srgb",
            "--disable-lcd-text",
            # Without these the fragment never lands: Chrome fires the
            # screenshot before the smooth scroll runs, so every section shot
            # comes back as the top of the page. Reduced motion turns the
            # scroll into a jump (the stylesheet already honours it) and the
            # virtual time budget gives the page time to build itself.
            "--force-prefers-reduced-motion",
            "--virtual-time-budget=3000",
            f"--user-data-dir={profile}",
            f"--window-size={shot.width},{HEIGHTS[shot.width]}",
            f"--screenshot={target}",
            # `cb` busts any 304 the local server would otherwise serve.
            f"{url}?theme={shot.theme}&cb={cache_buster}",
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    if not target.exists():
        msg = f"{browser} produced no file for {shot.name}"
        raise RuntimeError(msg)
    return target


def main() -> int:
    browser = find_browser()
    OUT.mkdir(parents=True, exist_ok=True)
    port = free_port()

    server = socketserver.TCPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}/"

    stamp = int(time.time())
    try:
        with tempfile.TemporaryDirectory() as profile:
            for shot in SHOTS:
                path = capture(browser, url, shot, Path(profile), stamp)
                size = path.stat().st_size // 1024
                height = HEIGHTS[shot.width]
                print(f"  {path.name:<20} {shot.width}x{height:<7} {size:>5} KB")
    finally:
        server.shutdown()
        server.server_close()

    print(f"\n{len(SHOTS)} screenshots in {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
