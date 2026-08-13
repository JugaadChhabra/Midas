#!/usr/bin/env python3
"""Measure how far the running app has drifted from the approved design.

    python scripts/design_diff.py                  # all screens, summary + drift
    python scripts/design_diff.py --screen running
    python scripts/design_diff.py --write-images   # PNGs for anything that drifted
    python scripts/design_diff.py --max-drift 8    # exit 1 above this % (CI gate)

Why two checks instead of one screenshot diff
---------------------------------------------
A whole-page pixel diff between the design and the app is close to useless
here: the design draws sample data (13 channels, "12 days old", six videos)
and the app draws yours (5,175 videos, 13 days, groups the design never had).
Almost every differing pixel would be a channel name, and the handful that
were real would be buried in them.

So each element is checked the way it can actually be checked:

  chrome  — the frame: rail, nav, headings, buttons, card edges. Same content
            on both sides, so these get a real pixel diff, clipped to the
            element so a row appearing above it cannot shift the comparison.

  data    — anything whose text comes from the database. Pixel-diffing these
            would only re-report that the numbers differ. They get a geometry
            and typography check instead: size, font, weight, colour, padding.
            A regression that matters — wrong size, wrong ink, wrong spacing —
            still shows up; a different channel name does not.

Exceptions
----------
Where the build should differ, say so in EXCEPTIONS with the reason. Anything
not recorded there is drift, and drift is the thing this script exists to
surface. Deleting a check to make the number go down defeats the point.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESIGN = REPO / "design" / "running-shape.html"
SCRATCH = REPO / ".design-diff"          # chrome profiles + output images

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
VIEWPORT = (1180, 940)

# Per-channel antialiasing tolerance. Text rendered at the same size in the
# same font still differs by a few levels at the edges; without this every
# glyph reads as a difference and the number means nothing.
CHANNEL_TOLERANCE = 24


# ── What to compare ──────────────────────────────────────────────────────
# (name, design selector, live selector, kind)
#
# The design is one page with sections; the app is two pages with panels, so
# the selectors differ even where the thing is identical.
SCREENS = {
    "running": {
        "design_step": 'document.querySelector(\'[data-go="running"]\').click()',
        "live_url": "/",
        "live_step": None,
        "checks": [
            ("rail",        ".rail",            ".sidebar",       "chrome"),
            ("brand",       ".brand",           ".sidebar-head",  "chrome"),
            ("nav-item",    ".nav button",      ".snav",          "chrome"),
            ("nav-section", ".nav-sec",         ".nav-sec",       "chrome"),
            ("panel",       ".main",            ".app-main",      "geometry"),
            ("eyebrow",     ".page.on .eyebrow", "#run-checked",  "data"),
            ("lede",        ".page.on .lede",   "#run-lede",      "data"),
            ("meta",        ".page.on .meta",   "#run-meta",      "data"),
            ("quota-fig",   ".quota-fig",       ".quota-fig",     "data"),
            ("quota-label", ".quota-l",         ".quota-l",       "data"),
            ("group-head",  ".grp",             ".group-head",    "data"),
            ("row",         ".row",             ".frow",          "geometry"),
            ("row-name",    ".row .nm",         ".frow .nm",      "data"),
            ("row-why",     ".row .why",        ".frow .why",     "data"),
            ("row-figure",  ".row .cap",        ".frow .fig",     "data"),
            ("row-action",  ".row .act .btn",   ".frow .act .btn", "chrome"),
            ("lamp",        ".row .lamp",       ".frow .lamp",    "chrome"),
        ],
    },
    "videos": {
        "design_step": 'document.querySelector(\'[data-go="videos"]\').click()',
        "live_url": "/channel?id={channel}",
        "live_step": 'document.querySelector(\'.snav[data-tab="videos"]\').click()',
        "checks": [
            ("rail",        ".rail",            ".sidebar",       "chrome"),
            ("eyebrow",     ".page.on .eyebrow", "#title",        "data"),
            ("lede",        ".page.on .lede",   "#v-lede",        "data"),
            ("meta",        ".page.on .meta",   "#v-meta",        "data"),
            ("search",      ".search",          "#v-search",      "chrome"),
            ("chip",        ".chips .chip",     "#v-chips .chip", "data"),
            ("table-head",  ".thead",           "#videos .dt-head", "data"),
            ("table-row",   ".trow",            "#videos .dt-row",  "geometry"),
            ("row-title",   ".trow .t-name",    "#videos .vid-title", "data"),
            ("row-id",      ".trow .t-sub",     "#videos .vid-sub",   "data"),
        ],
    },
    "settings": {
        "design_step": 'document.querySelector(\'[data-go="set"]\').click()',
        "live_url": "/channel?id={channel}",
        "live_step": 'document.querySelector(\'.snav[data-tab="settings"]\').click()',
        "checks": [
            ("rail",       ".rail",             ".sidebar",       "chrome"),
            ("lede",       ".page.on .lede",    ".tab-panel.active .page-lede", "data"),
            ("meta",       ".page.on .meta",    "#set-meta",      "data"),
            ("card",       ".page.on .card",    ".tab-panel.active .card", "geometry"),
            ("card-head",  ".page.on .sec-head h3", ".tab-panel.active .sec-head h3", "data"),
            ("field-label", ".field label",     ".tab-panel.active .field > label", "data"),
            ("field-hint", ".field .hint",      ".tab-panel.active .field .hint", "data"),
        ],
    },
}

# name -> (fields it is allowed to differ on, why). "*" means the whole check.
EXCEPTIONS = {
    "running/panel": (
        {"h"},
        "panel height follows the number of channel rows, and this account has "
        "a group the design never drew",
    ),
    "running/row": (
        {"w", "x", "y"},
        "row width follows the panel; x/y follow the rows above, which differ "
        "in number",
    ),
    "videos/table-row": (
        {"w", "x", "y", "h"},
        "the design drew six sample videos with no thumbnails loaded; row "
        "height follows the real thumbnail",
    ),
    "settings/card": (
        {"w", "h", "x", "y"},
        "card height follows the real prompt text, which is longer than the "
        "design's four sample lines",
    ),
    "running/quota-fig": (
        {"w"},
        "figure width follows the digit count of the real remaining quota",
    ),
}

GEOMETRY_FIELDS = ["fs", "fw", "col", "ff", "ls", "pad", "w", "h"]

# Recorded pixel drift per chrome element, as a fraction.
#
# These do not go to zero and should not be forced to. Two renders of the same
# words at the same size still place glyphs a fraction of a pixel apart, and a
# clipped element that is mostly text reads several percent different for that
# reason alone — the Update button measures 12% with identical geometry,
# identical colour and identical text.
#
# So the number that matters is the CHANGE. A check that has always sat at 6%
# and jumps to 30% has broken; one sitting at 6% forever has not. Re-record
# with --record after a deliberate design change, never to silence a surprise.
BASELINE = {
    "running/rail":        0.032,
    "running/brand":       0.078,
    "running/nav-item":    0.061,
    "running/nav-section": 0.069,
    "running/row-action":  0.120,
    "running/lamp":        0.000,
    "videos/rail":         0.033,
    "videos/search":       0.057,
    "settings/rail":       0.035,
}
BASELINE_SLACK = 0.05   # how far above its baseline a check may drift

PROBE = """(sel => {
  const e = document.querySelector(sel);
  if (!e) return null;
  const c = getComputedStyle(e), r = e.getBoundingClientRect();
  return { fs: c.fontSize, fw: c.fontWeight, col: c.color, ls: c.letterSpacing,
           pad: c.padding, ff: c.fontFamily.split(',')[0].trim().replace(/['"]/g, ''),
           w: Math.round(r.width), h: Math.round(r.height),
           x: Math.round(r.left), y: Math.round(r.top) };
})"""


# ── Chrome driving ───────────────────────────────────────────────────────
class Page:
    """One headless tab, driven over CDP. No extra dependencies beyond the
    websockets client the repo already vendors for its other browser checks."""

    def __init__(self, port: int, profile: Path):
        self.port, self.profile = port, profile
        self.proc = None
        self.ws = None
        self._id = 0

    async def __aenter__(self):
        import websockets

        shutil.rmtree(self.profile, ignore_errors=True)
        self.profile.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", "--no-first-run",
             "--allow-file-access-from-files", "--hide-scrollbars",
             "--force-device-scale-factor=1",
             f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(120):
            try:
                tabs = json.load(urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json"))
                target = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.25)
        if not target:
            raise RuntimeError(f"Chrome did not start on :{self.port}")
        self.ws = await websockets.connect(target["webSocketDebuggerUrl"],
                                           max_size=80_000_000)
        await self.send("Runtime.enable")
        await self.send("Page.enable")
        # Pin the viewport rather than trusting --window-size: the two sides
        # have to be measured in identical space or every width differs.
        await self.send("Emulation.setDeviceMetricsOverride",
                        {"width": VIEWPORT[0], "height": VIEWPORT[1],
                         "deviceScaleFactor": 1, "mobile": False})
        return self

    async def __aexit__(self, *_):
        if self.ws:
            await self.ws.close()
        if self.proc:
            self.proc.terminate()

    async def send(self, method, params=None):
        self._id += 1
        await self.ws.send(json.dumps(
            {"id": self._id, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def goto(self, url, settle=8.0):
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(settle)

    async def js(self, expr):
        r = await self.send("Runtime.evaluate",
                            {"expression": expr, "returnByValue": True})
        return r.get("result", {}).get("value")

    async def probe(self, selector):
        return await self.js(f"({PROBE})({json.dumps(selector)})")

    async def shot(self, box=None):
        params = {"format": "png", "captureBeyondViewport": False}
        if box:
            params["clip"] = {"x": box["x"], "y": box["y"],
                              "width": box["w"], "height": box["h"], "scale": 1}
        r = await self.send("Page.captureScreenshot", params)
        return base64.b64decode(r["data"])


# ── Comparison ───────────────────────────────────────────────────────────
def pixel_drift(a_png: bytes, b_png: bytes):
    """Fraction of pixels that differ beyond antialiasing, plus a diff image.

    Different sizes are not an error to hide: compare the overlap and let the
    size difference be reported separately by the geometry check."""
    from PIL import Image, ImageChops

    a = Image.open(io.BytesIO(a_png)).convert("RGB")
    b = Image.open(io.BytesIO(b_png)).convert("RGB")
    w, h = min(a.width, b.width), min(a.height, b.height)
    if w == 0 or h == 0:
        return 1.0, None
    a, b = a.crop((0, 0, w, h)), b.crop((0, 0, w, h))

    delta = ImageChops.difference(a, b).convert("L")
    mask = delta.point(lambda v: 255 if v > CHANNEL_TOLERANCE else 0)
    differing = sum(mask.histogram()[1:])
    total = w * h

    # Side by side, with the differing pixels burned in red on the live copy,
    # so a failure is diagnosable without opening two files and squinting.
    from PIL import Image as I
    out = I.new("RGB", (w * 2 + 8, h), (20, 20, 22))
    out.paste(a, (0, 0))
    tinted = b.copy()
    tinted.paste(I.new("RGB", (w, h), (255, 40, 60)), (0, 0), mask)
    out.paste(tinted, (w + 8, 0))
    return differing / total, out


def allowed(key, field):
    exc = EXCEPTIONS.get(key)
    if not exc:
        return False
    fields, _ = exc
    return "*" in fields or field in fields


async def run_screen(name, spec, channel, write_images):
    design_url = f"file://{DESIGN}"
    live_url = "http://127.0.0.1:8000" + spec["live_url"].format(channel=channel)

    async with Page(9500, SCRATCH / "p-design") as dp, \
               Page(9501, SCRATCH / "p-live") as lp:
        await dp.goto(design_url)
        if spec["design_step"]:
            await dp.js(spec["design_step"])
            await asyncio.sleep(2)
        await lp.goto(live_url)
        if spec["live_step"]:
            await lp.js(spec["live_step"])
            await asyncio.sleep(5)

        rows, checked, failed = [], 0, 0
        pixel_seen = {}
        for label, dsel, lsel, kind in spec["checks"]:
            key = f"{name}/{label}"
            d, l = await dp.probe(dsel), await lp.probe(lsel)
            if d is None or l is None:
                rows.append((key, kind, "MISSING",
                             "design" if d is None else "live"))
                failed += 1
                continue

            # Geometry and typography, for every kind.
            diffs = [f"{f}: {d[f]} vs {l[f]}" for f in GEOMETRY_FIELDS
                     if str(d[f]) != str(l[f]) and not allowed(key, f)]
            checked += len(GEOMETRY_FIELDS)
            failed += len(diffs)

            note = ""
            if kind == "chrome":
                da, la = await dp.shot(d), await lp.shot(l)
                drift, img = pixel_drift(da, la)
                base = BASELINE.get(key)
                ceiling = (base + BASELINE_SLACK) if base is not None else 0.05
                note = f"{drift * 100:.1f}%"
                if base is not None:
                    note += f"/{base * 100:.0f}%"
                if drift > ceiling:
                    note += " OVER"
                    failed += 1
                    if write_images and img:
                        SCRATCH.mkdir(parents=True, exist_ok=True)
                        img.save(SCRATCH / f"{name}-{label}.png")
                        note += f" -> .design-diff/{name}-{label}.png"
                pixel_seen[key] = drift
                checked += 1
            rows.append((key, kind, note or "ok", "; ".join(diffs)))
        return rows, checked, failed, pixel_seen


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screen", choices=sorted(SCREENS), action="append")
    ap.add_argument("--channel", default="",
                    help="channel id for the per-channel screens")
    ap.add_argument("--write-images", action="store_true")
    ap.add_argument("--max-drift", type=float, default=None,
                    help="exit 1 if the drift percentage exceeds this")
    ap.add_argument("--record", action="store_true",
                    help="print a BASELINE block as things currently stand — "
                         "paste it in after a deliberate design change, never "
                         "to silence an unexpected one")
    args = ap.parse_args()

    if not DESIGN.exists():
        sys.exit(f"missing {DESIGN} — see design/README.md")

    channel = args.channel
    if not channel:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/dashboard",
                                        timeout=20) as r:
                chans = json.load(r)["channels"]
            # A channel with videos, or the per-channel screens compare an
            # empty table against a full one and every row check is noise.
            channel = next((c["id"] for c in chans if c.get("video_count")),
                           chans[0]["id"])
        except Exception as e:
            sys.exit(f"could not reach the app on :8000 ({e}) — start it first")

    screens = args.screen or list(SCREENS)
    all_rows, checked, failed, recorded = [], 0, 0, {}
    for name in screens:
        r, c, f, seen = await run_screen(name, SCREENS[name], channel,
                                         args.write_images)
        all_rows += r
        checked += c
        failed += f
        recorded.update(seen)

    width = max(len(r[0]) for r in all_rows) + 2
    print(f"{'check':<{width}} {'kind':<9} {'pixels':<14} drift")
    print("-" * (width + 40))
    for key, kind, note, diffs in all_rows:
        print(f"{key:<{width}} {kind:<9} {note:<14} {diffs}")

    pct = (failed / checked * 100) if checked else 0
    print(f"\n{checked - failed}/{checked} checks match  ·  {pct:.1f}% drift")
    if EXCEPTIONS:
        print("\nrecorded exceptions (not counted as drift):")
        for key, (fields, why) in EXCEPTIONS.items():
            print(f"  {key} [{','.join(sorted(fields))}] — {why}")

    if args.record:
        print("\nBASELINE = {")
        for k in sorted(recorded):
            print(f'    "{k}":{" " * max(1, 22 - len(k))}{recorded[k]:.3f},')
        print("}")

    if args.max_drift is not None and pct > args.max_drift:
        sys.exit(f"\ndrift {pct:.1f}% exceeds --max-drift {args.max_drift}")


if __name__ == "__main__":
    asyncio.run(main())
