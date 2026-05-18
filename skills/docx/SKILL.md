---
name: docx
description: "Use this skill whenever the user wants to create, read, edit, or manipulate Word documents (.docx files). Triggers include: any mention of 'Word doc', 'word document', '.docx', or requests to produce professional documents with formatting like tables of contents, headings, page numbers, or letterheads. Also use when extracting or reorganizing content from .docx files, inserting or replacing images in documents, performing find-and-replace in Word files, working with tracked changes or comments, or converting content into a polished Word document. If the user asks for a 'report', 'memo', 'letter', 'template', or similar deliverable as a Word or .docx file, use this skill. Do NOT use for PDFs, spreadsheets, Google Docs, or general coding tasks unrelated to document generation."
license: Proprietary. LICENSE.txt has complete terms
---

# DOCX creation, editing, and analysis

## Overview

A .docx file is a ZIP archive containing XML files.

## Quick Reference

| Task | Approach |
|------|----------|
| Read/analyze content | `pandoc` or unpack for raw XML |
| Create new document | Use `docx-js` - see Creating New Documents below |
| Edit existing document | Unpack → edit XML → repack - see Editing Existing Documents below |

### Converting .doc to .docx

Legacy `.doc` files must be converted before editing:

```bash
python scripts/office/soffice.py --headless --convert-to docx document.doc
```

### Reading Content

```bash
# Text extraction with tracked changes
pandoc --track-changes=all document.docx -o output.md

# Raw XML access
python scripts/office/unpack.py document.docx unpacked/
```

### Converting to Images

```bash
python scripts/office/soffice.py --headless --convert-to pdf document.docx
pdftoppm -jpeg -r 150 document.pdf page
```

### Accepting Tracked Changes

To produce a clean document with all tracked changes accepted (requires LibreOffice):

```bash
python scripts/accept_changes.py input.docx output.docx
```

---

## Creating New Documents

Generate .docx files with JavaScript, then validate. Install: `npm install -g docx`

### Setup
```javascript
const { Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
        Header, Footer, AlignmentType, PageOrientation, LevelFormat, ExternalHyperlink,
        InternalHyperlink, Bookmark, FootnoteReferenceRun, PositionalTab,
        PositionalTabAlignment, PositionalTabRelativeTo, PositionalTabLeader,
        TabStopType, TabStopPosition, Column, SectionType,
        TableOfContents, HeadingLevel, BorderStyle, WidthType, ShadingType,
        VerticalAlign, PageNumber, PageBreak } = require('docx');

const doc = new Document({ sections: [{ children: [/* content */] }] });
Packer.toBuffer(doc).then(buffer => fs.writeFileSync("doc.docx", buffer));
```

### Validation
After creating the file, validate it. If validation fails, unpack, fix the XML, and repack.
```bash
python scripts/office/validate.py doc.docx
```

### Page Size

```javascript
// CRITICAL: docx-js defaults to A4, not US Letter
// Always set page size explicitly for consistent results
sections: [{
  properties: {
    page: {
      size: {
        width: 12240,   // 8.5 inches in DXA
        height: 15840   // 11 inches in DXA
      },
      margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } // 1 inch margins
    }
  },
  children: [/* content */]
}]
```

**Common page sizes (DXA units, 1440 DXA = 1 inch):**

