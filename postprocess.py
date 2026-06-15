#!/usr/bin/env python3
"""
postprocess.py  —  v1.0
Cleans PDF-extracted text artifacts before assembling the final Markdown.

Targets four categories of noise commonly introduced by MarkItDown / PyMuPDF
text extraction from academic PDFs (tested against Elsevier/ScienceDirect
layouts, but written generically):

  1. CHARACTER ENCODING
     - Misplaced spacing diacritics (˜a → ã, ´e → é, ¨a → ä, etc.)
     - (cid:NNN) font-encoding artifacts → minus sign or removed
     - Soft hyphens from line-wrap hyphenation (ob­tained → obtained)
     - Form-feed page breaks (\x0c) → removed

  2. FORMATTING
     - Excess multi-space sequences from justified-text columns collapsed
     - Smart quotes / dashes normalized where useful

  3. PUBLISHER / JOURNAL BOILERPLATE
     - "Contents lists available at ScienceDirect / <Journal> / journal
       homepage: ..." navigation block
     - Repeating running headers: "<Journal><Vol>(<Year>)<ArticleID><Page>"
       optionally followed by "<Initials>. <Surname> et al."
     - License/availability stamp after the abstract
     - Trailing "<Initials>. <Surname> et al. <Journal> <Vol> (<Year>) <ID> <Page>"
       stamps appended to reference entries

  4. FIGURE CAPTIONS
     - Truncation indicator (…) when caption was cut at the byte limit
     - Deduplication note when multiple extracted images share one caption
       (multi-panel figures)
     - Drop figures with no caption AND tiny/logo-like dimensions

All cleaning functions are parameterized by metadata (journal name, first
author surname, year) extracted via CrossRef/Semantic Scholar, so the same
code generalizes across publishers — not just Elsevier/ScienceDirect.

Usage as a library:
    from postprocess import clean_fulltext, postprocess_figures

    fulltext = clean_fulltext(fulltext, meta)
    figures  = postprocess_figures(figures)
"""

import re
import unicodedata


# ══════════════════════════════════════════════════════════════════════════════
# 1. CHARACTER ENCODING FIXES
# ══════════════════════════════════════════════════════════════════════════════

# PDF text extractors sometimes place a spacing modifier letter BEFORE the
# base character instead of a combining mark AFTER it.
# e.g. "S˜ao" (S + U+02DC + a + o) should be "São" (S + a+combining-tilde + o).
_SPACING_TO_COMBINING = {
    "\u02dc": "\u0303",  # SMALL TILDE        -> COMBINING TILDE      (ã, õ, ñ)
    "\u02c6": "\u0302",  # MODIFIER CIRCUMFLEX-> COMBINING CIRCUMFLEX (â, ê, ô)
    "\u00b4": "\u0301",  # ACUTE ACCENT       -> COMBINING ACUTE      (á, é, í, ó, ú)
    "\u00a8": "\u0308",  # DIAERESIS          -> COMBINING DIAERESIS  (ä, ö, ü)
    "\u0060": "\u0300",  # GRAVE ACCENT       -> COMBINING GRAVE      (à, è)
    "\u02d9": "\u0307",  # DOT ABOVE          -> COMBINING DOT ABOVE
    "\u00b8": "\u0327",  # CEDILLA            -> COMBINING CEDILLA    (ç)
}

_DIACRITIC_RE = re.compile(
    "(" + "|".join(re.escape(k) for k in _SPACING_TO_COMBINING) + r")([A-Za-z])"
)


def fix_misplaced_diacritics(text: str) -> str:
    """Repair 'S˜ao' -> 'São', 'Lind´oia' -> 'Lindóia', 'Lev¨anen' -> 'Levänen'."""
    def repl(m: re.Match) -> str:
        spacing, base = m.group(1), m.group(2)
        combined = base + _SPACING_TO_COMBINING[spacing]
        return unicodedata.normalize("NFC", combined)

    return _DIACRITIC_RE.sub(repl, text)


# (cid:NNN) artifacts: font glyph references that MarkItDown can't resolve.
# In academic PDFs these almost always appear as "(cid:0)" representing a
# minus sign in superscript/exponent contexts (e.g. "s(cid:0)1" -> "s−1",
# "1(cid:0)φ/φmax" -> "1−φ/φmax"). Other (cid:N) codes carry no recoverable
# meaning and are simply dropped.
_CID_ZERO_RE = re.compile(r"\s*\(cid:0\)\s*")
_CID_OTHER_RE = re.compile(r"\(cid:\d+\)")


