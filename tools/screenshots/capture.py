"""Capture the real dashboard using a read-only fictional publication."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from .demo import TODAY, demo_server


def capture(output: Path, browser_path: str | None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with demo_server() as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            origin = f"http://127.0.0.1:{server.server_port}"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=browser_path)
                context = browser.new_context(viewport={"width": 1440, "height": 1120},
                                              device_scale_factor=1, locale="en-US",
                                              timezone_id="America/New_York", reduced_motion="reduce",
                                              service_workers="block")
                local = urlsplit(origin)
                def local_only(route):
                    url = urlsplit(route.request.url)
                    if (url.scheme, url.netloc) == (local.scheme, local.netloc):
                        route.continue_()
                    else:
                        route.abort()
                context.route("**/*", local_only)
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.clock.set_fixed_time(datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc)
                                          .replace(hour=15))
                page.set_default_timeout(10_000)

                def save(name, *, height=1120):
                    page.set_viewport_size({"width": 1440, "height": height})
                    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                    page.mouse.move(0, 0)
                    if errors:
                        raise RuntimeError("Dashboard script error: " + "; ".join(errors))
                    path = output / f"{name}.png"
                    page.screenshot(path=path, animations="disabled")
                    print(path)

                page.goto(origin)
                expect(page.locator(".latest-post-title")).to_have_text("What a neighborhood sounds like at dawn")
                expect(page.locator("#chart .event-marker")).not_to_have_count(0)
                save("briefing", height=1320)

                page.goto(origin + "/discovery")
                expect(page.locator("#source-trend-chart path").first).to_be_visible()
                expect(page.locator("#post-story-dialog")).to_be_hidden()
                save("discovery-overview", height=1000)
                page.get_by_role("link", name="Open post: What a neighborhood sounds like at dawn").click()
                expect(page.locator("#post-story-dialog")).to_be_visible()
                expect(page.get_by_text("Sources credited with signups")).to_be_visible()
                save("discovery")

                page.goto(origin + "/notes")
                points = page.locator("#note-map-points button")
                expect(points).to_have_count(8)
                expect(page.locator("#note-compare-rows tr")).to_have_count(8)
                points.nth(0).click()
                points.nth(3).click()
                expect(page.locator("#note-map-points button[aria-pressed=true]")).to_have_count(2)
                save("notes", height=1600)

                page.goto(origin + "/planner")
                expect(page.locator("#planner-scheduled-count")).to_have_text("12")
                expect(page.locator("#planner-draft-count")).to_have_text("3")
                expect(page.locator("#planner-draft-list")).to_contain_text("ferry terminal")
                save("planner", height=1840)
                browser.close()
        finally:
            server.shutdown()
            thread.join()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("output/ux-screenshots"))
    parser.add_argument("--browser", help="Optional path to a local Chromium executable")
    args = parser.parse_args()
    capture(args.output, args.browser)