| Paper | Width | Height | Content Width (1" margins) |
|-------|-------|--------|---------------------------|
| US Letter | 12,240 | 15,840 | 9,360 |
| A4 (default) | 11,906 | 16,838 | 9,026 |

**Landscape orientation:** docx-js swaps width/height internally, so pass portrait dimensions and let it handle the swap:
```javascript
size: {
  width: 12240,   // Pass SHORT edge as width
  height: 15840,  // Pass LONG edge as height
  orientation: PageOrientation.LANDSCAPE  // docx-js swaps them in the XML
},
// Content width = 15840 - left margin - right margin (uses the long edge)
```

### Styles (Override Built-in Headings)

Use Arial as the default font (universally supported). Keep titles black for readability.

```javascript
const doc = new Document({
  styles: {
    default: { document: { run: { font: "Arial", size: 24 } } }, // 12pt default
    paragraphStyles: [
      // IMPORTANT: Use exact IDs to override built-in styles
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 240, after: 240 }, outlineLevel: 0 } }, // outlineLevel required for TOC
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 28, bold: true, font: "Arial" },
        paragraph: { spacing: { before: 180, after: 180 }, outlineLevel: 1 } },
    ]
  },
  sections: [{
    children: [
      new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Title")] }),
    ]
  }]
});
```

### Lists (NEVER use unicode bullets)

```javascript
// ❌ WRONG - never manually insert bullet characters
new Paragraph({ children: [new TextRun("• Item")] })  // BAD
new Paragraph({ children: [new TextRun("\u2022 Item")] })  // BAD

// ✅ CORRECT - use numbering config with LevelFormat.BULLET
const doc = new Document({
  numbering: {
    config: [
      { reference: "bullets",
        levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
      { reference: "numbers",
        levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 720, hanging: 360 } } } }] },
    ]
  },
  sections: [{
    children: [
      new Paragraph({ numbering: { reference: "bullets", level: 0 },
        children: [new TextRun("Bullet item")] }),
      new Paragraph({ numbering: { reference: "numbers", level: 0 },
        children: [new TextRun("Numbered item")] }),
    ]
  }]
});

// ⚠️ Each reference creates INDEPENDENT numbering
// Same reference = continues (1,2,3 then 4,5,6)
// Different reference = restarts (1,2,3 then 1,2,3)
```

### Tables

**CRITICAL: Tables need dual widths** - set both `columnWidths` on the table AND `width` on each cell. Without both, tables render incorrectly on some platforms.

```javascript
// CRITICAL: Always set table width for consistent rendering
// CRITICAL: Use ShadingType.CLEAR (not SOLID) to prevent black backgrounds
const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };

new Table({
  width: { size: 9360, type: WidthType.DXA }, // Always use DXA (percentages break in Google Docs)
  columnWidths: [4680, 4680], // Must sum to table width (DXA: 1440 = 1 inch)
  rows: [
    new TableRow({
      children: [
        new TableCell({
          borders,
          width: { size: 4680, type: WidthType.DXA }, // Also set on each cell
          shading: { fill: "D5E8F0", type: ShadingType.CLEAR }, // CLEAR not SOLID
          margins: { top: 80, bottom: 80, left: 120, right: 120 }, // Cell padding (internal, not added to width)
          children: [new Paragraph({ children: [new TextRun("Cell")] })]
        })
      ]
    })
  ]
})
```

**Table width calculation:**

Always use `WidthType.DXA` — `WidthType.PERCENTAGE` breaks in Google Docs.

```javascript
// Table width = sum of columnWidths = content width
// US Letter with 1" margins: 12240 - 2880 = 9360 DXA
width: { size: 9360, type: WidthType.DXA },
columnWidths: [7000, 2360]  // Must sum to table width
```

**Width rules:**
- **Always use `WidthType.DXA`** — never `WidthType.PERCENTAGE` (incompatible with Google Docs)
- Table width must equal the sum of `columnWidths`
- Cell `width` must match corresponding `columnWidth`
- Cell `margins` are internal padding - they reduce content area, not add to cell width
- For full-width tables: use content width (page width minus left and right margins)

### Images

```javascript
// CRITICAL: type parameter is REQUIRED
new Paragraph({
  children: [new ImageRun({
    type: "png", // Required: png, jpg, jpeg, gif, bmp, svg
    data: fs.readFileSync("image.png"),
    transformation: { width: 200, height: 150 },
    altText: { title: "Title", description: "Desc", name: "Name" } // All three required
  })]
})
```

### Page Breaks

```javascript
// CRITICAL: PageBreak must be inside a Paragraph
new Paragraph({ children: [new PageBreak()] })

// Or use pageBreakBefore
new Paragraph({ pageBreakBefore: true, children: [new TextRun("New page")] })
```

### Hyperlinks

```javascript
// External link
new Paragraph({
  children: [new ExternalHyperlink({
    children: [new TextRun({ text: "Click here", style: "Hyperlink" })],
    link: "https://example.com",
  })]
})

// Internal link (bookmark + reference)
// 1. Create bookmark at destination
new Paragraph({ heading: HeadingLevel.HEADING_1, children: [
  new Bookmark({ id: "chapter1", children: [new TextRun("Chapter 1")] }),
]})
// 2. Link to it
new Paragraph({ children: [new InternalHyperlink({
  children: [new TextRun({ text: "See Chapter 1", style: "Hyperlink" })],
  anchor: "chapter1",
})]})
```

### Footnotes

```javascript
const doc = new Document({
  footnotes: {
    1: { children: [new Paragraph("Source: Annual Report 2024")] },
    2: { children: [new Paragraph("See appendix for methodology")] },
  },
  sections: [{
    children: [new Paragraph({
      children: [
        new TextRun("Revenue grew 15%"),
        new FootnoteReferenceRun(1),
        new TextRun(" using adjusted metrics"),
        new FootnoteReferenceRun(2),
      ],
    })]
  }]
});
```

### Tab Stops

```javascript
// Right-align text on same line (e.g., date opposite a title)
new Paragraph({
  children: [
    new TextRun("Company Name"),
    new TextRun("\tJanuary 2025"),
  ],
  tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
})

// Dot leader (e.g., TOC-style)
new Paragraph({
  children: [
    new TextRun("Introduction"),
    new TextRun({ children: [
      new PositionalTab({
        alignment: PositionalTabAlignment.RIGHT,
        relativeTo: PositionalTabRelativeTo.MARGIN,
        leader: PositionalTabLeader.DOT,
      }),
      "3",
    ]}),
  ],
})
```

### Multi-Column Layouts

```javascript
// Equal-width columns
sections: [{
  properties: {
    column: {
      count: 2,          // number of columns
      space: 720,        // gap between columns in DXA (720 = 0.5 inch)
      equalWidth: true,
      separate: true,    // vertical line between columns
    },
  },
  children: [/* content flows naturally across columns */]
}]

// Custom-width columns (equalWidth must be false)
sections: [{
  properties: {
    column: {
      equalWidth: false,
      children: [
        new Column({ width: 5400, space: 720 }),
        new Column({ width: 3240 }),
      ],
    },
  },
  children: [/* content */]
}]
```

Force a column break with a new section using `type: SectionType.NEXT_COLUMN`.

### Table of Contents

```javascript
// CRITICAL: Headings must use HeadingLevel ONLY - no custom styles
new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-3" })
```

### Headers/Footers

```javascript
sections: [{
  properties: {
    page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } // 1440 = 1 inch
  },
  headers: {
    default: new Header({ children: [new Paragraph({ children: [new TextRun("Header")] })] })
  },
  footers: {
    default: new Footer({ children: [new Paragraph({
      children: [new TextRun("Page "), new TextRun({ children: [PageNumber.CURRENT] })]
    })] })
  },
  children: [/* content */]
}]
```

### Critical Rules for docx-js

- **Set page size explicitly** - docx-js defaults to A4; use US Letter (12240 x 15840 DXA) for US documents
- **Landscape: pass portrait dimensions** - docx-js swaps width/height internally; pass short edge as `width`, long edge as `height`, and set `orientation: PageOrientation.LANDSCAPE`
- **Never use `\n`** - use separate Paragraph elements
- **Never use unicode bullets** - use `LevelFormat.BULLET` with numbering config
- **PageBreak must be in Paragraph** - standalone creates invalid XML
- **ImageRun requires `type`** - always specify png/jpg/etc
- **Always set table `width` with DXA** - never use `WidthType.PERCENTAGE` (breaks in Google Docs)
- **Tables need dual widths** - `columnWidths` array AND cell `width`, both must match
- **Table width = sum of columnWidths** - for DXA, ensure they add up exactly
- **Always add cell margins** - use `margins: { top: 80, bottom: 80, left: 120, right: 120 }` for readable padding
- **Use `ShadingType.CLEAR`** - never SOLID for table shading
- **Never use tables as dividers/rules** - cells have minimum height and render as empty boxes (including in headers/footers); use `border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "2E75B6", space: 1 } }` on a Paragraph instead. For two-column footers, use tab stops (see Tab Stops section), not tables
- **TOC requires HeadingLevel only** - no custom styles on heading paragraphs
- **Override built-in styles** - use exact IDs: "Heading1", "Heading2", etc.
- **Include `outlineLevel`** - required for TOC (0 for H1, 1 for H2, etc.)

---

## Editing Existing Documents

**Follow all 3 steps in order.**

### Step 1: Unpack
```bash
python scripts/office/unpack.py document.docx unpacked/
```
Extracts XML, pretty-prints, merges adjacent runs, and converts smart quotes to XML entities (`&#x201C;` etc.) so they survive editing. Use `--merge-runs false` to skip run merging.

### Step 2: Edit XML

Edit files in `unpacked/word/`. See XML Reference below for patterns.

**Use "Claude" as the author** for tracked changes and comments, unless the user explicitly requests use of a different name.

**Use the Edit tool directly for string replacement. Do not write Python scripts.** Scripts introduce unnecessary complexity. The Edit tool shows exactly what is being replaced.

**CRITICAL: Use smart quotes for new content.** When adding text with apostrophes or quotes, use XML entities to produce smart quotes:
```xml
<!-- Use these entities for professional typography -->
<w:t>Here&#x2019;s a quote: &#x201C;Hello&#x201D;</w:t>
```
| Entity | Character |
|--------|-----------|
| `&#x2018;` | ‘ (left single) |
| `&#x2019;` | ’ (right single / apostrophe) |
| `&#x201C;` | “ (left double) |
| `&#x201D;` | ” (right double) |

**Adding comments:** Use `comment.py` to handle boilerplate across multiple XML files (text must be pre-escaped XML):
```bash
python scripts/comment.py unpacked/ 0 "Comment text with &amp; and &#x2019;"
python scripts/comment.py unpacked/ 1 "Reply text" --parent 0  # reply to comment 0
python scripts/comment.py unpacked/ 0 "Text" --author "Custom Author"  # custom author name
```
Then add markers to document.xml (see Comments in XML Reference).

### Step 3: Pack
```bash
python scripts/office/pack.py unpacked/ output.docx --original document.docx
```
Validates with auto-repair, condenses XML, and creates DOCX. Use `--validate false` to skip.

**Auto-repair will fix:**
- `durableId` >= 0x7FFFFFFF (regenerates valid ID)
- Missing `xml:space="preserve"` on `<w:t>` with whitespace

**Auto-repair won't fix:**
- Malformed XML, invalid element nesting, missing relationships, schema violations

### Common Pitfalls

- **Replace entire `<w:r>` elements**: When adding tracked changes, replace the whole `<w:r>...</w:r>` block with `<w:del>...<w:ins>...` as siblings. Don't inject tracked change tags inside a run.
- **Preserve `<w:rPr>` formatting**: Copy the original run's `<w:rPr>` block into your tracked change runs to maintain bold, font size, etc.

---

## XML Reference

### Schema Compliance

- **Element order in `<w:pPr>`**: `<w:pStyle>`, `<w:numPr>`, `<w:spacing>`, `<w:ind>`, `<w:jc>`, `<w:rPr>` last
- **Whitespace**: Add `xml:space="preserve"` to `<w:t>` with leading/trailing spaces
- **RSIDs**: Must be 8-digit hex (e.g., `00AB1234`)

### Tracked Changes

**Insertion:**
```xml
<w:ins w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:t>inserted text</w:t></w:r>
</w:ins>
```

**Deletion:**
```xml
<w:del w:id="2" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:delText>deleted text</w:delText></w:r>
</w:del>
```

**Inside `<w:del>`**: Use `<w:delText>` instead of `<w:t>`, and `<w:delInstrText>` instead of `<w:instrText>`.

**Minimal edits** - only mark what changes:
```xml
<!-- Change "30 days" to "60 days" -->
<w:r><w:t>The term is </w:t></w:r>
<w:del w:id="1" w:author="Claude" w:date="...">
  <w:r><w:delText>30</w:delText></w:r>
</w:del>
<w:ins w:id="2" w:author="Claude" w:date="...">
  <w:r><w:t>60</w:t></w:r>
</w:ins>
<w:r><w:t> days.</w:t></w:r>
```

**Deleting entire paragraphs/list items** - when removing ALL content from a paragraph, also mark the paragraph mark as deleted so it merges with the next paragraph. Add `<w:del/>` inside `<w:pPr><w:rPr>`:
```xml
<w:p>
  <w:pPr>
    <w:numPr>...</w:numPr>  <!-- list numbering if present -->
    <w:rPr>
      <w:del w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z"/>
    </w:rPr>
  </w:pPr>
  <w:del w:id="2" w:author="Claude" w:date="2025-01-01T00:00:00Z">
    <w:r><w:delText>Entire paragraph content being deleted...</w:delText></w:r>
  </w:del>
</w:p>
```
Without the `<w:del/>` in `<w:pPr><w:rPr>`, accepting changes leaves an empty paragraph/list item.

**Rejecting another author's insertion** - nest deletion inside their insertion:
```xml
<w:ins w:author="Jane" w:id="5">
  <w:del w:author="Claude" w:id="10">
    <w:r><w:delText>their inserted text</w:delText></w:r>
  </w:del>
</w:ins>
```

**Restoring another author's deletion** - add insertion after (don't modify their deletion):
```xml
<w:del w:author="Jane" w:id="5">
  <w:r><w:delText>deleted text</w:delText></w:r>
</w:del>
<w:ins w:author="Claude" w:id="10">
  <w:r><w:t>deleted text</w:t></w:r>
</w:ins>
```