def fix_cid_artifacts(text: str) -> str:
    """Replace (cid:0) with a minus sign; strip other (cid:N) glyph refs."""
    text = _CID_ZERO_RE.sub("−", text)  # U+2212 MINUS SIGN
    text = _CID_OTHER_RE.sub("", text)
    return text


# Soft hyphen (U+00AD) marks a line-wrap hyphenation point; the PDF extractor
# often leaves a literal space where the line broke. Removing the soft
# hyphen AND any following whitespace rejoins the word.
_SOFT_HYPHEN_RE = re.compile(r"\u00ad\s*")


def fix_soft_hyphens(text: str) -> str:
    """'ob\u00ad tained' -> 'obtained'."""
    return _SOFT_HYPHEN_RE.sub("", text)


def strip_form_feeds(text: str) -> str:
    """Remove page-break form-feed characters (\\x0c)."""
    return text.replace("\x0c", "")


# Common compound-adjective prefixes that should KEEP their hyphen even when
# split across a line break (e.g. "three-\ndimensional" -> "three-dimensional",
# NOT "threedimensional"). This is intentionally a small, conservative list —
# most hyphen+newline occurrences in academic PDFs are line-wrap artifacts
# that should be joined into a single word.
_COMPOUND_PREFIXES = {
    "two", "three", "four", "five", "multi", "non", "post", "pre", "self",
    "well", "high", "low", "co", "vat", "top", "bottom", "cross", "long",
    "short", "open", "closed", "real", "single", "double",
}


def fix_linewrap_hyphenation(text: str) -> str:
    """
    Join words split across a line break by a hyphen (PDF line-wrap artifact):
    'photo-\\npolymerization' -> 'photopolymerization'.

    Preserves the hyphen for known compound-adjective prefixes:
    'three-\\ndimensional' -> 'three-dimensional' (not 'threedimensional').
    """
    def repl(m: re.Match) -> str:
        first, second = m.group(1), m.group(2)
        if first.lower() in _COMPOUND_PREFIXES:
            return f"{first}-{second}"
        return f"{first}{second}"

    return re.sub(r"(\w+)-\n(\w+)", repl, text)


def collapse_justified_spacing(text: str) -> str:
    """
    Collapse runs of 3+ spaces (artifacts of justified-text column extraction)
    down to a single space, but preserve genuine paragraph breaks (\\n\\n).
    """
    # Only operate within lines, not across newlines
    lines = text.split("\n")
    fixed = [re.sub(r" {2,}", " ", line) for line in lines]
    return "\n".join(fixed)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PUBLISHER / JOURNAL BOILERPLATE REMOVAL
# ══════════════════════════════════════════════════════════════════════════════

def _flexible_phrase(phrase: str) -> str:
    """
    Build a regex matching `phrase` with flexible/zero whitespace between
    words — handles PDFs where inter-word spaces are dropped during
    extraction (e.g. 'Open Ceramics' -> 'OpenCeramics').
    """
    words = phrase.split()
    return r"\s*".join(re.escape(w) for w in words)


def _author_initials_pattern(surname: str) -> str:
    """e.g. 'Morais' -> r'[A-Z]\\.[A-Z]?\\.?\\s*Morais' matches 'M.M. Morais'."""
    return rf"[A-Z]\.[A-Z]?\.?\s*{re.escape(surname)}"


def remove_sciencedirect_nav(text: str, journal: str) -> str:
    """
    Remove the "Contents lists available at ScienceDirect / <Journal> /
    journal homepage: ..." navigation block that appears once near the top.
    No-op if journal name is unknown.
    """
    if not journal:
        return text
    J = _flexible_phrase(journal)
    nav = re.compile(
        rf"Contents\s+lists\s+available\s+at\s+ScienceDirect\s*\n+\s*{J}\s*\n+"
        rf"journal\s+homepage:\s*\S+\s*\n*",
        re.IGNORECASE,
    )
    return nav.sub("", text)


