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
    def repl(m: re.Match) -> str:
        spacing, base = m.group(1), m.group(2)
        combined = base + _SPACING_TO_COMBINING[spacing]
        return unicodedata.normalize("NFC", combined)
    return _DIACRITIC_RE.sub(repl, text)

_CID_ZERO_RE = re.compile(r"\s*\(cid:0\)\s*")
_CID_OTHER_RE = re.compile(r"\(cid:\d+\)")

def fix_cid_artifacts(text: str) -> str:
    text = _CID_ZERO_RE.sub("−", text)
    text = _CID_OTHER_RE.sub("", text)
    return text

_SOFT_HYPHEN_RE = re.compile(r"\u00ad\s*")

def fix_soft_hyphens(text: str) -> str:
    return _SOFT_HYPHEN_RE.sub("", text)

def strip_form_feeds(text: str) -> str:
    return text.replace("\x0c", "")

_COMPOUND_PREFIXES = {
    "two", "three", "four", "five", "multi", "non", "post", "pre", "self",
    "well", "high", "low", "co", "vat", "top", "bottom", "cross", "long",
    "short", "open", "closed", "real", "single", "double",
}

def fix_linewrap_hyphenation(text: str) -> str:
    def repl(m: re.Match) -> str:
        first, second = m.group(1), m.group(2)
        if first.lower() in _COMPOUND_PREFIXES:
            return f"{first}-{second}"
        return f"{first}{second}"
    return re.sub(r"(\w+)-\n(\w+)", repl, text)

def collapse_justified_spacing(text: str) -> str:
    lines = text.split("\n")
    fixed = [re.sub(r" {2,}", " ", line) for line in lines]
    return "\n".join(fixed)


# ══════════════════════════════════════════════════════════════════════════════
# 3. PUBLISHER / JOURNAL BOILERPLATE REMOVAL
# ══════════════════════════════════════════════════════════════════════════════

def _flexible_phrase(phrase: str) -> str:
    words = phrase.split()
    return r"\s*".join(re.escape(w) for w in words)

def _author_initials_pattern(surname: str) -> str:
    return rf"[A-Z]\.[A-Z]?\.?\s*{re.escape(surname)}"

def remove_sciencedirect_nav(text: str, journal: str) -> str:
    if not journal: return text
    J = _flexible_phrase(journal)
    nav = re.compile(
        rf"Contents\s+lists\s+available\s+at\s+ScienceDirect\s*\n+\s*{J}\s*\n+"
        rf"journal\s+homepage:\s*\S+\s*\n*", re.IGNORECASE)
    return nav.sub("", text)

def remove_running_headers(text: str, journal: str, year: str, first_author: str) -> str:
    if not (journal and year and first_author): return text
    J = _flexible_phrase(journal)
    A = _author_initials_pattern(first_author)

    with_license = re.compile(
        rf"{J}\s*\d+\s*\(\s*{year}\s*\)\s*\d+Availableonline.*?(?:nd/4\.0/\)\.|\.\)\.)\x0c{A}\s+et al\.",
        re.IGNORECASE | re.DOTALL)
    text = with_license.sub("", text)

    simple = re.compile(rf"{J}\s*\d+\s*\(\s*{year}\s*\)\s*\d+\x0c{A}\s+et al\.", re.IGNORECASE)
    text = simple.sub("", text)

    standalone = re.compile(rf"\n\s*{J}\s*\d+\s*\(\s*{year}\s*\)\s*\d+\s*\n", re.IGNORECASE)
    text = standalone.sub("\n", text)
    return text

def remove_reference_stamps(text: str, journal: str, year: str, first_author: str) -> str:
    if not first_author: return text
    A = _author_initials_pattern(first_author)
    if journal and year:
        J = _flexible_phrase(journal)
        with_stamp = re.compile(rf"\s*{A}\s+et al\.\s*{J}\s+\d+\s*\(\s*{year}\s*\)\s*\d+\s*\d*\s*$", re.IGNORECASE | re.MULTILINE)
        text = with_stamp.sub("", text)
    bare = re.compile(rf"\s*{A}\s+et al\.\s*$", re.MULTILINE)
    text = bare.sub("", text)
    return text


