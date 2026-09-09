# The human-facing docs

`index.html` — one page, EN/CZ, **no build step**. Open it by double-clicking,
or:

```
start docs/site/index.html          # Windows
```

It is a single self-contained file on purpose. This repository's own rule is
that the extension has no build; adding a Docusaurus toolchain here would mean
a `node_modules/`, a build command and a generated directory to keep in sync —
for a document that has to work when somebody opens it from a USB stick.

**Who it is for:** a person deciding whether Agency is worth their time, or
someone who has just been handed the repository. It is a sales and onboarding
document, not a reference — it deliberately stops before the technical detail.

| Where to send someone | For |
|---|---|
| `docs/site/index.html` | why this exists, what it does, how to start |
| `docs/concepts.md` | the six concepts, with the diagrams — one step past this page |
| `README.md` | the command surface and the exact shape on disk |
| `docs/plans/` | every decision and the reasoning behind it (Czech) |

The language switch remembers the choice in `localStorage` and otherwise
follows the browser. Both languages are in the file; nothing is fetched.

## The diagrams

Four figures are **inlined**, not linked, so the single-file promise holds. The
source of each is `docs/diagrams/<slug>.svg`, and `docs/diagrams/build.py`
rewrites the region between `<!-- diagram:<slug> -->` and
`<!-- /diagram:<slug> -->` from it. Run it after editing one; nothing else in
this file is touched. Their labels stay English like the rest of the code
surface, and the Czech is in the caption beneath.

The measure is on the blocks rather than on `main`, which is what lets a figure
use the whole column while the prose stays at 74ch.
