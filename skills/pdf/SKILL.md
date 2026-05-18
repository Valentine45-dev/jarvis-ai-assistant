---
name: pdf
description: Use this skill whenever the user wants to do anything with PDF files. This includes reading or extracting text/tables from PDFs, combining or merging multiple PDFs into one, splitting PDFs apart, rotating pages, adding watermarks, creating new PDFs, filling PDF forms, encrypting/decrypting PDFs, extracting images, and OCR on scanned PDFs to make them searchable. If the user mentions a .pdf file or asks to produce one, use this skill.
license: Proprietary. LICENSE.txt has complete terms
---

# PDF Processing Guide

## Overview

This guide covers essential PDF processing operations using Python libraries and command-line tools. For advanced features, JavaScript libraries, and detailed examples, see REFERENCE.md. If you need to fill out a PDF form, read FORMS.md and follow its instructions.

## Quick Start

```python
from pypdf import PdfReader, PdfWriter

# Read a PDF
reader = PdfReader("document.pdf")
print(f"Pages: {len(reader.pages)}")

# Extract text
text = ""
for page in reader.pages:
    text += page.extract_text()
```

## Python Libraries

### pypdf - Basic Operations

#### Merge PDFs
```python
from pypdf import PdfWriter, PdfReader

writer = PdfWriter()
for pdf_file in ["doc1.pdf", "doc2.pdf", "doc3.pdf"]:
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

with open("merged.pdf", "wb") as output:
    writer.write(output)
```

#### Split PDF
```python
reader = PdfReader("input.pdf")
for i, page in enumerate(reader.pages):
    writer = PdfWriter()
    writer.add_page(page)
    with open(f"page_{i+1}.pdf", "wb") as output:
        writer.write(output)
```

#### Extract Metadata
```python
reader = PdfReader("document.pdf")
meta = reader.metadata
print(f"Title: {meta.title}")
print(f"Author: {meta.author}")
print(f"Subject: {meta.subject}")
print(f"Creator: {meta.creator}")
```

#### Rotate Pages
```python
reader = PdfReader("input.pdf")
writer = PdfWriter()

page = reader.pages[0]
page.rotate(90)  # Rotate 90 degrees clockwise
writer.add_page(page)

with open("rotated.pdf", "wb") as output:
    writer.write(output)
```

### pdfplumber - Text and Table Extraction

#### Extract Text with Layout
```python
import pdfplumber

with pdfplumber.open("document.pdf") as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        print(text)
```

#### Extract Tables
```python
with pdfplumber.open("document.pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for j, table in enumerate(tables):
            print(f"Table {j+1} on page {i+1}:")
            for row in table:
                print(row)
```

#### Advanced Table Extraction
```python
import pandas as pd

with pdfplumber.open("document.pdf") as pdf:
    all_tables = []
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if table:  # Check if table is not empty
                df = pd.DataFrame(table[1:], columns=table[0])
                all_tables.append(df)

# Combine all tables
if all_tables:
    combined_df = pd.concat(all_tables, ignore_index=True)
    combined_df.to_excel("extracted_tables.xlsx", index=False)
```

### reportlab - Create PDFs

#### Basic PDF Creation
```python
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("hello.pdf", pagesize=letter)
width, height = letter

# Add text
c.drawString(100, height - 100, "Hello World!")
c.drawString(100, height - 120, "This is a PDF created with reportlab")

# Add a line
c.line(100, height - 140, 400, height - 140)

# Save
c.save()
```

#### Create PDF with Multiple Pages
```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet

doc = SimpleDocTemplate("report.pdf", pagesize=letter)
styles = getSampleStyleSheet()
story = []

# Add content
title = Paragraph("Report Title", styles['Title'])
story.append(title)
story.append(Spacer(1, 12))

body = Paragraph("This is the body of the report. " * 20, styles['Normal'])
story.append(body)
story.append(PageBreak())

# Page 2
story.append(Paragraph("Page 2", styles['Heading1']))
story.append(Paragraph("Content for page 2", styles['Normal']))

# Build PDF
doc.build(story)
```

