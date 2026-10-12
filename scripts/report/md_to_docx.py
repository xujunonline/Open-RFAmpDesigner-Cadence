"""Convert the experiment report (Markdown subset) to a Word .docx with the Python standard library only.

Supported: # headings, paragraphs, **bold**, `code`, inline/display LaTeX math (sub/superscripts, Greek letters and
common symbols rendered as Word runs), pipe tables, -/1. lists (nested by two spaces), > quotes, ``` code blocks,
![caption](image.png), --- rules.  A table of contents field, page numbers and A4 margins are added.

    python scripts/report/md_to_docx.py docs/139_experiment_report.md -o docs/139_experiment_report.docx
"""
from __future__ import annotations

import argparse
import re
import struct
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

PAGE_W, PAGE_H, MARGIN = 11906, 16838, 1247          # A4, 2.2 cm margins (twips)
TEXT_W = PAGE_W - 2 * MARGIN                          # usable width in twips
EMU_PER_TWIP = 635
BODY_FONT, HEAD_FONT, LATIN_FONT, MONO_FONT = "SimSun", "SimHei", "Times New Roman", "Consolas"

SYMBOLS = {
    r"\le": "≤", r"\ge": "≥", r"\approx": "≈", r"\cdot": "·", r"\parallel": "∥", r"\times": "×", r"\pm": "±",
    r"\Omega": "Ω", r"\omega": "ω", r"\pi": "π", r"\mu": "μ", r"\gamma": "γ", r"\delta": "δ", r"\alpha": "α",
    r"\tau": "τ", r"\lvert": "|", r"\rvert": "|", r"\Re": "Re", r"\Im": "Im", r"\max": "max", r"\min": "min",
    r"\infty": "∞", r"\to": "→", r"\quad": " ", r"\,": " ", r"\;": " ", r"\ ": " ", r"\%": "%",
}


# ------------------------------------------------------------------ inline math -> runs
def _group(s: str, i: int) -> tuple[str, int]:
    """Return the {...} group or single token starting at s[i]."""
    if i < len(s) and s[i] == "{":
        depth, j = 0, i
        while j < len(s):
            depth += {"{": 1, "}": -1}.get(s[j], 0)
            if depth == 0:
                return s[i + 1:j], j + 1
            j += 1
        return s[i + 1:], len(s)
    if i < len(s) and s[i] == "\\":
        m = re.match(r"\\[A-Za-z]+|\\.", s[i:])
        return m.group(0), i + len(m.group(0))
    return s[i:i + 1], i + 1


def math_runs(src: str, vert: str = "", upright: bool = False) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    i = 0
    while i < len(src):
        c = src[i]
        if c in "_^":
            g, i = _group(src, i + 1)
            out += math_runs(g, "subscript" if c == "_" else "superscript", upright)
            continue
        if c == "\\":
            m = re.match(r"\\[A-Za-z]+|\\.", src[i:])
            cmd = m.group(0)
            i += len(cmd)
            if cmd in (r"\text", r"\mathrm", r"\operatorname"):
                g, i = _group(src, i)
                out += math_runs(g, vert, upright=True)
            elif cmd in (r"\boldsymbol", r"\mathbf"):
                g, i = _group(src, i)
                out += [(t, dict(f, bold=True)) for t, f in math_runs(g, vert, upright)]
            elif cmd in (r"\left", r"\right", r"\bigl", r"\bigr", r"\Bigl", r"\Bigr", r"\displaystyle"):
                continue
            else:
                out.append((SYMBOLS.get(cmd, cmd.lstrip("\\")), {"vert": vert}))
            continue
        if c in "{}":
            i += 1
            continue
        j = i
        while j < len(src) and src[j] not in "_^\\{}":
            j += 1
        chunk = src[i:j]
        # letters italic (variables), everything else upright
        for part in re.findall(r"[A-Za-z]+|[^A-Za-z]+", chunk):
            italic = (not upright) and part.isalpha() and len(part) <= 2
            out.append((part, {"vert": vert, "italic": italic}))
        i = j
    return out


# ------------------------------------------------------------------ run / paragraph XML
def run_xml(text: str, *, bold=False, italic=False, mono=False, vert="", size=None, color=None) -> str:
    if not text:
        return ""
    props = []
    if mono:
        props.append(f'<w:rFonts w:ascii="{MONO_FONT}" w:hAnsi="{MONO_FONT}" w:eastAsia="{BODY_FONT}"/>')
    if bold:
        props.append("<w:b/><w:bCs/>")
    if italic:
        props.append("<w:i/><w:iCs/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    if size:
        props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    if vert:
        props.append(f'<w:vertAlign w:val="{vert}"/>')
    rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


INLINE = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\$[^$]+\$|\[[^\]]+\]\([^)]+\))")


