"""Fix B — document-generator AST validator calibration.

The validator used one receiver-blind name set, so it blocked any call whose bare
name OR attribute name matched. That over-blocked innocent python-docx idioms —
`setattr(section, 'left_margin', Inches(1))` (the reported bug) and, worse,
`re.compile(...)` (attr "compile"), even though `re` is allowlisted. The fix
splits the policy into three intent-specific tiers:

  - _DANGEROUS_BUILTINS  (eval/exec/compile/__import__) — bare Name calls only.
  - _DANGEROUS_OS_CALLS   (system/popen/execv*/fork*)    — Name OR Attribute.
  - getattr/setattr/delattr — allowed on ordinary objects, blocked only when the
    FIRST arg reaches into a guarded powerful module (the dynamic-access escape).

These tests pin both halves: innocent idioms PASS, real threats stay BLOCKED.
"""

from __future__ import annotations

from core.handlers.document_handler import _validate_script


def _blocks(code: str) -> list[str]:
    return _validate_script(code)[0]


# ── must PASS (innocent idioms the old validator wrongly blocked) ───────────


def test_setattr_on_plain_object_passes():
    assert _blocks("setattr(section, 'left_margin', Inches(1))\n") == []


def test_exact_margin_loop_regression_passes():
    # The VERBATIM idiom from the neural-networks bug. Must never block again.
    code = (
        "section = doc.sections[0]\n"
        "for attr in ('left_margin','right_margin','top_margin','bottom_margin'):\n"
        "    setattr(section, attr, Inches(1))\n"
    )
    assert _blocks(code) == []


def test_getattr_on_plain_object_passes():
    assert _blocks("x = getattr(obj, 'foo', None)\n") == []


def test_delattr_on_plain_object_passes():
    assert _blocks("delattr(obj, 'foo')\n") == []


def test_re_compile_passes():
    # `re` is allowlisted precisely so Sonnet can use it; re.compile is idiomatic.
    assert _blocks("import re\np = re.compile(r'\\d+')\n") == []


def test_innocent_docx_script_passes():
    code = (
        "from docx import Document\n"
        "from docx.shared import Inches\n"
        "d = Document()\n"
        "d.add_paragraph('hello')\n"
        "d.save('out.docx')\n"
    )
    assert _blocks(code) == []


# ── must BLOCK (real threats — the validator stays a safety net) ────────────


def test_exec_eval_compile_import_builtins_blocked():
    assert _blocks("eval('1+1')\n")
    assert _blocks("exec('x=1')\n")
    assert _blocks("compile('1', '<s>', 'eval')\n")          # builtin compile, not re.compile
    assert _blocks("__import__('os')\n")


def test_os_process_calls_blocked_as_attribute_and_name():
    assert _blocks("import os\nos.system('rm -rf /')\n")
    assert _blocks("import os\nos.popen('x')\n")
    # `from os import system; system(...)` — the bare-Name form.
    assert _blocks("from os import system\nsystem('x')\n")


def test_dynamic_access_into_guarded_module_blocked():
    # The security-critical guard: getattr/setattr into a powerful module is the
    # escape that defeats name-based blocking — it must STAY blocked.
    assert _blocks("import os\ngetattr(os, 'system')('x')\n")
    assert _blocks("import sys\nsetattr(sys, 'x', 1)\n")
    assert _blocks("import os\ndelattr(os, 'environ')\n")


def test_builtins_dotted_compile_escape_blocked():
    # Rare `__builtins__.compile(...)` form — guarded-receiver rule catches it,
    # while re.compile (receiver 're') still passes (test above).
    assert _blocks("__builtins__.compile('1', '<s>', 'eval')\n")


def test_dangerous_module_import_blocked():
    assert _blocks("import socket\n")
    assert _blocks("import subprocess\n")


def test_non_allowlisted_import_blocked():
    assert _blocks("import pandas\n")
