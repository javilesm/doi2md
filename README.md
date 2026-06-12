# 📄 doi2md

> **Convert scientific papers into enriched Markdown, ready for AI agents and RAG systems.**

`doi2md` is a Python command-line interface (CLI) tool that takes a DOI (Digital Object Identifier) or a local PDF file and generates a clean Markdown file. It automatically enriches the document with structured metadata fetched from **CrossRef** and downloads legal Open Access versions using **Unpaywall**.

Ideal for researchers, AI developers, and Retrieval-Augmented Generation (RAG) workflows that need to ingest scientific literature in a standardized format.

## ✨ Features

- 🔍 **Metadata Extraction:** Fetches authors, journal, year, keywords, and abstract from the CrossRef API.
- 🔓 **Open Access Search:** Automatically finds and downloads the legal PDF using the Unpaywall API.
- 📝 **Robust Markdown Conversion:** Uses `MarkItDown` to transform complex PDFs into clean, structured Markdown.
- 🏷️ **YAML Frontmatter:** Injects YAML headers into the generated files for easy integration with vector databases, Obsidian, Notion, or LangChain.
- 🔌 **Offline/Local Mode:** Process local PDFs while still injecting metadata fetched from a given DOI.

## 🛠️ Installation

1. Clone this repository:
   ```bash
   git clone [https://github.com/your-username/doi2md.git](https://github.com/your-username/doi2md.git)
   cd doi2md
   ```

2. Install the required dependencies (requests and markitdown):
  ```bash
   pip install requests markitdown
  ```
   
🚀 UsageThe script runs from the command line and offers multiple operation modes.

1. Fully Automatic Conversion (Via DOI)If the paper is Open Access, the script will download the PDF and convert it:
```bash
python doi_to_markdown.py 10.1016/j.oceram.2023.100348
```

2. Save with a Specific Filename:
```bash
python doi_to_markdown.py 10.1016/j.oceram.2023.100348 --output my_paper.md
```

3. Use a Local PDF + DOI MetadataIf you have a paper behind a paywall but already downloaded the PDF locally, you can combine them:
```bash
python doi_to_markdown.py 10.xxxx/xxxxx --pdf path/to/downloaded_paper.pdf
```

4. Extract Metadata OnlyIf you only want the abstract, citations, and Frontmatter (without downloading or converting the full PDF):
```bash
python doi_to_markdown.py 10.1016/j.oceram.2023.100348 --metadata-only
```

## ⚙️ CLI Arguments

| **Argument** | **Description** |
| --- | --- |
| doi | (Optional) The DOI of the scientific paper. |
| \--pdf | Local path to a PDF file. Skips the download step. |
| \--output, -o | Path and filename for the output Markdown file. |
| \--email | Email address for the Unpaywall API (highly recommended to avoid rate limits). |
| \--metadata-only | Generates a .md file with only the metadata and abstract. |


## 🧩 Generated Markdown Structure
The output file will begin with a YAML block and the abstract, followed by the full body text extracted from the PDF:

```bash
---
doi: "10.1016/j.oceram.2023.100348"
title: >
  Full title of the scientific paper...
authors:
  - "Author Name 1"
  - "Author Name 2"
journal: "Open Ceramics"
year: "2023"
keywords: ["ceramics", "materials science"]
converted_at: "2023-10-25T12:00:00.000000"
source: "doi2md"
---

## Abstract
[Document summary...]

---
[Content extracted from the PDF in Markdown...]
```

## 🤝 Contributing
Pull Requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

 
## 📄 License
This project is licensed under the MIT License. See the LICENSE file for more details.
