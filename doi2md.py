#!/usr/bin/env python3
"""
doi2md.py  —  v6.0  Deep Extraction Edition
Converts a scientific paper (DOI, PDF URL, or local file) to structured
Markdown optimized for AI agent analysis, RAG pipelines, and vector DBs.

Extraction layers:
  L1  CrossRef + Semantic Scholar  → merged bibliographic metadata + TL;DR
  L2  MarkItDown                   → full text (baseline)
  L3  pdfplumber                   → tables as TSV (structured)
  L4  pypdf                        → reference list parser → references.bib
  L5  PyMuPDF                      → figures extracted + caption linking
  L6  Structural parser            → section map + key entities

Output ZIP bundle:
  <slug>/
    <slug>.md          ← main Markdown (all layers merged)
    figures/           ← extracted figure images (≥150×150 px)
    tables/            ← per-table .tsv files
    references.bib     ← BibTeX-style reference stubs
    metadata.json      ← full merged metadata from all APIs

Usage:
  python doi2md.py 10.1016/j.oceram.2023.100348
  python doi2md.py --pdf https://storage.googleapis.com/bucket/paper.pdf --doi 10.xxxx/x
  python doi2md.py --pdf local.pdf
  python doi2md.py 10.xxxx/x --fast          # text + metadata only
  python doi2md.py 10.xxxx/x --no-tables --no-refs
"""

import sys
import re
import json
import shutil
import argparse
import textwrap
import tempfile
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

# ── Dependency checks ─────────────────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("❌  pip install requests markitdown pymupdf pdfplumber pypdf")

try:
    from markitdown import MarkItDown
except ImportError:
    sys.exit("❌  pip install markitdown")

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("❌  pip install pymupdf")


# ══════════════════════════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════════════════════════

def is_url(s: str) -> bool:
    try:
        r = urlparse(s)
        return bool(r.scheme and r.netloc)
    except ValueError:
        return False


def clean_doi(doi: str) -> str:
    if not doi:
        return ""
    doi = doi.strip()
    for prefix in ["https://doi.org/", "http://doi.org/", "doi.org/", "DOI:", "doi:"]:
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi


def doi_slug(doi: str) -> str:
    return doi.replace("/", "_").replace(".", "-") if doi else "paper"


def _first(val, default=""):
    if isinstance(val, list):
        return val[0] if val else default
    return val or default


