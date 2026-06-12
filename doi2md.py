#!/usr/bin/env python3
"""
doi2md.py
Converts a scientific paper to AI-ready Markdown.
Features Smart Input Detection, Semantic Scholar API, and Figure Extraction.
"""

import sys
import json
import argparse
import textwrap
import re
import tempfile
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

try:
    import requests
except ImportError:
    sys.exit("❌ Missing dependency: pip install requests")

try:
    from markitdown import MarkItDown
except ImportError:
    sys.exit("❌ Missing dependency: pip install 'markitdown[pdf]'")

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("❌ Missing dependency: pip install pymupdf")


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_url(path: str) -> bool:
    try:
        result = urlparse(path)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def clean_doi(doi: str) -> str:
    if not doi:
        return ""
    doi = doi.strip()
    prefixes = ["https://doi.org/", "http://doi.org/", "doi.org/", "DOI:", "doi:"]
    for prefix in prefixes:
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi

# ── API Integrations ─────────────────────────────────────────────────────────

def fetch_crossref(doi: str) -> dict:
    url = f"https://api.crossref.org/works/{doi}"
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "doi2md/4.0"})
        r.raise_for_status()
        return r.json().get("message", {})
    except requests.RequestException:
        return {}

def fetch_semantic_scholar(doi: str) -> dict:
    fields = "title,abstract,year,authors,referenceCount,citationCount,s2FieldsOfStudy,tldr"
    url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}?fields={fields}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        return r.json()
    except requests.RequestException:
        return {}

def fetch_unpaywall(doi: str, email: str) -> str | None:
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        
        best_oa = data.get("best_oa_location") or {}
        if best_oa.get("url_for_pdf"): return best_oa["url_for_pdf"]
        
        for loc in data.get("oa_locations", []):
            if loc.get("url_for_pdf"): return loc["url_for_pdf"]
    except requests.RequestException:
        pass
    return None