#### Subscripts and Superscripts

**IMPORTANT**: Never use Unicode subscript/superscript characters (₀₁₂₃₄₅₆₇₈₉, ⁰¹²³⁴⁵⁶⁷⁸⁹) in ReportLab PDFs. The built-in fonts do not include these glyphs, causing them to render as solid black boxes.

Instead, use ReportLab's XML markup tags in Paragraph objects:
```python
from reportlab.platypus import Paragraph
from reportlab.lib.styles import getSampleStyleSheet

styles = getSampleStyleSheet()

# Subscripts: use <sub> tag
chemical = Paragraph("H<sub>2</sub>O", styles['Normal'])

# Superscripts: use <super> tag
squared = Paragraph("x<super>2</super> + y<super>2</super>", styles['Normal'])
```

For canvas-drawn text (not Paragraph objects), manually adjust font the size and position rather than using Unicode subscripts/superscripts.

## Command-Line Tools

### pdftotext (poppler-utils)
```bash
# Extract text
pdftotext input.pdf output.txt

# Extract text preserving layout
pdftotext -layout input.pdf output.txt

# Extract specific pages
pdftotext -f 1 -l 5 input.pdf output.txt  # Pages 1-5
```

### qpdf
```bash
# Merge PDFs
qpdf --empty --pages file1.pdf file2.pdf -- merged.pdf

# Split pages
qpdf input.pdf --pages . 1-5 -- pages1-5.pdf
qpdf input.pdf --pages . 6-10 -- pages6-10.pdf

# Rotate pages
qpdf input.pdf output.pdf --rotate=+90:1  # Rotate page 1 by 90 degrees

# Remove password
qpdf --password=mypassword --decrypt encrypted.pdf decrypted.pdf
```

### pdftk (if available)
```bash
# Merge
pdftk file1.pdf file2.pdf cat output merged.pdf

# Split
pdftk input.pdf burst

# Rotate
pdftk input.pdf rotate 1east output rotated.pdf
```

## Common Tasks

### Extract Text from Scanned PDFs
```python
# Requires: pip install pytesseract pdf2image
import pytesseract
from pdf2image import convert_from_path

# Convert PDF to images
images = convert_from_path('scanned.pdf')

# OCR each page
text = ""
for i, image in enumerate(images):
    text += f"Page {i+1}:\n"
    text += pytesseract.image_to_string(image)
    text += "\n\n"

print(text)
```

### Add Watermark
```python
from pypdf import PdfReader, PdfWriter

# Create watermark (or load existing)
watermark = PdfReader("watermark.pdf").pages[0]

# Apply to all pages
reader = PdfReader("document.pdf")
writer = PdfWriter()

for page in reader.pages:
    page.merge_page(watermark)
    writer.add_page(page)

with open("watermarked.pdf", "wb") as output:
    writer.write(output)
```

### Extract Images
```bash
# Using pdfimages (poppler-utils)
pdfimages -j input.pdf output_prefix

# This extracts all images as output_prefix-000.jpg, output_prefix-001.jpg, etc.
```

### Password Protection
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("input.pdf")
writer = PdfWriter()

for page in reader.pages:
    writer.add_page(page)

# Add password
writer.encrypt("userpassword", "ownerpassword")

with open("encrypted.pdf", "wb") as output:
    writer.write(output)
