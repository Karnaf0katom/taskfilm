"""Check a release site's downloads, responsive layout and real MP4 playback."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright


def verify(site: Path, output: Path) -> dict:
    package = json.loads((site / 'SHOWCASE.json').read_text())
    movies = [row for row in package['files'] if row['path'].startswith('assets/')
              and row['path'].endswith('.mp4')]
    assert 1 <= len(movies) <= 8
    output.mkdir(parents=True, exist_ok=False)
    handler = partial(SimpleHTTPRequestHandler, directory=str(site.resolve()))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = {"viewports": [], "downloads": [], "movies": []}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for label, width, height in (("desktop", 1440, 1000), ("mobile", 390, 844)):
                    page = browser.new_page(viewport={"width": width, "height": height})
                    response = page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
                    assert response.status == 200
                    assert "Taskfilm" in page.title()
                    assert page.locator("h1").inner_text().strip()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    assert page.locator("video").count() == len(movies)
                    assert "Private release review" not in page.locator("body").inner_text()
                    for index, expected in enumerate(movies):
                        movie = page.locator("video").nth(index)
                        movie.evaluate("v => v.load()")
                        page.wait_for_function("i => Number.isFinite(document.querySelectorAll('video')[i].duration)", arg=index)
                        duration = movie.evaluate("v => v.duration")
                        assert abs(duration - expected['seconds']) <= 0.05
                        assert movie.evaluate('v => v.videoWidth') == expected['width']
                        assert movie.evaluate('v => v.videoHeight') == expected['height']
                        seek = min(5, duration / 2)
                        movie.evaluate("(v, t) => {v.muted = true; v.currentTime = t;}", seek)
                        page.wait_for_function("i => !document.querySelectorAll('video')[i].seeking", arg=index)
                        movie.evaluate("v => v.play()")
                        page.wait_for_function("([i,t]) => document.querySelectorAll('video')[i].currentTime > t + 0.15", arg=[index, seek])
                        movie.evaluate("v => v.pause()")
                        report["movies"].append({"viewport": label, "index": index + 1,
                                                 "seconds": duration, "playback_and_seek": "passed"})
                    for button in page.locator('[data-filter]').all():
                        kind = button.get_attribute('data-filter')
                        button.click()
                        expected_count = len(movies) if kind == 'all' else sum(row.get('kind') == kind for row in movies)
                        assert page.locator('.movie:visible').count() == expected_count
                        assert button.get_attribute('aria-pressed') == 'true'
                    if page.locator('[data-filter="all"]').count():
                        page.locator('[data-filter="all"]').click()
                    if label == "desktop":
                        for link in page.locator("a.download").all():
                            href = link.get_attribute("href")
                            assert href.startswith("downloads/") and ".." not in href
                            assert "jarvis" not in href.lower()
                            asset = site / href
                            assert asset.is_file() and asset.stat().st_size > 0
                            report["downloads"].append({"path": href, "bytes": asset.stat().st_size})
                    page.screenshot(path=str(output / f"{label}.png"), full_page=True)
                    report["viewports"].append({"name": label, "width": width, "overflow": False})
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.site, arguments.out), indent=2))
