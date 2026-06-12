#!/usr/bin/env python3
"""
doi_to_markdown.py
Convierte un paper científico (DOI) a Markdown para análisis con agentes IA.

Estrategia:
  1. Consulta CrossRef → metadatos
  2. Consulta Unpaywall → URL del PDF open-access
  3. Descarga el PDF
  4. Convierte con MarkItDown → .md limpio
  5. Genera encabezado YAML con metadatos

Uso:
  python doi_to_markdown.py 10.1016/j.oceram.2023.100348
  python doi_to_markdown.py 10.1016/j.oceram.2023.100348 --output paper.md
  python doi_to_markdown.py --pdf ruta/al/paper.pdf --doi 10.xxxx/xxxxx
"""

import sys
import json
import argparse
import textwrap
import re
import tempfile
from pathlib import Path
from datetime import datetime

# ── Dependencias opcionales ──────────────────────────────────────────────────
try:
    import requests
except ImportError:
    sys.exit("❌  Instala dependencias: pip install requests markitdown")

try:
    from markitdown import MarkItDown
except ImportError:
    sys.exit("❌  Instala MarkItDown: pip install markitdown")


# ── Helpers ──────────────────────────────────────────────────────────────────

def doi_clean(doi: str) -> str:
    """Normaliza el DOI: elimina prefijos https://doi.org/ etc."""
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "DOI:", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    return doi


def fetch_crossref(doi: str) -> dict:
    """Obtiene metadatos desde CrossRef."""
    url = f"https://api.crossref.org/works/{doi}"
    try:
        r = requests.get(url, timeout=15,
                         headers={"User-Agent": "doi2md/1.0 (mailto:tu@email.com)"})
        r.raise_for_status()
        return r.json().get("message", {})
    except Exception as e:
        print(f"⚠️  CrossRef no disponible: {e}")
        return {}


def fetch_unpaywall(doi: str, email: str = "researcher@example.com") -> str | None:
    """Busca URL de PDF open-access vía Unpaywall."""
    url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        best = data.get("best_oa_location") or {}
        pdf_url = best.get("url_for_pdf") or best.get("url")
        if pdf_url:
            print(f"✅  PDF OA encontrado: {pdf_url}")
            return pdf_url
        # Buscar en todas las ubicaciones OA
        for loc in data.get("oa_locations", []):
            if loc.get("url_for_pdf"):
                print(f"✅  PDF OA alternativo: {loc['url_for_pdf']}")
                return loc["url_for_pdf"]
    except Exception as e:
        print(f"⚠️  Unpaywall no disponible: {e}")
    return None