def inline_xml(text: str, *, bold=False, size=None, color=None) -> str:
    parts = []
    for tok in INLINE.split(text):
        if not tok:
            continue
        if tok.startswith("**") and tok.endswith("**"):
            parts.append(inline_xml(tok[2:-2], bold=True, size=size, color=color))
        elif tok.startswith("`") and tok.endswith("`"):
            parts.append(run_xml(tok[1:-1], mono=True, bold=bold, size=size, color=color))
        elif tok.startswith("$") and tok.endswith("$") and len(tok) > 2:
            for t, f in math_runs(tok[1:-1]):
                parts.append(run_xml(t, bold=bold or f.get("bold", False), italic=f.get("italic", False),
                                     vert=f.get("vert", ""), size=size, color=color))
        elif tok.startswith("[") and "](" in tok:
            parts.append(run_xml(tok[1:tok.index("](")], bold=bold, size=size, color=color))
        else:
            parts.append(run_xml(tok, bold=bold, size=size, color=color))
    return "".join(parts)


def para(content: str, *, style=None, align=None, ind_left=None, num=None, shade=None, border_left=False,
         keep_next=False, page_break_before=False, spacing=None) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        ppr.append("<w:keepNext/>")
    if page_break_before:
        ppr.append("<w:pageBreakBefore/>")
    if num:
        ppr.append(f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>')
    if border_left:
        ppr.append('<w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="BFBFBF"/></w:pBdr>')
    if shade:
        ppr.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{shade}"/>')
    if spacing:
        ppr.append(spacing)
    if ind_left is not None:
        ppr.append(f'<w:ind w:left="{ind_left}"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(ppr)}</w:pPr>{content}</w:p>"


# ------------------------------------------------------------------ tables
def _vis_len(s: str) -> float:
    s = re.sub(r"\$[^$]+\$", "xx", s)
    s = re.sub(r"[*`]", "", s)
    return sum(2.0 if ord(ch) > 0x2E80 else 1.0 for ch in s)


def table_xml(rows: list[list[str]]) -> str:
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    weight = [max(min(_vis_len(r[c]), 60.0), 4.0) for c in range(ncol) for r in rows[:1]]
    weight = [max(max(min(_vis_len(r[c]), 60.0) for r in rows), 4.0) for c in range(ncol)]
    tot = sum(weight)
    widths = [int(TEXT_W * w / tot) for w in weight]
    widths[-1] += TEXT_W - sum(widths)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    border = ('<w:tblBorders>' + "".join(
        f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="808080"/>'
        for s in ("top", "left", "bottom", "right", "insideH", "insideV")) + "</w:tblBorders>")
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_W}" w:type="dxa"/><w:tblLayout w:type="fixed"/>{border}'
           '<w:tblCellMar><w:left w:w="70" w:type="dxa"/><w:right w:w="70" w:type="dxa"/></w:tblCellMar>'
           f'</w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    for ri, r in enumerate(rows):
        trpr = "<w:trPr><w:tblHeader/><w:cantSplit/></w:trPr>" if ri == 0 else "<w:trPr><w:cantSplit/></w:trPr>"
        cells = []
        for ci, cell in enumerate(r):
            shd = '<w:shd w:val="clear" w:color="auto" w:fill="E8EEF4"/>' if ri == 0 else ""
            p = para(inline_xml(cell.strip(), bold=(ri == 0), size=18),
                     spacing='<w:spacing w:before="20" w:after="20" w:line="260" w:lineRule="auto"/>')
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[ci]}" w:type="dxa"/>{shd}</w:tcPr>{p}</w:tc>')
        out.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out) + para("", spacing='<w:spacing w:before="0" w:after="60"/>')


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, in_math, in_code = [], "", False, False
    for ch in line:
        if ch == "$" and not in_code:
            in_math = not in_math
        if ch == "`" and not in_math:
            in_code = not in_code
        if ch == "|" and not in_math and not in_code:
            cells.append(cur)
            cur = ""
        else:
            cur += ch
    cells.append(cur)
    return [c.strip() for c in cells]


# ------------------------------------------------------------------ images
def png_size(path: Path) -> tuple[int, int]:
    with path.open("rb") as fh:
        head = fh.read(24)
    return struct.unpack(">II", head[16:24])


def image_xml(rid: str, idx: int, name: str, w_px: int, h_px: int) -> str:
    cx = TEXT_W * EMU_PER_TWIP
    cy = int(cx * h_px / w_px)
    return (f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/>'
            f'<wp:docPr id="{idx}" name="{escape(name)}"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:nvPicPr><pic:cNvPr id="{idx}" name="{escape(name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>'
            "</wp:inline></w:drawing></w:r>")


