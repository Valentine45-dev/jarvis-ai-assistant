---
name: xlsx
description: "Use this skill any time a spreadsheet file is the primary input or output. This means any task where the user wants to: open, read, edit, or fix an existing .xlsx, .xlsm, .csv, or .tsv file (e.g., adding columns, computing formulas, formatting, charting, cleaning messy data); create a new spreadsheet from scratch or from other data sources; or convert between tabular file formats. Trigger especially when the user references a spreadsheet file by name or path — even casually (like \"the xlsx in my downloads\") — and wants something done to it or produced from it. Also trigger for cleaning or restructuring messy tabular data files (malformed rows, misplaced headers, junk data) into proper spreadsheets. The deliverable must be a spreadsheet file. Do NOT trigger when the primary deliverable is a Word document, HTML report, standalone Python script, database pipeline, or Google Sheets API integration, even if tabular data is involved."
license: Proprietary. LICENSE.txt has complete terms
---

> ### JARVIS Python sandbox rule — applies to every generator
>
> **NEVER call `__import__()` for any reason.** The AST validator blocks
> dynamic imports outright and rejects the entire script — no document is
> produced.
>
> Wrong (this is what most often trips the sandbox):
>
> ```python
> run.add_break(__import__('docx.enum.text', fromlist=['WD_BREAK']).WD_BREAK.PAGE)
> ```
>
> Correct — all imports go at the top of the file with standard syntax:
>
> ```python
> from docx.enum.text import WD_BREAK
> # ... later, in the function:
> run.add_break(WD_BREAK.PAGE)
> ```
>
> Same rule for `importlib`, `getattr(module, 'name')`, and any other
> dynamic-import trick. If you need a symbol, import it at the top.

# Requirements for Outputs

## All Excel files

### Professional Font
- Use a consistent, professional font (e.g., Arial, Times New Roman) for all deliverables unless otherwise instructed by the user

