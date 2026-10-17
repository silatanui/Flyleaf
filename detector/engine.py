"""Score English prose with a detector already trained on public human/AI text.

The weights are desklib/ai-text-detector-v1.01, a DeBERTa model fine-tuned on
the RAID benchmark. This project does not train them.
"""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path

import torch
import torch.nn as nn
from transformers import AutoConfig, AutoModel, AutoTokenizer, PreTrainedModel

ROOT = Path(__file__).resolve().parent.parent
MODEL_ID = "desklib/ai-text-detector-v1.01"
CACHE_DIR = ROOT / "models"
LOCAL_DIR = CACHE_DIR / "desklib"
SECTION_WORDS = 120
AI_CUTOFF = 0.65
HUMAN_CUTOFF = 0.35

os.environ.setdefault("HF_HOME", str(CACHE_DIR))
os.environ.setdefault("HF_HUB_CACHE", str(CACHE_DIR / "hub"))

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[\"'A-Z0-9])")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "it", "this", "that",
    "as", "by", "from", "not", "have", "has", "had", "i", "you", "we", "they",
}


class DesklibAIDetectionModel(PreTrainedModel):
    """Mean-pooled DeBERTa with a single logit. Matches the published model card."""

    config_class = AutoConfig

    def __init__(self, config):
        super().__init__(config)
        self.model = AutoModel.from_config(config)
        self.classifier = nn.Linear(config.hidden_size, 1)
        self.post_init()

    def forward(self, input_ids, attention_mask=None, labels=None):
        outputs = self.model(input_ids, attention_mask=attention_mask)
        last_hidden_state = outputs[0]
        mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        pooled = torch.sum(last_hidden_state * mask, dim=1) / torch.clamp(mask.sum(dim=1), min=1e-9)
        logits = self.classifier(pooled)
        loss = None
        if labels is not None:
            loss = nn.BCEWithLogitsLoss()(logits.view(-1), labels.float())
        output = {"logits": logits}
        if loss is not None:
            output["loss"] = loss
        return output


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def split_sentences(text: str) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n+", text) if block.strip()]
    sentences: list[str] = []
    for block in blocks:
        parts = [part.strip() for part in _SENTENCE_BREAK.split(block) if part.strip()]
        sentences.extend(parts or [block])
    return sentences


def _word_chunks(sentence: str, limit: int) -> list[str]:
    words = sentence.split()
    if len(words) <= limit:
        return [sentence]
    return [" ".join(words[index:index + limit]) for index in range(0, len(words), limit)]


def pack_sections(text: str, words_per_section: int = SECTION_WORDS) -> list[dict]:
    """Score every paragraph. Short lines stay with the paragraph they introduce."""
    paragraphs = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    sections: list[dict] = []
    short: list[str] = []
    short_words = 0

    def add_section(parts: list[str]) -> None:
        blob = " ".join(parts).strip()
        sentences = [sentence for sentence in split_sentences(blob) if word_count(sentence)]
        if not sentences:
            return
        bucket: list[str] = []
        count = 0

        def flush() -> None:
            nonlocal bucket, count
            if not bucket:
                return
            sections.append(
                {
                    "sentences": bucket,
                    "text": " ".join(bucket),
                    "words": count,
                    "qualifying": True,
                }
            )
            bucket = []
            count = 0

        for sentence in sentences:
            for piece in _word_chunks(sentence, words_per_section):
                words = word_count(piece)
                if bucket and count + words > words_per_section:
                    flush()
                bucket.append(piece)
                count += words
        flush()

    for paragraph in paragraphs:
        words = word_count(paragraph)
        if words >= 25:
            add_section(short + [paragraph])
            short = []
            short_words = 0
            continue
        short.append(paragraph)
        short_words += words
        if short_words >= words_per_section:
            add_section(short)
            short = []
            short_words = 0
    if short:
        add_section(short)
    return sections