# ------------------------------------------------------------------ document body
class Builder:
    def __init__(self, md_path: Path) -> None:
        self.md_path = md_path
        self.body: list[str] = []
        self.images: list[tuple[str, Path]] = []
        self.nums: list[str] = []            # numbering instances (abstract id per list)

    def new_num(self, ordered: bool) -> int:
        self.nums.append("1" if ordered else "0")
        return len(self.nums)

    def build(self) -> str:
        lines = self.md_path.read_text(encoding="utf-8").splitlines()
        i, first_h1, chapter_seen, toc_done = 0, True, False, False
        list_num: dict[tuple[int, bool], int] = {}
        while i < len(lines):
            ln = lines[i]
            s = ln.strip()
            if not s:
                list_num.clear() if (i + 1 < len(lines) and not re.match(r"\s*([-*]|\d+\.)\s", lines[i + 1])) else None
                i += 1
                continue
            if s.startswith("```"):
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    self.body.append(para(run_xml(lines[i], mono=True, size=18), shade="F2F2F2", ind_left=200,
                                          spacing='<w:spacing w:before="0" w:after="0" w:line="260" w:lineRule="auto"/>'))
                    i += 1
                i += 1
                continue
            if s.startswith("$$"):
                expr = s.strip("$")
                if not s.endswith("$$") or s == "$$":
                    i += 1
                    buf = []
                    while i < len(lines) and not lines[i].strip().startswith("$$"):
                        buf.append(lines[i].strip())
                        i += 1
                    expr = " ".join(buf)
                runs = "".join(run_xml(t, italic=f.get("italic", False), vert=f.get("vert", ""), bold=f.get("bold", False))
                               for t, f in math_runs(expr.replace("\\\\", " ")))
                self.body.append(para(runs, align="center"))
                i += 1
                continue
            m = re.match(r"(#{1,4})\s+(.*)", s)
            if m:
                level, text = len(m.group(1)), m.group(2)
                if level == 1 and first_h1:
                    self.body.append(para(inline_xml(text, bold=True, size=36), align="center",
                                          spacing='<w:spacing w:before="1200" w:after="600"/>'))
                    first_h1 = False
                else:
                    is_chapter = level == 2
                    if is_chapter and not toc_done:
                        self.body.append(para(run_xml("目　录", bold=True, size=32), align="center", page_break_before=True))
                        self.body.append(TOC_FIELD)
                        toc_done = True
                    self.body.append(para(inline_xml(text), style=f"Heading{level - 1 if level > 1 else 1}",
                                          keep_next=True, page_break_before=is_chapter and chapter_seen))
                    chapter_seen = chapter_seen or is_chapter
                i += 1
                continue
            if s == "---":
                i += 1
                continue
            mi = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", s)
            if mi:
                cap, rel = mi.group(1), mi.group(2)
                path = (self.md_path.parent / rel).resolve()
                rid = f"rIdImg{len(self.images) + 1}"
                self.images.append((rid, path))
                w, h = png_size(path)
                self.body.append(para(image_xml(rid, len(self.images), path.name, w, h), align="center", keep_next=True))
                self.body.append(para(inline_xml(cap, size=20), align="center"))
                i += 1
                continue
            if s.startswith("|"):
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    if not re.match(r"^\|?\s*:?-{2,}", lines[i].strip()):
                        rows.append(split_row(lines[i]))
                    i += 1
                self.body.append(table_xml(rows))
                continue
            if s.startswith(">"):
                while i < len(lines) and lines[i].strip().startswith(">"):
                    q = lines[i].strip()[1:].strip()
                    if q:
                        self.body.append(para(inline_xml(q, color="404040", size=20), ind_left=280, border_left=True))
                    i += 1
                continue
            ml = re.match(r"(\s*)([-*]|\d+\.)\s+(.*)", ln)
            if ml:
                depth = min(len(ml.group(1).expandtabs(2)) // 2, 2)
                ordered = ml.group(2)[0].isdigit()
                key = (depth, ordered)
                if key not in list_num:
                    list_num[key] = self.new_num(ordered)
                    for k in [k for k in list_num if k[0] > depth]:
                        del list_num[k]
                text = ml.group(3)
                i += 1
                while i < len(lines) and lines[i].startswith(" " * (len(ml.group(1)) + 3)) and lines[i].strip() \
                        and not re.match(r"\s*([-*]|\d+\.)\s", lines[i]) and not lines[i].strip().startswith(("|", "```", "$$")):
                    text += lines[i].strip()
                    i += 1
                self.body.append(para(inline_xml(text), num=(list_num[key], depth)))
                continue
            # plain paragraph (consecutive non-empty lines joined)
            buf = [s]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"\s*(#|\||>|```|\$\$|!\[|[-*]\s|\d+\.\s|---)", lines[i]):
                buf.append(lines[i].strip())
                i += 1
            self.body.append(para(inline_xml("".join(buf))))
        return "".join(self.body)


