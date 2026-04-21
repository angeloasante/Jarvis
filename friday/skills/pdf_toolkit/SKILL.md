---
name: pdf-toolkit
description: Create, extract, merge, split, and manipulate PDF files. Use when Travis needs PDF work beyond just generating CVs.
agents: [system_agent, job_agent, code_agent]
---

# PDF Toolkit

Full PDF manipulation — not just CV generation.

## Extract Text from PDF

```bash
python3 -c "
import pypdf
reader = pypdf.PdfReader('INPUT.pdf')
for page in reader.pages:
    print(page.extract_text())
"
```

For tables, use pdfplumber (better structure):
```bash
python3 -c "
import pdfplumber
with pdfplumber.open('INPUT.pdf') as pdf:
    for page in pdf.pages:
        print(page.extract_text())
        tables = page.extract_tables()
        for t in tables:
            for row in t:
                print(' | '.join(str(c) for c in row))
"
```

## Create PDF from Scratch

Use reportlab for simple PDFs:
```python
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

c = canvas.Canvas("output.pdf", pagesize=A4)
c.setFont("Helvetica", 12)
c.drawString(72, 750, "Title here")
c.drawString(72, 730, "Body text here")
c.save()
```

For complex layouts (CVs, reports) — use WeasyPrint + Jinja2 (already in FRIDAY's stack):
```python
from weasyprint import HTML
html_content = "<h1>Report</h1><p>Content</p>"
HTML(string=html_content).write_pdf("output.pdf")
```

## Merge PDFs

```python
from pypdf import PdfMerger
merger = PdfMerger()
merger.append("file1.pdf")
merger.append("file2.pdf")
merger.write("merged.pdf")
merger.close()
```

## Split PDF (extract pages)

```python
from pypdf import PdfReader, PdfWriter
reader = PdfReader("input.pdf")
writer = PdfWriter()
writer.add_page(reader.pages[0])  # First page only
writer.write("page1.pdf")
```

## Rotate Pages

```python
from pypdf import PdfReader, PdfWriter
reader = PdfReader("input.pdf")
writer = PdfWriter()
for page in reader.pages:
    page.rotate(90)
    writer.add_page(page)
writer.write("rotated.pdf")
```

## Where to Save

Always save PDFs to `~/Documents/friday_files/` unless Travis specifies otherwise.
Name files descriptively: `trainline_cv_tailored.pdf`, `merged_report.pdf`, etc.

## When Travis Says...

- "merge these PDFs" → PdfMerger
- "extract text from this PDF" → pypdf or pdfplumber
- "create a PDF" → WeasyPrint for complex, reportlab for simple
- "split this PDF" → PdfWriter with specific pages
- "read this PDF and summarize" → extract text, then summarize with LLM