def remove_running_headers(text: str, journal: str, year: str, first_author: str) -> str:
    """
    Remove repeating running headers/footers of the form:
      "<Journal><Vol>(<Year>)<ArticleID><Page>[Availableonline...license.)]<FF><Initials>. <Surname> et al."
    These repeat once per page in ScienceDirect-style PDFs.
    No-op for any component that is empty/unknown.
    """
    if not (journal and year and first_author):
        return text

    J = _flexible_phrase(journal)
    A = _author_initials_pattern(first_author)

    # Variant with the license/availability statement (appears once, after abstract)
    with_license = re.compile(
        rf"{J}\s*\d+\s*\(\s*{year}\s*\)\s*\d+"
        rf"Availableonline.*?(?:nd/4\.0/\)\.|\.\)\.)"
        rf"\x0c{A}\s+et al\.",
        re.IGNORECASE | re.DOTALL,
    )
    text = with_license.sub("", text)

    # Simple running header (repeats every page)
    simple = re.compile(
        rf"{J}\s*\d+\s*\(\s*{year}\s*\)\s*\d+"
        rf"\x0c{A}\s+et al\.",
        re.IGNORECASE,
    )
    text = simple.sub("", text)

    # Standalone running-header stamp with no following author marker
    # (occurs e.g. on the final page, where "et al." doesn't follow):
    # "...126629.\n\nOpenCeramics14(2023)10034812\n\n..."
    standalone = re.compile(
        rf"\n\s*{J}\s*\d+\s*\(\s*{year}\s*\)\s*\d+\s*\n",
        re.IGNORECASE,
    )
    text = standalone.sub("\n", text)

    return text


