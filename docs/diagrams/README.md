# The diagrams

Six figures for [`../concepts.md`](../concepts.md). Each one exists once, as
`<slug>.svg`, and is used in three places:

| Where | How |
|---|---|
| `concepts.md`, `README.md` | `![…](diagrams/<slug>.svg)` — the file itself |
| a page you can open | `<slug>.html`, generated |
| `docs/site/index.html` | inlined, so the site stays one file with nothing fetched |

The `.svg` is the source. It carries its own tokens and its own
`prefers-color-scheme` block, so the same bytes are correct on a light page, on
a dark one, and inside the site — whose palette these tokens are taken from.
Ids are prefixed per diagram (`#dg-shape`, `shape-arrow`, `shape-title`), which
is what lets six of them share one page.

## Changing one

Edit the `.svg`, then:

```powershell
python docs/diagrams/build.py
```

It rewrites only what it generates: the `.html` pages, and the region of
`index.html` between `<!-- diagram:<slug> -->` and `<!-- /diagram:<slug> -->`.
A slug with no such region in the site is simply not inlined.

## Where the style comes from

They are drawn under the [diagram-design](https://github.com/cathrynlavery/diagram-design)
skill, on a profile whose tokens are the ones `docs/site/index.html` already
ships — bone paper, bistre ink, the agency green as the single accent. The
profile lives at `~/.diagram-design/profiles/veriflow-agency.md`, and the
`.diagram-design` marker in the repository root selects it, so a diagram drawn
on another machine comes out in the same skin.

Install the skill with:

```
/plugin marketplace add cathrynlavery/diagram-design
/plugin install diagram-design@diagram-design
```

## Checking one

Two checks ship with the skill and both must pass:

```powershell
python <skill>/scripts/self_check.py docs/diagrams/<slug>.html   # accessible-SVG contract, single-file safety
python <repo>/scripts/verify-geometry.py docs/diagrams/<slug>.html  # label masks against node fills
```

The rules they enforce are the ones worth knowing before editing: orthogonal
connectors only, a 6–10px visible gap between an arrow label and its stroke, no
two connectors sharing a stroke path or an attach point, every coordinate a
multiple of four, and at most two accent elements per figure. `<title>` is the
first child of the `<svg>` and `<desc>` says what the figure shows in words a
reader could use without seeing it.
