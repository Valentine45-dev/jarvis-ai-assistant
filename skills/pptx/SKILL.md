---
name: pptx
description: "Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions \"deck,\" \"slides,\" \"presentation,\" or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill."
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

# PPTX Skill

## Quick Reference

| Task | Guide |
|------|-------|
| Read/analyze content | `python -m markitdown presentation.pptx` |
| Edit or create from template | Read [editing.md](editing.md) |
| Create from scratch | Read [pptxgenjs.md](pptxgenjs.md) |

---

## Reading Content

```bash
# Text extraction
python -m markitdown presentation.pptx

# Visual overview
python scripts/thumbnail.py presentation.pptx

# Raw XML
python scripts/office/unpack.py presentation.pptx unpacked/
```

---

## Editing Workflow

**Read [editing.md](editing.md) for full details.**

1. Analyze template with `thumbnail.py`
2. Unpack → manipulate slides → edit content → clean → pack

---

## Creating from Scratch

**Read [pptxgenjs.md](pptxgenjs.md) for full details.**

Use when no template or reference presentation is available.

---

## Design Ideas

**Don't create boring slides.** Plain bullets on a white background won't impress anyone. Consider ideas from this list for each slide.

### Before Starting

- **Pick a bold, content-informed color palette**: The palette should feel designed for THIS topic. If swapping your colors into a completely different presentation would still "work," you haven't made specific enough choices.
- **Dominance over equality**: One color should dominate (60-70% visual weight), with 1-2 supporting tones and one sharp accent. Never give all colors equal weight.
- **Dark/light contrast**: Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure). Or commit to dark throughout for a premium feel.
- **Commit to a visual motif**: Pick ONE distinctive element and repeat it — rounded image frames, icons in colored circles, thick single-side borders. Carry it across every slide.

### Color Palettes

Choose colors that match your topic — don't default to generic blue. Use these palettes as inspiration:

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| **Forest & Moss** | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| **Coral Energy** | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| **Warm Terracotta** | `B85042` (terracotta) | `E7E8D1` (sand) | `A7BEAE` (sage) |
| **Ocean Gradient** | `065A82` (deep blue) | `1C7293` (teal) | `21295C` (midnight) |
| **Charcoal Minimal** | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| **Teal Trust** | `028090` (teal) | `00A896` (seafoam) | `02C39A` (mint) |
| **Berry & Cream** | `6D2E46` (berry) | `A26769` (dusty rose) | `ECE2D0` (cream) |
| **Sage Calm** | `84B59F` (sage) | `69A297` (eucalyptus) | `50808E` (slate) |
| **Cherry Bold** | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### For Each Slide

**Every slide needs a visual element** — image, chart, icon, or shape. Text-only slides are forgettable.

