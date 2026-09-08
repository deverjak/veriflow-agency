"""An output's fingerprint, and dedup across runs.

Why at all: a second run over the same commit — or a run over a PR that has
moved three commits on — produces most of the same findings again. Without
dedup the queue grows faster than it can be worked through, and `precision` is
computed from numbers in which the same finding appears three times.

The fingerprint is DELIBERATELY not computed from the line number or the title:

  the line number  shifts on every commit over the file,
  the title        gets reworded even when the claim is identical.

It is computed from the PLACE (what it is about) and the signature of the
CLAIM (what it says). The place is the symbol or file from the anchor, and for
an output with no anchor its `subject` — a bet sits on a bet, not in
`footer.tsx`. The signature is the set of the most load-bearing words —
rewording the connective text does not change it, changing the content does.

None of this is an LLM call. A dedup that needed a model would cost more than
the finding it throws away.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

from . import anchor

# Words carrying zero information about WHAT a finding claims. Czech and
# English alike, because findings arrive in both languages depending on
# `review.language`.
STOPWORDS = {
    "ktery", "ktera", "ktere", "kteri", "kterou", "kterym", "kterych",
    "protoze", "prototo", "takze", "pritom", "potom", "kdyz", "jenze",
    "tohle", "tento", "tato", "toto", "tyto", "tomu", "toho", "tim",
    "nebo", "ale", "aby", "jako", "jsou", "byla", "bylo", "byly", "bude",
    "budou", "muze", "muzou", "musi", "neni", "nema", "nemaji", "vsak",
    "pouze", "jeste", "uz", "pak", "tak", "tedy", "vzdy", "nikdy", "vsechny",
    "that", "this", "these", "those", "with", "without", "which", "when",
    "then", "than", "from", "into", "will", "would", "should", "could",
    "have", "has", "had", "been", "being", "does", "doesnt", "dont",
    "the", "and", "for", "not", "but", "are", "was", "were", "its",
}

_WORD = re.compile(r"[a-z0-9_]+")
# Code blocks are quotations, not claims — those go entirely.
_FENCE = re.compile(r"```.*?```", re.S)
# The rest of the markdown carries form, not content. CAREFUL: for inline code
# only the backticks are stripped, NOT the content — `getUser` is the most
# load-bearing word of the whole finding, and deleting it leaves dedup
# comparing connective text.
_MD = re.compile(r"[`*_>#|]+|\[([^\]]*)\]\([^)]*\)")


def deaccent(s: str) -> str:
    """Without diacritics. `přeteče` and `pretece` are the same claim."""
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def tokens(text: str) -> set[str]:
    """The load-bearing words of a text. Short words and conjunctions fall out
    — what is left is the claim."""
    cleaned = _MD.sub(" ", _FENCE.sub(" ", text or ""))
    words = _WORD.findall(deaccent(cleaned).lower())
    return {w for w in words if len(w) >= 4 and w not in STOPWORDS}


def claim(finding: dict) -> set[str]:
    """The load-bearing words of the CLAIM. Only `body`, never the title.

    A title survives a corrected diagnosis — the content does not. Matching
    findings by title is exactly the mistake baseline.md paid for by hand
    (§7.2, rule 3).
    """
    return tokens(finding.get("body") or "")


def signature(finding: dict, size: int = 12) -> list[str]:
    """The claim's signature: the `size` longest load-bearing words, sorted.

    The longest, because in a finding about code those are the names of
    symbols, files and the domain — exactly the words rewording leaves alone.
    """
    t = claim(finding)
    return sorted(sorted(t, key=lambda w: (-len(w), w))[:size])


def subject_key(finding: dict) -> str:
    """Where the output sits. Empty string when nowhere.

    Three sources, in this order — the first one that answers wins:

      subject   what the pack says the output is ABOUT (`{kind, ref}`),
      symbol    from the anchor: survives a moved block and a refactor,
      file      from the anchor: weaker, but still independent of the line.

    The anchor is read through `anchor.of()`, so an output that points at
    source with a `code` evidence item gets the same key as one that used the
    `anchor` field — provided its locator carries the same `symbol`. That is
    the whole reason a locator may carry one: a pack that migrates and loses
    the symbol would silently re-report everything it already reported.

    An explicit `subject` wins over the anchor because it is the pack saying
    it, and the anchor-derived key is what an output written before subjects
    existed falls back to. No committed finding carries one, so every
    fingerprint in history keeps its value — that is why the derived shapes
    stay `sym:` and `file:` rather than becoming `symbol:` and `file:` in one
    generalising sweep.

    Empty for an output with no anchor and no subject — a bet is about a
    market and has no place in the source. That is NOT the same as `file:?`:
    a shared `?` would have made every anchorless output share one place,
    which turns the guard in `is_duplicate` — two claims in different places
    are two claims — into the opposite of a guard.
    """
    subject = finding.get("subject") or {}
    kind, ref = subject.get("kind"), subject.get("ref")
    if kind and ref:
        return f"{kind}:{ref}"
    a = anchor.of(finding)
    sym = a.get("symbol") or {}
    name = sym.get("name") if isinstance(sym, dict) else None
    if name:
        return f"sym:{name}"
    file = a.get("file")
    return f"file:{file}" if file else ""


def fingerprint(finding: dict) -> str:
    """A deterministic fingerprint. Same input, same fingerprint, on every machine."""
    parts = [
        (finding.get("pack") or "").split("@")[0],
        finding.get("type") or "finding",
        finding.get("dimension") or "",
        subject_key(finding),
        " ".join(signature(finding)),
    ]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:16]


def overlap(a: set[str], b: set[str]) -> float:
    """Overlap relative to the smaller set, not Jaccard.

    Jaccard punishes length: a finding written out over ten lines and the same
    finding condensed into three have a large union, and an honest overlap
    drowns in it. The question is "does the smaller of them say the same as the
    larger?", and overlap is what answers it.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