### Zero Formula Errors
- Every Excel model MUST be delivered with ZERO formula errors (#REF!, #DIV/0!, #VALUE!, #N/A, #NAME?)

### Preserve Existing Templates (when updating templates)
- Study and EXACTLY match existing format, style, and conventions when modifying files
- Never impose standardized formatting on files with established patterns
- Existing template conventions ALWAYS override these guidelines

## Financial models

### Color Coding Standards
Unless otherwise stated by the user or existing template

#### Industry-Standard Color Conventions
- **Blue text (RGB: 0,0,255)**: Hardcoded inputs, and numbers users will change for scenarios
- **Black text (RGB: 0,0,0)**: ALL formulas and calculations
- **Green text (RGB: 0,128,0)**: Links pulling from other worksheets within same workbook
- **Red text (RGB: 255,0,0)**: External links to other files
- **Yellow background (RGB: 255,255,0)**: Key assumptions needing attention or cells that need to be updated

### Number Formatting Standards

#### Required Format Rules
- **Years**: Format as text strings (e.g., "2024" not "2,024")
- **Currency**: Use $#,##0 format; ALWAYS specify units in headers ("Revenue ($mm)")
- **Zeros**: Use number formatting to make all zeros "-", including percentages (e.g., "$#,##0;($#,##0);-")
- **Percentages**: Default to 0.0% format (one decimal)
- **Multiples**: Format as 0.0x for valuation multiples (EV/EBITDA, P/E)
- **Negative numbers**: Use parentheses (123) not minus -123

### Formula Construction Rules

#### Assumptions Placement
- Place ALL assumptions (growth rates, margins, multiples, etc.) in separate assumption cells
- Use cell references instead of hardcoded values in formulas
- Example: Use =B5*(1+$B$6) instead of =B5*1.05

#### Formula Error Prevention
- Verify all cell references are correct
- Check for off-by-one errors in ranges
- Ensure consistent formulas across all projection periods
- Test with edge cases (zero values, negative numbers)
- Verify no unintended circular references

#### Documentation Requirements for Hardcodes
- Comment or in cells beside (if end of table). Format: "Source: [System/Document], [Date], [Specific Reference], [URL if applicable]"
- Examples:
  - "Source: Company 10-K, FY2024, Page 45, Revenue Note, [SEC EDGAR URL]"
  - "Source: Company 10-Q, Q2 2025, Exhibit 99.1, [SEC EDGAR URL]"
  - "Source: Bloomberg Terminal, 8/15/2025, AAPL US Equity"
  - "Source: FactSet, 8/20/2025, Consensus Estimates Screen"

# XLSX creation, editing, and analysis

## Overview

A user may ask you to create, edit, or analyze the contents of an .xlsx file. You have different tools and workflows available for different tasks.

## Important Requirements

**LibreOffice Required for Formula Recalculation**: You can assume LibreOffice is installed for recalculating formula values using the `scripts/recalc.py` script. The script automatically configures LibreOffice on first run, including in sandboxed environments where Unix sockets are restricted (handled by `scripts/office/soffice.py`)

## Reading and analyzing data

### Data analysis with pandas
For data analysis, visualization, and basic operations, use **pandas** which provides powerful data manipulation capabilities:

```python
import pandas as pd

# Read Excel
df = pd.read_excel('file.xlsx')  # Default: first sheet
all_sheets = pd.read_excel('file.xlsx', sheet_name=None)  # All sheets as dict

# Analyze
df.head()      # Preview data
df.info()      # Column info
df.describe()  # Statistics

# Write Excel
df.to_excel('output.xlsx', index=False)
```

## Excel File Workflows

## CRITICAL: Use Formulas, Not Hardcoded Values

**Always use Excel formulas instead of calculating values in Python and hardcoding them.** This ensures the spreadsheet remains dynamic and updateable.

### ❌ WRONG - Hardcoding Calculated Values
```python
# Bad: Calculating in Python and hardcoding result
total = df['Sales'].sum()
sheet['B10'] = total  # Hardcodes 5000

# Bad: Computing growth rate in Python
growth = (df.iloc[-1]['Revenue'] - df.iloc[0]['Revenue']) / df.iloc[0]['Revenue']
sheet['C5'] = growth  # Hardcodes 0.15

# Bad: Python calculation for average
avg = sum(values) / len(values)
sheet['D20'] = avg  # Hardcodes 42.5
```

### ✅ CORRECT - Using Excel Formulas
```python
# Good: Let Excel calculate the sum
sheet['B10'] = '=SUM(B2:B9)'

# Good: Growth rate as Excel formula
sheet['C5'] = '=(C4-C2)/C2'

# Good: Average using Excel function
sheet['D20'] = '=AVERAGE(D2:D19)'
```

This applies to ALL calculations - totals, percentages, ratios, differences, etc. The spreadsheet should be able to recalculate when source data changes.

## Common Workflow
1. **Choose tool**: pandas for data, openpyxl for formulas/formatting
2. **Create/Load**: Create new workbook or load existing file
3. **Modify**: Add/edit data, formulas, and formatting
4. **Save**: Write to file
5. **Recalculate formulas (MANDATORY IF USING FORMULAS)**: Use the scripts/recalc.py script
   ```bash
   python scripts/recalc.py output.xlsx
   ```
6. **Verify and fix any errors**: 
   - The script returns JSON with error details
   - If `status` is `errors_found`, check `error_summary` for specific error types and locations
   - Fix the identified errors and recalculate again
   - Common errors to fix:
     - `#REF!`: Invalid cell references
     - `#DIV/0!`: Division by zero
     - `#VALUE!`: Wrong data type in formula
     - `#NAME?`: Unrecognized formula name

### Creating new Excel files

```python
# Using openpyxl for formulas and formatting
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

wb = Workbook()
sheet = wb.active

# Add data
sheet['A1'] = 'Hello'
sheet['B1'] = 'World'
sheet.append(['Row', 'of', 'data'])

# Add formula
sheet['B2'] = '=SUM(A1:A10)'

# Formatting
sheet['A1'].font = Font(bold=True, color='FF0000')
sheet['A1'].fill = PatternFill('solid', start_color='FFFF00')
sheet['A1'].alignment = Alignment(horizontal='center')

# Column width
sheet.column_dimensions['A'].width = 20

wb.save('output.xlsx')
```

### Editing existing Excel files

```python
# Using openpyxl to preserve formulas and formatting
from openpyxl import load_workbook

# Load existing file
wb = load_workbook('existing.xlsx')
sheet = wb.active  # or wb['SheetName'] for specific sheet

# Working with multiple sheets
for sheet_name in wb.sheetnames:
    sheet = wb[sheet_name]
    print(f"Sheet: {sheet_name}")

# Modify cells
sheet['A1'] = 'New Value'
sheet.insert_rows(2)  # Insert row at position 2
sheet.delete_cols(3)  # Delete column 3

# Add new sheet
new_sheet = wb.create_sheet('NewSheet')
new_sheet['A1'] = 'Data'

wb.save('modified.xlsx')
```

## Recalculating formulas

Excel files created or modified by openpyxl contain formulas as strings but not calculated values. Use the provided `scripts/recalc.py` script to recalculate formulas:

```bash
python scripts/recalc.py <excel_file> [timeout_seconds]
```

Example:
```bash
python scripts/recalc.py output.xlsx 30
```

The script:
- Automatically sets up LibreOffice macro on first run
- Recalculates all formulas in all sheets
- Scans ALL cells for Excel errors (#REF!, #DIV/0!, etc.)
- Returns JSON with detailed error locations and counts
- Works on both Linux and macOS

## Formula Verification Checklist

Quick checks to ensure formulas work correctly:

### Essential Verification
- [ ] **Test 2-3 sample references**: Verify they pull correct values before building full model
- [ ] **Column mapping**: Confirm Excel columns match (e.g., column 64 = BL, not BK)
- [ ] **Row offset**: Remember Excel rows are 1-indexed (DataFrame row 5 = Excel row 6)

### Common Pitfalls
- [ ] **NaN handling**: Check for null values with `pd.notna()`
- [ ] **Far-right columns**: FY data often in columns 50+ 
- [ ] **Multiple matches**: Search all occurrences, not just first
- [ ] **Division by zero**: Check denominators before using `/` in formulas (#DIV/0!)
- [ ] **Wrong references**: Verify all cell references point to intended cells (#REF!)
- [ ] **Cross-sheet references**: Use correct format (Sheet1!A1) for linking sheets

### Formula Testing Strategy
- [ ] **Start small**: Test formulas on 2-3 cells before applying broadly
- [ ] **Verify dependencies**: Check all cells referenced in formulas exist
- [ ] **Test edge cases**: Include zero, negative, and very large values

### Interpreting scripts/recalc.py Output
The script returns JSON with error details:
```json
{
  "status": "success",           // or "errors_found"
  "total_errors": 0,              // Total error count
  "total_formulas": 42,           // Number of formulas in file
  "error_summary": {              // Only present if errors found
    "#REF!": {
      "count": 2,
      "locations": ["Sheet1!B5", "Sheet1!C10"]
    }
  }
}
```

## Best Practices

### Library Selection
- **pandas**: Best for data analysis, bulk operations, and simple data export
- **openpyxl**: Best for complex formatting, formulas, and Excel-specific features

### Working with openpyxl
- Cell indices are 1-based (row=1, column=1 refers to cell A1)
- Use `data_only=True` to read calculated values: `load_workbook('file.xlsx', data_only=True)`
- **Warning**: If opened with `data_only=True` and saved, formulas are replaced with values and permanently lost
- For large files: Use `read_only=True` for reading or `write_only=True` for writing
- Formulas are preserved but not evaluated - use scripts/recalc.py to update values

### Working with pandas
- Specify data types to avoid inference issues: `pd.read_excel('file.xlsx', dtype={'id': str})`
- For large files, read specific columns: `pd.read_excel('file.xlsx', usecols=['A', 'C', 'E'])`
- Handle dates properly: `pd.read_excel('file.xlsx', parse_dates=['date_column'])`

## Code Style Guidelines
**IMPORTANT**: When generating Python code for Excel operations:
- Write minimal, concise Python code without unnecessary comments
- Avoid verbose variable names and redundant operations
- Avoid unnecessary print statements

**For Excel files themselves**:
- Add comments to cells with complex formulas or important assumptions
- Document data sources for hardcoded values
- Include notes for key calculations and model sections

---

<!-- ════════════════════════════════════════════════════════════════════
     JARVIS Spreadsheet Intelligence — custom additions (Phase 3.3+)
     Owned by jarvis-project. Preserve when syncing upstream Anthropic skill.
     ════════════════════════════════════════════════════════════════════ -->

# JARVIS Spreadsheet Intelligence

JARVIS sends the handler a `doc_type` parameter on every `create_xlsx` call (`dataset` | `dashboard` | `tracker` | `invoice`). The user message will say *"Apply the {doc_type} formatting standards from the skill guide."* — apply the matching block below. **`doc_type` is a hard input contract, not a hint.**

Spreadsheets differ from documents and decks in one important way: **they are functional first, visual second.** Numbers, formulas, structure, and data integrity matter more than typography. Colour is used purposefully (status pills, conditional formatting, chart series) — not decoratively.

## Resolution cascade (same shape as docx / pptx)

1. **STRUCTURAL RULES per doc_type** — sheet structure, column layout, number formats, freeze panes, formula conventions. **Inviolable.**
2. **User-described design** — explicit colour or formatting cues in the user's topic/style.
3. **Topic-aware palette** — restrained colour choices for headers, status pills, and chart series.
4. **doc_type default palette** — final fallback.

## Section A — User-described design

Same rules as docx/pptx Section A but adapted for spreadsheets:
- *"red and black"* / *"blue theme"* → use as header fill colour and accent for chart series.
- *"minimal"* / *"no colors"* → plain bold headers on white. Status columns use text only (no fills).
- *"corporate"* / *"professional"* → conservative palette (navy/gray), no bright colours.
- Named conventions: *"financial model style"* → calculations on one sheet, inputs blue-fill, outputs grey-fill, formula links between sheets.

## Section B — Topic-aware palette (data-aware)

Spreadsheet palettes follow three concerns:
- **Header fill** — solid colour behind the header row (white text 11pt bold)
- **Status colours** — semantic palette for tracker columns (green=OK, amber=at-risk, red=blocked, grey=done)
- **Chart series** — accessible categorical scale (works for colour-blind viewers); use the same palette across all charts in one workbook

| Topic domain | Header fill / Chart series |
|---|---|
| Finance / sales / revenue | `#1F4E79` navy / sequential blue scale `#DBE7F5`→`#1F4E79` for heatmaps |
| Operations / project / engineering | `#0D1B2A` deep navy / categorical: `#0D1B2A`, `#00B4D8`, `#5B6770`, `#E0A458` |
| Marketing / customer / growth | `#6B2737` burgundy / `#E94560`, `#F4A261`, `#2A9D8F`, `#264653` |
| Logistics / inventory | `#1B5E20` forest green / sequential green scale |
| Generic / unknown | `#1F4E79` navy / Excel default categorical (`#4472C4`, `#ED7D31`, `#A5A5A5`, `#FFC000`) |

Status pill palette (used in TRACKER and DASHBOARD):
- `OK` / `Done` / `Active` → fill `#C6EFCE`, font `#006100` (Excel's built-in "Good")
- `At Risk` / `In Progress` → fill `#FFEB9C`, font `#9C5700` (Excel's "Neutral")
- `Blocked` / `Overdue` → fill `#FFC7CE`, font `#9C0006` (Excel's "Bad")
- `Cancelled` / `N/A` → fill `#E7E6E6`, font `#595959` (grey)

## Section C — Spreadsheet type standards

All four spreadsheet types have dedicated standards blocks: **DATASET**, **DASHBOARD**, **TRACKER**, **INVOICE**. The Universal Spreadsheet Rules at the end apply to every type.

### DATASET (structured data table)

A clean, queryable data table — the most common spreadsheet shape. Single sheet, frozen header row, autofilter on, sortable, no charts (unless the user asks). Sample data should be realistic for the topic.

| Aspect | Standard |
|---|---|
| Sheet name | Descriptive snake_case or Title Case — e.g. `sales_q3` or `Sales Q3 2025`. **Never** leave it as `Sheet1`. |
| Header row | Row 1. Bold white text 11pt on header-fill colour from Section B. Row height ~22. |
| Body rows | Calibri 11pt black. Alternating row fills (`#FFFFFF` and `#F5F5F5`) when there are ≥6 rows. |
| Column widths | Auto-fit to content (~12-25 width). Date columns ~12, currency ~14, text/name ~22, description/notes ~30+. |
| Number formats | Numbers: `#,##0.00` or `#,##0`. Currency: `$#,##0.00` (or appropriate locale). Percent: `0.0%`. Dates: `yyyy-mm-dd` (ISO) unless user signals otherwise. |
| Freeze panes | `worksheet.freeze_panes = "A2"` (freeze header row). If first column is an identifier (ID/name), use `"B2"` instead. |
| Autofilter | `worksheet.auto_filter.ref = worksheet.dimensions` — turn it on for any table with ≥5 rows. |
| Data validation | Use dropdown validations for columns with bounded enums (status, region, category). |
| Borders | None on the body — header row gets a bottom border only. Heavy borders look amateurish. |
| Row count | **Generate realistic sample data** — 15–40 rows is plenty. Use Python loops with `random.choice` or `datetime` arithmetic to synthesize variety, don't hand-write 40 row literals. |

**Standard DATASET workbook structure:**
1. Single data sheet, named appropriately
2. Frozen header row + autofilter on
3. Realistic 15–40 row sample, generated programmatically when possible
4. Number formats applied per column type
5. Status/category columns may use the status pill palette via conditional formatting
6. No summary row, no totals, no charts — that's DASHBOARD territory

### DASHBOARD (KPI summary with charts)

A two-sheet workbook: **`Summary`** (KPI cards + charts) and **`Data`** (the raw data). The Summary sheet is what the audience sees first — clean, scannable, chart-driven. The Data sheet follows DATASET conventions and feeds the charts.

| Aspect | Standard |
|---|---|
| Workbook structure | **Two sheets**: `Summary` (active sheet at position 0) and `Data`. Use `wb.create_sheet("Data", 1)` after creating the Summary sheet. |
| Summary sheet name | `Summary` or `Dashboard` |
| Summary sheet layout | Top band (rows 1–3): merged title cell, bold 18pt, header-fill colour. KPI cards from row 5. Charts below the cards. |
| KPI cards | 4–6 cards arranged in a 2×3 or 3×2 grid. Each card: a 3×2 merged block (e.g. `B5:D7`) with the metric number (28pt bold, header-fill colour) on the top row and a 9pt label below. Light fill (`#F5F5F5`) on the card background. |
| Charts | 1–2 charts below the KPI cards. Use **openpyxl native** (`BarChart`, `LineChart`, `PieChart`) — never matplotlib. Chart anchor: `ws.add_chart(chart, "B14")`. Chart size: `chart.width = 15`, `chart.height = 8`. |
| Chart series colours | From Section B chart-series palette. Apply via `series.graphicalProperties.solidFill = "1F4E79"`. |
| Data sheet | Full DATASET treatment — frozen header, autofilter, alternating rows, number formats per column. **The KPI formulas on Summary must reference this sheet** (`=SUM(Data!H:H)`, `=AVERAGE(Data!E2:E40)`, etc.) so the dashboard updates when data changes. |
| Print area | `ws.print_options.horizontalCentered = True`. Page orientation landscape: `ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE`. |
| Autofilter on Summary | **Off.** Summary is read-only. Autofilter only on the Data sheet. |
| Freeze panes on Summary | Optional — freeze the title band (`ws.freeze_panes = "A4"`). |

**Standard DASHBOARD structure:**
1. Summary sheet — title band → KPI card grid (4-6 cards) → 1-2 charts
2. Data sheet — full DATASET layout, drives the Summary via cell references
3. All KPI numbers are **formulas**, never hardcoded (`=COUNTA(Data!B:B)-1`, `=SUMIF(Data!F:F, "Closed Won", Data!K:K)`)

### TRACKER (task / project / budget / habit)

Single sheet, scannable, action-oriented. Each row is one item to track. Status is the most important visual signal — coloured pills via conditional formatting. Dropdown validation on bounded enum columns. Realistic sample tasks for the topic.

| Aspect | Standard |
|---|---|
| Sheet name | Descriptive — `Tasks`, `Project Tracker`, `Q3 Budget`, etc. |
| Columns (default tracker shape) | `ID`, `Title` (or `Task` / `Item`), `Status`, `Priority`, `Owner`, `Due Date`, `Created`, `Notes`. Drop or add columns as the topic demands. |
| Header row | Same as DATASET — bold white text on header-fill colour, row 1, height 22. |
| Status column | **Dropdown validation** via `DataValidation(type="list", formula1='"Backlog,In Progress,Blocked,Done,Cancelled"')`. Conditional formatting applies the status pill palette (Section B). |
| Priority column | Dropdown validation: `"Low,Medium,High,Critical"`. Optional conditional formatting (Critical → red bg, High → amber bg). |
| Due Date column | Conditional formatting: if `<TODAY()` and Status not Done → red fill; if `<TODAY()+7` and Status not Done → amber fill. Use `FormulaRule` for these. |
| Owner column | Plain text. If the user provides a team list, add a dropdown. |
| Freeze panes | `ws.freeze_panes = "B2"` (freeze header row + ID column for horizontal scrolling). |
| Autofilter | On (`ws.auto_filter.ref = ws.dimensions`) — users sort by status or owner constantly. |
| Default sort | By Status (Active items first), then Priority (Critical first), then Due Date (soonest first) — apply via the data generation, not via XML sort definitions. |
| Row count | 15–25 realistic rows. Names from a real list, dates spanning ~3 months around today. |

**Standard TRACKER structure:**
1. Single sheet
2. Default columns: `ID | Title | Status | Priority | Owner | Due Date | Created | Notes`
3. Dropdowns on Status + Priority; conditional formatting on Status + Due Date
4. Frozen header + ID column; autofilter on
5. 15–25 realistic sample rows

### INVOICE (printable single-sheet template)

A printable document, not a queryable table. Single sheet, portrait orientation, fits one page. Header blocks at top (sender + recipient), line items table in the middle, totals box bottom-right. Merged cells are allowed here — **this is the one xlsx doc_type where merged cells are permitted** (header blocks, totals box).

| Aspect | Standard |
|---|---|
| Sheet name | `Invoice` |
| Page setup | Portrait orientation (`ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT`), paper US Letter or A4, margins ~0.5". Print area set with `ws.print_area = "A1:F40"` (or appropriate). |
| Top band | Merged `A1:F2` — company name (24pt bold, header-fill colour) or logo placeholder text. |
| Invoice metadata block | Right-aligned merged block (e.g. `D4:F8`): `Invoice #` / `Date` / `Due Date` / `Payment Terms`. Label column bold, value column right-aligned. |
| Sender ("From:") block | Top-left, rows 4–8, columns A–C. `From:` label bold, address lines plain Calibri 10pt. |
| Recipient ("Bill To:") block | Mid-left, rows 10–14, columns A–C. `Bill To:` label bold, address lines plain. |
| Line items table | Starts row 17. Headers: `Item` / `Description` / `Quantity` / `Unit Price` / `Tax` / `Total`. Bold white on header-fill. Body rows: 10–15 line items max. |
| Totals box | Bottom-right merged block. `Subtotal`, `Tax`, `Total` labels. **Total uses a formula** (`=SUM(F18:F32)` or similar). Bold Total row, larger font (14pt). |
| Number formats | Currency cells: `$#,##0.00`. Quantity: `#,##0`. Tax: `0.0%`. Dates: `yyyy-mm-dd`. |
| Footer | Below the totals box: payment instructions (bank/wire info, payment-link URL), thank-you note. Italic 9pt grey. |
| Autofilter | **Off.** Invoices are documents. |
| Freeze panes | **Off.** Single-page document. |
| Merged cells | **Allowed** — header blocks (sender/recipient/metadata), top band, totals box. This is the one xlsx doc_type where merged cells don't break expected behaviour. |
| Borders | Light borders around the line items table only (`Side(style="thin", color="CCCCCC")`). The rest of the sheet is borderless. |

**Standard INVOICE structure:**
1. Single sheet, portrait, printable
2. Top band (company name/logo) → sender block (left) + invoice metadata (right) → recipient block → line items table → totals box (right-aligned) → footer
3. Total is a formula referencing the line items column
4. Print area set so it lands cleanly on one page
5. Realistic placeholder sender/recipient/items — the user will customise but should see a credible template

## Universal Spreadsheet Rules (apply to every type)

1. **Sheet naming** — Always rename `Sheet1`. Use descriptive snake_case or Title Case. Multiple sheets get parallel names (`Data`, `Summary`, `Charts`).
2. **Header row formatting** — Bold, white text on coloured fill, frozen below. Non-negotiable for any data table.
3. **Number formats are not optional** — Raw `1234.5` in a currency column is broken. Always apply `cell.number_format = "$#,##0.00"` (or appropriate).
4. **Use formulas, not hardcoded values** for any computed cell. `=SUM(B2:B40)` not `=1234.50`. The user expects the spreadsheet to recalculate when they edit it.
5. **Charts via openpyxl native classes** (`openpyxl.chart.BarChart`, `LineChart`, `PieChart`) — NOT matplotlib. Excel charts must be live objects that update when data changes. This is the opposite of the pptx rule.
6. **Conditional formatting** for status / threshold colouring — use `openpyxl.formatting.rule.CellIsRule` or `FormulaRule`. Apply with the status pill palette.
7. **Realistic sample data** — names from a real list (`["Alex Chen", "Priya Sharma", ...]`), dates within a sensible range, numbers that make sense for the domain. Don't use `Lorem ipsum` or `Person 1, Person 2`.
8. **Programmatic data generation** — when generating >20 rows, use Python loops + `random.choice` / `random.randint` / `datetime` arithmetic. Hand-writing 50 row literals burns output tokens.
9. **No merged cells in data tables** — they break sorting, filtering, and formula references. Merged cells are only acceptable in INVOICE templates (header blocks) and DASHBOARD KPI cards.
10. **Don't hallucinate openpyxl methods.** Methods that exist: `worksheet.cell(row, col, value)`, `worksheet[A1] = value`, `worksheet.column_dimensions["A"].width = 15`, `worksheet.freeze_panes = "A2"`, `worksheet.auto_filter.ref = worksheet.dimensions`, `cell.number_format = "..."`, `cell.fill = PatternFill(...)`, `cell.font = Font(...)`, `cell.alignment = Alignment(...)`. When in doubt, prefer plain assignment over XML traversal.

<!-- ════════════════════════════════════════════════════════════════════
     End JARVIS Spreadsheet Intelligence
     ════════════════════════════════════════════════════════════════════ -->