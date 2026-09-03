# Looking up the law

**One rule: primary source or nothing.** A law firm's blog, a competitor's terms and a previous model's summary are all pointers. None of them is a citation. Every finding this pack produces names a provision, and the wording behind that name was read this run — not remembered.

Both sources below are free, need no key and no registration, and return the wording that is actually in force. Everything here was verified working; where a route is known to fail, that is written down too, so nobody spends the run rediscovering it.

---

## Czech law — e-Sbírka over ELI

The Collection of Laws is published as linked data, addressed by ELI:

```
https://opendata.eselpoint.gov.cz/esel-esb/eli/cz/sb/<year>/<number>[/<version-date>]
```

Ask for `text/turtle`. Without the header you get an HTML data browser, which is 5× larger and no easier to read.

### 1. Which consolidated versions exist

The version date is not "today" — it is a date on which something changed. Guessing one returns an empty document, which is the most common way to waste ten minutes here.

```bash
curl -s -H "Accept: text/turtle" \
  "https://opendata.eselpoint.gov.cz/esel-esb/eli/cz/sb/2004/480" \
| grep -o 'esel-esb/eli/cz/sb/2004/480/[0-9-]*' | sort -u
```

```
…/2020-07-01
…/2023-03-23     ← the wording in force
```

For the Civil Code (89/2012) `2026-01-01` is a real version; for act 480/2004 it is not. Always list first.

### 2. Find the paragraph inside that version

The version document lists every fragment URI it contains, and the URIs are readable — `par_1752`, `odst_2`, `pism_c`:

```bash
curl -s -H "Accept: text/turtle" \
  "https://opendata.eselpoint.gov.cz/esel-esb/eli/cz/sb/2012/89/2026-01-01" > oz.ttl

grep -o 'esel-esb/eli/cz/sb/2012/89/2026-01-01/dokument/norma/[a-z0-9_/]*par_2389q[a-z0-9_/]*' oz.ttl | sort -u
```

```
…/dokument/norma/cast_4/hlava_2/dil_2/oddil_6/pododdil_2/par_2389q
…/par_2389q/odst_1
…/par_2389q/odst_1/pism_a
…/par_2389q/odst_2
…
```

That file is around a megabyte for a large code. Fetch it once per run and keep it in `<RUN_DIR>/evidence/`.

### 3. Read the actual text — two hops

A structural node carries metadata and a pointer; the wording lives on the fragment it points at. So: node → `obsahuje-fragment` → fragment → `text-fragmentu`.

```bash
NODE="https://opendata.eselpoint.gov.cz/esel-esb/eli/cz/sb/2012/89/2026-01-01/dokument/norma/cast_4/hlava_1/dil_2/oddil_3/par_1752/odst_1"

FRAG=$(curl -s -H "Accept: text/turtle" "$NODE" \
       | grep -o 'esel-esb/pr%C3%A1vn%C3%AD-akt-fragment/[0-9]*' | head -1)

curl -s -H "Accept: text/turtle" "https://opendata.eselpoint.gov.cz/$FRAG" \
| grep -A2 'text-fragmentu'
```

```
"<var>(1)</var> Uzavírá-li strana v běžném obchodním styku s větším počtem osob smlouvy
zavazující dlouhodobě k opětovným plněním stejného druhu s odkazem na obchodní podmínky …"
```

Notes that will save a retry:

- The paragraph node itself (`par_1752`, no `odst_`) usually carries only the marker `§ 1752`. Go one level down for the wording.
- The fragment path is URL-encoded (`pr%C3%A1vn%C3%AD-akt-fragment`). Do not decode it.
- `<var>…</var>` wraps the numbering. Strip the tags before quoting.

### 4. Cite the human-readable portal

A finding is read by a person. Link the same ELI on the public portal — the fragment id doubles as the anchor:

```
https://www.e-sbirka.cz/eli/cz/sb/2012/89/2026-01-01#par_1752
```

That page is a single-page application, so it is worth nothing to a scripted fetch. Read from open data, link the portal.

### Numbers worth keeping at hand

| Act | ELI base |
|---|---|
| 89/2012 Civil Code | `/eli/cz/sb/2012/89` |
| 634/1992 Consumer Protection Act | `/eli/cz/sb/1992/634` |
| 480/2004 on certain information-society services (commercial messages) | `/eli/cz/sb/2004/480` |
| 127/2005 Electronic Communications Act (cookies, § 89(3)) | `/eli/cz/sb/2005/127` |
| 110/2019 on personal data processing | `/eli/cz/sb/2019/110` |
| 164/2013 on international cooperation in tax administration (DAC7) | `/eli/cz/sb/2013/164` |
| 424/2023 accessibility of certain products and services | `/eli/cz/sb/2023/424` |

---

## EU law — CELLAR by CELEX

```bash
curl -sL -H "Accept: application/xhtml+xml" -H "Accept-Language: ces" \
  "http://publications.europa.eu/resource/celex/32019R1150"
```

Returns the full Czech wording as XHTML. `Accept-Language: eng` gives English; the Czech version is what you quote when the finding is written in Czech.

**Do not fetch `eur-lex.europa.eu/legal-content/...` from a script.** It answers `202` with an empty body — it looks like a network problem and is not one. Use CELLAR for the text and link EUR-Lex for the reader:

```
https://eur-lex.europa.eu/legal-content/CS/TXT/?uri=CELEX:32019R1150
```

| Instrument | CELEX |
|---|---|
| GDPR 2016/679 | `32016R0679` |
| P2B 2019/1150 (platform ↔ business users) | `32019R1150` |
| DSA 2022/2065 (digital services) | `32022R2065` |
| DAC7 2021/514 (platform reporting) | `32021L0514` |
| Digital content directive 2019/770 | `32019L0770` |
| Consumer rights directive 2011/83 | `32011L0083` |
| ePrivacy 2002/58 | `32002L0058` |
| Accessibility 2019/882 | `32019L0882` |
| ODR repeal 2024/3228 | `32024R3228` |

---

## Guidance and enforcement

Regulator guidance is not law, but it is what the authority will apply to you, and it is a legitimate citation as long as it is labelled as guidance:

| Who | What they answer | Where |
|---|---|---|
| ÚOOÚ | personal data, cookies | `uoou.gov.cz` |
| ČOI | consumer contracts, ADR, digital content | `coi.gov.cz` |
| ČTÚ | DSA — Czech Digital Services Coordinator | `ctu.gov.cz`, `dsacesko.ctu.gov.cz` |
| MPO | P2B, consumer policy, ADR register | `mpo.gov.cz` |
| Finanční správa | DAC7 registration, filing, FAQ | `financnisprava.gov.cz` |
| EDPB | GDPR guidelines (incl. the inherited WP29 ones) | `edpb.europa.eu` |

Case law has no open API. Search by hand and cite the case number: Supreme Court `rozhodnuti.nsoud.cz`, Constitutional Court `nalus.usoud.cz`, Supreme Administrative Court `nssoud.cz`, CJEU `curia.europa.eu`.

---

## What to keep from a lookup

Write every wording you relied on into `<RUN_DIR>/evidence/law/<act>-<provision>.txt` — the text, the ELI or CELEX, the version date, the day you fetched it. Two reasons, and the second is the important one:

1. The next run does not re-fetch it.
2. When a finding is disputed a year later, the argument is about the wording that was in force then, not about what the current portal happens to show.