```

## Quick Reference

| Task | Best Tool | Command/Code |
|------|-----------|--------------|
| Merge PDFs | pypdf | `writer.add_page(page)` |
| Split PDFs | pypdf | One page per file |
| Extract text | pdfplumber | `page.extract_text()` |
| Extract tables | pdfplumber | `page.extract_tables()` |
| Create PDFs | reportlab | Canvas or Platypus |
| Command line merge | qpdf | `qpdf --empty --pages ...` |
| OCR scanned PDFs | pytesseract | Convert to image first |
| Fill PDF forms | pdf-lib or pypdf (see FORMS.md) | See FORMS.md |

## Next Steps

- For advanced pypdfium2 usage, see REFERENCE.md
- For JavaScript libraries (pdf-lib), see REFERENCE.md
- If you need to fill out a PDF form, follow the instructions in FORMS.md
- For troubleshooting guides, see REFERENCE.md

---

<!-- ════════════════════════════════════════════════════════════════════
     JARVIS PDF Intelligence — custom additions (Phase 4.1+)
     Owned by jarvis-project. Preserve when syncing upstream Anthropic skill.
     ════════════════════════════════════════════════════════════════════ -->

# JARVIS PDF Intelligence

JARVIS sends the handler a `doc_type` parameter on every `create_pdf` call (`report` | `academic` | `invoice` | `certificate`). The user message will say *"Apply the {doc_type} formatting standards from the skill guide."* — apply the matching block below. **`doc_type` is a hard input contract, not a hint.**

PDFs differ from docx/pptx/xlsx in one key way: **the layout is final.** Once rendered, the user can't reflow text or resize columns. Get spacing, fonts, and page breaks right the first time.

## Resolution cascade (same shape as the other formats)

1. **STRUCTURAL RULES per doc_type** — page size, layout strategy, font choice, structure. **Inviolable.**
2. **User-described design** — explicit colour, tone, or layout cues in the user's topic/style.
3. **Topic-aware palette** — restrained colour choices for headings, dividers, accents.
4. **doc_type default palette** — final fallback.

## Section A — User-described design

Same rules as the other formats: parse the user's topic and style for colour words, mood words, format words, "no colors" / "simple" / "minimalist" → black on white, named-standard overrides (`APA` / `MLA` → force academic conventions).

## Section B — Topic-aware palette (PDF-tuned)

PDFs are usually shared as final artifacts — colour is fine, but restrained. Two-colour palette (primary heading colour + a neutral body/grey) is the safe default.

| Topic domain | Primary / Neutral |
|---|---|
| Business / finance / sales | `#1F4E79` navy / `#5B6770` slate grey |
| Technology / engineering | `#0D1B2A` deep navy / `#5B6770` slate grey |
| Health / medical | `#0077B6` clinical blue / `#5B6770` slate grey |
| Education / academic-but-not-essay | `#6B2737` burgundy / `#5B6770` slate grey |
| Environment / sustainability | `#1B5E20` forest green / `#5B6770` slate grey |
| Generic / unknown | `#1F4E79` navy / `#5B6770` slate grey |

Body text on white is always pure black `#000000`. Use the primary colour ONLY for: document title, H1 headings, dividers, and table headers (with white text). Never colour body paragraphs.

## ReportLab strategy — Platypus vs canvas

ReportLab has two layout models. Use the right one per doc_type:

- **Platypus** (`SimpleDocTemplate`, `Paragraph`, `Spacer`, `Table`, `PageBreak`) — for text-flowing documents. Use for `report` and `academic`. Platypus handles page breaks, paragraph wrapping, and multi-page layouts automatically.
- **canvas** (`canvas.Canvas`, `canvas.drawString`, `canvas.drawCentredString`, `canvas.rect`, `canvas.line`, `canvas.setFont`, `canvas.setFillColor`) — for fixed-position layouts where you need exact pixel control. Use for `invoice` and `certificate`. The whole document fits on one (or few) pages.

**Default to Platypus** unless the doc_type explicitly calls for canvas (invoice / certificate).

## ReportLab APIs that DO exist (so you don't hallucinate)

