# Claude Code — local dev conventions

This file is loaded by **Claude Code** (the dev assistant) only. JARVIS's brain
(`core/brain.py`) reads `CLAUDE.md`/`Claude.md` directly as its system prompt and
never reads this file, so dev-only guidance lives here to keep it out of JARVIS's
prompt.

## Shell command conventions

Write commands that work in the target shell and are robust **when it matters** —
don't over-engineer a trivial one-shot command.

- **Verify and surface failures.** Prefer commands whose success/failure is
  unambiguous. Use defensive patterns **when relevant** (a precondition check
  before a mutation, a `cmd || fallback` so a no-result run reads cleanly) — not on
  simple commands like `git status`.
- **Right operator for the shell (match the actual tool):**
  - **PowerShell tool = Windows PowerShell 5.1** — `&&` and `||` are a parse error.
    Use `;` for an unconditional sequence and `if ($?) { B }` for run-on-success;
    `if (-not $?) { ... }` / `try/catch` for a fallback.
  - **Bash tool = git-bash (POSIX sh)** — `&&`, `||`, `;`, `|` all work normally.
  - Don't mix: never put `&&` in a PowerShell command, never assume PowerShell
    cmdlets in bash.
- **Search files — prefer the dedicated tools.** Use **Grep** (content) and
  **Glob** (filenames) over shelling out — results integrate with the UI and are
  faster. When you *do* shell out for search, use efficient flags and a fallback so
  "no matches" is obvious: bash `grep -rniE 'pat' path || echo "none"`; PowerShell
  `Select-String -Pattern 'pat' -Path path` (never `grep`), with
  `if (-not $?) { 'none' }` when natural.
- **One-liners over round-trips.** Combine a check + action when it reads clearly,
  but keep each Bash/PowerShell call independently understandable.