# ══════════════════════════════════════════════════════════════════════════════
# MASTER FULL-TEXT CLEANER & RECONSTRUCTION
# ══════════════════════════════════════════════════════════════════════════════

def strip_flattened_tables(text: str) -> str:
    """
    Elimina tablas aplanadas usando heurísticas de densidad de texto,
    haciéndolo universal para cualquier editorial, patente o idioma.
    """
    lines = text.split("\n")
    cleaned_lines = []
    skip_mode = False
    grace_lines = 0
    
    # 1. Diccionario Internacional (Trigger)
    table_trigger = re.compile(r"^(?:Table|Tabla|Tableau|Tabelle|Tab\.|Table:\s*)\s*[\dIVX]+", re.IGNORECASE)
    
    for line in lines:
        stripped = line.strip()
        
        # ¿Inicia una tabla? Encendemos la aspiradora
        if table_trigger.match(stripped):
            skip_mode = True
            grace_lines = 4  # Damos hasta 4 líneas de gracia para que pase el título/leyenda
            continue
            
        if skip_mode:
            if not stripped:
                continue
                
            if grace_lines > 0:
                grace_lines -= 1
                continue
            
            # Analizamos la línea actual para saber si ya salimos de la tabla
            words = stripped.split()
            word_count = len(words)
            is_narrative = False
            
            if word_count > 12:
                is_narrative = True
            elif word_count > 7 and stripped[-1] in (".", "?", "!", ":"):
                is_narrative = True
                
            if is_narrative:
                skip_mode = False  # Apagamos la aspiradora, volvimos al paper
                cleaned_lines.append(line)
            else:
                continue # Sigue siendo basura de tabla, la descartamos
                
        else:
            cleaned_lines.append(line)
            
    return "\n".join(cleaned_lines)

def fix_fragmented_units(text: str) -> str:
    text = re.sub(r"[◦°˚]\s*[\n\r]+\s*C\b", "°C", text)
    text = re.sub(r"(\b\d+(?:\.\d+)?)\s*[\n\r]+\s*(°?C)\b", r"\1 °C", text)
    text = re.sub(r"^[ \t]*[◦°˚][ \t]*$[\n\r]*", "", text, flags=re.MULTILINE)
    text = re.sub(r"([a-z])\s*[\n\r]+\s*°C\b", r"\1 °C", text)
    return text

def heal_paragraphs(text: str) -> str:
    return re.sub(r"([a-z,\-])[ \t]*\n[ \t]*([a-zA-Z0-9])", r"\1 \2", text)
  
def clean_fulltext(text: str, meta: dict) -> str:
    """Apply the full cleaning pipeline to extracted full text."""
    journal = (meta.get("journal") or "").strip()
    year    = str(meta.get("year") or "").strip()

    first_author_surname = ""
    authors = meta.get("authors") or []
    if authors:
        first_name = authors[0].get("name", "") if isinstance(authors[0], dict) else str(authors[0])
        parts = first_name.split()
        if parts:
            first_author_surname = parts[-1]

    # ── 3. Boilerplate removal ─────────────────────
    text = remove_sciencedirect_nav(text, journal)
    text = remove_running_headers(text, journal, year, first_author_surname)
    text = remove_reference_stamps(text, journal, year, first_author_surname)

    # ── 1. Character encoding fixes ────────────────
    text = fix_misplaced_diacritics(text)
    text = fix_cid_artifacts(text)
    text = fix_soft_hyphens(text)
    text = strip_form_feeds(text)
    text = fix_linewrap_hyphenation(text)

    # ── 2. Formatting cleanup ──────────────────────
    text = collapse_justified_spacing(text)

    # ── 4. Reconstrucción Avanzada (Las nuevas funciones) ──
    text = strip_flattened_tables(text)
    text = fix_fragmented_units(text)
    text = heal_paragraphs(text)

    # Limpieza final de saltos de línea (deja maximo 2 saltos)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ══════════════════════════════════════════════════════════════════════════════