Imports:
- `from reportlab.lib.pagesizes import letter, A4, landscape, portrait`
- `from reportlab.lib.units import inch, cm, mm`
- `from reportlab.lib.colors import HexColor, black, white, grey`
- `from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle`
- `from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY`
- `from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image, KeepTogether, HRFlowable`
- `from reportlab.pdfgen import canvas`

Platypus pattern:
```
doc = SimpleDocTemplate(output_path, pagesize=letter,
                        leftMargin=inch, rightMargin=inch,
                        topMargin=inch, bottomMargin=inch)
styles = getSampleStyleSheet()
story = [Paragraph("Title", styles["Title"]), Spacer(1, 0.2*inch), ...]
doc.build(story)
```

Canvas pattern:
```
c = canvas.Canvas(output_path, pagesize=letter)
c.setFont("Helvetica-Bold", 24)
c.setFillColor(HexColor("#1F4E79"))
c.drawString(1*inch, 10*inch, "Title")
c.save()
```

## What DOESN'T exist in reportlab (common hallucinations)

- `doc.add_heading()` — that's python-docx. Use `Paragraph(text, style)` in reportlab.
- `canvas.drawTextField()` — fillable form fields need `canvas.acroForm.textfield(...)` (advanced).
- `Paragraph.set_alignment()` — alignment lives on the `ParagraphStyle`, not the Paragraph.
- `Table.set_style()` — use `Table(data, style=TableStyle([...]))` or `table.setStyle(TableStyle([...]))`.

When in doubt, prefer the documented APIs over guessing.

## Font policy — built-ins only

The sandboxed subprocess may not have access to system fonts. **Use ONLY reportlab's built-in fonts:**

- `Helvetica`, `Helvetica-Bold`, `Helvetica-Oblique`, `Helvetica-BoldOblique` (for Calibri-like sans-serif content)
- `Times-Roman`, `Times-Bold`, `Times-Italic`, `Times-BoldItalic` (for academic / formal content)
- `Courier`, `Courier-Bold`, `Courier-Oblique` (for code samples or monospace)

When the user signals an academic context (or `doc_type == "academic"`), use Times-Roman. Otherwise default to Helvetica.

## Section C — PDF type standards

Phase 4.1 ships **REPORT** only. Other types are accepted by the handler but currently fall back to REPORT defaults until their blocks land (Phase 4.2).

### REPORT (business report as PDF)

Multi-page, text-flowing document. Use **Platypus**. Cover block → executive summary → numbered sections → conclusion. Charts and tables embedded inline. Most-common PDF doc_type.