### Comments

After running `comment.py` (see Step 2), add markers to document.xml. For replies, use `--parent` flag and nest markers inside the parent's.

**CRITICAL: `<w:commentRangeStart>` and `<w:commentRangeEnd>` are siblings of `<w:r>`, never inside `<w:r>`.**

```xml
<!-- Comment markers are direct children of w:p, never inside w:r -->
<w:commentRangeStart w:id="0"/>
<w:del w:id="1" w:author="Claude" w:date="2025-01-01T00:00:00Z">
  <w:r><w:delText>deleted</w:delText></w:r>
</w:del>
<w:r><w:t> more text</w:t></w:r>
<w:commentRangeEnd w:id="0"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r>

<!-- Comment 0 with reply 1 nested inside -->
<w:commentRangeStart w:id="0"/>
  <w:commentRangeStart w:id="1"/>
  <w:r><w:t>text</w:t></w:r>
  <w:commentRangeEnd w:id="1"/>
<w:commentRangeEnd w:id="0"/>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="0"/></w:r>
<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="1"/></w:r>
```

### Images

1. Add image file to `word/media/`
2. Add relationship to `word/_rels/document.xml.rels`:
```xml
<Relationship Id="rId5" Type=".../image" Target="media/image1.png"/>
```
3. Add content type to `[Content_Types].xml`:
```xml
<Default Extension="png" ContentType="image/png"/>
```
4. Reference in document.xml:
```xml
<w:drawing>
  <wp:inline>
    <wp:extent cx="914400" cy="914400"/>  <!-- EMUs: 914400 = 1 inch -->
    <a:graphic>
      <a:graphicData uri=".../picture">
        <pic:pic>
          <pic:blipFill><a:blip r:embed="rId5"/></pic:blipFill>
        </pic:pic>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>
```