def download_file(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, timeout=60, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except requests.RequestException:
        return False

# ── Extraction Engines ───────────────────────────────────────────────────────

def extract_figures(pdf_path: Path, output_md_path: Path) -> list[Path]:
    """
    Extracts meaningful figures from the PDF and saves them in a sibling directory.
    Filters out tiny images (like ORCID logos or copyright watermarks).
    """
    doc = fitz.open(pdf_path)
    base_name = output_md_path.stem
    figures_dir = output_md_path.parent / f"{base_name}_figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    
    extracted_images = []
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            width = base_image.get("width", 0)
            height = base_image.get("height", 0)
            
            # Smart Filter: Skip images smaller than 150x150 pixels (likely icons/logos)
            if width < 150 or height < 150:
                continue
                
            image_filename = f"page_{page_num + 1}_fig_{img_index + 1}.{image_ext}"
            image_filepath = figures_dir / image_filename
            
            with open(image_filepath, "wb") as f:
                f.write(image_bytes)
                
            extracted_images.append(image_filepath)
            
    return extracted_images

# ── Content Generation ───────────────────────────────────────────────────────

def merge_metadata(cr_meta: dict, s2_meta: dict, doi: str) -> dict:
    title = cr_meta.get("title", [""])[0] if isinstance(cr_meta.get("title"), list) else cr_meta.get("title", "")
    if not title: title = s2_meta.get("title", "Unknown Title")

    abstract = s2_meta.get("abstract") or cr_meta.get("abstract", "")
    abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    keywords = set()
    for field in s2_meta.get("s2FieldsOfStudy", []):
        keywords.add(field.get("category", ""))
    for subj in cr_meta.get("subject", []):
        keywords.add(subj)
    keywords = [k for k in keywords if k]

    authors = []
    for a in s2_meta.get("authors", []):
        authors.append(a.get("name", ""))
    if not authors:
        for a in cr_meta.get("author", []):
            authors.append(f"{a.get('given', '')} {a.get('family', '')}".strip())

    journal = cr_meta.get("container-title", [""])[0] if isinstance(cr_meta.get("container-title"), list) else ""
    
    year = s2_meta.get("year")
    if not year:
        parts = (cr_meta.get("published-print") or cr_meta.get("published-online") or {}).get("date-parts", [[]])
        year = str(parts[0][0]) if parts and parts[0] else "N/A"

    return {
        "doi": doi,
        "title": title,
        "authors": authors,
        "journal": journal,
        "year": str(year),
        "abstract": abstract,
        "keywords": keywords,
        "citations": s2_meta.get("citationCount") or cr_meta.get("is-referenced-by-count", "N/A"),
        "references": s2_meta.get("referenceCount") or cr_meta.get("references-count", "N/A"),
        "tldr": s2_meta.get("tldr", {}).get("text", "")
    }

def generate_markdown(meta: dict, pdf_text: str, figures: list[Path], output_md_path: Path) -> str:
    header = f"""---
doi: "{meta.get('doi', '')}"
title: >
  {textwrap.fill(meta.get('title', 'Unknown'), width=80, subsequent_indent='  ')}
authors:
{chr(10).join(f'  - "{a}"' for a in meta.get('authors', [])) if meta.get('authors') else '  - "Unknown"'}
journal: "{meta.get('journal', '')}"
year: {meta.get('year', 'N/A')}
citations: {meta.get('citations', 'N/A')}
references_count: {meta.get('references', 'N/A')}
keywords: {json.dumps(meta.get('keywords', []))}
converted_at: "{datetime.now().isoformat()}"
source: "doi2md"
---

"""
    body = f"# {meta.get('title', 'Document')}\n\n"
    
    if meta.get('tldr'):
        body += f"> **AI TLDR:** {meta['tldr']}\n\n"

    if meta.get('abstract'):
        body += f"## Abstract\n\n{meta['abstract']}\n\n---\n\n"

    if pdf_text:
        body += f"## Full Text Extracted via MarkItDown\n\n{pdf_text}\n"
    else:
        body += "> ⚠️ **Full Text Missing:** PDF was not provided locally and could not be found via Open Access.\n"

    # Append Figures Section
    if figures:
        body += "\n---\n## Extracted Figures\n\n"
        for fig_path in figures:
            # Create a relative path from the markdown file to the image folder
            rel_path = f"{output_md_path.stem}_figures/{fig_path.name}"
            body += f"![Figure: {fig_path.name}]({rel_path})\n\n"

    return header + body


# ── Main Execution ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Convert scientific papers to AI-ready Markdown with Figure Extraction.")
    parser.add_argument("input", nargs="?", help="Universal Input: DOI, PDF URL, or Local PDF path")
    parser.add_argument("--doi", help="Explicitly define DOI (useful if input is just a bucket PDF)")
    parser.add_argument("--output", "-o", help="Custom output Markdown filename.")
    parser.add_argument("--email", default="researcher@example.com", help="Email for Unpaywall.")
    args = parser.parse_args()

    if not args.input and not args.doi:
        parser.print_help()
        sys.exit(1)

    target_doi = clean_doi(args.doi) if args.doi else ""
    target_pdf = ""

    if args.input:
        if is_url(args.input):
            if "doi.org" in args.input.lower() or args.input.startswith("10."):
                target_doi = clean_doi(args.input)
            else:
                target_pdf = args.input
        elif args.input.lower().endswith(".pdf") or Path(args.input).exists():
            target_pdf = args.input
        else:
            target_doi = clean_doi(args.input)

    print("\n🚀 doi2md Execution Started")
    print("=" * 60)
    
    # Pre-calculate Output Path to organize figures accurately
    out_name = args.output
    if not out_name:
        if target_doi:
            out_name = f"{target_doi.replace('/', '_')}.md"
        elif target_pdf and not is_url(target_pdf):
            out_name = f"{Path(target_pdf).stem}.md"
        else:
            out_name = "extracted_paper.md"
    out_path = Path(out_name)

    print(f"📄 Detected DOI: {target_doi or 'None (PDF-only mode)'}")
    if target_pdf:
        print(f"📂 Detected PDF Source: {target_pdf}")

    # Fetch Metadata
    cr_meta, s2_meta = {}, {}
    if target_doi:
        print("\n🔍 Fetching base metadata from CrossRef...")
        cr_meta = fetch_crossref(target_doi)
        print("🧠 Fetching enriched metadata from Semantic Scholar...")
        s2_meta = fetch_semantic_scholar(target_doi)
    
    unified_meta = merge_metadata(cr_meta, s2_meta, target_doi)

    # Handle PDF Source
    pdf_path = None
    is_temp_pdf = False

    if target_pdf:
        if is_url(target_pdf):
            print("\n🌐 Downloading PDF from Bucket/URL...")
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            tmp_path = Path(tmp.name)
            if download_file(target_pdf, tmp_path):
                pdf_path, is_temp_pdf = tmp_path, True
            else:
                tmp_path.unlink(missing_ok=True)
                sys.exit("❌ Failed to fetch PDF from URL.")
        else:
            pdf_path = Path(target_pdf)
            if not pdf_path.exists(): sys.exit(f"❌ Local PDF not found: {pdf_path}")

    elif target_doi:
        print("\n🔓 Searching for Open Access PDF via Unpaywall...")
        pdf_url = fetch_unpaywall(target_doi, args.email)
        if pdf_url:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.close()
            tmp_path = Path(tmp.name)
            if download_file(pdf_url, tmp_path):
                pdf_path, is_temp_pdf = tmp_path, True
            else:
                tmp_path.unlink(missing_ok=True)
        else:
            print("⚠️  No OA PDF found. Metadata only will be generated.")

    # Processing (Text + Figures)
    pdf_text = ""
    extracted_figs = []
    
    if pdf_path:
        print("\n🖼️  Extracting figures from PDF...")
        extracted_figs = extract_figures(pdf_path, out_path)
        print(f"✅ Found and saved {len(extracted_figs)} significant figures.")

        print("\n⚙️  Parsing PDF full text with MarkItDown...")
        try:
            md_converter = MarkItDown(enable_plugins=False)
            pdf_text = md_converter.convert(str(pdf_path)).text_content
            print(f"✅ Full text extracted ({len(pdf_text):,} characters).")
        except Exception as e:
            print(f"❌ MarkItDown failed: {e}")
        
        if is_temp_pdf:
            pdf_path.unlink(missing_ok=True)

    markdown_content = generate_markdown(unified_meta, pdf_text, extracted_figs, out_path)

    # Save Output
    out_path.write_text(markdown_content, encoding="utf-8")
    
    print(f"\n💾 Document saved to: {out_path.absolute()}")
    if extracted_figs:
        print(f"📁 Figures saved to: {(out_path.parent / (out_path.stem + '_figures')).absolute()}")
    print("🤖 Process complete.\n")

if __name__ == "__main__":
    main()