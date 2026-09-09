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

## The type scale and the palette

Both are set for the size these actually render at: about 820px inside the
site's column, not the 1200px a diagram gets on its own page. So the ramp is
larger than the skill's default — 16px node names, 12px sublabels and field
rows, 11px arrow labels and legends, 10px eyebrows — and `muted` and `soft` are
darkened until both clear WCAG AA on the paper. The site's own `--dim` reads at
about 2.9:1 there, which is fine for 16px prose and not for a 9px sublabel.

Two things that bite when editing:

  - **Runs of spaces do not survive.** Chrome collapses whitespace in SVG
    `<text>` and ignores `xml:space`, so a key/value row is two `<text>`
    elements at fixed x, not one string padded with spaces.
  - **A wider box is cheaper than smaller type.** Every diagram has slack
    around the edges; take it before shrinking a label.

## Where the style comes from

They are drawn under the [diagram-design](https://github.com/cathrynlavery/diagram-design)
skill, on a profile built from the tokens `docs/site/index.html` ships — bone
paper, bistre ink, the agency green as the single accent — pushed for contrast
as above.

The profile is [`style-guide.md`](style-guide.md), committed here because the
skill keeps its own profiles in the home directory, and a marker pointing at a
profile nobody else has is a marker that fails on the second machine. Install
the skill, then put a copy where the skill looks for it:

```
/plugin marketplace add cathrynlavery/diagram-design
/plugin install diagram-design@diagram-design
```

```powershell
mkdir -Force ~/.diagram-design/profiles
Copy-Item docs/diagrams/style-guide.md ~/.diagram-design/profiles/veriflow-agency.md
```

The `.diagram-design` marker in the repository root names that profile, so from
then on a diagram drawn here comes out in the same skin. Edit the committed copy
when the skin changes, and copy it across again — the file here is the one under
review.

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