---

## Dependencies

- **pandoc**: Text extraction
- **docx**: `npm install -g docx` (new documents)
- **LibreOffice**: PDF conversion (auto-configured for sandboxed environments via `scripts/office/soffice.py`)
- **Poppler**: `pdftoppm` for images

---

<!-- ════════════════════════════════════════════════════════════════════
     JARVIS Document Intelligence — custom additions (Phase 2.5+)
     Owned by jarvis-project. Preserve when syncing upstream Anthropic skill.
     ════════════════════════════════════════════════════════════════════ -->

# JARVIS Document Intelligence

JARVIS sends the handler a `doc_type` parameter on every `create_docx` call (`report` | `academic` | `memo` | `letter` | `resume` | `legal`). The user message will say *"Apply the {doc_type} formatting standards from the skill guide."* — that means apply the matching block below. **`doc_type` is a hard input contract, not a hint.**

## Resolution cascade (apply in this order — higher levels override lower)

1. **STRUCTURAL RULES per doc_type** — font family, point sizes, margins, line spacing, alignment, section structure, page numbers. **Inviolable.** A user saying *"make my academic paper bold and colorful"* must still produce 12pt Times New Roman, double-spaced, 1-inch margins — *colour and tone* can vary, *structure cannot.*
2. **User-described design** — if the user's topic/style text contains explicit design language (see Section A), use it for accent colour and tone of prose. Cannot override structural rules from level 1. A doc_type that requires `no color` (`academic`, `legal`) ignores user colour requests; respect that constraint.
3. **Topic-aware palette** — when the user gave no colour direction and the doc_type permits colour, pick a palette from Section B based on the subject matter.
4. **doc_type default palette** — final fallback if Section B doesn't match the topic.