def patch_deberta_attention() -> None:
    """DeBERTa's attention helpers are TorchScript, which ignores inputs on Python 3.14.

    Swap in the same math as ordinary functions so different passages no longer share one score.
    """
    import transformers.models.deberta_v2.modeling_deberta_v2 as deberta

    def make_log_bucket_position(relative_pos, bucket_size: int, max_position: int):
        sign = torch.sign(relative_pos)
        mid = bucket_size // 2
        abs_pos = torch.where(
            (relative_pos < mid) & (relative_pos > -mid),
            torch.tensor(mid - 1).type_as(relative_pos),
            torch.abs(relative_pos),
        )
        log_pos = (
            torch.ceil(torch.log(abs_pos / mid) / torch.log(torch.tensor((max_position - 1) / mid)) * (mid - 1))
            + mid
        )
        return torch.where(abs_pos <= mid, relative_pos.type_as(log_pos), log_pos * sign)

    def c2p_dynamic_expand(c2p_pos, query_layer, relative_pos):
        return c2p_pos.expand([query_layer.size(0), query_layer.size(1), query_layer.size(2), relative_pos.size(-1)])

    def p2c_dynamic_expand(c2p_pos, query_layer, key_layer):
        return c2p_pos.expand([query_layer.size(0), query_layer.size(1), key_layer.size(-2), key_layer.size(-2)])

    def pos_dynamic_expand(pos_index, p2c_att, key_layer):
        return pos_index.expand(p2c_att.size()[:2] + (pos_index.size(-2), key_layer.size(-2)))

    def scaled_size_sqrt(query_layer, scale_factor: int):
        return torch.sqrt(torch.tensor(query_layer.size(-1), dtype=torch.float) * scale_factor)

    def build_rpos(query_layer, key_layer, relative_pos, position_buckets: int, max_relative_positions: int):
        if key_layer.size(-2) != query_layer.size(-2):
            return deberta.build_relative_position(
                key_layer,
                key_layer,
                bucket_size=position_buckets,
                max_position=max_relative_positions,
            )
        return relative_pos

    deberta.make_log_bucket_position = make_log_bucket_position
    deberta.c2p_dynamic_expand = c2p_dynamic_expand
    deberta.p2c_dynamic_expand = p2c_dynamic_expand
    deberta.pos_dynamic_expand = pos_dynamic_expand
    deberta.scaled_size_sqrt = scaled_size_sqrt
    deberta.build_rpos = build_rpos


def weights_ready() -> bool:
    path = LOCAL_DIR / "model.safetensors"
    stamp = LOCAL_DIR / "model.safetensors.ok"
    expected = "c024a1704c65f5a4bffeda58745c58fc0ed67d6ca07b158b068a257238815265"
    return path.exists() and stamp.exists() and stamp.read_text(encoding="utf-8").strip() == expected


def english_hint(text: str) -> str | None:
    letters = [char for char in text if char.isalpha()]
    if len(letters) < 40:
        return None
    ascii_ratio = sum(char.isascii() for char in letters) / len(letters)
    tokens = re.findall(r"[A-Za-z']+", text.lower())
    if not tokens or ascii_ratio < 0.8:
        return "This does not look like English. The model was trained on English only, so ignore this score."
    stop_ratio = sum(token in _STOPWORDS for token in tokens) / len(tokens)
    if stop_ratio < 0.08:
        return "This may not be English. The model was trained on English only, so ignore this score."
    return None


def _label(probability: float) -> str:
    if probability >= AI_CUTOFF:
        return "ai"
    if probability <= HUMAN_CUTOFF:
        return "human"
    return "uncertain"