def download_pdf(url: str, dest: Path) -> bool:
    """Descarga el PDF desde una URL."""
    try:
        r = requests.get(url, timeout=60, stream=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        size_kb = dest.stat().st_size / 1024
        print(f"✅  PDF descargado: {dest} ({size_kb:.0f} KB)")
        return True
    except Exception as e:
        print(f"❌  No se pudo descargar el PDF: {e}")
        return False


def pdf_to_markdown(pdf_path: Path) -> str:
    """Convierte PDF a Markdown con MarkItDown."""
    md = MarkItDown(enable_plugins=False)
    result = md.convert(str(pdf_path))
    return result.text_content


def build_yaml_header(meta: dict, doi: str) -> str:
    """Genera encabezado YAML para el archivo Markdown."""
    title = ""
    if meta.get("title"):
        title = meta["title"][0] if isinstance(meta["title"], list) else meta["title"]

    authors = []
    for a in meta.get("author", []):
        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
        if name:
            authors.append(name)

    journal = ""
    if meta.get("container-title"):
        journal = meta["container-title"][0] if isinstance(meta["container-title"], list) else meta["container-title"]

    year = ""
    published = meta.get("published-print") or meta.get("published-online") or {}
    parts = published.get("date-parts", [[]])
    if parts and parts[0]:
        year = str(parts[0][0])

    abstract = meta.get("abstract", "")
    # Limpia tags HTML del abstract (CrossRef los incluye)
    abstract = re.sub(r"<[^>]+>", "", abstract).strip()

    keywords = meta.get("subject", [])

    header = f"""---
doi: "{doi}"
title: >
  {textwrap.fill(title, width=80, subsequent_indent='  ')}
authors:
{chr(10).join(f'  - "{a}"' for a in authors) or '  - ""'}
journal: "{journal}"
year: "{year}"
keywords: {json.dumps(keywords)}
converted_at: "{datetime.now().isoformat()}"
source: "doi2md"
---

"""
    if abstract:
        header += f"## Abstract\n\n{abstract}\n\n---\n\n"

    return header


def metadata_only_markdown(meta: dict, doi: str) -> str:
    """Genera un .md solo con metadatos cuando no hay PDF disponible."""
    title = ""
    if meta.get("title"):
        title = meta["title"][0] if isinstance(meta["title"], list) else meta["title"]

    authors = []
    for a in meta.get("author", []):
        name = f"{a.get('given', '')} {a.get('family', '')}".strip()
        if name:
            orcid = a.get("ORCID", "")
            authors.append(f"{name}" + (f" (ORCID: {orcid})" if orcid else ""))

    journal = ""
    if meta.get("container-title"):
        journal = meta["container-title"][0] if isinstance(meta["container-title"], list) else meta["container-title"]

    published = meta.get("published-print") or meta.get("published-online") or {}
    parts = published.get("date-parts", [[]])
    year = str(parts[0][0]) if parts and parts[0] else "N/A"

    abstract = re.sub(r"<[^>]+>", "", meta.get("abstract", "")).strip()
    keywords = meta.get("subject", [])
    references_count = meta.get("references-count", "N/A")
    citations = meta.get("is-referenced-by-count", "N/A")

    lines = [
        f"# {title}\n",
        f"**DOI:** https://doi.org/{doi}  ",
        f"**Journal:** {journal}  ",
        f"**Year:** {year}  ",
        f"**Citations:** {citations}  ",
        f"**References:** {references_count}  \n",
        "## Authors\n",
        *[f"- {a}" for a in authors],
        "",
    ]

    if keywords:
        lines += ["\n## Keywords\n", *[f"- {k}" for k in keywords], ""]

    if abstract:
        lines += ["\n## Abstract\n", abstract, ""]

    lines += [
        "\n---",
        "> ⚠️  PDF no disponible en acceso abierto.",
        "> Descarga manualmente el PDF y ejecuta:",
        f"> ```",
        f"> python doi_to_markdown.py --pdf paper.pdf --doi {doi}",
        f"> ```",
    ]

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convierte un paper científico (DOI) a Markdown para agentes IA"
    )
    parser.add_argument("doi", nargs="?", help="DOI del paper (e.g. 10.1016/j.oceram.2023.100348)")
    parser.add_argument("--pdf", help="Ruta local al PDF (omite descarga)")
    parser.add_argument("--output", "-o", help="Archivo de salida .md (default: <doi_slug>.md)")
    parser.add_argument("--email", default="researcher@example.com",
                        help="Email para Unpaywall API (recomendado para rate limits)")
    parser.add_argument("--metadata-only", action="store_true",
                        help="Solo genera metadatos sin intentar descargar PDF")
    args = parser.parse_args()

    if not args.doi and not args.pdf:
        parser.print_help()
        sys.exit(1)

    # ── Normalizar DOI ──
    doi = doi_clean(args.doi) if args.doi else ""

    print(f"\n📄 DOI: {doi or 'N/A'}")
    print("=" * 60)

    # ── Metadatos via CrossRef ──
    meta = {}
    if doi:
        print("🔍 Consultando CrossRef...")
        meta = fetch_crossref(doi)
        if meta.get("title"):
            title = meta["title"][0] if isinstance(meta["title"], list) else meta["title"]
            print(f"📌 Título: {title[:80]}...")

    # ── Nombre de salida ──
    if args.output:
        out_path = Path(args.output)
    elif doi:
        slug = doi.replace("/", "_").replace(".", "-")
        out_path = Path(f"{slug}.md")
    else:
        stem = Path(args.pdf).stem
        out_path = Path(f"{stem}.md")

    # ── Ruta al PDF ──
    pdf_path = None

    if args.pdf:
        pdf_path = Path(args.pdf)
        if not pdf_path.exists():
            sys.exit(f"❌  PDF no encontrado: {pdf_path}")
        print(f"📂 Usando PDF local: {pdf_path}")

    elif not args.metadata_only and doi:
        print("🔓 Buscando PDF en acceso abierto (Unpaywall)...")
        pdf_url = fetch_unpaywall(doi, email=args.email)

        if pdf_url:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            if download_pdf(pdf_url, tmp_path):
                pdf_path = tmp_path
            else:
                tmp_path.unlink(missing_ok=True)
        else:
            print("⚠️  PDF OA no encontrado. Generando solo metadatos...")

    # ── Conversión ──
    yaml_header = build_yaml_header(meta, doi)

    if pdf_path:
        print("⚙️  Convirtiendo PDF a Markdown...")
        body = pdf_to_markdown(pdf_path)
        # Limpiar tmp si aplica
        if args.pdf is None:
            pdf_path.unlink(missing_ok=True)
        markdown_content = yaml_header + body
        print(f"✅  Conversión exitosa ({len(body):,} caracteres)")
    else:
        print("📋 Generando Markdown solo con metadatos...")
        markdown_content = yaml_header + metadata_only_markdown(meta, doi)

    # ── Guardar ──
    out_path.write_text(markdown_content, encoding="utf-8")
    print(f"\n💾 Guardado en: {out_path}")
    print(f"   Tamaño: {out_path.stat().st_size / 1024:.1f} KB")
    print(f"   Líneas: {markdown_content.count(chr(10)):,}")
    print("\n🤖 Listo para análisis con agentes IA.\n")


if __name__ == "__main__":
    main()