## Section A — User-described design (priority 2 above)

Parse the user's topic and style strings for design intent:

| Cue in user text | Action |
|---|---|
| Color words: *"red and black"*, *"blue theme"*, *"green and gold"* | Use those colours as primary/accent. Pick the darker shade for headings, lighter for fills. |
| Mood words: *"modern"*, *"minimal"*, *"bold"*, *"corporate"*, *"elegant"*, *"playful"* | Map to tone of prose AND choice within the doc_type's allowed palette. |
| Format words: *"magazine style"*, *"newspaper layout"*, *"datasheet"* | Match the aesthetic where it doesn't conflict with structural rules. |
| *"no colors"*, *"simple"*, *"black and white"*, *"minimalist"* | Pure black text on white. No accents. |
| Named standard: *"APA"*, *"MLA"*, *"Chicago"*, *"Harvard"* | Override doc_type → force `academic` and follow the named standard exactly. |

Style *never* overrides font/margin/spacing rules. It only controls *tone of prose* and *accent colour choices within allowed palettes*.

## Section B — Topic-aware palette (priority 3 above)

When the user gives no colour direction and the doc_type allows colour, pick a palette by subject. Choose ONE palette and apply it consistently within the document.

| Topic domain | Palette (primary / accent) | Notes |
|---|---|---|
| Technology / AI / software / data / cybersecurity | `#0D1B2A` deep navy / `#00B4D8` electric blue OR `#1B2A3B` charcoal / `#0078D4` cyan | Use Consolas 10pt for any code or technical terms inline |
| Environment / sustainability / climate | `#1B5E20` forest green / `#81C784` sage OR `#2E7D32` / `#4CAF50` | |
| Finance / business / economics | `#1F4E79` navy / `#C9A84C` gold | Data-heavy — tables prominent |
| Health / medical / pharma | `#0077B6` clinical blue / white OR `#006D77` teal / white | Heavy white space, no decorative borders |
| Education / academic-but-not-essay | `#6B2737` burgundy / `#002147` Oxford blue | Traditional serif fonts preferred |
| Creative / arts / design | One bold accent that matches the field | More visual personality permitted |
| Law / legal subjects | Black only — no exceptions | Even when doc_type is not `legal` |
| Government / policy | `#003087` navy | Formal structured layout |
| Human resources / workplace | `#0066CC` professional blue OR teal | |
| General / unknown | `#1F4E79` navy / `#5B6770` gray | Conservative default |