# The similarity threshold and the minimum absolute overlap. Both at once,
# because the ratio alone spikes on short findings — three matching words out
# of six is 0.5, and they can still be two different findings in the same
# function.
#
# The risk is asymmetric: a false duplicate THROWS work away, a missed one only
# lengthens the queue. So the threshold is set on the strict side.
SIMILARITY = 0.5
MIN_SHARED = 4


def is_duplicate(new: dict, old: dict) -> tuple[bool, str]:
    """Is `new` a duplicate of `old`? Returns how it was recognised, too.

    Two layers, each catching a different case:
      fingerprint  the same finding from a repeated run, claim word for word
      similarity   the same finding reworded by another run or another model
    """
    if new.get("fingerprint") and new["fingerprint"] == old.get("fingerprint"):
        return True, "fingerprint"
    # Two outputs of different types are never the same output. A bet and a
    # finding about the same page share their nouns, and without this the
    # similarity layer would quietly fold one into the other.
    if (new.get("type") or "finding") != (old.get("type") or "finding"):
        return False, ""
    # With no matching place there is no comparison at all. Two findings about
    # the same thing in different functions are two findings.
    place = subject_key(new)
    if place != subject_key(old):
        return False, ""
    # And with no place on either side, only an identical claim counts. An
    # output that names neither an anchor nor a subject has said nothing about
    # where it sits, and similarity between two such is a guess with nothing
    # to constrain it. The asymmetry decides it, as it does for the threshold
    # above: a false duplicate throws work away, a missed one only lengthens
    # the queue. A pack that wants its anchorless outputs deduplicated by
    # meaning gives them a `subject`; that is what it is for.
    if not place:
        return False, ""
    a, b = claim(new), claim(old)
    shared = a & b
    score = overlap(a, b)
    if score >= SIMILARITY and len(shared) >= MIN_SHARED:
        return True, f"similarity {score:.2f} ({len(shared)} words)"
    return False, ""


def mark_duplicates(new: list[dict], seen: list[dict]) -> list[dict]:
    """Marks duplicates in `new` against `seen` (older findings) and within `new`.

    A finding is NOT thrown away — it gets `state: duplicate` and
    `duplicateOf`. Throwing it away would lose the information that the pack
    found it a second time; and `dedup ratio` is the metric that is counted
    from exactly that.
    """
    pool = list(seen)
    marked = []
    for f in new:
        f.setdefault("fingerprint", fingerprint(f))
        hit = None
        for old in pool:
            dup, how = is_duplicate(f, old)
            if dup:
                hit = (old, how)
                break
        if hit:
            old, how = hit
            f["state"] = "duplicate"
            f["duplicateOf"] = old.get("id")
            marked.append({"id": f.get("id"), "duplicateOf": old.get("id"),
                           "runId": old.get("runId"), "how": how,
                           "title": f.get("title")})
        else:
            f.setdefault("state", "candidate")
            pool.append(f)
    return marked
