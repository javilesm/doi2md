# 📄 doi2md (v6.1 — Deep Extraction & Post-Processing Edition)

> **An advanced, multi-layered extraction pipeline converting scientific papers into clean, structured Markdown bundles optimized for AI Agents, Vector DBs, and RAG architectures.**

`doi2md` is a powerful CLI tool that takes a DOI, a PDF URL, or a local PDF file and performs a deep extraction of its contents. Unlike standard converters that flatten documents into messy text, `doi2md` parses the document through 6 specialized layers—extracting metadata, tables, figures, references, and structural entities. 

**New in v6.2:** * **L5b Vision AI Integration:** Uses multimodal LLMs (Google Gemini) to automatically analyze extracted figures and inject semantic descriptions directly into the Markdown, making visual data searchable for RAG systems.
* **Interactive Cost Triage:** A Human-in-the-Loop HTML preview system that allows you to select which images to process with AI, drastically reducing API costs by skipping publisher logos and irrelevant graphics.
* **Semantic Table Serialization:** Tables are no longer just raw TSVs; they are now intelligently normalized, transposed, and serialized into highly readable semantic sentences optimized for LLM attention mechanisms.

## 🌊 The Extraction Pipeline

```text
PDF (Local, URL, or GCS Bucket)
   │
   ├─ L1  CrossRef + Semantic Scholar  →  Metadata (dict)
   │
   ├─ L2  MarkItDown                   →  Full-text (raw extraction)
   │         │
   │         └──▶ clean_fulltext()     ──▶ Purified text (no boilerplate/artifacts)
   │
   ├─ L3  pdfplumber + pandas          →  Tables (TSV) + Semantic Serialization
   ├─ L4  pypdf                        →  References (BibTeX)
   │
   ├─ L5  PyMuPDF                      →  Figures (raw images + captions)
   │         │
   │         ├──▶ postprocess_figures()──▶ Filtered figures (no logos/tiny icons)
   │         └──▶ Interactive Triage   ──▶ Local HTML preview for API cost control
   │
   ├─ L5b Vision AI (Gemini)           →  Semantic Graph Descriptions injected
   │
   ├─ L6  Structural Parser            →  Section Map + Entities
   │         (Runs safely on the purified text to avoid header/footer confusion)
   │
   └─ Markdown Assembler               →  <slug>.md & ZIP Bundle
```

## ✨ The 6-Layer Architecture

| Layer | Engine | Extraction Scope |
| :--- | :--- | :--- |
| **L1** | CrossRef + Semantic Scholar | Merged bibliographic metadata, TL;DR, and exact publication data. |
| **L2** | MarkItDown | Robust full-text extraction mapped to structured Markdown. |
| **L3** | pdfplumber + pandas | Parses complex tables, normalizes nulls, and outputs semantic RAG sentences & .tsv files. |
| **L4** | pypdf + Heuristics | Parses the reference list and generates BibTeX-style stubs. |
| **L5** | PyMuPDF | Extracts raster figures (≥150x150 px) and attempts caption linking. |
| **L5b** | Google GenAI (Gemini) | Multimodal analysis of charts and graphs for deep context vectorization. |
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

2. Install the required deep-extraction dependencies:
  ```bash
   pip install -r requirements.txt
  ```

3. Configure your Vision API Key (Required for L5b):
Set your Google Gemini API key as an environment variable. If using GitHub Codespaces, it is highly recommended to add this as a Repository Secret for secure, automatic injection.
  ```bash
   export GEMINI_API_KEY="your_api_key_here"
  ```

(Note: Ensure postprocess.py remains in the same directory as doi2md.py so the post-processor can be imported successfully).
   
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
## 🧠 Interactive Cost Optimization
When processing documents with figures, doi2md will automatically generate a local vision_preview.html file containing base64-encoded thumbnails of the extracted assets. The CLI will pause and prompt you to select which images are worth processing with the Gemini Vision API (saving tokens by skipping publisher logos or irrelevant diagrams).

## ⚡ Customization Flags
Disable specific extraction layers to speed up processing or reduce bundle size:

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

-   **Figures Gallery** (Embedded syntax linked to images, enriched with Gemini Vision AI semantic descriptions).
  
-   **Semantic Tables** (Structured sentence arrays optimized for vector search).

-   **Full Text & References**.

## 🤝 Contributing
Pull Requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

 
## 📄 License
This project is licensed under the MIT License. See the LICENSE file for more details.