**Resume palette by field** (applies when `doc_type: "resume"`):
- Tech/engineering → charcoal + cyan, minimal
- Creative/design → one bold field-appropriate accent, more visual
- Business/finance → navy + gold, conservative
- Healthcare → blue/teal, clinical
- Academic/research → burgundy + serif, traditional

## Section C — Document type standards

Standards blocks below cover **REPORT**, **ACADEMIC**, **MEMO**, and **LETTER**. **RESUME** and **LEGAL** ship in Phase 2.7 — until then they fall back to REPORT for resume and to ACADEMIC's zero-colour Times-Roman block for legal (closest safe approximation).

### REPORT (workplace / business)

| Aspect | Standard |
|---|---|
| Body font | Calibri 11pt |
| Heading 1 (sections) | Calibri 16pt bold, primary palette colour |
| Heading 2 (subsections) | Calibri 13pt bold |
| Document title | Calibri 22pt bold, primary palette colour |
| Margins | 1 inch all sides |
| Line spacing | 1.15 (`WD_LINE_SPACING.MULTIPLE`, value `1.15`) |
| Alignment | LEFT for body text. Never JUSTIFY. |
| Body colour | Pure black `#000000` |
| Accent colour | One primary + one secondary from Section B palette |
| Structure | Cover block (title + subtitle + meta line) → Executive Summary → 3–5 numbered sections → Conclusion → optional References |
| Page numbers | Footer, centre-aligned, Arabic |
| Tables | `Table Grid` style. Header row filled with primary accent, white bold text 10pt. Body rows alternate white / `#F5F5F5`. Cell text 10pt, left-aligned for text / centred for short categorical data. |
| Decorative rules | Thin (0.5–1pt) horizontal rule in accent colour below H1 headings is acceptable |