class Detector:
    def __init__(self) -> None:
        self.status = "loading"
        self.error: str | None = None
        self._model = None
        self._tokenizer = None
        self._device = torch.device("cpu")
        self._lock = threading.Lock()

    def load(self) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            patch_deberta_attention()
            torch.set_num_threads(max(1, (os.cpu_count() or 2) - 1))
            source = str(LOCAL_DIR) if weights_ready() else MODEL_ID
            local_only = weights_ready()
            self._tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=local_only, cache_dir=str(CACHE_DIR))
            self._model = DesklibAIDetectionModel.from_pretrained(
                source,
                local_files_only=local_only,
                cache_dir=str(CACHE_DIR),
                low_cpu_mem_usage=False,
            )
            self._model.to(self._device)
            self._model.eval()
            self.status = "ready"
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            raise

    def _probabilities(self, texts: list[str]) -> list[float]:
        encoded = self._tokenizer(
            texts,
            truncation=True,
            max_length=512,
            padding=True,
            return_tensors="pt",
        )
        input_ids = encoded["input_ids"].to(self._device)
        attention_mask = encoded["attention_mask"].to(self._device)
        with torch.inference_mode():
            logits = self._model(input_ids=input_ids, attention_mask=attention_mask)["logits"]
            return [float(value) for value in torch.sigmoid(logits).view(-1)]

    def score(self, text: str, progress=None) -> dict:
        if self.status != "ready":
            raise RuntimeError(self.error or "The detector is still loading.")

        cleaned = text.replace("\x00", " ").strip()
        if word_count(cleaned) < 20:
            raise ValueError("Paste at least a short paragraph. A few words is not enough to score.")

        language_warning = english_hint(cleaned)
        sections = pack_sections(cleaned)
        if not sections:
            raise ValueError("No scoreable text was found.")

        with self._lock:
            qualifying = [section for section in sections if section["qualifying"]]
            total = len(qualifying) or 1
            batch = 8
            for start in range(0, len(qualifying), batch):
                if progress:
                    progress(start, total, "Reviewing the draft")
                chunk = qualifying[start:start + batch]
                for section, probability in zip(chunk, self._probabilities([item["text"] for item in chunk])):
                    section["ai_probability"] = probability
                    section["label"] = _label(probability)
            if progress:
                progress(total, total, "Finishing the report")

        for section in sections:
            if section.get("ai_probability") is None:
                section["ai_probability"] = 0.0
                section["label"] = "clear"

        scored_sentences = []
        for section in sections:
            for sentence in section["sentences"]:
                scored_sentences.append(
                    {
                        "text": sentence,
                        "ai_probability": section["ai_probability"],
                        "label": section["label"],
                    }
                )

        counted = [section for section in sections if section["qualifying"]] or sections
        weight_total = sum(section["words"] for section in counted) or 1
        average = sum(section["ai_probability"] * section["words"] for section in counted) / weight_total
        flagged_words = sum(section["words"] for section in counted if section["label"] == "ai")
        uncertain_words = sum(section["words"] for section in counted if section["label"] == "uncertain")
        probabilities = [section["ai_probability"] for section in counted]
        spread = max(probabilities) - min(probabilities) if len(probabilities) > 1 else 0.0
        flagged_percent = round(100 * flagged_words / weight_total)
        uncertain_percent = round(100 * uncertain_words / weight_total)

        warnings = []
        if language_warning:
            warnings.append(language_warning)
        if weight_total < 300:
            warnings.append(
                "Under 300 words. Treat the percentage as a rough reading of this passage, not a document finding."
            )
        if spread >= 0.35:
            warnings.append("Sections of this text disagree. Read the highlights instead of relying on one percentage.")

        if language_warning:
            confidence = "low"
        elif weight_total < 300 or spread >= 0.35:
            confidence = "low"
        elif weight_total >= 300 and spread < 0.18:
            confidence = "high"
        else:
            confidence = "moderate"

        return {
            "word_count": word_count(cleaned),
            "character_count": len(cleaned),
            "scored_words": weight_total,
            "ai_probability": round(average, 4),
            "flagged_percent": flagged_percent,
            "uncertain_percent": uncertain_percent,
            "detected_percent": min(100, flagged_percent + uncertain_percent),
            "confidence": confidence,
            "warnings": warnings,
            "truncated": False,
            "sentences": scored_sentences,
            "sections": [
                {
                    "ai_probability": round(section["ai_probability"], 4),
                    "label": section["label"],
                    "words": section["words"],
                    "preview": section["text"][:180],
                }
                for section in sections
            ],
            "model": MODEL_ID,
        }


detector = Detector()
