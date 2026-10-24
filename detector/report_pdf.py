"""Writing report: cover, overview, then the original pages with marks."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
FONT_FILE = ROOT / "static" / "fonts" / "JosefinSans-Regular.ttf"
FONT_MEDIUM = ROOT / "static" / "fonts" / "JosefinSans-Medium.ttf"
FONT_LIGHT = ROOT / "static" / "fonts" / "JosefinSans-ExtraLight.ttf"

WHITE = (1, 1, 1)
INK = (0.10, 0.12, 0.14)
MUTED = (0.22, 0.26, 0.30)
RULE = (0.86, 0.88, 0.90)
BLUE = (0 / 255, 87 / 255, 184 / 255)
CYAN = (184 / 255, 232 / 255, 240 / 255)
PURPLE = (214 / 255, 196 / 255, 240 / 255)
BOX = (0.96, 0.97, 0.98)
CAUTION = (0.90, 0.96, 0.99)
HEADER_H = 46
FOOTER_H = 40


def _page_lines(page) -> list[dict]:
    rows = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            x0, y0, _x1, y1 = line["bbox"]
            size = max((span.get("size") or 12 for span in line.get("spans", [])), default=12)
            rows.append({"text": text, "x0": x0, "y0": y0, "y1": y1, "size": size})
    rows.sort(key=lambda row: (row["y0"], row["x0"]))
    return rows


def _join_wrapped(left: str, right: str) -> str:
    if left.endswith("-") and right[:1].islower():
        return f"{left[:-1]}{right}"
    return f"{left} {right}"


def page_paragraphs(page) -> str:
    """Join wrapped print lines back into paragraphs. A line break is not a new sentence."""
    rows = _page_lines(page)
    if not rows:
        return ""
    paragraphs = [rows[0]["text"]]
    previous = rows[0]
    for row in rows[1:]:
        gap = row["y0"] - previous["y1"]
        same_size = abs(row["size"] - previous["size"]) < 1.5
        wrapped = same_size and 0 <= gap <= max(previous["size"], 12) * 0.9
        if wrapped:
            paragraphs[-1] = _join_wrapped(paragraphs[-1], row["text"])
        else:
            paragraphs.append(row["text"])
        previous = row
    return "\n".join(paragraph.strip() for paragraph in paragraphs if paragraph.strip())


def pdf_text(raw: bytes) -> str:
    document = fitz.open(stream=raw, filetype="pdf")
    try:
        return "\n".join(page_paragraphs(page) for page in document).strip()
    finally:
        document.close()


def docx_to_pdf(raw: bytes) -> bytes:
    """Convert a Word file to PDF while keeping its page layout for the review."""
    from detector.docx_pdf import docx_to_pdf as _convert

    return _convert(raw)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _hits(page, sentence: str) -> list:
    target = [part for part in _clean(sentence).split() if part]
    if len(target) < 3:
        return []
    tokens = []
    for word in page.get_text("words"):
        cleaned = _clean(str(word[4]))
        if cleaned:
            tokens.append((word[0], word[1], word[2], word[3], cleaned.casefold()))
    wanted = [part.casefold() for part in target]
    rects = []
    index = 0
    while index < len(tokens):
        if tokens[index][4] != wanted[0]:
            index += 1
            continue
        matched = []
        cursor = index
        found = True
        for piece in wanted:
            if cursor >= len(tokens) or tokens[cursor][4] != piece:
                found = False
                break
            matched.append(fitz.Rect(tokens[cursor][0], tokens[cursor][1], tokens[cursor][2], tokens[cursor][3]))
            cursor += 1
        if not found:
            index += 1
            continue
        line = matched[0]
        for rect in matched[1:]:
            if abs(rect.y0 - line.y0) < 4:
                line |= rect
            else:
                rects.append(line)
                line = rect
        rects.append(line)
        index = cursor
    return rects


def _font():
    # ExtraLight (~200) for cover/overview; fall back toward Regular.
    for path in (FONT_LIGHT, FONT_FILE, FONT_MEDIUM):
        if path.exists():
            try:
                return fitz.Font(fontfile=str(path)), "josefin"
            except Exception:
                continue
    return fitz.Font("helv"), "helv"


def _use_font(page, fontname: str) -> None:
    if fontname != "josefin":
        return
    path = FONT_LIGHT if FONT_LIGHT.exists() else FONT_FILE if FONT_FILE.exists() else FONT_MEDIUM
    if path and path.exists():
        page.insert_font(fontname="josefin", fontfile=str(path))


def _width(fontobj, text: str, size: float) -> float:
    return fontobj.text_length(text, fontsize=size)


def _wrap(text: str, fontobj, size: float, width: float) -> list[str]:
    words = _clean(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if _width(fontobj, trial, size) <= width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _put(page, point, text, fontsize, fontname, color, heavy=False) -> None:
    page.insert_text(point, text, fontsize=fontsize, fontname=fontname, color=color)


def _write(page, fontname, fontobj, text, x, y, width, size, color, leading=None, heavy=False) -> float:
    step = leading or (size + 4)
    for line in _wrap(text, fontobj, size, width):
        _put(page, (x, y), line, size, fontname, color, heavy)
        y += step
    return y


def _leaf(page, x, y, size=12) -> None:
    def point(px, py):
        return fitz.Point(x + size * px / 32, y + size * py / 32)

    shape = page.new_shape()
    shape.draw_bezier(point(16, 2), point(22, 8), point(27, 15), point(24.5, 22.5))
    shape.draw_bezier(point(24.5, 22.5), point(23, 27), point(19.2, 29), point(16, 30.2))
    shape.draw_bezier(point(16, 30.2), point(12.8, 29), point(9, 27), point(7.5, 22.5))
    shape.draw_bezier(point(7.5, 22.5), point(5, 15), point(10, 8), point(16, 2))
    shape.finish(color=BLUE, fill=BLUE, closePath=True, width=0.2)
    shape.draw_bezier(point(16, 26.5), point(16.2, 18), point(17.4, 12), point(21.5, 6.5))
    shape.finish(color=(0.957, 0.969, 0.976), width=max(0.4, size * 0.04))
    shape.commit()


def _bar(page, width, height, fontname, fontobj, number: int, total: int, kind: str, filename: str, top: bool, heavy=False) -> None:
    if top:
        y_text = 28
        page.draw_rect(fitz.Rect(0, HEADER_H - 0.7, width, HEADER_H), color=None, fill=RULE)
        _put(page, (16, y_text), "Fly", 13, fontname, BLUE, heavy)
        _leaf(page, 16 + _width(fontobj, "Fly", 13) + 4, y_text - 12, 13)
    else:
        y_text = height - 16
        page.draw_rect(fitz.Rect(0, height - FOOTER_H, width, height - FOOTER_H + 0.7), color=None, fill=RULE)
        _put(page, (16, y_text), "Fly", 11, fontname, BLUE, heavy)
        _leaf(page, 16 + _width(fontobj, "Fly", 11) + 3, y_text - 10, 11)
    label = f"Page {number} of {total} - {kind}"
    label_w = _width(fontobj, label, 9)
    page.insert_text(((width - label_w) / 2, y_text if not top else 28), label, fontsize=9, fontname=fontname, color=MUTED)
    shown = filename
    while shown and _width(fontobj, shown, 9) > 160:
        shown = shown[:-1]
    if shown != filename and len(shown) > 1:
        shown = shown[:-1] + "."
    page.insert_text((width - 16 - _width(fontobj, shown, 9), y_text if not top else 28), shown, fontsize=9, fontname=fontname, color=MUTED)


def _cover(page, width, fontname, fontobj, result: dict, filename: str, file_size: int, total: int) -> None:
    _use_font(page, fontname)
    _bar(page, width, page.rect.height, fontname, fontobj, 1, total, "Cover Page", filename, True, heavy=True)
    _bar(page, width, page.rect.height, fontname, fontobj, 1, total, "Cover Page", filename, False, heavy=True)
    title = Path(filename).stem.replace("_", " ") or "Draft"
    ai_only = int(result.get("flagged_percent") or 0)
    unsure = int(result.get("uncertain_percent") or 0)
    y = 118
    y = _write(page, fontname, fontobj, title, 48, y, width - 96, 28, INK, leading=32, heavy=True)
    y += 4
    _put(page, (48, y), "AI writing report", 14, fontname, BLUE, heavy=True)
    y += 28
    score_box = fitz.Rect(48, y, 220, y + 78)
    page.draw_rect(score_box, color=None, fill=CAUTION)
    _put(page, (score_box.x0 + 14, score_box.y0 + 28), f"{ai_only}%", 28, fontname, BLUE, heavy=True)
    _put(page, (score_box.x0 + 14, score_box.y0 + 48), "AI-like share", 11, fontname, INK, heavy=True)
    _put(page, (score_box.x1 + 18, score_box.y0 + 28), f"{unsure}% inconclusive", 12, fontname, INK, heavy=True)
    _put(page, (score_box.x1 + 18, score_box.y0 + 48), "Kept separate from the headline", 10, fontname, MUTED, heavy=True)
    y = score_box.y1 + 28
    _put(page, (48, y), "Document details", 12, fontname, INK, heavy=True)
    y += 20
    when = datetime.now().strftime("%b %d, %Y, %I:%M %p")
    size_mb = file_size / (1024 * 1024)
    size_label = f"{size_mb:.1f} MB" if size_mb >= 0.1 else f"{max(file_size, 1) / 1024:.0f} KB"
    rows = (
        ("File name", filename),
        ("Reviewed", when),
        ("File size", size_label),
        ("Words scored", f"{int(result.get('scored_words') or 0):,}"),
        ("Confidence", str(result.get("confidence") or "medium").title()),
    )
    for label, value in rows:
        _put(page, (48, y), label, 9, fontname, MUTED, heavy=True)
        y += 13
        y = _write(page, fontname, fontobj, str(value), 48, y, 250, 11, INK, leading=14, heavy=True)
        y += 8
    box = fitz.Rect(width - 230, 250, width - 48, 430)
    page.draw_rect(box, color=None, fill=BOX)
    page.draw_rect(fitz.Rect(box.x0, box.y0, box.x0 + 4, box.y1), color=None, fill=BLUE)
    facts = (
        (f"{int(result.get('source_pages') or 0)}", "Pages in the draft"),
        (f"{int(result.get('word_count') or 0):,}", "Words"),
        (f"{int(result.get('character_count') or 0):,}", "Characters"),
        (f"{total}", "Pages in this report"),
    )
    fy = 278
    for value, label in facts:
        _put(page, (box.x0 + 18, fy), value, 16, fontname, INK, heavy=True)
        _put(page, (box.x0 + 18, fy + 16), label, 10, fontname, MUTED, heavy=True)
        fy += 34
    note_y = max(y, box.y1) + 24
    _put(page, (48, note_y), "How to use this file", 12, fontname, INK, heavy=True)
    _write(
        page,
        fontname,
        fontobj,
        "The cover gives the headline. The next page explains the groups. Later pages keep your original text with cyan marks for AI-like lines and purple marks for inconclusive lines. A percentage is a reason to reread, not a finding of misconduct.",
        48,
        note_y + 18,
        width - 96,
        11,
        INK,
        leading=15,
        heavy=True,
    )


def _overview(page, width, fontname, fontobj, result: dict, filename: str, total: int) -> None:
    _use_font(page, fontname)
    height = page.rect.height
    _bar(page, width, height, fontname, fontobj, 2, total, "AI Writing Overview", filename, True, heavy=True)
    _bar(page, width, height, fontname, fontobj, 2, total, "AI Writing Overview", filename, False, heavy=True)
    ai_only = int(result.get("flagged_percent") or 0)
    unsure = int(result.get("uncertain_percent") or 0)
    x = 48
    y = 78
    content_w = width - 96
    score = f"{ai_only}%"
    _put(page, (x, y), score, 32, fontname, BLUE, heavy=True)
    _put(page, (x + _width(fontobj, score, 32) + 8, y), "AI-like", 18, fontname, BLUE, heavy=True)
    y += 22
    y = _write(
        page,
        fontname,
        fontobj,
        "The headline is only passages classified as AI-like. Inconclusive passages are listed separately and are not added into that number.",
        x,
        y,
        content_w * 0.62,
        11,
        INK,
        leading=15,
        heavy=True,
    )
    box = fitz.Rect(x + content_w * 0.66, 70, width - 40, 168)
    page.draw_rect(box, color=None, fill=CAUTION)
    _put(page, (box.x0 + 12, box.y0 + 20), "Caution: Review required.", 11, fontname, BLUE, heavy=True)
    _write(
        page,
        fontname,
        fontobj,
        "A percentage is a reason to reread a passage. It is not a finding of misconduct and it does not grade the work.",
        box.x0 + 12,
        box.y0 + 38,
        box.width - 24,
        10,
        INK,
        leading=13,
        heavy=True,
    )
    y = max(y + 18, 196)
    _put(page, (x, y), "Detection groups", 15, fontname, INK, heavy=True)
    y += 26
    groups = (
        (CYAN, "AI-generated only", ai_only, "Passages read as likely written by a language model."),
        (PURPLE, "Uncertain", unsure, "Passages between a human reading and an AI reading."),
    )
    for fill, name, percent, meaning in groups:
        page.draw_rect(fitz.Rect(x, y - 10, x + 12, y + 2), color=None, fill=fill)
        _put(page, (x + 20, y), name, 12, fontname, INK, heavy=True)
        percent_label = f"{percent}%"
        _put(page, (width - 48 - _width(fontobj, percent_label, 12), y), percent_label, 12, fontname, BLUE, heavy=True)
        y += 16
        y = _write(page, fontname, fontobj, meaning, x + 20, y, content_w - 20, 11, INK, leading=14, heavy=True)
        y += 12
    y += 6
    _put(page, (x, y), "Disclaimer", 13, fontname, INK, heavy=True)
    y += 16
    y = _write(
        page,
        fontname,
        fontobj,
        "This reading can miss AI text and can mark human text. It should not be the only basis for a decision about a student's work. It takes a person, and the rules of their school, to decide whether misconduct occurred.",
        x,
        y,
        content_w,
        11,
        INK,
        leading=14,
        heavy=True,
    )
    y += 14
    _put(page, (x, y), "How to read the marks", 13, fontname, INK, heavy=True)
    y += 16
    _write(
        page,
        fontname,
        fontobj,
        "Every extracted word is included. Cyan marks a passage read as AI-like. Purple marks a passage the model could not place. A different detector can still disagree. Prepared as a free portfolio project by Tanui Kipngetich Sila.",
        x,
        y,
        content_w,
        11,
        INK,
        leading=14,
        heavy=True,
    )


def build_reviewed_pdf(raw: bytes, result: dict, filename: str, file_size: int = 0) -> bytes:
    source = fitz.open(stream=raw, filetype="pdf")
    marked = [item for item in result.get("sentences", []) if item.get("label") in {"ai", "uncertain"}]
    try:
        for page in source:
            grouped: dict[str, list] = {"ai": [], "uncertain": []}
            for item in marked:
                grouped[item["label"]].extend(_hits(page, item["text"]))
            for label, rects in grouped.items():
                if not rects:
                    continue
                annot = page.add_highlight_annot(rects)
                annot.set_colors(stroke=CYAN if label == "ai" else PURPLE)
                annot.update()
        source.bake(annots=True)

        output = fitz.open()
        fontobj, fontname = _font()
        sample = source[0].rect if source.page_count else fitz.Rect(0, 0, 612, 792)
        width = sample.width
        height = sample.height
        title = _clean(filename)[:80] or "Draft"
        total = source.page_count + 2
        result = dict(result)
        result["source_pages"] = source.page_count

        cover = output.new_page(width=width, height=height)
        _cover(cover, width, fontname, fontobj, result, title, file_size or len(raw), total)
        overview = output.new_page(width=width, height=height)
        _overview(overview, width, fontname, fontobj, result, title, total)

        for index in range(source.page_count):
            page = source[index]
            new = output.new_page(width=width, height=height)
            _use_font(new, fontname)
            _bar(new, width, height, fontname, fontobj, index + 3, total, "AI Writing Submission", title, True)
            _bar(new, width, height, fontname, fontobj, index + 3, total, "AI Writing Submission", title, False)
            avail = fitz.Rect(10, HEADER_H + 2, width - 10, height - FOOTER_H - 2)
            # Never enlarge the submission page — that made Word fonts look oversized.
            scale = min(1.0, avail.width / page.rect.width, avail.height / page.rect.height)
            draw_w = page.rect.width * scale
            draw_h = page.rect.height * scale
            x0 = avail.x0 + (avail.width - draw_w) / 2
            y0 = avail.y0
            new.show_pdf_page(fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h), source, index)

        output.set_metadata(
            {
                "title": f"Flyleaf review: {title}",
                "author": "Tanui Kipngetich Sila",
                "subject": "AI writing report",
            }
        )
        data = output.tobytes()
        output.close()
        return data
    finally:
        source.close()


def build_text_reviewed_pdf(text: str, result: dict, filename: str, file_size: int = 0) -> bytes:
    """Build the same AI report for .docx / .txt uploads (cover, overview, marked draft)."""
    fontobj, fontname = _font()
    width, height = 595, 842
    title = _clean(filename)[:80] or "Draft"
    body = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    payload = dict(result)
    payload.setdefault("character_count", len(body))
    payload.setdefault("word_count", len(re.findall(r"\b[\w']+\b", body)))

    output = fitz.open()
    output.new_page(width=width, height=height)  # cover
    output.new_page(width=width, height=height)  # overview
    body_start = output.page_count
    _layout_marked_text(output, width, height, fontname, fontobj, body, result, body_start)

    total = output.page_count
    payload["source_pages"] = max(0, total - 2)
    # Draw after bake so page handles stay valid.
    _cover(output[0], width, fontname, fontobj, payload, title, file_size or len(body.encode("utf-8")), total)
    _overview(output[1], width, fontname, fontobj, payload, title, total)

    for index in range(body_start, total):
        page = output[index]
        _use_font(page, fontname)
        _bar(page, width, height, fontname, fontobj, index + 1, total, "AI Writing Submission", title, True, heavy=True)
        _bar(page, width, height, fontname, fontobj, index + 1, total, "AI Writing Submission", title, False, heavy=True)

    output.set_metadata(
        {
            "title": f"Flyleaf review: {title}",
            "author": "Tanui Kipngetich Sila",
            "subject": "AI writing report",
        }
    )
    data = output.tobytes()
    output.close()
    return data


def _layout_marked_text(
    output,
    width,
    height,
    fontname,
    fontobj,
    text: str,
    result: dict,
    body_start: int,
) -> None:
    size = 11
    leading = 15
    left = 48
    right = width - 48
    top = HEADER_H + 28
    bottom = height - FOOTER_H - 20
    content_w = right - left

    page = output.new_page(width=width, height=height)
    _use_font(page, fontname)
    y = top

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()] if text else []
    if text and not paragraphs:
        paragraphs = [text]
    if not paragraphs:
        _put(page, (left, y), "No draft text was available to print.", size, fontname, INK, heavy=True)

    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            continue
        line = ""
        for word in words:
            trial = word if not line else f"{line} {word}"
            if _width(fontobj, trial, size) <= content_w:
                line = trial
                continue
            if y + leading > bottom:
                page = output.new_page(width=width, height=height)
                _use_font(page, fontname)
                y = top
            if line:
                _put(page, (left, y), line, size, fontname, INK, heavy=True)
                y += leading
            line = word
        if line:
            if y + leading > bottom:
                page = output.new_page(width=width, height=height)
                _use_font(page, fontname)
                y = top
            _put(page, (left, y), line, size, fontname, INK, heavy=True)
            y += leading
        y += 10

    marked = [item for item in result.get("sentences", []) if item.get("label") in {"ai", "uncertain"}]
    for page_index in range(body_start, output.page_count):
        page = output[page_index]
        for item in marked:
            excerpt = _clean(str(item.get("text") or ""))
            if len(excerpt.split()) < 3:
                continue
            probes = [excerpt]
            words = excerpt.split()
            if len(words) > 18:
                probes.append(" ".join(words[:18]))
                probes.append(" ".join(words[len(words) // 2 : len(words) // 2 + 18]))
            stroke = CYAN if item.get("label") == "ai" else PURPLE
            for probe in probes:
                rects = page.search_for(probe, quads=False)
                if not rects and len(probe.split()) > 8:
                    rects = page.search_for(" ".join(probe.split()[:8]), quads=False)
                if not rects:
                    continue
                annot = page.add_highlight_annot(rects)
                annot.set_colors(stroke=stroke)
                annot.update()
                break
    output.bake(annots=True)


def write_preview_images(pdf: bytes, folder: Path) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    document = fitz.open(stream=pdf, filetype="pdf")
    try:
        for index, page in enumerate(document, start=1):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.45, 1.45), alpha=False)
            pixmap.save(folder / f"{index}.png")
        return document.page_count
    finally:
        document.close()