Universal rules also apply (font hierarchy, contrast, white space — see Phase 2.7 when it ships).

### ACADEMIC (school paper / essay / thesis chapter)

Default to APA-style unless the user names MLA, Chicago, or Harvard (Section A handles that override). Academic is **zero-colour** — every `run.font.color.rgb` is `RGBColor(0, 0, 0)`. No accent palette, no decorative rules, no shaded table headers.

| Aspect | Standard |
|---|---|
| Body font | Times New Roman 12pt, every run, no exceptions |
| Heading 1 (sections like "Introduction", "Methods", "References") | Times New Roman 13pt bold, black, left-aligned. Section numbering is acceptable (`1. Introduction`) but not required for APA. |
| Heading 2 (subsections) | Times New Roman 12pt bold italic, black, left-aligned |
| Document title | Times New Roman 16pt bold, black, centred. On its own page (or top of page 1 for short papers). |
| Margins | 1 inch all sides |
| Line spacing | Double (`WD_LINE_SPACING.DOUBLE`, or `MULTIPLE` with `2.0`) for body AND references |
| Alignment | LEFT (never JUSTIFY). Title is CENTER. |
| Body colour | Pure black `#000000` everywhere |
| Paragraph indent | First-line indent of 0.5 inch (`first_line_indent = Inches(0.5)`) on body paragraphs. No indent on the first paragraph after a heading. |
| Structure | Title page (title + author + institution + date, all centred) → page break → Abstract (single paragraph, no indent) → page break → Introduction → Body sections → Conclusion → page break → References |
| Page numbers | Header, right-aligned, Arabic. Footer page numbers are also acceptable. |
| References | Hanging indent: `left_indent = Inches(0.5)`, `first_line_indent = Inches(-0.5)`. Double-spaced. Alphabetical by first author surname. |
| In-text citations | `(Author, Year)` for APA; `(Author Page)` for MLA. Reference list format matches the chosen style. |
| Tables | Simple black borders, white fill only. Header row bold black on white — never coloured fill. |

Forbidden in academic: any colour beyond black; bullet-point lists for body content (use full prose paragraphs); decorative rules; coloured table headers; sans-serif fonts.

### MEMO (internal business communication)