TOC_FIELD = ('<w:p><w:r><w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
             '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-2" \\h \\z \\u </w:instrText></w:r>'
             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
             '<w:r><w:rPr><w:color w:val="808080"/></w:rPr><w:t>（打开后若未显示目录：右键此处，选择"更新域"。）</w:t></w:r>'
             '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>')


def styles_xml() -> str:
    def heading(n: int, size: int, before: int) -> str:
        return (f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/>'
                f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="{before}" w:after="120"/>'
                f'<w:outlineLvl w:val="{n - 1}"/></w:pPr><w:rPr><w:rFonts w:ascii="{LATIN_FONT}" w:hAnsi="{LATIN_FONT}" '
                f'w:eastAsia="{HEAD_FONT}"/><w:b/><w:bCs/><w:sz w:val="{size}"/><w:szCs w:val="{size}"/></w:rPr></w:style>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="{LATIN_FONT}" w:hAnsi="{LATIN_FONT}" '
            f'w:eastAsia="{BODY_FONT}" w:cs="{LATIN_FONT}"/><w:sz w:val="21"/><w:szCs w:val="21"/><w:lang w:val="en-US" '
            'w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="100" '
            'w:line="340" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
            + heading(1, 32, 360) + heading(2, 26, 240) + heading(3, 22, 180) +
            '<w:style w:type="paragraph" w:styleId="TOC1"><w:name w:val="toc 1"/><w:basedOn w:val="Normal"/>'
            '<w:pPr><w:spacing w:after="60"/></w:pPr></w:style>'
            '<w:style w:type="paragraph" w:styleId="TOC2"><w:name w:val="toc 2"/><w:basedOn w:val="Normal"/>'
            '<w:pPr><w:spacing w:after="40"/><w:ind w:left="420"/></w:pPr></w:style>'
            '</w:styles>')


def numbering_xml(nums: list[str]) -> str:
    def lvl(i: int, ordered: bool) -> str:
        fmt, text = ("decimal", f"%{i + 1}.") if ordered else ("bullet", ["●", "○", "▪"][i])
        return (f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{420 * (i + 1)}" w:hanging="300"/></w:pPr>'
                + ("" if ordered else '<w:rPr><w:sz w:val="14"/></w:rPr>') + "</w:lvl>")
    abstract = "".join(f'<w:abstractNum w:abstractNumId="{a}"><w:multiLevelType w:val="hybridMultilevel"/>'
                       + "".join(lvl(i, a == 1) for i in range(3)) + "</w:abstractNum>" for a in (0, 1))
    inst = "".join(f'<w:num w:numId="{k + 1}"><w:abstractNumId w:val="{a}"/>'
                   '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
                   '<w:lvlOverride w:ilvl="1"><w:startOverride w:val="1"/></w:lvlOverride></w:num>'
                   for k, a in enumerate(nums))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">{abstract}{inst}</w:numbering>')


def write_docx(md: Path, out: Path) -> None:
    b = Builder(md)
    body = b.build()
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
          'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
          'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
          'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
    sect = (f'<w:sectPr><w:footerReference w:type="default" r:id="rIdFooter"/><w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="708" '
            'w:footer="708" w:gutter="0"/></w:sectPr>')
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>{body}{sect}</w:body></w:document>'
    footer = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>'
              '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
              '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>1</w:t></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>'
              '</w:p></w:ftr>')
    rels = ['<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
            '<Relationship Id="rIdNum" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>',
            '<Relationship Id="rIdSettings" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>',
            '<Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>']
    rels += [f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
             f'Target="media/image{k + 1}.png"/>' for k, (rid, _) in enumerate(b.images)]
    settings = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:updateFields w:val="true"/></w:settings>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/>'
              '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
              '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
              '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
              '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
              '<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
              '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                 '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                 '</Relationships>')
    title = escape(md.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip())
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>' + title + '</dc:title>'
            '<dc:creator>徐鹤岩</dc:creator></cp:coreProperties>')
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles_xml())
        z.writestr("word/numbering.xml", numbering_xml(b.nums))
        z.writestr("word/settings.xml", settings)
        z.writestr("word/footer1.xml", footer)
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(rels) + "</Relationships>")
        for k, (_, path) in enumerate(b.images):
            z.write(path, f"word/media/image{k + 1}.png")
    print(f"written {out} ({len(b.images)} images, {len(b.nums)} lists)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("markdown")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    write_docx(Path(a.markdown), Path(a.out))


if __name__ == "__main__":
    main()
