"""Rewrite stiff English into plainer sentences.

The weights prefer humarin/chatgpt_paraphraser_on_T5_base, a public T5
paraphraser. Lynote/humanize-text-model is the fallback. A rewrite is still
a draft to review. It does not hide how the text was written.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import torch
from transformers import T5ForConditionalGeneration, T5Tokenizer

from detector.engine import split_sentences, word_count
from detector.plain import loosen

ROOT = Path(__file__).resolve().parent.parent
PARAPHRASE_DIR = ROOT / "models" / "paraphraser"
LOCAL_DIR = ROOT / "models" / "humanizer" / "en"
PARAPHRASE_ID = "humarin/chatgpt_paraphraser_on_T5_base"
MODEL_ID = "Lynote/humanize-text-model"
MAX_WORDS = 1800
CHUNK_WORDS = 40


class Humanizer:
    def __init__(self) -> None:
        self.status = "loading"
        self.error: str | None = None
        self._model = None
        self._tokenizer = None
        self._device = torch.device("cpu")
        self._lock = threading.Lock()
        self._prefix = ""
        self.model_name = MODEL_ID

    def load(self) -> None:
        try:
            folder, prefix, name = self._source()
            self._tokenizer = T5Tokenizer.from_pretrained(str(folder), local_files_only=True)
            self._model = T5ForConditionalGeneration.from_pretrained(
                str(folder),
                local_files_only=True,
                low_cpu_mem_usage=False,
            )
            self._model.to(self._device)
            self._model.eval()
            self._prefix = prefix
            self.model_name = name
            self.status = "ready"
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            raise

    def _source(self) -> tuple[Path, str, str]:
        if _has_weights(PARAPHRASE_DIR, 800_000_000):
            return PARAPHRASE_DIR, "paraphrase: ", PARAPHRASE_ID
        if not _has_weights(LOCAL_DIR, 60_000_000):
            from huggingface_hub import snapshot_download

            snapshot_download(repo_id=MODEL_ID, allow_patterns=["en/*"], local_dir=str(ROOT / "models" / "humanizer"))
        return LOCAL_DIR, "", MODEL_ID

    def rewrite(self, text: str, progress=None) -> dict:
        cleaned = text.strip()
        total_words = word_count(cleaned)
        if total_words == 0:
            raise ValueError("Add some text to humanize.")
        if total_words > MAX_WORDS:
            raise ValueError(f"Keep the draft under {MAX_WORDS} words. This one has {total_words}.")

        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        pieces = [piece for paragraph in paragraphs for piece in _pieces(paragraph)]
        if progress:
            progress(0, max(len(pieces), 1))

        rewritten: list[str] = []
        cursor = 0
        with self._lock:
            for paragraph in paragraphs:
                lines = []
                for piece in _pieces(paragraph):
                    lines.append(piece if word_count(piece) < 8 else self._one(piece))
                    cursor += 1
                    if progress:
                        progress(cursor, len(pieces))
                rewritten.append(" ".join(line for line in lines if line))
        body = "\n\n".join(part for part in rewritten if part)
        before = _reading(cleaned)
        chosen, after = _lower_reading(cleaned, [loosen(body), loosen(cleaned), body], total_words)
        return {
            "text": chosen,
            "word_count": word_count(chosen),
            "source_words": total_words,
            "before_percent": before[0],
            "after_percent": after[0],
            "before_flagged": before[1],
            "after_flagged": after[1],
            "before_uncertain": before[2],
            "after_uncertain": after[2],
            "model": self.model_name,
        }

    def _one(self, text: str) -> str:
        encoded = self._tokenizer(
            f"{self._prefix}{text}",
            return_tensors="pt",
            truncation=True,
            max_length=256,
        )
        input_ids = encoded["input_ids"].to(self._device)
        attention_mask = encoded["attention_mask"].to(self._device)
        with torch.inference_mode():
            output = self._model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=96,
                num_beams=5,
                num_return_sequences=5,
                early_stopping=True,
                no_repeat_ngram_size=3,
                repetition_penalty=2.5,
            )
        candidates = [
            re.sub(r"\s+", " ", self._tokenizer.decode(row, skip_special_tokens=True)).strip()
            for row in output
        ]
        return _choose(text, candidates)


def _has_weights(folder: Path, minimum: int) -> bool:
    for name in ("model.safetensors", "pytorch_model.bin"):
        path = folder / name
        if path.exists() and path.stat().st_size >= minimum:
            return True
    return False


def _reading(text: str) -> tuple[int | None, int | None, int | None]:
    from detector.engine import detector

    if detector.status != "ready" or word_count(text) < 20:
        return None, None, None
    try:
        result = detector.score(text)
    except Exception:
        return None, None, None
    return (
        round(result["ai_probability"] * 100),
        int(result["flagged_percent"]),
        int(result["uncertain_percent"]),
    )


def _lower_reading(source: str, candidates: list[str], total_words: int) -> tuple[str, tuple[int | None, int | None, int | None]]:
    floor = max(8, total_words // 2)
    best_text = ""
    best_reading: tuple[int | None, int | None, int | None] = (None, None, None)
    best_score = 101
    seen: set[str] = set()
    for candidate in candidates:
        key = re.sub(r"\s+", " ", candidate).strip()
        if not key or key in seen or word_count(key) < floor:
            continue
        seen.add(key)
        reading = _reading(key)
        score = 101 if reading[0] is None else reading[0]
        if score < best_score:
            best_score = score
            best_text = key
            best_reading = reading
    if best_text:
        return best_text, best_reading
    fallback = next((re.sub(r"\s+", " ", item).strip() for item in candidates if item.strip()), source)
    return fallback, _reading(fallback)


def _choose(source: str, candidates: list[str]) -> str:
    source_words = set(re.findall(r"[a-z']+", source.lower()))
    floor = max(4, word_count(source) // 3)
    best = ""
    best_novelty = -1.0
    for candidate in candidates:
        if word_count(candidate) < floor:
            continue
        words = set(re.findall(r"[a-z']+", candidate.lower()))
        if not words:
            continue
        novelty = 1 - (len(source_words & words) / max(len(source_words), 1))
        if novelty > best_novelty:
            best_novelty = novelty
            best = candidate
    return _restore_caps(best) or source


def _restore_caps(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", text)
    restored = []
    for part in parts:
        if part and part[0].islower():
            part = part[0].upper() + part[1:]
        restored.append(part)
    return " ".join(restored)


def _pieces(paragraph: str) -> list[str]:
    sentences = split_sentences(paragraph.replace("\n", " "))
    pieces: list[str] = []
    for sentence in sentences:
        if word_count(sentence) <= CHUNK_WORDS:
            pieces.append(sentence)
            continue
        words_list = sentence.split()
        for start in range(0, len(words_list), CHUNK_WORDS):
            pieces.append(" ".join(words_list[start:start + CHUNK_WORDS]))
    return pieces or [paragraph]


humanizer = Humanizer()