Short, dense, action-oriented. Max 2 pages. No cover page, no table of contents, no abstract.

| Aspect | Standard |
|---|---|
| Body font | Calibri 11pt |
| Heading | Calibri 12pt bold, primary palette colour. Use sparingly — memos rarely need more than 1-2 section headings. |
| Document title | Calibri 18pt bold, primary palette colour, top of page 1. Text: `MEMORANDUM` (all caps). |
| Header block | Four-row mini-table (or aligned paragraphs) at the top: `TO:` / `FROM:` / `DATE:` / `RE:` (or `SUBJECT:`). Label column bold Calibri 11pt, value column Calibri 11pt normal. A thin horizontal rule (0.75pt, primary accent) separates the header block from the body. |
| Margins | 1 inch all sides |
| Line spacing | Single (`WD_LINE_SPACING.SINGLE`) |
| Alignment | LEFT body. Header block label column left, value column left. |
| Body colour | Pure black `#000000` |
| Accent colour | One colour from Section B palette (or HR blue `#0066CC` as default). Used only for the title, header rule, and any subheading. Body text stays black. |
| Structure | Header block (TO/FROM/DATE/RE) → optional one-line context paragraph → 2-5 short body paragraphs → "Action items" or "Next steps" closing section (often a short bulleted list) |
| Page numbers | None for ≤2-page memos. Add footer centre page numbers only if longer. |
| Tables | Use only when comparing options or summarising data. Same REPORT styling but smaller — 10pt content. |

Memos prize brevity. Sonnet should target 1 page of content unless the topic genuinely requires more.

### LETTER (formal business correspondence)

Full block format — everything left-aligned. No indents on paragraphs. Single line within paragraphs, blank line between.

| Aspect | Standard |
|---|---|
| Body font | Calibri 12pt OR Times New Roman 12pt (use Calibri unless the user signals a traditional tone) |
| Document title | None. Letters have no title. |
| Margins | 1 inch all sides |
| Line spacing | Single within paragraphs. `space_after = Pt(12)` between paragraphs (creates the blank-line effect). |
| Alignment | LEFT throughout (block format) |
| Body colour | Pure black `#000000` |
| Accent colour | None. Letters are black on white. |
| Structure (top to bottom, each block separated by a blank line) | 1. Sender's address block (3-4 lines: name, street, city/state/zip) — OR letterhead<br/>2. Date (e.g., `19 May 2026`)<br/>3. Recipient's address block (name, title, organisation, address — 3-5 lines)<br/>4. Salutation: `Dear [Name],` (formal: `Dear Mr./Ms. [Surname],`)<br/>5. Body paragraphs (2-5, each 2-4 sentences)<br/>6. Closing: `Sincerely,` / `Best regards,` / `Respectfully,`<br/>7. Three blank lines for signature<br/>8. Typed name<br/>9. Title (if applicable)<br/>10. Optional `Enclosures:` line if attachments are mentioned |
| Page numbers | None for single-page. If >1 page, add `[Recipient Name] — Page X of Y` to top-right of pages 2+. |
| Tables | Rare. If used, embed without coloured headers. |

For **cover letters specifically** (`topic` mentions "cover letter" or "job application"): keep to one page, three body paragraphs (opening hook → relevant qualifications → call to action + close), match the formality the role demands.

### Interim fallbacks (Phase 2.7 will land full blocks)

- `doc_type: "resume"` → apply REPORT standards with these overrides: single line spacing throughout, 0.75-inch margins, no Executive Summary section, content is dense bullet points (no full-prose paragraphs), one accent colour for the name header and section dividers only.
- `doc_type: "legal"` → apply ACADEMIC standards with these overrides: title block at top (parties, subject, date), no abstract, numbered clauses (`1.`, `1.1`, `1.2`, etc.) instead of named sections, signature block at the end with lines for parties' signatures.

<!-- ════════════════════════════════════════════════════════════════════
     End JARVIS Document Intelligence
     ════════════════════════════════════════════════════════════════════ -->
