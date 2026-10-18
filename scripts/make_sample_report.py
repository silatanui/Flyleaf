"""Build richer homepage sample-report preview images from the real PDF builder."""

from __future__ import annotations

from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "images"

PARAGRAPHS = [
    (
        "I missed the 6:40 daladala and ended up walking from Mwenge with a torn umbrella. "
        "The rain was not even heavy, just steady enough to soak my socks before I reached "
        "the bus stop near the university gate. By the time I sat down in the lecture hall, "
        "the first slide was already gone and my notebook still smelled like wet paper."
    ),
    (
        "Artificial intelligence has transformed the landscape of academic writing in recent "
        "years, creating both opportunities and challenges for students and educators alike. "
        "Language models can draft outlines, rephrase dense passages, and suggest citations "
        "within seconds, which changes how a first draft begins. Institutions now face a "
        "difficult question: how to encourage useful tools without treating every polished "
        "paragraph as misconduct."
    ),
    (
        "It is important to distinguish between using digital tools for research assistance "
        "and using them to generate entire essays without original thought. Looking up a date, "
        "checking a spelling, or asking for a clearer explanation of a concept is not the same "
        "as pasting a full answer into a submission. Clear classroom rules help students know "
        "where that line sits before a deadline arrives."
    ),
    (
        "In my own drafting, I keep a short log of what I wrote by hand and what I asked a "
        "model to rephrase. That habit makes revision slower at first, yet it leaves a trail "
        "I can defend if a teacher asks how the page took shape. A marked report can point to "
        "the sentences that need a second look; it cannot replace that conversation."
    ),
    (
        "When rain stops and the corridor dries, the class still waits for one careful reading "
        "of a draft. A percentage on a cover page is a cue to reread, not a verdict. The useful "
        "work happens in the margins, where a cyan mark and a purple mark ask whether the voice "
        "still sounds like the person who walked through Mwenge with a broken umbrella."
    ),
]


def _wrap(text: str, fontname: str, fontsize: float, max_width: float) -> list[str]:
    words = text.split()
    line = ""
    lines: list[str] = []
    for word in words:
        trial = f"{line} {word}".strip()
        if fitz.get_text_length(trial, fontname=fontname, fontsize=fontsize) > max_width:
            if line:
                lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


def _source_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    font = "helv"
    y = 64
    page.insert_text(
        (54, y),
        "Campus notes after the rain",
        fontsize=18,
        fontname=font,
        color=(0.08, 0.1, 0.12),
    )
    y += 26
    page.insert_text(
        (54, y),
        "A short draft for a writing seminar",
        fontsize=11,
        fontname=font,
        color=(0.28, 0.32, 0.36),
    )
    y += 28
    for paragraph in PARAGRAPHS:
        for line in _wrap(paragraph, font, 11, 504):
            if y > 730:
                break
            page.insert_text((54, y), line, fontsize=11, fontname=font, color=(0.08, 0.08, 0.1))
            y += 15
        y += 12
    data = document.tobytes()
    document.close()
    return data


def main() -> None:
    from detector.report_pdf import build_reviewed_pdf

    words = sum(len(part.split()) for part in PARAGRAPHS)
    chars = sum(len(part) for part in PARAGRAPHS)
    result = {
        "flagged_percent": 28,
        "uncertain_percent": 18,
        "detected_percent": 46,
        "ai_probability": 0.61,
        "confidence": "medium",
        "warnings": [],
        "word_count": words,
        "scored_words": words,
        "character_count": chars,
        "source_pages": 1,
        "sentences": [
            {"text": PARAGRAPHS[0], "label": "clear", "ai_probability": 0.12},
            {"text": PARAGRAPHS[1], "label": "ai", "ai_probability": 0.91},
            {"text": PARAGRAPHS[2], "label": "uncertain", "ai_probability": 0.55},
            {"text": PARAGRAPHS[3], "label": "clear", "ai_probability": 0.22},
            {"text": PARAGRAPHS[4], "label": "ai", "ai_probability": 0.78},
        ],
    }
    raw = _source_pdf()
    pdf = build_reviewed_pdf(raw, result, "Sample-draft.pdf", file_size=18432)
    OUT.mkdir(parents=True, exist_ok=True)
    document = fitz.open(stream=pdf, filetype="pdf")
    targets = {
        0: OUT / "sample-report-cover.png",
        1: OUT / "sample-report-overview.png",
        2: OUT / "sample-report-page.png",
    }
    for index, path in targets.items():
        pixmap = document[index].get_pixmap(matrix=fitz.Matrix(2.4, 2.4), alpha=False)
        pixmap.save(path)
        print(f"{path.name}: {path.stat().st_size} bytes, {pixmap.width}x{pixmap.height}")
    document.close()
    print(f"words={words} pages={len(targets)}")


if __name__ == "__main__":
    main()