| Aspect | Standard |
|---|---|
| Page size | US Letter (`letter` from `reportlab.lib.pagesizes`) |
| Orientation | Portrait |
| Margins | 1 inch all sides (`leftMargin=inch, rightMargin=inch, topMargin=inch, bottomMargin=inch`) |
| Layout model | **Platypus** (`SimpleDocTemplate` + `story` list) |
| Body font | Helvetica 11pt |
| H1 (sections) | Helvetica-Bold 16pt, primary palette colour |
| H2 (subsections) | Helvetica-Bold 13pt, primary palette colour |
| Document title | Helvetica-Bold 22pt, primary palette colour, centred |
| Subtitle | Helvetica 13pt, italic, neutral grey, centred |
| Line spacing | `leading=14` on body ParagraphStyle (~1.27× of 11pt) |
| Alignment | Body `TA_LEFT`. Title `TA_CENTER`. Never `TA_JUSTIFY` (reportlab's justified text has the same uneven-spacing issue as docx). |
| Body colour | Pure black `#000000` |
| Accent colour | One primary from Section B. Used on title + H1 + H2 + table headers + dividers only. |
| Structure | Title block (title + subtitle + meta line "Prepared by X · Date") → divider → Executive Summary → 3–5 numbered sections → Conclusion → optional References |
| Page numbers | Footer, centre-aligned: implement via `doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)` where `footer_fn(canvas, doc)` draws `f"Page {doc.page}"`. |
| Tables | `Table(data, style=TableStyle([...]))`. Header row: filled with primary colour, white bold text. Body rows: alternate `colors.white` and `colors.HexColor("#F5F5F5")`. Use `('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CCCCCC'))` for thin borders. |
| Charts | Generate with matplotlib (300 DPI), save to temp PNG, embed via `Image(png_path, width=6*inch, height=3.5*inch)` in the story. |

**Standard REPORT structure (Platypus story):**
```
story = [
    Paragraph(title, title_style),
    Paragraph(subtitle, subtitle_style),
    Paragraph(meta_line, meta_style),
    Spacer(1, 0.3*inch),
    HRFlowable(width="100%", thickness=1, color=accent),
    Spacer(1, 0.2*inch),
    Paragraph("Executive Summary", h1_style),
    Paragraph(exec_summary_text, body_style),
    PageBreak(),
    Paragraph("1. Section Title", h1_style),
    Paragraph(section_text, body_style),
    # ... 3-5 sections
    Paragraph("Conclusion", h1_style),
    Paragraph(conclusion_text, body_style),
]
doc.build(story, onFirstPage=footer_fn, onLaterPages=footer_fn)
```

### Other doc_types (placeholder until Phase 4.2)

If the handler injects `doc_type: "academic" | "invoice" | "certificate"` and you don't see a dedicated block above, apply REPORT standards with these adjustments:
- `academic`: switch font to `Times-Roman` 12pt throughout. Line spacing `leading=24` (double-spaced). No colour at all — every accent becomes black. Hanging-indent references at end. Title page (title centred mid-page + author + institution + date), then `PageBreak()`, then Abstract, then `PageBreak()`, then body.
- `invoice`: switch from Platypus to **canvas**. Single-page fixed layout — company name top, sender/recipient blocks, line items table mid-page, totals box bottom-right. Use `canvas.drawString` for labels and `Table` flowables embedded via `Table.wrapOn(canvas, ...)` + `Table.drawOn(canvas, x, y)`.
- `certificate`: switch to canvas, **landscape** orientation (`canvas.Canvas(path, pagesize=landscape(letter))`). Decorative border via `c.rect(margin, margin, w-2*margin, h-2*margin, stroke=1, fill=0)` (or double border for elegance). Title 36pt centred top. "This is to certify that" 14pt italic. Recipient name 28pt bold centred. Achievement description 14pt. Date + signature lines at bottom corners.

## Universal PDF Rules (apply to every type)

1. **Page size: US Letter by default** (`8.5" × 11"`). Switch to A4 only when the user names a non-US locale or explicitly says "A4".
2. **One page size per document.** Never mix Letter and A4 in the same PDF.
3. **Margins ≥ 0.75 inch.** 1 inch is the safe default. Tighter than 0.75" looks cramped when printed.
4. **Built-in fonts only** — Helvetica family, Times family, Courier family. Don't reach for Calibri, Cambria, or other system fonts; the sandbox may not have them.
5. **Body text LEFT-aligned.** Never `TA_JUSTIFY`. Reportlab's justification has uneven word-spacing.
6. **Pure black body text.** Accent colour only on titles, headings, dividers, table headers.
7. **No more than two colours in a document** — the primary accent + neutral grey. Never three accent colours.
8. **Page numbers on multi-page documents.** Single-page PDFs (certificate, single-page invoice) skip them.
9. **Charts via matplotlib** — generate PNG at 300 DPI, embed via `Image(png_path, width=..., height=...)`. Same pattern as pptx — PDFs are static, matplotlib PNGs are appropriate.
10. **Don't hallucinate reportlab APIs.** See the "DOES exist" and "DOESN'T exist" lists above. When in doubt, prefer documented Platypus flowables and the simple canvas drawing methods.

<!-- ════════════════════════════════════════════════════════════════════
     End JARVIS PDF Intelligence
     ════════════════════════════════════════════════════════════════════ -->
