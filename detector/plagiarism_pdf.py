"""PDF report for a public-web similarity check.

Layout follows the same spirit as a submission report: cover, source overview,
then the full draft with matched passages highlighted. Flyleaf branding only;
no commercial logos or fake database buckets.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import fitz

from detector.report_pdf import (
    BLUE,
    BOX,
    CAUTION,
    FOOTER_H,
    HEADER_H,
    INK,
    MUTED,
    _bar,
    _clean,
    _font,
    _hits,
    _put,
    _use_font,
    _width,
    _write,
)

ROOT = Path(__file__).resolve().parent.parent
HIGHLIGHT = (1.0, 0.92, 0.55)
SOURCE_COLORS = (
    (184 / 255, 232 / 255, 240 / 255),  # cyan
    (1.0, 0.92, 0.55),  # amber
    (214 / 255, 196 / 255, 240 / 255),  # purple
    (0.85, 0.93, 0.78),  # green
    (1.0, 0.86, 0.78),  # peach
)


def build_similarity_pdf(
    result: dict,
    filename: str = "draft.txt",
    draft_text: str = "",
    pdf_bytes: bytes | None = None,
) -> bytes:
    fontobj, fontname = _font()
    sources = list(result.get("sources") or [])
    matches = list(result.get("matches") or [])
    text = _clean_blocks(draft_text or "")
    title = _clean(filename)[:80] or "Draft"

    if pdf_bytes:
        return _build_from_pdf(pdf_bytes, result, title, filename, sources, matches, fontname, fontobj)

    width, height = 595, 842
    output = fitz.open()

    cover = output.new_page(width=width, height=height)
    _cover(cover, width, height, fontname, fontobj, result, filename)

    overview = output.new_page(width=width, height=height)
    _overview(overview, width, height, fontname, fontobj, result, filename, sources)

    if matches:
        detail = output.new_page(width=width, height=height)
        _match_list(detail, width, height, fontname, fontobj, matches, sources)

    body_start = output.page_count
    if text:
        _write_highlighted_body(output, width, height, fontname, fontobj, text, matches, sources, body_start)
    else:
        empty = output.new_page(width=width, height=height)
        _empty_body(empty, width, height, fontname, fontobj, result)

    total = output.page_count
    match_list_page = 3 if matches else None
    for index, page in enumerate(output, start=1):
        if index == 1:
            kind = "Cover"
        elif index == 2:
            kind = "Overview"
        elif match_list_page and index == match_list_page:
            kind = "Match List"
        else:
            kind = "Submission"
        _bar(page, width, height, fontname, fontobj, index, total, kind, filename, True, heavy=True)
        _bar(page, width, height, fontname, fontobj, index, total, kind, filename, False, heavy=True)

    output.set_metadata(
        {
            "title": f"Flyleaf similarity: {title}",
            "author": "Tanui Kipngetich Sila",
            "subject": "Public web similarity report",
        }
    )
    data = output.tobytes()
    output.close()
    return data


def _build_from_pdf(raw: bytes, result: dict, title: str, filename: str, sources, matches, fontname, fontobj) -> bytes:
    source = fitz.open(stream=raw, filetype="pdf")
    try:
        color_map = _source_color_map(sources)
        for page in source:
            for item in matches:
                excerpt = _clean(str(item.get("draft_excerpt") or ""))
                if len(excerpt.split()) < 4:
                    continue
                rects = _hits(page, excerpt)
                if not rects and len(excerpt) > 80:
                    rects = _hits(page, " ".join(excerpt.split()[:18]))
                if not rects:
                    continue
                annot = page.add_highlight_annot(rects)
                annot.set_colors(stroke=color_map.get(item.get("url"), HIGHLIGHT))
                annot.update()
        source.bake(annots=True)

        sample = source[0].rect if source.page_count else fitz.Rect(0, 0, 612, 792)
        width, height = sample.width, sample.height
        output = fitz.open()
        total = source.page_count + (3 if matches else 2)

        cover = output.new_page(width=width, height=height)
        _cover(cover, width, height, fontname, fontobj, result, filename)
        overview = output.new_page(width=width, height=height)
        _overview(overview, width, height, fontname, fontobj, result, filename, sources)
        if matches:
            detail = output.new_page(width=width, height=height)
            _match_list(detail, width, height, fontname, fontobj, matches, sources)

        for index in range(source.page_count):
            page = source[index]
            new = output.new_page(width=width, height=height)
            _use_font(new, fontname)
            kind = "Submission"
            number = index + (4 if matches else 3)
            _bar(new, width, height, fontname, fontobj, number, total, kind, filename, True, heavy=True)
            _bar(new, width, height, fontname, fontobj, number, total, kind, filename, False, heavy=True)
            avail = fitz.Rect(18, HEADER_H + 6, width - 18, height - FOOTER_H - 6)
            scale = min(avail.width / page.rect.width, avail.height / page.rect.height)
            draw_w = page.rect.width * scale
            draw_h = page.rect.height * scale
            x0 = avail.x0 + (avail.width - draw_w) / 2
            y0 = avail.y0 + (avail.height - draw_h) / 2
            new.show_pdf_page(fitz.Rect(x0, y0, x0 + draw_w, y0 + draw_h), source, index)

        # Header bars on front matter
        for index, page in enumerate(output, start=1):
            if index > (3 if matches else 2):
                break
            kind = "Cover" if index == 1 else "Overview" if index == 2 else "Match List"
            _bar(page, width, height, fontname, fontobj, index, total, kind, filename, True, heavy=True)
            _bar(page, width, height, fontname, fontobj, index, total, kind, filename, False, heavy=True)

        output.set_metadata(
            {
                "title": f"Flyleaf similarity: {title}",
                "author": "Tanui Kipngetich Sila",
                "subject": "Public web similarity report",
            }
        )
        data = output.tobytes()
        output.close()
        return data
    finally:
        source.close()


def _clean_blocks(text: str) -> str:
    lines = []
    for raw in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        piece = _clean(raw)
        if piece:
            lines.append(piece)
    return "\n\n".join(lines)


def _source_color_map(sources: list[dict]) -> dict:
    mapping = {}
    for index, source in enumerate(sources):
        url = source.get("url")
        if url:
            mapping[url] = SOURCE_COLORS[index % len(SOURCE_COLORS)]
    return mapping


def _cover(page, width, height, fontname, fontobj, result, filename) -> None:
    _use_font(page, fontname)
    title = Path(filename).stem.replace("_", " ") or "Draft"
    y = 120
    y = _write(page, fontname, fontobj, title, 48, y, width - 96, 24, INK, leading=28, heavy=True)
    y += 8
    _put(page, (48, y), "Public web similarity report", 14, fontname, MUTED, heavy=True)
    y += 40
    score = f"{int(result.get('overall_percent') or 0)}%"
    _put(page, (48, y), score, 36, fontname, BLUE, heavy=True)
    _put(page, (48 + _width(fontobj, score, 36) + 10, y + 12), "Overall Similarity", 14, fontname, BLUE, heavy=True)
    y += 48
    y = _write(
        page,
        fontname,
        fontobj,
        "The combined share of the draft that matched public web pages found for this check. "
        "Overlapping matches are counted once.",
        48,
        y,
        width - 96,
        11,
        INK,
        leading=15,
        heavy=True,
    )
    y += 18
    box = fitz.Rect(48, y, width - 48, y + 78)
    page.draw_rect(box, color=None, fill=CAUTION)
    _write(
        page,
        fontname,
        fontobj,
        result.get("disclaimer")
        or "This estimate comes from public web pages found for this draft. It is not a finding of misconduct.",
        60,
        y + 28,
        width - 120,
        11,
        INK,
        leading=15,
        heavy=True,
    )
    y = box.y1 + 28
    when = datetime.now().strftime("%b %d, %Y, %I:%M %p")
    rows = (
        ("File name", filename),
        ("Reviewed", when),
        ("Words in draft", f"{int(result.get('word_count') or 0):,}"),
        ("Sources matched", str(int(result.get("source_count") or 0))),
        ("Matched excerpts", str(len(result.get("matches") or []))),
    )
    for label, value in rows:
        _put(page, (48, y), label, 9, fontname, MUTED, heavy=True)
        y += 14
        y = _write(page, fontname, fontobj, str(value), 48, y, 320, 11, INK, leading=14, heavy=True)
        y += 8


def _overview(page, width, height, fontname, fontobj, result, filename, sources) -> None:
    _use_font(page, fontname)
    y = 78
    _put(page, (48, y), "Top Sources", 16, fontname, INK, heavy=True)
    y += 22
    y = _write(
        page,
        fontname,
        fontobj,
        "Public pages with the highest matched share of the draft. Only pages reached for this check are listed.",
        48,
        y,
        width - 96,
        10,
        MUTED,
        leading=14,
        heavy=True,
    )
    y += 18
    if not sources:
        box = fitz.Rect(48, y, width - 48, y + 70)
        page.draw_rect(box, color=None, fill=CAUTION)
        _write(
            page,
            fontname,
            fontobj,
            "No public sources were matched. The overall percentage is 0%.",
            60,
            y + 28,
            width - 120,
            11,
            INK,
            leading=15,
            heavy=True,
        )
        return

    for index, source in enumerate(sources[:15], start=1):
        if y > height - 90:
            break
        share = f"{int(source.get('share') or 0)}%"
        host = str(source.get("host") or source.get("url") or "")
        title = str(source.get("title") or host)
        fill = SOURCE_COLORS[(index - 1) % len(SOURCE_COLORS)]
        page.draw_rect(fitz.Rect(48, y - 4, width - 48, y + 50), color=None, fill=BOX)
        page.draw_rect(fitz.Rect(48, y - 4, 56, y + 50), color=None, fill=fill)
        _put(page, (66, y + 14), f"{index}.", 11, fontname, MUTED, heavy=True)
        _put(page, (width - 48 - _width(fontobj, share, 14) - 12, y + 16), share, 14, fontname, BLUE, heavy=True)
        y = _write(page, fontname, fontobj, title[:90], 92, y + 12, width - 210, 11, INK, leading=14, heavy=True)
        y = _write(page, fontname, fontobj, host[:90], 92, y + 2, width - 210, 9, MUTED, leading=12, heavy=True)
        y += 18


def _match_list(page, width, height, fontname, fontobj, matches, sources) -> None:
    _use_font(page, fontname)
    y = 78
    _put(page, (48, y), "Matched excerpts", 16, fontname, INK, heavy=True)
    y += 20
    y = _write(
        page,
        fontname,
        fontobj,
        "Highlighted passages also appear in the submission pages that follow.",
        48,
        y,
        width - 96,
        10,
        MUTED,
        leading=13,
        heavy=True,
    )
    y += 14
    colors = _source_color_map(sources)
    for index, match in enumerate(matches[:8], start=1):
        if y > height - 140:
            break
        score = f"{round(100 * float(match.get('score') or 0))}%"
        title = str(match.get("title") or match.get("url") or "Source")
        fill = colors.get(match.get("url"), HIGHLIGHT)
        page.draw_rect(fitz.Rect(48, y - 4, width - 48, y + 108), color=None, fill=BOX)
        page.draw_rect(fitz.Rect(48, y - 4, 56, y + 108), color=None, fill=fill)
        _put(page, (66, y + 12), f"Match {index}", 10, fontname, MUTED, heavy=True)
        _put(page, (width - 48 - _width(fontobj, score, 12) - 12, y + 12), score, 12, fontname, BLUE, heavy=True)
        y = _write(page, fontname, fontobj, title[:100], 66, y + 28, width - 140, 10, INK, leading=13, heavy=True)
        y = _write(
            page,
            fontname,
            fontobj,
            "Draft: " + str(match.get("draft_excerpt") or "")[:240],
            66,
            y + 4,
            width - 130,
            9,
            INK,
            leading=12,
            heavy=True,
        )
        y = _write(
            page,
            fontname,
            fontobj,
            "Source: " + str(match.get("source_excerpt") or "")[:240],
            66,
            y + 2,
            width - 130,
            9,
            MUTED,
            leading=12,
            heavy=True,
        )
        y += 20


def _empty_body(page, width, height, fontname, fontobj, result) -> None:
    _use_font(page, fontname)
    y = 100
    _put(page, (48, y), "Submission", 16, fontname, INK, heavy=True)
    y += 28
    note = "No draft text was available to print."
    warnings = result.get("warnings") or []
    if warnings:
        note = warnings[0]
    _write(page, fontname, fontobj, note, 48, y, width - 96, 11, INK, leading=15, heavy=True)


def _write_highlighted_body(output, width, height, fontname, fontobj, text, matches, sources, body_start: int) -> None:
    """Lay out the full draft, then highlight matched excerpts on those pages."""
    size = 11
    leading = 15
    left = 48
    right = width - 48
    top = HEADER_H + 28
    bottom = height - FOOTER_H - 20
    content_w = right - left

    page = output.new_page(width=width, height=height)
    _use_font(page, fontname)
    _put(page, (left, top - 8), "Submission · matched text is highlighted", 10, fontname, MUTED, heavy=True)
    y = top + 10

    paragraphs = text.split("\n\n") if text else []
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

    colors = _source_color_map(sources)
    for page_index in range(body_start, output.page_count):
        page = output[page_index]
        for item in matches:
            excerpt = _clean(str(item.get("draft_excerpt") or ""))
            if len(excerpt.split()) < 4:
                continue
            probes = [excerpt]
            words = excerpt.split()
            if len(words) > 16:
                probes.append(" ".join(words[:16]))
                probes.append(" ".join(words[len(words) // 2 : len(words) // 2 + 16]))
            stroke = colors.get(item.get("url"), HIGHLIGHT)
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
