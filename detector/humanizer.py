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
            _download_humanizer()
        return LOCAL_DIR, "", MODEL_ID

    def rewrite(self, text: str, progress=None) -> dict:
        cleaned = text.strip()
        total_words = word_count(cleaned)
        if total_words == 0:
            raise ValueError("Add some text to humanize.")
        if total_words > MAX_WORDS:
            raise ValueError(f"Keep the draft under {MAX_WORDS} words. This one has {total_words}.")

        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
        grouped = [_pieces(paragraph) for paragraph in paragraphs]
        piece_count = sum(len(group) for group in grouped) or 1
        steps = piece_count
        if progress:
            progress(0, steps)

        rewritten: list[str] = []
        done = 0
        with self._lock:
            for group in grouped:
                lines = self._batch(group)
                rewritten.append(" ".join(line for line in lines if line))
                done += len(group)
                if progress:
                    progress(done, steps)
        body = "\n\n".join(part for part in rewritten if part)
        chosen = body if word_count(body) >= max(8, total_words // 2) else loosen(body)
        if progress:
            progress(steps, steps)
        return {
            "text": chosen,
            "word_count": word_count(chosen),
            "source_words": total_words,
            "model": self.model_name,
        }

    def _batch(self, pieces: list[str]) -> list[str]:
        """Rewrite a paragraph in one pass. Greedy decoding stays fast on one CPU thread."""
        results = list(pieces)
        pending = [index for index, piece in enumerate(pieces) if word_count(piece) >= 8]
        if not pending or self._model is None or self._tokenizer is None:
            return results
        prompts = [f"{self._prefix}{pieces[index]}" for index in pending]
        encoded = self._tokenizer(
            prompts,
            return_tensors="pt",
            truncation=True,
            max_length=128,
            padding=True,
        )
        input_ids = encoded["input_ids"].to(self._device)
        attention_mask = encoded["attention_mask"].to(self._device)
        longest = int(attention_mask.sum(dim=1).max().item())
        max_new = min(64, max(24, longest))
        with torch.inference_mode():
            output = self._model.generate(
                input_ids=input_ids,
                attention_mask=attention_mask,
                max_new_tokens=max_new,
                num_beams=1,
                do_sample=False,
            )
        for row, index in zip(output, pending):
            text = re.sub(r"\s+", " ", self._tokenizer.decode(row, skip_special_tokens=True)).strip()
            if text.lower().startswith("paraphrase:"):
                text = text.split(":", 1)[1].strip()
            results[index] = _restore_caps(text) or pieces[index]
        return results


def _download_humanizer() -> None:
    """Download one file at a time. snapshot_download opens a thread pool, and this host rejects that."""
    from huggingface_hub import hf_hub_download, list_repo_files

    destination = ROOT / "models" / "humanizer"
    destination.mkdir(parents=True, exist_ok=True)
    names = [name for name in list_repo_files(MODEL_ID) if name.startswith("en/") and not name.endswith("/")]
    if not names:
        raise RuntimeError("The humanizer model has no English files to download.")
    for name in names:
        hf_hub_download(repo_id=MODEL_ID, filename=name, local_dir=str(destination))


def _has_weights(folder: Path, minimum: int) -> bool:
    for name in ("model.safetensors", "pytorch_model.bin"):
        path = folder / name
        if path.exists() and path.stat().st_size >= minimum:
            return True
    return False


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
