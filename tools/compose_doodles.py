"""Put the Figma doodle pieces (one SVG per stroke) back together as one SVG per rule.

Each piece keeps its own SVG intact; it is nested at the box Figma placed it in
(the layer box grown by the negative inset, exactly like the generated code).
Usage: python -I compose.py <pieces.txt> <downloaded-dir> <out-dir>
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)
ALLOWED = {"svg", "path", "line", "polyline", "polygon", "circle", "ellipse", "rect", "g", "defs", "clipPath"}


def px(token, size):
    if token.endswith("%"):
        return float(token[:-1]) / 100 * size
    return float(token.removesuffix("px"))


def inset(tokens, w, h):
    t = tokens + [None] * (4 - len(tokens))
    if len(tokens) == 1:
        t = tokens * 4
    elif len(tokens) == 2:
        t = [tokens[0], tokens[1], tokens[0], tokens[1]]
    top, right, bottom, left = t
    return px(top, h), px(right, w), px(bottom, h), px(left, w)


def clean(path):
    root = ET.parse(path).getroot()
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ALLOWED:
            raise SystemExit(f"{path.name}: unexpected <{tag}>")
        for k in list(el.attrib):
            name = k.split("}")[-1]
            if name.startswith("on") or "href" in name:
                raise SystemExit(f"{path.name}: unexpected attribute {name}")
    return root


def main():
    pieces, src, out = map(Path, sys.argv[1:4])
    doodles = {}
    for line in pieces.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        name, asset, left, top, w, h, *ins = line.split()
        left, top, w, h = map(float, (left, top, w, h))
        t, r, b, l = inset(ins, w, h)
        box = (left + l, top + t, w - l - r, h - t - b)  # insets are negative: the box grows
        doodles.setdefault(name, []).append((asset, box))

    out.mkdir(parents=True, exist_ok=True)
    for name, items in doodles.items():
        x0 = min(b[0] for _, b in items)
        y0 = min(b[1] for _, b in items)
        x1 = max(b[0] + b[2] for _, b in items)
        y1 = max(b[1] + b[3] for _, b in items)
        W, H = x1 - x0, y1 - y0
        doc = ET.Element(f"{{{SVG}}}svg", {
            "width": f"{W:.2f}", "height": f"{H:.2f}",
            "viewBox": f"0 0 {W:.2f} {H:.2f}", "fill": "none",
        })
        for asset, (x, y, w, h) in items:
            piece = clean(src / f"{asset}.svg")
            piece.set("x", f"{x - x0:.3f}")
            piece.set("y", f"{y - y0:.3f}")
            piece.set("width", f"{w:.3f}")
            piece.set("height", f"{h:.3f}")
            piece.set("preserveAspectRatio", "none")
            doc.append(piece)
        text = ET.tostring(doc, encoding="unicode")
        text = re.sub(r"\s+", " ", text)
        (out / f"rule-{name}.svg").write_text(text + "\n", encoding="utf-8")
        print(f"rule-{name}.svg {W:.1f}x{H:.1f} pieces={len(items)}")


main()
