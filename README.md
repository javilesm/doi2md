# 📄 doi2md (DOI to Markdown)

> **Convert scientific papers into enriched Markdown, ready for AI agents and RAG systems.**
> **An advanced, multi-layered extraction pipeline converting scientific papers into structured Markdown bundles optimized for AI Agents, Vector DBs, and RAG architectures.**

`doi2md` is a powerful CLI tool that takes a DOI, a PDF URL, or a local PDF file and performs a deep extraction of its contents. Unlike standard converters that flatten documents into messy text, `doi2md` parses the document through 6 specialized layers—extracting metadata, tables, figures, references, and structural entities—and packages everything into a clean, portable `.zip` bundle.

## ✨ The 6-Layer Architecture

| Layer | Engine | Extraction Scope |
| :--- | :--- | :--- |
| **L1** | CrossRef + Semantic Scholar | Merged bibliographic metadata, TL;DR, and exact publication data. |
| **L2** | MarkItDown | Robust full-text extraction mapped to structured Markdown. |
| **L3** | pdfplumber | Parses complex tables and outputs programmatic `.tsv` files. |
| **L4** | pypdf + Heuristics | Parses the reference list and generates BibTeX-style stubs. |
| **L5** | PyMuPDF | Extracts raster figures (≥150x150 px) and attempts caption linking. |
| **L6** | Structural Parser | Generates a section map and auto-extracts chemical/measurement entities. |

## 📦 Output Bundle Structure

The tool automatically compresses the extracted assets into a single `<slug>.zip` file containing a highly organized directory:

```text
<slug>/
├── <slug>.md           # Main Markdown file (with integrated galleries & maps)
├── metadata.json       # Full merged metadata from all L1 APIs
├── references.bib      # BibTeX-style reference stubs
├── figures/            # Extracted figure images (.png, .jpeg)
└── tables/             # Per-table .tsv files for data analysis
```

## 🛠️ Installation

1. Clone this repository:
   ```bash
   git clone [https://github.com/your-username/doi2md.git](https://github.com/your-username/doi2md.git)
   cd doi2md
   ```

2. Install the required dependencies (requests and markitdown):
  ```bash
   pip install requests "markitdown[pdf]" pymupdf pdfplumber pypdf
  ```
   
## 🚀 Usage
The CLI features Smart Input Detection. You can pass a DOI, a URL, or a local file directly.

1. Standard Extraction:
```bash
python doi2md.py 10.1016/j.oceram.2023.100348
```

2. Remote PDF + DOI Injection:
Combine a remote PDF with its strict DOI metadata:
```bash
python doi2md.py --pdf [https://storage.googleapis.com/bucket/paper.pdf](https://storage.googleapis.com/bucket/paper.pdf) --doi 10.xxxx/x
```

3. Local PDF Processing:
```bash
python doi2md.py --pdf my_local_paper.pdf
```

4. Extract Metadata OnlyIf you only want the abstract, citations, and Frontmatter (without downloading or converting the full PDF):
```bash
python doi_to_markdown.py 10.1016/j.oceram.2023.100348 --fast
```

## ⚡ Customization Flags

| **Flag** | **Description** |
| --- | --- |
| `--fast` | Text + metadata only (skips all optional L3-L6 layers). |
| `--no-tables` | Skips `.tsv` table extraction. |
| `--no-refs` | Skips `.bib` reference parsing. |
| `--no-figures` | Skips image extraction. |
| `--no-struct` | Skips AI section mapping. |
| `--no-entities` | Skips chemical/measurement entity extraction. |
| `--email` | Custom email for the Unpaywall API rate limits. |
| `--output`, `-o` | Set a custom base name for the output ZIP. |


## 🧩 Markdown Anatomy
The generated `<slug>.md` file is tailored for Large Language Models. It includes:

-   **Rich YAML Frontmatter** (Authors, ORCIDs, funders, keywords).

-   **Document Statistics & Section Map** (First 3 sentences of each section for rapid agent scanning).

-   **Entity Lists** (Auto-extracted chemicals and units).

-   **Figure Gallery** (Embedded `![alt](figures/...)` syntax linked to the extracted images).

-   **Full Text & References**.

## 🤝 Contributing
Pull Requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

 
## 📄 License
This project is licensed under the MIT License. See the LICENSE file for more details.
