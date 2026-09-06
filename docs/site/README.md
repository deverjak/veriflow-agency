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
| `README.md` | the command surface and the exact shape on disk |
| `docs/plans/` | every decision and the reasoning behind it (Czech) |

The language switch remembers the choice in `localStorage` and otherwise
follows the browser. Both languages are in the file; nothing is fetched.