**Layout options:**
- Two-column (text left, illustration on right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2x2 or 2x3 grid (image on one side, grid of content blocks on other)
- Half-bleed image (full left or right side) with content overlay

**Data display:**
- Large stat callouts (big numbers 60-72pt with small labels below)
- Comparison columns (before/after, pros/cons, side-by-side options)
- Timeline or process flow (numbered steps, arrows)

**Visual polish:**
- Icons in small colored circles next to section headers
- Italic accent text for key stats or taglines

### Typography

**Choose an interesting font pairing** — don't default to Arial. Pick a header font with personality and pair it with a clean body font.

| Header Font | Body Font |
|-------------|-----------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Element | Size |
|---------|------|
| Slide title | 36-44pt bold |
| Section header | 20-24pt bold |
| Body text | 14-16pt |
| Captions | 10-12pt muted |

### Spacing

- 0.5" minimum margins
- 0.3-0.5" between content blocks
- Leave breathing room—don't fill every inch

### Avoid (Common Mistakes)

- **Don't repeat the same layout** — vary columns, cards, and callouts across slides
- **Don't center body text** — left-align paragraphs and lists; center only titles
- **Don't skimp on size contrast** — titles need 36pt+ to stand out from 14-16pt body
- **Don't default to blue** — pick colors that reflect the specific topic
- **Don't mix spacing randomly** — choose 0.3" or 0.5" gaps and use consistently
- **Don't style one slide and leave the rest plain** — commit fully or keep it simple throughout
- **Don't create text-only slides** — add images, icons, charts, or visual elements; avoid plain title + bullets
- **Don't forget text box padding** — when aligning lines or shapes with text edges, set `margin: 0` on the text box or offset the shape to account for padding
- **Don't use low-contrast elements** — icons AND text need strong contrast against the background; avoid light text on light backgrounds or dark text on dark backgrounds
- **NEVER use accent lines under titles** — these are a hallmark of AI-generated slides; use whitespace or background color instead

---

## QA (Required)

**Assume there are problems. Your job is to find them.**

Your first render is almost never correct. Approach QA as a bug hunt, not a confirmation step. If you found zero issues on first inspection, you weren't looking hard enough.

### Content QA

```bash
python -m markitdown output.pptx
```

Check for missing content, typos, wrong order.

**When using templates, check for leftover placeholder text:**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

If grep returns results, fix them before declaring success.

### Visual QA

**⚠️ USE SUBAGENTS** — even for 2-3 slides. You've been staring at the code and will see what you expect, not what's there. Subagents have fresh eyes.

Convert slides to images (see [Converting to Images](#converting-to-images)), then use this prompt:

```
Visually inspect these slides. Assume there are issues — find them.

Look for:
- Overlapping elements (text through shapes, lines through words, stacked elements)
- Text overflow or cut off at edges/box boundaries
- Decorative lines positioned for single-line text but title wrapped to two lines
- Source citations or footers colliding with content above
- Elements too close (< 0.3" gaps) or cards/sections nearly touching
- Uneven gaps (large empty area in one place, cramped in another)
- Insufficient margin from slide edges (< 0.5")
- Columns or similar elements not aligned consistently
- Low-contrast text (e.g., light gray text on cream-colored background)
- Low-contrast icons (e.g., dark icons on dark backgrounds without a contrasting circle)
- Text boxes too narrow causing excessive wrapping
- Leftover placeholder content

For each slide, list issues or areas of concern, even if minor.

Read and analyze these images:
1. /path/to/slide-01.jpg (Expected: [brief description])
2. /path/to/slide-02.jpg (Expected: [brief description])

Report ALL issues found, including minor ones.
```

### Verification Loop

1. Generate slides → Convert to images → Inspect
2. **List issues found** (if none found, look again more critically)
3. Fix issues
4. **Re-verify affected slides** — one fix often creates another problem
5. Repeat until a full pass reveals no new issues

**Do not declare success until you've completed at least one fix-and-verify cycle.**

---

## Converting to Images

Convert presentations to individual slide images for visual inspection:

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

This creates `slide-01.jpg`, `slide-02.jpg`, etc.

To re-render specific slides after fixes:

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```

---

## Dependencies

- `pip install "markitdown[pptx]"` - text extraction
- `pip install Pillow` - thumbnail grids
- `npm install -g pptxgenjs` - creating from scratch
- LibreOffice (`soffice`) - PDF conversion (auto-configured for sandboxed environments via `scripts/office/soffice.py`)
- Poppler (`pdftoppm`) - PDF to images

---

<!-- ════════════════════════════════════════════════════════════════════
     JARVIS Presentation Intelligence — custom additions (Phase 3.1+)
     Owned by jarvis-project. Preserve when syncing upstream Anthropic skill.
     ════════════════════════════════════════════════════════════════════ -->

# JARVIS Presentation Intelligence

JARVIS sends the handler a `doc_type` parameter on every `create_pptx` call (`pitch` | `report` | `training` | `sales`) plus a `slide_count` int (clamped to 3–20, default 6). The user message will say *"Apply the {doc_type} formatting standards from the skill guide."* — apply the matching block below. **`doc_type` is a hard input contract, not a hint.**

The cascade and Section A/B logic mirror the docx skill but adapt for slides: where docx prizes readability, slides prize **visual hierarchy and impact**. Colour is more welcome here — even formal decks use accent colour. The defaults are bolder.

## Resolution cascade (apply in this order — higher levels override lower)

1. **STRUCTURAL RULES per doc_type** — slide layouts, font sizes, slide budget, content density per slide. **Inviolable.**
2. **User-described design** — explicit colour or mood cues in the user's topic/style. Overrides palette defaults; cannot override structural rules.
3. **Topic-aware palette** — when the user gave no colour direction, pick from Section B based on subject matter.
4. **doc_type default palette** — final fallback.

## Section A — User-described design

Identical rules to docx Section A: parse the user's topic and style for colour words ("red and black"), mood words ("bold", "minimal"), format words ("magazine style"), `"no colors"`/`"simple"`/`"minimalist"` → black-and-white, named-standard overrides.

Decks tolerate more visual personality than documents — so when the user says "bold" or "modern", interpret it more aggressively (larger title fonts, full-bleed accent backgrounds on title slides, stronger colour contrast).

## Section B — Topic-aware palette (slide-tuned)

When the user gives no colour direction, pick a palette by subject. **For pptx, palettes have THREE colours**: primary (title slides, accent bars, large headings), secondary (data charts, supporting accents), text-on-dark (used when a slide has a dark background — usually white).

| Topic domain | Primary / Secondary / Text-on-dark |
|---|---|
| Technology / AI / software / data | `#0D1B2A` deep navy / `#00B4D8` electric blue / `#F8F9FA` near-white |
| Environment / sustainability | `#1B5E20` forest green / `#FBC02D` amber / `#FFFFFF` |
| Finance / business / economics | `#1F4E79` navy / `#C9A84C` gold / `#FFFFFF` |
| Health / medical | `#0077B6` clinical blue / `#2EC4B6` teal / `#FFFFFF` |
| Creative / arts / design | One bold field-appropriate accent / one complementary neutral / `#FFFFFF` |
| Education / training | `#6B2737` burgundy / `#E0A458` warm amber / `#FFFFFF` |
| Government / policy | `#003087` navy / `#A8201A` muted red / `#FFFFFF` |
| Startup / pitch (default if topic-unclear) | `#1A1A2E` near-black / `#E94560` vivid coral-red / `#F8F9FA` |
| General / unknown | `#1F4E79` navy / `#5B6770` slate gray / `#FFFFFF` |

Body text on light backgrounds is always pure black or near-black (`#1A1A2E`). Use the text-on-dark colour only when the slide itself has a dark fill.

## Section C — Presentation type standards

All four deck types have dedicated standards blocks: **PITCH**, **REPORT**, **TRAINING**, **SALES**. The Universal Slide Rules at the end apply to every type.

### PITCH (investor / startup / new-idea deck)

The pitch deck is **the** canonical slide format. Bold, fast, emotionally engaging. Each slide answers one question. Visual hierarchy is everything.

| Aspect | Standard |
|---|---|
| Slide size | 16:9 widescreen (`Inches(13.333)` × `Inches(7.5)`) |
| Slide background | Light theme: white `#FFFFFF` for content slides, primary-colour fill for the title slide and section dividers. (Dark theme acceptable when user signals "dark" / "minimal black" — invert.) |
| Font family | Calibri or a similar geometric sans-serif. **Title and body share one family.** |
| Title slide — title text | 48–60pt bold, primary colour on light bg OR white on primary fill |
| Title slide — subtitle | 18–22pt regular, secondary colour |
| Section divider slide title | 36–44pt bold, primary colour or white on primary fill |
| Content slide — title | 28–32pt bold, primary colour, top of slide (top margin ≤ `Inches(0.5)`) |
| Content slide — body | 18–22pt regular, near-black `#1A1A2E`. **One key idea per slide. Max 30 words.** |
| Bullets (when used) | 16–20pt regular, max 4 bullets/slide, each ≤10 words. **No nested bullets.** |
| Data / chart slides | Title 28pt, chart fills 70% of slide area, callout text 14–16pt for labels |
| Accent bar | Optional 0.15" horizontal bar in primary colour at the top of every content slide. Strong unifying visual. Skip on title slide. |
| Slide numbers | Bottom-right, 10pt regular, secondary colour. Skip on title slide. |

**Standard 6-slide pitch structure** (scale with `slide_count`):
1. **Title** — Company/idea name, one-line value prop, small footer (author + date)
2. **Problem** — The pain point. One sentence + supporting data or emotive callout.
3. **Solution** — What we built. One sentence + 2–3 differentiators as short bullets.
4. **Market / opportunity** — TAM/SAM or audience size. Big numbers, minimal text.
5. **Traction / proof** — Metrics, logos, testimonials. Data-driven.
6. **Ask / closing** — What we want (investment, partnership, hire). Contact info. Call to action.

**Scaling rules:**
- `slide_count: 3` → Title + Problem-and-Solution combined + Ask
- `slide_count: 4–5` → Drop market or traction; keep title + problem + solution + ask
- `slide_count: 6` → The canonical structure above
- `slide_count: 7–10` → Add team slide, business model slide, competition / "why us" slide, financials slide
- `slide_count: 11–20` → Expand with detailed financials, roadmap, product-demo placeholders, use-case deep-dives

### REPORT (status update / quarterly review / executive summary)

Neutral business language, data-heavy, more density than a pitch. The audience is internal stakeholders or leadership — they want substance, not marketing tone. Tables and charts are central; emotional hooks are not.

| Aspect | Standard |
|---|---|
| Slide size | 16:9 widescreen (`Inches(13.333)` × `Inches(7.5)`) |
| Background | Light theme throughout (`#FFFFFF` or near-white). Title slide may use the primary colour as a thin top band rather than a full fill. |
| Font family | Calibri or similar sans-serif. One family throughout. |
| Title slide — title | 36–44pt bold, primary colour. Smaller than a pitch — this isn't a hero moment. |
| Title slide — subtitle | 18pt regular, secondary colour. Include reporting period (e.g. "Q3 2025 · Engineering"). |
| Content slide — title | 24–28pt bold, primary colour |
| Content slide — body | 14–18pt regular, near-black `#1A1A2E`. **35–45 words/slide acceptable** — reports tolerate more density than pitches. |
| Bullets | 14–16pt regular, up to 6 bullets/slide, each ≤15 words. Sub-bullets allowed one level deep. |
| Data slides | Tables and charts are the headline. Title 24pt, chart/table fills 60–70% of slide. Callouts annotate the data. |
| Accent bar | Same as PITCH — 0.12" primary-colour bar at top of every content slide |
| Slide numbers | Every slide including title (top-right or bottom-right, 10pt) |
| Header/footer | Footer left: report title + date. Footer right: slide number. |

**Standard 6-slide report structure** (scale with `slide_count`):
1. **Title** — Report name, reporting period, presenter/team
2. **Executive Summary** — Top 3 takeaways as short bulleted statements with supporting numbers
3. **Highlights / Wins** — What went well. KPI table or 3–4 metric cards.
4. **Metrics deep-dive** — Charts: trend line, breakdown, comparison vs. last period
5. **Risks / Lowlights** — What didn't go well. Tables of issues + owners + status.
6. **Next steps / asks** — Action items table (action / owner / date) + any decisions needed

**Scaling rules:**
- `slide_count: 3` → Title + Summary + Next-steps (skip deep-dive)
- `slide_count: 4–5` → Drop one of Highlights or Risks
- `slide_count: 7–10` → Split metrics into per-area slides (revenue / engagement / ops)
- `slide_count: 11–20` → One slide per workstream, plus appendix tables

### TRAINING (educational deck / workshop / onboarding)

The goal is teaching, not pitching. Structure mirrors a lesson: objectives → modules → recap → Q&A. Each step gets its own slide. Higher text density acceptable because learners read along.

| Aspect | Standard |
|---|---|
| Slide size | 16:9 widescreen |
| Background | Light theme throughout. Section divider slides use a primary-colour band on the left third. |
| Font family | Calibri or similar sans-serif. **A secondary serif font (e.g. Cambria) is allowed for pull-quotes only.** |
| Title slide — title | 40–48pt bold, primary colour |
| Title slide — subtitle | 18–20pt, secondary colour. Include course/module name. |
| Section divider — title | 32–36pt bold on coloured band. Numbered (e.g. "Module 2: Working with the API"). |
| Content slide — title | 26–30pt bold, primary colour |
| Content slide — body | 16–20pt regular, near-black. **35–50 words/slide acceptable.** Use prose paragraphs OR bullets, not both on one slide. |
| Pull-quote callout | 22pt italic Cambria or Georgia, secondary colour, centred. Use sparingly for key concepts. |
| Code / command samples | Consolas 12–14pt in a light grey rounded rectangle. Black text. |
| Bullets | 16–18pt regular. Numbered when teaching steps, plain bullets for lists. |
| Accent bar | 0.15" primary-colour bar at the top of every content slide |
| Slide numbers | Every slide. Format: `<module>.<slide-in-module>` (e.g. `2.3`) for navigability. |
| Footer | Course name + module label on left, slide number on right |

**Standard 6-slide training structure** (scale with `slide_count`):
1. **Title** — Course title, "by [instructor]", duration estimate
2. **Learning objectives** — "By the end you'll be able to…" + 3–4 bulleted outcomes
3. **Module 1 / Step 1** — Concept + diagram or example
4. **Module 2 / Step 2** — Building on previous, with code/example
5. **Recap** — "What we covered" + same outcome list, now marked complete
6. **Q&A / next steps** — Resources, links to deeper material, contact

**Scaling rules:**
- `slide_count: 3` → Title + One-page-summary + Recap (skip step decomposition — for tightly-scoped topics only)
- `slide_count: 4–5` → Drop recap or split objectives into multiple slides
- `slide_count: 7–10` → Expand into 4–6 module slides + add an examples / exercises slide
- `slide_count: 11–20` → Full curriculum: section dividers between modules, 2–3 slides per module, exercises slide, glossary slide

### SALES (product/service pitch to a customer)

Outward-facing, customer-centric. Use "you" and "your team" — not "we" — throughout the body. Lead with the customer's problem, not your product. End with a clear ask and contact info.

| Aspect | Standard |
|---|---|
| Slide size | 16:9 widescreen |
| Background | Light theme for content; **brand colours stronger than PITCH** — title and section divider slides should fill ~60% of the slide with primary colour |
| Font family | Calibri or similar sans-serif. One family. |
| Title slide — title | 48–56pt bold, primary colour OR white on primary fill. Tagline-style if appropriate ("How [Customer] Can Reduce Churn by 40%"). |
| Title slide — subtitle | 18–22pt, secondary colour. Include presenter + company. |
| Content slide — title | 30–34pt bold, primary colour. Should be **a benefit statement, not a feature name** — "Cut onboarding time by 70%" beats "Onboarding Module". |
| Content slide — body | 18–22pt regular, near-black. **One key benefit per slide, max 30 words.** Match PITCH density. |
| Bullets | 16–20pt regular, max 4 bullets/slide. Lead each with a strong outcome verb. |
| Customer-proof slide | Logo grid (3×2 or 4×3 of customer logos) OR testimonial pull-quote (28pt italic, attributed in 14pt with photo placeholder) |
| Pricing slide | 2–3 tier cards. The middle/recommended tier visually pops (primary fill, accent badge "RECOMMENDED"). |
| Accent bar | Same as PITCH |
| Slide numbers | Optional — many sales decks skip them for a cleaner look. If included, bottom-right 10pt. |

**Standard 6-slide sales structure** (scale with `slide_count`):
1. **Title / hook** — Customer-facing title, presenter info, customer logo if known
2. **Their problem** — The pain point in the customer's own language. Numbers if available.
3. **Your solution** — One sentence about your product, 2–3 differentiators
4. **Proof** — Customer logos OR case study with metrics OR testimonial pull-quote
5. **Pricing / packages** — 2–3 tier cards, recommended tier highlighted
6. **Call to action** — Next step: trial, demo, signed proposal. Contact info prominent.

**Scaling rules:**
- `slide_count: 3` → Title + Problem-and-Solution combined + CTA
- `slide_count: 4–5` → Drop pricing OR proof; keep title + problem + solution + CTA
- `slide_count: 7–10` → Add feature deep-dives between solution and proof (each slide = one capability + benefit)
- `slide_count: 11–20` → Full enterprise sales deck: dedicated case studies (one per slide), security/compliance slide, integration/architecture slide, success-team slide, contract terms slide

## Universal Slide Rules (apply to every deck)

1. **One idea per slide.** If you find yourself writing >40 words on a content slide, split it.
2. **Visual hierarchy** — title > body > footnotes. No exceptions.
3. **Contrast** — text on backgrounds must hit 4.5:1 minimum.
4. **No paragraph-style prose.** Break into phrases, bullets, or split across slides.
5. **Consistent positioning** — slide titles always at the same vertical position across content slides (same `top` value).
6. **Don't centre body text unless it's a hero callout** — body content reads better left-aligned.
7. **Speaker notes encouraged** — `slide.notes_slide.notes_text_frame.text = "..."` for talking points. Especially useful for pitch decks.
8. **No clip-art icons.** If an icon visual is needed, add a placeholder rectangle with a label like `[icon: rocket]` for the user to swap in. Don't try to draw vector icons via XML.
9. **Charts via matplotlib** — generate at 300 DPI, save to a temp PNG, insert via `slide.shapes.add_picture()`. Don't draw charts with python-pptx primitives.
10. **Don't hallucinate python-pptx XML methods.** Stick to documented APIs: `slide.shapes.add_textbox`, `add_picture`, `add_shape`, `tf.paragraphs[i].runs[j]`. Avoid invented `get_or_add_*` methods on slide internals.

<!-- ════════════════════════════════════════════════════════════════════
     End JARVIS Presentation Intelligence
     ════════════════════════════════════════════════════════════════════ -->
