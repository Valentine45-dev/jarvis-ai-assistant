"""Region screenshots that span SEVERAL elements (a heading + an input + the
items listed below it) — the picker asks Haiku for the bounding *set* of refs,
unions their document-space boxes, and clips the page via
``page.screenshot(clip=union, full_page=True)``.

A single ref degrades to a crisp element-level shot; multiple refs are clipped.
These tests cover the pure helpers (ref-list parsing, union math) and the
``_screenshot_region`` routing (one ref → element shot, many → union clip,
none → legacy fallback, unresolvable boxes → clean error).
"""

from __future__ import annotations

import pytest

from core.browser.picker import _PickerMixin


# ── _coerce_ref / _parse_haiku_refs ─────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    (5, 5),
    ("ref_5", 5),
    ("  7 ", 7),
    (True, None),          # bool is not a ref
    ("nope", None),
    (3.2, None),
])
def test_coerce_ref(raw, expected) -> None:
    assert _PickerMixin._coerce_ref(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ('{"refs": [1, 2, 3]}', [1, 2, 3]),
    ('{"refs": ["ref_1", "2", 3]}', [1, 2, 3]),
    ('{"ref": 5}', [5]),                              # degrade single → list
    ('```json\n{"refs": [4, 4, 9]}\n```', [4, 9]),    # fenced + de-dup
    ('garbage', []),
    ('{"refs": "not a list"}', []),
    ('{"refs": [true, "x", 6]}', [6]),                # filter junk items
    ('', []),
])
def test_parse_haiku_refs(raw, expected) -> None:
    assert _PickerMixin._parse_haiku_refs(raw) == expected


# ── _union_clip ──────────────────────────────────────────────────────────────

def test_union_clip_spans_all_boxes() -> None:
    boxes = [
        {"x": 0.0, "y": 100.0, "width": 900.0, "height": 40.0},   # heading
        {"x": 150.0, "y": 200.0, "width": 600.0, "height": 40.0},  # input
        {"x": 0.0, "y": 300.0, "width": 160.0, "height": 20.0},    # last item
    ]
    clip = _PickerMixin._union_clip(boxes, pad=8.0)
    # left/top = min - pad ; right/bottom = max + pad
    assert clip["x"] == -8.0
    assert clip["y"] == 92.0
    assert clip["x"] + clip["width"] == 900.0 + 8.0     # widest box (heading) + pad
    assert clip["y"] + clip["height"] == 320.0 + 8.0    # bottom of last item + pad


def test_union_clip_single_box_just_pads() -> None:
    clip = _PickerMixin._union_clip([{"x": 10.0, "y": 10.0, "width": 100.0, "height": 50.0}], pad=4.0)
    assert clip == {"x": 6.0, "y": 6.0, "width": 108.0, "height": 58.0}


# ── _screenshot_region routing (no real browser) ─────────────────────────────

class _FakePage:
    """Records page.screenshot(clip=…, full_page=…) calls; nothing else used here."""

    def __init__(self) -> None:
        self.shots: list[dict] = []

    def evaluate(self, _js):  # page-dimension clamp probe
        return {"w": 1000.0, "h": 2000.0}

    def screenshot(self, path=None, clip=None, full_page=None):
        self.shots.append({"path": path, "clip": clip, "full_page": full_page})


class _Host(_PickerMixin):
    def __init__(self, ref_map, boxes=None, refs=None) -> None:
        self._page = _FakePage()
        self._ref_map = ref_map
        self._boxes = boxes or {}
        self._refs = refs or []
        self.element_calls: list[tuple] = []
        self.legacy_calls: list[tuple] = []

    # stub the Haiku call
    def _pick_region_refs(self, goal, tree_text, cfg):
        return list(self._refs), "stub"

    # stub box resolution by node identity
    def _doc_box_for_node(self, node):
        return self._boxes.get(id(node))

    def _resolve_shot_path(self, path, tag=""):
        return path or "out.png"

    def _exec_screenshot_by_role(self, role, name, goal, path):
        self.element_calls.append((role, name, goal, path))
        return {"success": True, "output": "element", "error": ""}

    def _find_legacy_fallback(self, goal, action, value):
        self.legacy_calls.append((goal, action, value))
        return {"success": False, "output": "", "error": "fallback"}


def _noop(_msg: str) -> None:
    pass


def test_single_ref_uses_element_shot() -> None:
    node = {"role": "heading", "raw_name": "Title"}
    host = _Host(ref_map={1: node}, refs=[1])
    res = host._screenshot_region("the title", "tree", "x.png", cfg=None, dlog=_noop)
    assert res["success"] is True
    assert host.element_calls == [("heading", "Title", "the title", "x.png")]
    assert host._page.shots == []          # no page clip for a single element


def test_multiple_refs_union_clip_full_page() -> None:
    n1, n2, n3 = ({"role": "heading"}, {"role": "textbox"}, {"role": "button"})
    boxes = {
        id(n1): {"x": 0.0, "y": 100.0, "width": 900.0, "height": 40.0},
        id(n2): {"x": 150.0, "y": 200.0, "width": 600.0, "height": 40.0},
        id(n3): {"x": 0.0, "y": 300.0, "width": 160.0, "height": 20.0},
    }
    host = _Host(ref_map={1: n1, 2: n2, 3: n3}, boxes=boxes, refs=[1, 2, 3])
    res = host._screenshot_region("agenda section", "tree", "r.png", cfg=None, dlog=_noop)
    assert res["success"] is True
    assert host.element_calls == []        # not the single-element path
    assert len(host._page.shots) == 1
    shot = host._page.shots[0]
    assert shot["full_page"] is True       # below-fold spans need full_page+clip
    assert shot["clip"]["x"] == 0.0        # left clamped to >=0 (was -8)
    assert shot["clip"]["y"] == 92.0
    # bottom of last box (320) + pad (8), within page height (2000)
    assert shot["clip"]["y"] + shot["clip"]["height"] == 328.0


def test_no_refs_falls_back_to_legacy() -> None:
    host = _Host(ref_map={}, refs=[])
    res = host._screenshot_region("nothing", "tree", None, cfg=None, dlog=_noop)
    assert res["success"] is False
    assert host.legacy_calls == [("nothing", "screenshot", "")]


def test_unresolvable_boxes_clean_error_no_shot() -> None:
    n1, n2 = ({"role": "heading"}, {"role": "button"})
    host = _Host(ref_map={1: n1, 2: n2}, boxes={}, refs=[1, 2])  # no boxes resolve
    res = host._screenshot_region("ghost area", "tree", None, cfg=None, dlog=_noop)
    assert res["success"] is False
    assert "ghost area" in res["error"]
    assert host._page.shots == []          # nothing captured