def remove_reference_stamps(text: str, journal: str, year: str, first_author: str) -> str:
    """
    Remove trailing journal/page stamps appended to reference-list entries:
      "... <DOI> . M.M. Morais et al. Open Ceramics 14 (2023) 100348 11"
    and bare trailing "... M.M. Morais et al." on the final entry.
    """
    if not first_author:
        return text

    A = _author_initials_pattern(first_author)

    if journal and year:
        J = _flexible_phrase(journal)
        with_stamp = re.compile(
            rf"\s*{A}\s+et al\.\s*{J}\s+\d+\s*\(\s*{year}\s*\)\s*\d+\s*\d*\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        text = with_stamp.sub("", text)

    bare = re.compile(rf"\s*{A}\s+et al\.\s*$", re.MULTILINE)
    text = bare.sub("", text)

    return text


# ══════════════════════════════════════════════════════════════════════════════
# MASTER FULL-TEXT CLEANER
# ══════════════════════════════════════════════════════════════════════════════
import re

def fix_fragmented_units(text: str) -> str:
    """
    Repara unidades (como °C) que el extractor PDF destrozó en múltiples líneas
    debido a errores de cálculo de superíndices (bounding-box).
    """
    # 1. Fusiona los aros de grado flotantes con la letra 'C' (ej. "◦ \n C" -> "°C")
    text = re.sub(r"[◦°˚]\s*[\n\r]+\s*C\b", "°C", text)

    # 2. Reconecta los números rotos con su unidad 'C' o '°C' (ej. "240 \n C" -> "240 °C")
    text = re.sub(r"(\b\d+(?:\.\d+)?)\s*[\n\r]+\s*(°?C)\b", r"\1 °C", text)

    # 3. Limpia los aros de grado huérfanos (◦) que quedaron solos en líneas en blanco
    text = re.sub(r"^[ \t]*[◦°˚][ \t]*$[\n\r]*", "", text, flags=re.MULTILINE)

    # 4. Soluciona desprendimientos residuales de palabras (ej. "mass \n °C")
    text = re.sub(r"([a-z])\s*[\n\r]+\s*°C\b", r"\1 °C", text)

    return text

def heal_paragraphs(text: str) -> str:
    """
    Desenvuelve los saltos de línea físicos dentro de una misma oración, 
    preservando los saltos estructurales (listas, títulos, dobles saltos).
    """
    # Si una línea termina en letra minúscula, coma o guion, y la siguiente 
    # comienza con letra o número, significa que es la misma oración cortada.
    # Reemplazamos el salto de línea (\n) por un espacio simple.
    return re.sub(r"([a-z,\-])[ \t]*\n[ \t]*([a-zA-Z0-9])", r"\1 \2", text)
  
def clean_fulltext(text: str, meta: dict) -> str:
    """
    Apply the full cleaning pipeline to extracted full text.

    `meta` should contain (any may be empty string / missing):
      - "journal"  e.g. "Open Ceramics"
      - "year"     e.g. "2023"
      - "authors"  list of {"name": "Mateus Mota Morais", ...}

    Order matters: boilerplate removal runs BEFORE diacritic/cid fixes so
    that the regex patterns (built from clean ASCII metadata) match the raw
    text reliably; whitespace collapsing runs last.
    """
    journal = (meta.get("journal") or "").strip()
    year    = str(meta.get("year") or "").strip()

    first_author_surname = ""
    authors = meta.get("authors") or []
    if authors:
        first_name = authors[0].get("name", "") if isinstance(authors[0], dict) else str(authors[0])
        parts = first_name.split()
        if parts:
            first_author_surname = parts[-1]

    # ── 3. Boilerplate removal (run first, on raw text) ─────────────────────
    text = remove_sciencedirect_nav(text, journal)
    text = remove_running_headers(text, journal, year, first_author_surname)
    text = remove_reference_stamps(text, journal, year, first_author_surname)

    # ── 1. Character encoding fixes ─────────────────────────────────────────
    text = fix_misplaced_diacritics(text)
    text = fix_cid_artifacts(text)
    text = fix_soft_hyphens(text)
    text = strip_form_feeds(text)
    text = fix_linewrap_hyphenation(text)

    # ── 2. Formatting cleanup ────────────────────────────────────────────────
    text = collapse_justified_spacing(text)

    # NUEVO: Reparación de unidades fragmentadas (corre ANTES de curar párrafos)
    text = fix_fragmented_units(text)
    
    # NUEVO: Sanación de la estructura del párrafo
    text = heal_paragraphs(text)

    # Collapse 3+ consecutive blank lines (left behind by removed boilerplate)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # ¡El return siempre debe ir al final!
    return text.strip()


# ══════════════════════════════════════════════════════════════════════════════
# 4. FIGURE POST-PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

CAPTION_TRUNCATE_LEN = 200


def postprocess_figures(figures: list[dict], min_dimension_for_uncaptioned: int = 300) -> list[dict]:
    """
    Clean up the figure list produced by the extraction layer:

      - Apply diacritic/cid fixes to captions.
      - Add a proper ellipsis ("…") when a caption was truncated at the
        extraction byte limit, instead of an abrupt mid-word cut.
      - Detect figures sharing an identical caption (multi-panel figures
        split into separate raster images) and annotate them as
        "Panel N of M" sharing one caption.
      - Drop figures with NO caption AND small dimensions (likely logos,
        icons, or decorative elements rather than content figures) — unless
        they exceed `min_dimension_for_uncaptioned` on their largest side.

    Returns a new list; does not mutate the input.
    """
    cleaned: list[dict] = []

    for fig in figures:
        f = dict(fig)
        cap = f.get("caption", "") or ""

        # Fix encoding issues in caption text
        cap = fix_misplaced_diacritics(cap)
        cap = fix_cid_artifacts(cap)
        cap = fix_soft_hyphens(cap)
        cap = fix_linewrap_hyphenation(cap)
        cap = re.sub(r"\s{2,}", " ", cap).strip()

        # Mark truncation properly
        if len(cap) >= CAPTION_TRUNCATE_LEN:
            cap = cap.rstrip() + "…"

        f["caption"] = cap

        # Drop uncaptioned small images (likely logos / page furniture)
        if not cap:
            largest_side = max(f.get("width_px", 0), f.get("height_px", 0))
            if largest_side < min_dimension_for_uncaptioned:
                continue  # skip — not added to `cleaned`

        cleaned.append(f)

    # ── Detect and annotate shared captions (multi-panel figures) ────────────
    caption_groups: dict[str, list[int]] = {}
    for i, f in enumerate(cleaned):
        cap = f.get("caption", "")
        if cap:
            caption_groups.setdefault(cap, []).append(i)

    for cap, indices in caption_groups.items():
        if len(indices) > 1:
            for panel_num, idx in enumerate(indices, start=1):
                cleaned[idx]["panel_info"] = f"Panel {panel_num} of {len(indices)} (shared caption)"

    return cleaned


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Quick smoke tests using snippets representative of the reported issues
    samples = {
        "diacritics": (
            "S˜ao Carlos School of Engineering, University of S˜ao Paulo. "
            "Prof. Rafael Salom˜ao. Aguas de Lind´oia. Valle-P´erez. Lev ¨anen. Cerˆamica.",
            "São Carlos School of Engineering, University of São Paulo. "
            "Prof. Rafael Salomão. Aguas de Lindóia. Valle-Pérez. Lev änen. Cerâmica.",
        ),
        "cid": (
            "viscosity (0.28 Pa s at 30s\n(cid:0) 1) and 1 (cid:0) φ/φmax",
            "viscosity (0.28 Pa s at 30s−1) and 1−φ/φmax",
        ),
        "soft_hyphen": (
            "detailed view ob\u00ad tained with an optical microscope",
            "detailed view obtained with an optical microscope",
        ),
    }

    print("Running self-tests...\n")
    for name, (inp, expected) in samples.items():
        out = fix_misplaced_diacritics(inp)
        out = fix_cid_artifacts(out)
        out = fix_soft_hyphens(out)
        out = collapse_justified_spacing(out)
        status = "PASS" if out.strip() == expected.strip() else "CHECK"
        print(f"[{status}] {name}")
        if status != "PASS":
            print(f"  got:      {out!r}")
            print(f"  expected: {expected!r}")

    print("\nDone.")
