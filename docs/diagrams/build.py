"""Wrap each `<slug>.svg` in a standalone `<slug>.html`, and inline it into the site.

The `.svg` file is the source. It carries its own tokens and its own
`prefers-color-scheme` block, so the same bytes render correctly in three
places: as an image in a markdown file, as the page below, and inlined into
`docs/site/index.html` — which stays a single file with nothing fetched.

    python docs/diagrams/build.py

Run it after editing any `.svg` here. It rewrites only what it generates:
the `.html` files, and the region of `index.html` between
`<!-- diagram:<slug> -->` and `<!-- /diagram:<slug> -->`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SITE = HERE.parent / "site" / "index.html"

FONTS = ("https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1"
         "&family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600&display=swap")

#: slug → the eyebrow above the title on the standalone page.
EYEBROW = {
    "shape": "Architecture",
    "run-to-board": "Process",
    "the-gate": "Flowchart",
    "an-output": "Data model",
    "where-it-sits": "Flowchart",
    "two-questions": "State machine",
}

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · VeriFlow Agency</title>
<link href="{fonts}" rel="stylesheet">
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{--paper:#fbfaf7;--ink:#1b1a17;--muted:#6d6a62;
    --sans:'Geist',ui-sans-serif,system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
    --serif:'Instrument Serif',Georgia,serif;
    --mono:'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
  @media (prefers-color-scheme:dark){{:root{{--paper:#14140f;--ink:#eceae3;--muted:#97948a}}}}
  body{{font-family:var(--sans);background:var(--paper);color:var(--ink);min-height:100vh;
    display:flex;align-items:center;justify-content:center;padding:3rem 2rem}}
  .frame{{max-width:1200px;width:100%}}
  .eyebrow{{font-family:var(--mono);font-size:.66rem;font-weight:500;letter-spacing:.18em;
    text-transform:uppercase;color:var(--muted);margin-bottom:.5rem}}
  h1{{font-family:var(--serif);font-size:clamp(1.5rem,2.4vw + .75rem,2rem);font-weight:400;
    letter-spacing:-.02em;line-height:1.15;margin-bottom:1.5rem}}
  svg{{width:100%;min-width:900px;display:block}}
  .colophon{{font-family:var(--mono);font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;
    color:var(--muted);margin-top:1.5rem;padding-top:.75rem;border-top:1px solid rgba(109,106,98,.25)}}
</style>
</head>
<body>
<div class="frame">
<p class="eyebrow">{eyebrow} · VeriFlow Agency</p>
<h1>{title}</h1>
{svg}
<p class="colophon">docs/diagrams/{slug}.svg — regenerate with docs/diagrams/build.py</p>
</div>
</body>
</html>
"""


def title_of(svg: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", svg, re.S)
    if not m:
        raise SystemExit("an svg with no <title> is not an accessible figure")
    return m.group(1).strip()


def indent(svg: str, pad: str) -> str:
    return "\n".join(pad + line if line.strip() else line for line in svg.splitlines())


def main() -> int:
    slugs = sorted(p.stem for p in HERE.glob("*.svg"))
    if not slugs:
        raise SystemExit("no .svg files here")

    site = SITE.read_text(encoding="utf-8") if SITE.is_file() else None
    written, inlined = [], []

    for slug in slugs:
        svg = (HERE / f"{slug}.svg").read_text(encoding="utf-8").strip()
        title = title_of(svg)
        page = PAGE.format(title=title, eyebrow=EYEBROW.get(slug, "Diagram"),
                           fonts=FONTS, svg=svg, slug=slug)
        (HERE / f"{slug}.html").write_text(page, encoding="utf-8")
        written.append(slug)

        if site is None:
            continue
        open_tag, close_tag = f"<!-- diagram:{slug} -->", f"<!-- /diagram:{slug} -->"
        if open_tag not in site:
            continue
        pattern = re.compile(re.escape(open_tag) + r".*?" + re.escape(close_tag), re.S)
        site = pattern.sub(lambda _: f"{open_tag}\n{indent(svg, '  ')}\n  {close_tag}", site, count=1)
        inlined.append(slug)

    if site is not None:
        SITE.write_text(site, encoding="utf-8")

    print(f"wrote {len(written)} page(s): {', '.join(written)}")
    print(f"inlined into the site: {', '.join(inlined) or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