# 4. FIGURE POST-PROCESSING
# ══════════════════════════════════════════════════════════════════════════════

CAPTION_TRUNCATE_LEN = 200

def postprocess_figures(figures: list[dict], min_dimension_for_uncaptioned: int = 300) -> list[dict]:
    cleaned: list[dict] = []

    for fig in figures:
        f = dict(fig)
        cap = f.get("caption", "") or ""

        cap = fix_misplaced_diacritics(cap)
        cap = fix_cid_artifacts(cap)
        cap = fix_soft_hyphens(cap)
        cap = fix_linewrap_hyphenation(cap)
        cap = re.sub(r"\s{2,}", " ", cap).strip()

        if len(cap) >= CAPTION_TRUNCATE_LEN:
            cap = cap.rstrip() + "…"
        f["caption"] = cap

        if not cap:
            largest_side = max(f.get("width_px", 0), f.get("height_px", 0))
            if largest_side < min_dimension_for_uncaptioned:
                continue 

        cleaned.append(f)

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

import re
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None

def optimize_table_for_rag(tsv_path: Path, table_id: int) -> str:
    """
    Lee un TSV crudo, lo limpia de artefactos académicos, decide si debe 
    reestructurarlo (transponer) y lo serializa en oraciones para el LLM.
    """
    if pd is None:
        return "[Pandas no está instalado. Omitiendo optimización de tabla.]"

    try:
        # Cargar el TSV
        df = pd.read_csv(tsv_path, sep='\t', dtype=str)
        
        # =========================================================
        # 1. LIMPIEZA Y NORMALIZACIÓN (Data Cleansing)
        # =========================================================
        # Elimina citas bibliográficas incrustadas ej: "310.2 [14]" -> "310.2"
        # Elimina llamadas de nota al pie ej: "0.511a" o "0.511*" -> "0.511"
        df = df.replace(to_replace=r'\s*\[\d+\]|\*|\^[a-zA-Z]', value='', regex=True)
        
        # Limpia espacios extra en todas las celdas
        df = df.apply(lambda col: col.str.strip())
        
        # Manejo de vacíos (Imputación)
        df = df.fillna("N/A")
        df = df.replace(["", "-", "–"], "N/A")

        # Guardamos la versión limpia sobre el TSV original
        df.to_csv(tsv_path, sep='\t', index=False)

        # =========================================================
        # 2. TRANSFORMACIÓN ESTRUCTURAL (Data Wrangling)
        # =========================================================
        # Regla RAG: A los LLMs les cuesta leer tablas de más de 5-6 columnas.
        # Si la tabla es muy ancha, la transponemos (giramos 90 grados).
        if len(df.columns) >= 6:
            # Transponer y usar la primera columna como nuevos encabezados
            df_t = df.T
            df_t.columns = [f"Item_{i}" for i in range(len(df_t.columns))]
            df_t.reset_index(inplace=True)
            df_t = df_t.rename(columns={"index": "Atributo"})
            df = df_t

        # =========================================================
        # 3. SERIALIZACIÓN SEMÁNTICA (Optimización para RAG)
        # =========================================================
        # En lugar de devolver Markdown `| X | Y |`, creamos viñetas lógicas
        # que inyectan el contexto de la tabla en cada fragmento de texto.
        
        sentences = [f"### Datos Extraídos de la Tabla {table_id}:\n"]
        columns = df.columns.tolist()
        
        for index, row in df.iterrows():
            # Filtramos las celdas que dicen N/A para no meter ruido al LLM
            row_data = [f"{col}: {row[col]}" for col in columns if str(row[col]) != "N/A"]
            
            # Construimos una oración por fila
            if row_data:
                sentence = f"- Fila {index + 1}: " + ", ".join(row_data) + "."
                sentences.append(sentence)

        return "\n".join(sentences)

    except Exception as e:
        return f"[Error procesando TSV para RAG: {e}]"