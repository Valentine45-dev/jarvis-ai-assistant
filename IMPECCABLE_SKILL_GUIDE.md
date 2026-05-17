# Impeccable Skill Guide

This guide explains how to use the Impeccable design skill in this project. Use it when you want the UI to feel intentional, production-ready, and aligned with `PRODUCT.md`, not just "styled."

## What Impeccable Is

Impeccable is a frontend design workflow. It helps with:

- Planning UI before coding.
- Reviewing visual quality.
- Finding accessibility, responsiveness, theming, and performance issues.
- Improving weak or generic screens.
- Polishing a feature before it ships.

It is not only a styling command. The best results come from using it as a sequence: understand the product, shape the design, build or review, then refine.

## Required Context

Before Impeccable can work well, the project needs product context.

- `PRODUCT.md`: Required. Explains users, purpose, personality, anti-references, and design principles.
- `DESIGN.md`: Optional but recommended. Explains tokens, components, typography, color rules, and design system conventions.

If `PRODUCT.md` is missing or shallow, Impeccable should stop and ask for `/impeccable teach`.

For this project, `PRODUCT.md` defines JARVIS as a precise, command-oriented personal OS controller. That means the UI should feel controlled, sharp, restrained, and operational. It should not feel like a friendly chatbot.

## Main Workflow

Use this sequence for serious UI work:

1. `/impeccable shape <feature>`
   Plan the UX and UI before code. Produces a design brief.

2. `/impeccable craft <feature>`
   Shape, build, inspect, and iterate on a feature end-to-end.

3. `/impeccable critique <target>`
   Review an existing interface from a design quality perspective.

4. `/impeccable audit <target>`
   Run a technical UI audit across accessibility, performance, theming, responsiveness, and anti-patterns.

5. `/impeccable polish <target>`
   Do the final detail pass once the feature already works.

For JARVIS, a good cycle is:

```text
/impeccable shape command history screen
/impeccable craft command history screen
/impeccable critique ui/history.py
/impeccable audit ui/history.py
/impeccable polish ui/history.py
```

## Command Categories

### Build Commands

Use these when creating or planning UI.

- `/impeccable teach`
  Creates or improves product context. Use this when `PRODUCT.md` is missing, vague, or outdated.

- `/impeccable document`
  Creates `DESIGN.md` from the existing codebase. Use this after the UI has enough patterns worth documenting.

- `/impeccable shape <feature>`
  Produces a design brief. Use before building anything non-trivial.

- `/impeccable craft <feature>`
  Runs the full design-to-code workflow. Use when you want the agent to build the feature, not just plan it.

- `/impeccable extract <target>`
  Pulls repeated UI values and components into a clearer design system.

### Evaluate Commands

Use these when you want feedback before changing code.

- `/impeccable critique <target>`
  Design critique. Looks at visual hierarchy, UX, cognitive load, AI slop tells, copy, layout, emotional fit, and user friction.

- `/impeccable audit <target>`
  Technical audit. Looks at accessibility, performance, theming, responsive behavior, and implementation-level anti-patterns.

### Refine Commands

Use these when a screen exists but needs a specific improvement.

- `/impeccable polish <target>`
  Final quality pass. Best after the feature works.

- `/impeccable bolder <target>`
  Makes a bland UI more distinctive.

- `/impeccable quieter <target>`
  Reduces visual noise or overdone styling.

- `/impeccable distill <target>`
  Removes complexity and strips the UI to its essence.

- `/impeccable harden <target>`
  Improves edge cases, accessibility, keyboard behavior, error states, and production readiness.

- `/impeccable onboard <target>`
  Improves first-run flows, empty states, and activation paths.

### Enhance Commands

Use these for focused design improvements.

- `/impeccable animate <target>`
  Adds purposeful motion. Motion should communicate state, not decorate.

- `/impeccable colorize <target>`
  Improves color strategy and token use.

- `/impeccable typeset <target>`
  Improves typography hierarchy, font use, line length, and readability.

- `/impeccable layout <target>`
  Fixes spacing, rhythm, alignment, and visual hierarchy.

- `/impeccable delight <target>`
  Adds memorable details without breaking usability.

- `/impeccable overdrive <target>`
  Pushes the concept harder when the current UI is too safe.

### Fix Commands

Use these when the problem is known.

- `/impeccable clarify <target>`
  Improves labels, errors, empty states, and UX copy.

- `/impeccable adapt <target>`
  Improves responsiveness across screen sizes.

- `/impeccable optimize <target>`
  Diagnoses and fixes UI performance problems.

- `/impeccable live`
  Iterates visually in a running browser or app surface when available.

## Understanding `critique`

Use `critique` when you want design feedback, not code fixes.

Good examples:

```text
/impeccable critique ui/dashboard.py
/impeccable critique the settings screen
/impeccable critique the command history page
```

`critique` should answer:

- Does this look AI-generated?
- Is the visual hierarchy clear?
- Is the main user action obvious?
- Is the screen too busy or too empty?
- Does the interface match `PRODUCT.md`?
- Does the copy sound right for the product?
- Where does the user hesitate?
- Which 3 to 5 issues matter most?

For JARVIS, critique should be strict about:

- Avoiding chatbot patterns.
- Avoiding friendly or apologetic UI copy.
- Avoiding generic neon sci-fi excess.
- Preserving sharp command-oriented structure.
- Making system status obvious at a glance.

## Understanding `audit`

Use `audit` when you want measurable technical findings.

Good examples:

```text
/impeccable audit ui/
/impeccable audit ui/sidebar.py
/impeccable audit ui/dashboard.py
```

`audit` scores five dimensions:

- Accessibility.
- Performance.
- Responsive design.
- Theming.
- Anti-patterns.

Use `audit` after `critique` when you want to know what implementation problems are causing the design problems.

## Understanding `polish`

Use `polish` only after the feature works.

Good examples:

```text
/impeccable polish ui/settings.py
/impeccable polish the voice interface
```

`polish` checks:

- Alignment.
- Spacing.
- Typography.
- Interaction states.
- Focus states.
- Copy consistency.
- Edge cases.
- Loading, empty, error, and success states.
- Token usage.
- Responsive details.

Do not use `polish` as the first command for a broken or incomplete feature. Use `shape`, `craft`, `harden`, or `audit` first.

## Which Command Should I Use?

Use `/impeccable shape` when:

- You are about to build a new UI.
- The feature is not fully defined.
- You need a design brief before coding.

Use `/impeccable craft` when:

- You want the agent to plan and build the feature.
- The feature touches multiple components or states.
- You want browser or visual iteration included.

Use `/impeccable critique` when:

- The UI exists and you want honest design feedback.
- You want to know what feels wrong.
- You want a prioritized list of design issues.

Use `/impeccable audit` when:

- You want technical quality scores.
- You care about accessibility, responsive behavior, performance, or theming.
- You want measurable findings before fixes.

Use `/impeccable harden` when:

- Keyboard navigation, edge cases, confirmations, and error states need work.
- The UI is close but not production-safe.

Use `/impeccable adapt` when:

- The layout breaks on small screens.
- There are fixed widths or cramped panels.
- Touch targets are too small.

Use `/impeccable optimize` when:

- Animations feel heavy.
- The UI repaints too often.
- Timers or effects run when hidden.

Use `/impeccable polish` when:

- The feature works and needs final refinement.
- You want to remove rough edges before calling it done.

## Example JARVIS Command Plans

### Improve the Sidebar

```text
/impeccable critique ui/sidebar.py
/impeccable harden ui/sidebar.py
/impeccable polish ui/sidebar.py
```

Why:

- `critique` finds design and UX issues.
- `harden` fixes keyboard and interaction reliability.
- `polish` aligns the details.

### Fix Desktop-Only Layout

```text
/impeccable audit ui/dashboard.py
/impeccable adapt ui/dashboard.py
/impeccable polish ui/dashboard.py
```

Why:

- `audit` identifies fixed-width and responsive problems.
- `adapt` fixes layout behavior.
- `polish` cleans up visual details after the layout changes.

### Make a Screen Less Generic

```text
/impeccable critique ui/history.py
/impeccable bolder ui/history.py
/impeccable polish ui/history.py
```

Why:

- `critique` explains what feels generic.
- `bolder` pushes the screen toward a stronger identity.
- `polish` prevents the stronger design from becoming noisy.

### Improve Theme Consistency

```text
/impeccable document
/impeccable audit ui/
/impeccable colorize ui/
/impeccable polish ui/
```

Why:

- `document` captures the design system.
- `audit` finds token drift.
- `colorize` rationalizes color usage.
- `polish` finishes the details.

## Impeccable Rules To Remember

- Product context comes first. Do not design without `PRODUCT.md`.
- Shape is task-specific. `PRODUCT.md` does not replace `/impeccable shape`.
- Critique reports issues. It does not fix them.
- Audit checks measurable implementation quality. It is not a taste review.
- Polish is last. Do not polish incomplete work.
- Use design tokens instead of one-off colors.
- Every interactive element needs default, hover, focus, active, disabled, loading, error, and success states where relevant.
- Motion must communicate state.
- Avoid generic AI patterns: gradient text, decorative glass, identical card grids, hero metrics, and random neon glow.
- For JARVIS, restraint matters. The UI should feel like precision equipment.

## Personal Cheat Sheet

When unsure, use this:

```text
New feature?
  /impeccable shape, then /impeccable craft

Existing UI feels wrong?
  /impeccable critique

Existing UI may be technically weak?
  /impeccable audit

UI breaks on screen sizes?
  /impeccable adapt

UI has weak keyboard, error, or edge-case behavior?
  /impeccable harden

Colors are inconsistent?
  /impeccable colorize

Spacing or hierarchy is off?
  /impeccable layout

Text and labels feel unclear?
  /impeccable clarify

Feature works but feels unfinished?
  /impeccable polish
```

## Best Learning Path

Start with these five commands:

1. `/impeccable teach`
2. `/impeccable document`
3. `/impeccable critique <target>`
4. `/impeccable audit <target>`
5. `/impeccable polish <target>`

Once those feel natural, learn:

1. `/impeccable shape`
2. `/impeccable craft`
3. `/impeccable harden`
4. `/impeccable adapt`
5. `/impeccable colorize`

The strongest habit is simple: critique before fixing, audit before broad refactors, polish only after the feature works.