def download_file(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, timeout=90, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 doi2md/6.0"})
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        print(f"   OK  {dest.name}  ({dest.stat().st_size / 1024:.0f} KB)")
        return True
    except Exception as e:
        print(f"   FAIL  Download: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# L1 — METADATA  (CrossRef + Semantic Scholar)
# ══════════════════════════════════════════════════════════════════════════════

def fetch_crossref(doi: str) -> dict:
    try:
        r = requests.get(
            f"https://api.crossref.org/works/{doi}",
            timeout=15,
            headers={"User-Agent": "doi2md/6.0 (mailto:researcher@example.com)"},
        )
        r.raise_for_status()
        return r.json().get("message", {})
    except Exception as e:
        print(f"   WARN  CrossRef: {e}")
        return {}


def fetch_semantic_scholar(doi: str) -> dict:
    fields = (
        "title,abstract,year,authors,referenceCount,citationCount,"
        "s2FieldsOfStudy,tldr,publicationVenue,externalIds"
    )
    try:
        r = requests.get(
            f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields={fields}",
            timeout=15,
            headers={"User-Agent": "doi2md/6.0"},
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"   WARN  Semantic Scholar: {e}")
        return {}


def fetch_unpaywall(doi: str, email: str) -> str | None:
    try:
        r = requests.get(
            f"https://api.unpaywall.org/v2/{doi}?email={email}", timeout=15
        )
        r.raise_for_status()
        data = r.json()
        best = data.get("best_oa_location") or {}
        url = best.get("url_for_pdf") or best.get("url")
        if url:
            return url
        for loc in data.get("oa_locations", []):
            if loc.get("url_for_pdf"):
                return loc["url_for_pdf"]
    except Exception as e:
        print(f"   WARN  Unpaywall: {e}")
    return None


def merge_metadata(cr: dict, s2: dict, doi: str) -> dict:
    """Merge CrossRef + Semantic Scholar into a single canonical dict."""
    title = _first(cr.get("title")) or s2.get("title", "Unknown Title")
    abstract = s2.get("abstract") or re.sub(r"<[^>]+>", "", cr.get("abstract", "")).strip()

    # Authors: prefer S2 (has full names), fallback CrossRef with ORCID + affiliation
    authors = []
    if s2.get("authors"):
        for a in s2["authors"]:
            name = a.get("name", "").strip()
            if name:
                authors.append({"name": name, "orcid": "", "affiliation": "", "s2id": a.get("authorId", "")})
    else:
        for a in cr.get("author", []):
            name = f"{a.get('given', '')} {a.get('family', '')}".strip()
            if name:
                orcid = a.get("ORCID", "")
                affil_list = a.get("affiliation", [])
                affil = (affil_list[0].get("name", "") if affil_list else "")
                authors.append({"name": name, "orcid": orcid, "affiliation": affil, "s2id": ""})

    # Keywords: union of S2 fields + CrossRef subjects
    kw_set = set()
    for f in s2.get("s2FieldsOfStudy", []):
        kw_set.add(f.get("category", ""))
    for s in cr.get("subject", []):
        kw_set.add(s)
    keywords = sorted(k for k in kw_set if k)

    journal = _first(cr.get("container-title")) or (s2.get("publicationVenue") or {}).get("name", "")

    published = cr.get("published-print") or cr.get("published-online") or {}
    parts = published.get("date-parts", [[]])
    year = str(parts[0][0]) if parts and parts[0] else str(s2.get("year", "N/A"))

    publisher  = cr.get("publisher", "")
    issn       = _first(cr.get("ISSN"), "")
    license_url = next((lic.get("URL", "") for lic in cr.get("license", [])), "")
    funder_list = [f.get("name", "") for f in cr.get("funder", []) if f.get("name")]
    citations  = s2.get("citationCount") or cr.get("is-referenced-by-count", "N/A")
    ref_count  = s2.get("referenceCount") or cr.get("references-count", "N/A")
    tldr       = (s2.get("tldr") or {}).get("text", "")
    s2_id      = s2.get("paperId", "")

    return {
        "doi": doi, "title": title, "authors": authors,
        "journal": journal, "publisher": publisher,
        "year": year, "issn": issn,
        "abstract": abstract, "keywords": keywords,
        "citations": citations, "references_count": ref_count,
        "license": license_url, "funders": funder_list,
        "tldr": tldr, "s2_paper_id": s2_id,
        "_crossref_raw": cr, "_s2_raw": s2,
    }


# ══════════════════════════════════════════════════════════════════════════════
# L2 — FULL TEXT  (MarkItDown)
# ══════════════════════════════════════════════════════════════════════════════

def extract_fulltext(pdf_path: Path) -> str:
    try:
        md = MarkItDown(enable_plugins=False)
        return md.convert(str(pdf_path)).text_content
    except Exception as e:
        print(f"   WARN  MarkItDown: {e}")
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# L3 — TABLES  (pdfplumber)
# ══════════════════════════════════════════════════════════════════════════════

def extract_tables(pdf_path: Path, tables_dir: Path) -> list[dict]:
    """
    Returns list of table dicts with md_table and tsv_path.
    Writes individual .tsv files to tables_dir.
    """
    try:
        import pdfplumber
    except ImportError:
        print("   WARN  pdfplumber not installed — skipping tables")
        return []

    tables_dir.mkdir(parents=True, exist_ok=True)
    results = []
    table_id = 0

    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                for raw in page.extract_tables():
                    if not raw or len(raw) < 2:
                        continue
                    table_id += 1

                    cleaned = [
                        [str(c).replace("\n", " ").strip() if c else "" for c in row]
                        for row in raw
                    ]

                    # Write TSV
                    tsv_name = f"table_{table_id:02d}_page{page_num}.tsv"
                    tsv_path = tables_dir / tsv_name
                    tsv_path.write_text(
                        "\n".join("\t".join(row) for row in cleaned), encoding="utf-8"
                    )

                    # Build Markdown table
                    col_count = max(len(r) for r in cleaned)
                    cleaned = [r + [""] * (col_count - len(r)) for r in cleaned]
                    header = cleaned[0]
                    md_rows = [
                        "| " + " | ".join(header) + " |",
                        "| " + " | ".join(["---"] * len(header)) + " |",
                    ] + ["| " + " | ".join(row) + " |" for row in cleaned[1:]]

                    results.append({
                        "id": table_id, "page": page_num,
                        "rows": len(cleaned), "cols": col_count,
                        "md_table": "\n".join(md_rows),
                        "tsv_name": tsv_name,
                    })
    except Exception as e:
        print(f"   WARN  Table extraction: {e}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# L4 — REFERENCES  (pypdf + heuristic parser → BibTeX stubs)
# ══════════════════════════════════════════════════════════════════════════════

def extract_references(pdf_path: Path, refs_path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        print("   WARN  pypdf not installed — skipping references")
        return []

    try:
        reader = PdfReader(str(pdf_path))
        full_text = "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception as e:
        print(f"   WARN  pypdf: {e}")
        return []

    # Find references section
    ref_start = -1
    for pat in [
        r"\n(?:References|REFERENCES|Bibliography|BIBLIOGRAPHY|Works Cited)\s*\n",
        r"\n(?:REFERENCES AND NOTES|References and Notes)\s*\n",
    ]:
        m = re.search(pat, full_text)
        if m:
            ref_start = m.end()
            break

    if ref_start == -1:
        return []

    ref_block = full_text[ref_start:].strip()

    # Split on numbered/author-year patterns
    entries = re.split(
        r"\n(?=\[\d+\]|\d{1,3}\.\s+[A-Z]|[A-Z][a-z]+,\s+[A-Z]\.)",
        ref_block,
    )
    if len(entries) < 3:
        entries = [e.strip() for e in ref_block.split("\n") if len(e.strip()) > 30]

    clean = []
    for entry in entries[:200]:
        entry = re.sub(r"\s{2,}", " ", entry.strip().replace("\n", " "))
        if len(entry) > 20:
            clean.append(entry)

    # Write BibTeX stubs
    bib_entries = []
    for i, ref in enumerate(clean, start=1):
        year_m = re.search(r"\b(19|20)\d{2}\b", ref)
        year   = year_m.group() if year_m else "YYYY"
        auth_m = re.match(r"([A-Z][a-z]+)", ref)
        key    = f"{auth_m.group(1) if auth_m else 'ref'}{year}_{i}"
        bib_entries.append(
            f"@article{{{key},\n  note = {{{ref}}},\n  year = {{{year}}}\n}}"
        )

    if bib_entries:
        refs_path.write_text("\n\n".join(bib_entries), encoding="utf-8")

    return clean


# ══════════════════════════════════════════════════════════════════════════════
# L5 — FIGURES  (PyMuPDF — extract bytes + caption linking)
# ══════════════════════════════════════════════════════════════════════════════

def extract_figures(pdf_path: Path, figures_dir: Path) -> list[dict]:
    """
    Extracts raster figures (≥150×150 px).
    Attempts caption detection from nearby text blocks.
    """
    figures_dir.mkdir(parents=True, exist_ok=True)
    results = []
    fig_id = 0

    try:
        doc = fitz.open(str(pdf_path))
        for page_num, page in enumerate(doc, start=1):
            images = page.get_images(full=True)
            text_blocks = page.get_text("blocks")
            seen_xrefs: set[int] = set()

            for img in images:
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)

                try:
                    base = doc.extract_image(xref)
                except Exception:
                    continue

                w, h = base.get("width", 0), base.get("height", 0)
                if w < 150 or h < 150:
                    continue

                fig_id += 1
                ext   = base.get("ext", "png")
                fname = f"fig_{fig_id:03d}_page{page_num}.{ext}"
                (figures_dir / fname).write_bytes(base["image"])

                # Caption heuristic: search text within 100pt below or 80pt above image
                caption = ""
                img_rects = page.get_image_rects(xref)
                if img_rects:
                    rect = img_rects[0]
                    for block in text_blocks:
                        bx0, by0, bx1, by1 = block[0], block[1], block[2], block[3]
                        btext = block[4].strip().replace("\n", " ")
                        # Below image
                        if by0 >= rect.y1 and by1 <= rect.y1 + 100:
                            if re.match(r"(?i)fig(ure)?\.?\s*\d+", btext):
                                caption = btext
                                break
                        # Above image
                        if by1 <= rect.y0 and by0 >= rect.y0 - 80:
                            if re.match(r"(?i)fig(ure)?\.?\s*\d+", btext):
                                caption = btext
                                break

                results.append({
                    "id": fig_id, "page": page_num, "filename": fname,
                    "width_px": w, "height_px": h,
                    "caption": caption[:200] if caption else "",
                })

        doc.close()
    except Exception as e:
        print(f"   WARN  Figure extraction: {e}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# L6 — STRUCTURAL ANALYSIS  (section parser + entity extraction)
# ══════════════════════════════════════════════════════════════════════════════

SECTION_RE = {
    "introduction":       r"(?i)^\s*(?:\d[\.\d]*\s+)?introduction\s*$",
    "related_work":       r"(?i)^\s*(?:\d[\.\d]*\s+)?(?:related work|literature review|background)\s*$",
    "methods":            r"(?i)^\s*(?:\d[\.\d]*\s+)?(?:materials?\s+and\s+methods?|experimental|methodology|methods?|procedures?)\s*$",
    "results":            r"(?i)^\s*(?:\d[\.\d]*\s+)?results?\s*$",
    "discussion":         r"(?i)^\s*(?:\d[\.\d]*\s+)?discussion\s*$",
    "results_discussion": r"(?i)^\s*(?:\d[\.\d]*\s+)?results?\s+and\s+discussion\s*$",
    "conclusions":        r"(?i)^\s*(?:\d[\.\d]*\s+)?conclusions?\s*$",
    "acknowledgments":    r"(?i)^\s*(?:\d[\.\d]*\s+)?acknowledg\w+\s*$",
}


def parse_sections(fulltext: str) -> dict[str, str]:
    lines = fulltext.split("\n")
    sections: dict[str, list[str]] = {"preamble": []}
    current = "preamble"
    for line in lines:
        matched = False
        for name, pat in SECTION_RE.items():
            if re.match(pat, line):
                current = name
                sections.setdefault(current, [])
                matched = True
                break
        if not matched:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items() if "".join(v).strip()}


def extract_entities(text: str) -> dict:
    """Extract chemical formulas and measurements without NLP dependencies."""
    chemicals = {
        c for c in re.findall(r"\b[A-Z][a-z]?(?:\d*[A-Z][a-z]?)+\d*(?:\(\w+\)\d*)?\b", text)
        if re.search(r"\d", c) and 2 < len(c) < 20
    }

    raw_meas = re.findall(
        r"\b\d+(?:[.,]\d+)?\s*"
        r"(?:°C|°F|K|MPa|GPa|kPa|Pa|%|wt\.?\s*%|vol\.?\s*%|at\.?\s*%|"
        r"nm|μm|mm|cm|m|g/cm[³3]|kg/m[³3]|g/L|mol/L|mL|μL|rpm|"
        r"min|h|s|Hz|kHz|MHz|W|kW|J|eV|N|kN|mol|mmol|μmol|ppm|ppb)\b",
        text,
    )
    seen: set[str] = set()
    unique_meas = []
    for m in raw_meas:
        ms = re.sub(r"\s+", " ", m.strip())
        if ms not in seen:
            seen.add(ms)
            unique_meas.append(ms)

    return {"chemicals": sorted(chemicals)[:50], "measurements": unique_meas[:80]}


# ══════════════════════════════════════════════════════════════════════════════
# MARKDOWN ASSEMBLER
# ══════════════════════════════════════════════════════════════════════════════

def build_frontmatter(meta: dict) -> str:
    author_lines = []
    for a in meta["authors"]:
        line = f'  - name: "{a["name"]}"'
        if a.get("orcid"):
            line += f'\n    orcid: "{a["orcid"]}"'
        if a.get("affiliation"):
            line += f'\n    affiliation: "{a["affiliation"]}"'
        if a.get("s2id"):
            line += f'\n    s2id: "{a["s2id"]}"'
        author_lines.append(line)

    funders_yaml = "\n".join(f'  - "{f}"' for f in meta["funders"]) or '  - ""'

    return f"""---
doi: "{meta['doi']}"
title: >
  {textwrap.fill(meta['title'], 80, subsequent_indent="  ")}
authors:
{chr(10).join(author_lines) or '  - name: "Unknown"'}
journal: "{meta['journal']}"
publisher: "{meta['publisher']}"
year: {meta['year']}
issn: "{meta['issn']}"
license: "{meta['license']}"
keywords: {json.dumps(meta['keywords'])}
citations_received: {meta['citations']}
references_count: {meta['references_count']}
funders:
{funders_yaml}
s2_paper_id: "{meta['s2_paper_id']}"
converted_at: "{datetime.now().isoformat()}"
source: "doi2md-v6"
---

"""


SECTION_LABELS = {
    "introduction":       "Introduction",
    "related_work":       "Related Work",
    "methods":            "Methods / Experimental",
    "results":            "Results",
    "discussion":         "Discussion",
    "results_discussion": "Results & Discussion",
    "conclusions":        "Conclusions",
    "acknowledgments":    "Acknowledgments",
}


def build_markdown(
    meta: dict,
    fulltext: str,
    sections: dict,
    entities: dict,
    tables: list[dict],
    figures: list[dict],
    references: list[str],
) -> str:
    parts = [build_frontmatter(meta)]

    # ── Title + TL;DR + Abstract ──────────────────────────────────────────────
    parts.append(f"# {meta['title']}\n")
    if meta.get("tldr"):
        parts.append(f"> **TL;DR (AI-generated):** {meta['tldr']}\n")
    if meta.get("abstract"):
        parts.append(f"\n## Abstract\n\n{meta['abstract']}\n")

    # ── Document statistics ───────────────────────────────────────────────────
    detected_secs = [SECTION_LABELS.get(k, k) for k in sections if k not in ("preamble",)]
    parts.append(f"""
## Document Statistics

| Metric | Value |
|---|---|
| Words extracted | {len(fulltext.split()):,} |
| Figures | {len(figures)} |
| Tables | {len(tables)} |
| References parsed | {len(references)} |
| Detected sections | {", ".join(detected_secs) or "—"} |
| Converted | {datetime.now().strftime("%Y-%m-%d %H:%M UTC")} |

""")

    # ── Section map (quick-reference for agents) ──────────────────────────────
    if any(k in sections for k in SECTION_LABELS):
        parts.append("## Section Map\n\n"
                     "> First 3 sentences per section — agent quick-reference.\n")
        for key, label in SECTION_LABELS.items():
            text = sections.get(key, "")
            if not text:
                continue
            words = len(text.split())
            preview = " ".join(re.split(r"(?<=[.!?])\s+", text)[:3])[:600]
            parts.append(f"\n### {label} *({words:,} words)*\n\n{preview}…\n")

    # ── Key entities ──────────────────────────────────────────────────────────
    chems = entities.get("chemicals", [])
    meas  = entities.get("measurements", [])
    if chems or meas:
        parts.append("\n## Key Entities\n\n"
                     "> Auto-extracted chemical compounds and quantitative values.\n")
        if chems:
            parts.append(f"\n**Chemical compounds ({len(chems)}):**  \n"
                         f"`{'` · `'.join(chems)}`\n")
        if meas:
            parts.append(f"\n**Measurements ({len(meas)}):**  \n"
                         f"`{'` · `'.join(meas)}`\n")

    # ── Figures gallery ───────────────────────────────────────────────────────
    if figures:
        parts.append("\n## Figures\n")
        for fig in figures:
            cap = fig["caption"] or f"Figure {fig['id']} — page {fig['page']}"
            parts.append(
                f"\n### Figure {fig['id']} (page {fig['page']})\n\n"
                f"![{cap}](figures/{fig['filename']})\n\n"
                f"*{cap}*  \n"
                f"Resolution: {fig['width_px']} × {fig['height_px']} px\n"
            )

    # ── Tables ────────────────────────────────────────────────────────────────
    if tables:
        parts.append("\n## Tables\n\n"
                     "> Raw TSV files available in `tables/` for programmatic parsing.\n")
        for t in tables:
            parts.append(
                f"\n### Table {t['id']} — page {t['page']} "
                f"({t['rows']} rows × {t['cols']} cols)\n\n"
                f"{t['md_table']}\n"
            )

    # ── Full text ─────────────────────────────────────────────────────────────
    if fulltext:
        parts.append(f"\n---\n\n## Full Text\n\n{fulltext}\n")

    # ── References ────────────────────────────────────────────────────────────
    if references:
        parts.append(f"\n---\n\n## References ({len(references)} parsed)\n\n"
                     "> BibTeX stubs available in `references.bib`.\n\n")
        for i, ref in enumerate(references, 1):
            parts.append(f"{i}. {ref}\n")

    return "\n".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="doi2md v6 — Scientific paper to Deep Markdown + ZIP for AI agents"
    )
    parser.add_argument("input", nargs="?",
                        help="DOI, PDF URL, or local PDF path")
    parser.add_argument("--doi",    help="Explicit DOI (combine with --pdf)")
    parser.add_argument("--pdf",    help="PDF URL or local path")
    parser.add_argument("--output", "-o", help="Output base name (default: DOI slug)")
    parser.add_argument("--email",  default="researcher@example.com",
                        help="Email for Unpaywall API")
    parser.add_argument("--no-tables",    action="store_true")
    parser.add_argument("--no-refs",      action="store_true")
    parser.add_argument("--no-figures",   action="store_true")
    parser.add_argument("--no-struct",    action="store_true")
    parser.add_argument("--no-entities",  action="store_true")
    parser.add_argument("--fast", action="store_true",
                        help="Text + metadata only (skips all optional layers)")
    args = parser.parse_args()

    if args.fast:
        args.no_tables = args.no_refs = args.no_figures = args.no_struct = args.no_entities = True

    if not args.input and not args.doi and not args.pdf:
        parser.print_help()
        sys.exit(1)

    # ── Resolve inputs ─────────────────────────────────────────────────────────
    target_doi = clean_doi(args.doi or "")
    target_pdf = args.pdf or ""

    if args.input:
        inp = args.input.strip()
        if is_url(inp):
            if "doi.org" in inp or re.match(r"10\.\d{4,}/", inp):
                target_doi = clean_doi(inp)
            else:
                target_pdf = inp
        elif inp.lower().endswith(".pdf") or Path(inp).exists():
            target_pdf = inp
        else:
            target_doi = clean_doi(inp)

    base_name = (
        args.output
        or (doi_slug(target_doi) if target_doi else None)
        or (Path(target_pdf).stem if target_pdf and not is_url(target_pdf) else "paper")
    )

    print(f"\ndoi2md v6  —  Deep Extraction")
    print("=" * 60)
    print(f"  DOI : {target_doi or '—'}")
    print(f"  PDF : {target_pdf or '(auto-discover)'}")
    print(f"  Out : {base_name}.zip\n")

    # ── L1: Metadata ───────────────────────────────────────────────────────────
    cr_meta, s2_meta = {}, {}
    if target_doi:
        print("[L1] CrossRef...")
        cr_meta = fetch_crossref(target_doi)
        print("[L1] Semantic Scholar...")
        s2_meta = fetch_semantic_scholar(target_doi)

    meta = merge_metadata(cr_meta, s2_meta, target_doi)
    if meta["title"] and meta["title"] != "Unknown Title":
        print(f"  Title : {meta['title'][:70]}...")
    if meta.get("tldr"):
        print(f"  TL;DR : {meta['tldr'][:80]}...")

    # ── Acquire PDF ─────────────────────────────────────────────────────────────
    pdf_path: Path | None = None
    is_temp = False

    if target_pdf:
        if is_url(target_pdf):
            print(f"\nDownloading PDF from URL...")
            tmp = Path(tempfile.mktemp(suffix=".pdf"))
            if download_file(target_pdf, tmp):
                pdf_path, is_temp = tmp, True
            else:
                sys.exit("FAIL  PDF download.")
        else:
            pdf_path = Path(target_pdf)
            if not pdf_path.exists():
                sys.exit(f"FAIL  Not found: {pdf_path}")

    elif target_doi:
        print("\n[L1] Unpaywall OA search...")
        oa = fetch_unpaywall(target_doi, args.email)
        if oa:
            print(f"  OA PDF: {oa}")
            tmp = Path(tempfile.mktemp(suffix=".pdf"))
            if download_file(oa, tmp):
                pdf_path, is_temp = tmp, True
        else:
            print("  No OA PDF — metadata only.")

    # ── Staging directory ────────────────────────────────────────────────────
    staging     = Path(f"{base_name}_bundle")
    figures_dir = staging / "figures"
    tables_dir  = staging / "tables"
    staging.mkdir(parents=True, exist_ok=True)

    fulltext  = ""
    sections  = {}
    entities  = {}
    tables    = []
    figures   = []
    references = []

    if pdf_path:
        # L2
        print("\n[L2] MarkItDown full text extraction...")
        fulltext = extract_fulltext(pdf_path)
        print(f"  {len(fulltext):,} chars  /  {len(fulltext.split()):,} words")

        # L6a sections
        if not args.no_struct:
            sections = parse_sections(fulltext)
            detected = [k for k in sections if k != "preamble"]
            print(f"  Sections: {', '.join(detected) or 'none detected'}")

        # L6b entities
        if not args.no_entities:
            entities = extract_entities(fulltext)
            print(f"  Entities: {len(entities.get('chemicals', []))} compounds  "
                  f"{len(entities.get('measurements', []))} measurements")

        # L3
        if not args.no_tables:
            print("\n[L3] pdfplumber table extraction...")
            tables = extract_tables(pdf_path, tables_dir)
            print(f"  {len(tables)} tables")
            if not tables and tables_dir.exists():
                shutil.rmtree(tables_dir, ignore_errors=True)

        # L5
        if not args.no_figures:
            print("\n[L5] PyMuPDF figure extraction...")
            figures = extract_figures(pdf_path, figures_dir)
            print(f"  {len(figures)} figures")
            if not figures and figures_dir.exists():
                shutil.rmtree(figures_dir, ignore_errors=True)

        # L4
        if not args.no_refs:
            print("\n[L4] pypdf reference parser...")
            refs_path = staging / "references.bib"
            references = extract_references(pdf_path, refs_path)
            print(f"  {len(references)} references parsed")

        if is_temp:
            pdf_path.unlink(missing_ok=True)

    # ── metadata.json ─────────────────────────────────────────────────────────
    meta_export = {k: v for k, v in meta.items() if not k.startswith("_")}
    (staging / "metadata.json").write_text(
        json.dumps(meta_export, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ── Assemble & write Markdown ─────────────────────────────────────────────
    print("\nAssembling Markdown...")
    md_content = build_markdown(meta, fulltext, sections, entities, tables, figures, references)
    (staging / f"{base_name}.md").write_text(md_content, encoding="utf-8")

    # ── ZIP ───────────────────────────────────────────────────────────────────
    print(f"Packaging ZIP...")
    shutil.make_archive(base_name, "zip", staging)
    shutil.rmtree(staging)

    zip_path = Path(f"{base_name}.zip")
    print(f"\n{'=' * 60}")
    print(f"  {zip_path.name}  ({zip_path.stat().st_size / 1024:.0f} KB)\n")
    print(f"  Bundle contents:")
    print(f"    {base_name}.md         <- main Markdown (all layers)")
    print(f"    metadata.json          <- merged API metadata")
    if figures:  print(f"    figures/  ({len(figures)} images)")
    if tables:   print(f"    tables/   ({len(tables)} TSV files)")
    if references: print(f"    references.bib  ({len(references)} entries)")
    print(f"\n  Ready for RAG / vector DB / AI agent analysis.\n")


if __name__ == "__main__":
    main()