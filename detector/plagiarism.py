"""Match draft passages against public web pages found for this draft.

Uses sentence-transformers/all-MiniLM-L6-v2 for embeddings. A match is a reason
to cite or rewrite. It is not a finding of misconduct, and it does not claim
access to publication or student-paper databases.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

from detector.device import inference_device
from detector.engine import split_sentences, word_count

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "models"
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
LOCAL_DIR = CACHE_DIR / "minilm"
HUB_DIR = CACHE_DIR / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots"


def _similarity_source() -> tuple[str, bool]:
    """Prefer a local copy so the host does not wait on Hugging Face."""
    if (LOCAL_DIR / "config.json").is_file():
        return str(LOCAL_DIR), True
    if HUB_DIR.is_dir():
        snaps = sorted(
            (path for path in HUB_DIR.iterdir() if path.is_dir() and (path / "config.json").is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if snaps:
            return str(snaps[0]), True
    offline = os.environ.get("FLYLEAF_OFFLINE", "").strip().lower() in {"1", "true", "yes"}
    if offline:
        raise FileNotFoundError(
            "Similarity weights are missing. Upload models/minilm, then restart."
        )
    return MODEL_ID, False
PASSAGE_WORDS = 100
MAX_QUERIES = 16
MAX_SOURCES = 16
MAX_PAGE_CHARS = 120_000
FETCH_TIMEOUT = 12
SEARCH_TIMEOUT = 12
SIM_FLOOR = 0.68
NGRAM_FLOOR = 0.22
LITERAL_FLOOR = 0.45
USER_AGENT = "Flyleaf/1.0 (portfolio project; contact silatanuikipngetich@gmail.com)"

os.environ.setdefault("HF_HOME", str(CACHE_DIR))
os.environ.setdefault("HF_HUB_CACHE", str(CACHE_DIR / "hub"))

_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.I | re.S)
_WS = re.compile(r"\s+")
_BING_LINK = re.compile(r'<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
_BING_TARGET = re.compile(r"[?&]u=a1([A-Za-z0-9_\-+=]+)")
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "in", "on", "at", "to", "for",
    "of", "with", "is", "was", "are", "were", "be", "been", "it", "this", "that",
    "as", "by", "from", "not", "have", "has", "had", "i", "you", "we", "they",
    "their", "our", "your", "can", "will", "may", "also", "than", "then", "into",
}


def _clean(text: str) -> str:
    return _WS.sub(" ", text or "").strip()


def _passage_chunks(text: str) -> list[str]:
    sentences = split_sentences(text)
    if not sentences:
        return []
    chunks: list[str] = []
    bucket: list[str] = []
    count = 0
    for sentence in sentences:
        words = word_count(sentence)
        if bucket and count + words > PASSAGE_WORDS:
            chunks.append(" ".join(bucket))
            bucket = []
            count = 0
        bucket.append(sentence)
        count += words
    if bucket:
        chunks.append(" ".join(bucket))
    return chunks


def _search_queries(passages: list[str]) -> list[str]:
    """Spread search queries across the whole draft, not only the opening pages."""
    if not passages:
        return []
    indexes = sorted(
        {
            0,
            len(passages) - 1,
            *[round(i * (len(passages) - 1) / max(MAX_QUERIES - 1, 1)) for i in range(MAX_QUERIES)],
        }
    )
    queries: list[str] = []
    seen: set[str] = set()
    for index in indexes:
        for query in (_phrase_query(passages[index]), _query_for(passages[index])):
            key = query.casefold()
            if key and key not in seen:
                seen.add(key)
                queries.append(query)
            if len(queries) >= MAX_QUERIES:
                return queries
    return queries


def _query_for(passage: str) -> str:
    words = [part for part in re.findall(r"[A-Za-z']+", passage.lower()) if part not in _STOP and len(part) > 2]
    picked = words[:6] if words else [part for part in passage.split() if len(part) > 2][:6]
    return " ".join(picked)[:90]


def _phrase_query(passage: str) -> str:
    """Quoted phrase so search engines can find the exact page someone copied from."""
    words = [part for part in re.findall(r"[A-Za-z0-9']+", passage) if len(part) > 1]
    if len(words) < 8:
        return _query_for(passage)
    start = max(0, (len(words) // 2) - 5)
    phrase = " ".join(words[start:start + 10])
    return f'"{phrase}"'


def _strip_html(raw: str) -> str:
    text = _SCRIPT.sub(" ", raw)
    text = _TAG.sub(" ", text)
    text = html.unescape(text)
    return _clean(text)


def _decode_bing_url(href: str) -> str:
    href = html.unescape(href)
    match = _BING_TARGET.search(href)
    if not match:
        return href if href.startswith("http") else ""
    raw = match.group(1).replace("-", "+").replace("_", "/")
    raw += "=" * (-len(raw) % 4)
    try:
        decoded = base64.b64decode(raw).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return ""
    return decoded if decoded.startswith("http") else ""


def _page_key(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = (parsed.path or "/").rstrip("/").lower()
    return f"{parsed.netloc.lower()}{path}"


def _search_wikipedia(query: str) -> list[dict]:
    cleaned = query.strip().strip('"')
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": cleaned,
            "srlimit": 5,
            "srnamespace": 0,
            "format": "json",
        }
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=SEARCH_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return []
    found = []
    for row in (payload.get("query") or {}).get("search") or []:
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        href = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        found.append(
            {
                "url": href,
                "title": title,
                "host": "en.wikipedia.org",
                "kind": "wikipedia",
            }
        )
    return found


def _search_bing(query: str) -> list[dict]:
    url = "https://www.bing.com/search?" + urllib.parse.urlencode(
        {"q": query, "setlang": "en-US", "cc": "US"}
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Flyleaf/1.0)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=SEARCH_TIMEOUT) as response:
            body = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    found: list[dict] = []
    seen: set[str] = set()
    for match in _BING_LINK.finditer(body):
        href = _decode_bing_url(match.group(1))
        title = _clean(_TAG.sub(" ", html.unescape(match.group(2))))
        if not href:
            continue
        host = urllib.parse.urlparse(href).netloc.lower()
        key = _page_key(href)
        if not host or key in seen or "bing.com" in host or "microsoft.com" in host:
            continue
        seen.add(key)
        found.append({"url": href, "title": title or host, "host": host, "kind": "web"})
        if len(found) >= 5:
            break
    return found


def _search_public(query: str) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()

    def add_all(items: list[dict]) -> None:
        for item in items:
            key = _page_key(item["url"])
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

    plain = query.strip().strip('"')
    add_all(_search_wikipedia(plain))
    if not results and " " in plain:
        add_all(_search_wikipedia(" ".join(plain.split()[:3])))
    add_all(_search_bing(query))
    if query.startswith('"') and plain != query:
        add_all(_search_bing(plain))
    return results


def _wikipedia_extract(title: str) -> str:
    # Full article plain text. Mid-page copies fail if we only pull the intro.
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "titles": title,
            "format": "json",
        }
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return ""
    pages = (payload.get("query") or {}).get("pages") or {}
    for page in pages.values():
        return _clean(page.get("extract") or "")[:MAX_PAGE_CHARS]
    return ""


def _fetch_page(item: dict) -> str:
    if item.get("kind") == "wikipedia":
        text = _wikipedia_extract(item.get("title") or "")
        if text:
            return text
    request = urllib.request.Request(item["url"], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
            ctype = (response.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "text" not in ctype and ctype:
                return ""
            raw = response.read(MAX_PAGE_CHARS + 8000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError):
        return ""
    return _strip_html(raw)[:MAX_PAGE_CHARS]


def _source_windows(text: str, size: int = PASSAGE_WORDS) -> list[str]:
    words = text.split()
    if len(words) < 20:
        return [text] if text else []
    step = max(size // 2, 40)
    windows = []
    for start in range(0, len(words), step):
        piece = " ".join(words[start:start + size])
        if word_count(piece) >= 20:
            windows.append(piece)
        if len(windows) >= 48:
            break
    return windows


def _ngram_overlap(left: str, right: str, n: int = 5) -> float:
    a = left.lower().split()
    b = right.lower().split()
    if len(a) < n or len(b) < n:
        return 0.0
    grams = {" ".join(a[i:i + n]) for i in range(len(a) - n + 1)}
    hits = sum(1 for i in range(len(b) - n + 1) if " ".join(b[i:i + n]) in grams)
    return hits / max(len(a) - n + 1, 1)


def _literal_overlap(passage: str, source_text: str, n: int = 8) -> tuple[float, str]:
    """Share of draft n-grams that appear anywhere in the source page."""
    draft = passage.lower().split()
    source = source_text.lower().split()
    if len(draft) < 4 or len(source) < 4:
        return 0.0, ""
    width = min(n, max(4, len(draft) // 2))
    if len(draft) < width:
        return 0.0, ""
    source_grams: dict[str, int] = {}
    for index in range(len(source) - width + 1):
        gram = " ".join(source[index:index + width])
        source_grams.setdefault(gram, index)
    hits = 0
    best = ""
    for index in range(len(draft) - width + 1):
        gram = " ".join(draft[index:index + width])
        place = source_grams.get(gram)
        if place is None:
            continue
        hits += 1
        if not best:
            left = max(0, place - 20)
            right = min(len(source), place + PASSAGE_WORDS)
            best = " ".join(source[left:right])
    score = hits / max(len(draft) - width + 1, 1)
    return score, best


def _mean_pool(model, tokenizer, texts: list[str]) -> torch.Tensor:
    device = next(model.parameters()).device
    encoded = tokenizer(
        texts,
        padding=True,
        truncation=True,
        max_length=256,
        return_tensors="pt",
    )
    encoded = {key: value.to(device) for key, value in encoded.items()}
    with torch.inference_mode():
        output = model(**encoded)
        mask = encoded["attention_mask"].unsqueeze(-1).expand(output.last_hidden_state.size()).float()
        summed = torch.sum(output.last_hidden_state * mask, dim=1)
        counts = torch.clamp(mask.sum(dim=1), min=1e-9)
        vectors = summed / counts
        return torch.nn.functional.normalize(vectors, p=2, dim=1)


class SimilarityChecker:
    def __init__(self) -> None:
        self.status = "loading"
        self.error: str | None = None
        self.model_name = MODEL_ID
        self._tokenizer = None
        self._model = None
        self._device = inference_device()
        self._lock = threading.Lock()

    def load(self) -> None:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            self._device = inference_device()
            source, local_only = _similarity_source()
            self._tokenizer = AutoTokenizer.from_pretrained(
                source,
                local_files_only=local_only,
                cache_dir=str(CACHE_DIR),
            )
            # MiniLM is small (~90 MB). low_cpu_mem_usage can leave weights on the
            # meta device and then inference fails with "cpu is not on ... meta".
            self._model = AutoModel.from_pretrained(
                source,
                local_files_only=local_only,
                cache_dir=str(CACHE_DIR),
                low_cpu_mem_usage=False,
            )
            self._model.to(self._device)
            self._model.eval()
            self.status = "ready"
            self.error = None
        except Exception as exc:
            self.status = "error"
            text = str(exc)
            lowered = text.lower()
            if "meta" in lowered and "device" in lowered:
                self.error = (
                    "The similarity model did not finish loading onto the device. "
                    "Restart the app and try again."
                )
            elif "local_files_only" in lowered or "not found" in lowered or "no such file" in lowered:
                self.error = (
                    "Similarity weights are missing on the server. "
                    "Upload models/minilm or the Hugging Face MiniLM cache, then restart."
                )
            elif "out of memory" in lowered or "oom" in lowered:
                self.error = "Not enough memory to load the similarity model on this host."
            else:
                self.error = text
            raise

    def _embed(self, texts: list[str]) -> torch.Tensor:
        if not texts:
            return torch.zeros((0, 384))
        batch = 4
        parts = []
        for start in range(0, len(texts), batch):
            parts.append(_mean_pool(self._model, self._tokenizer, texts[start:start + batch]))
        return torch.cat(parts, dim=0)

    def check(self, text: str, progress=None) -> dict:
        if self.status != "ready":
            raise RuntimeError(self.error or "The similarity checker is still loading.")

        cleaned = _clean(text.replace("\x00", " "))
        total_words = word_count(cleaned)
        if total_words < 40:
            raise ValueError("Paste at least a short paragraph for a similarity check.")

        passages = _passage_chunks(cleaned)
        if not passages:
            raise ValueError("No scoreable text was found.")

        def tick(done: int, total: int, message: str) -> None:
            if progress:
                progress(done, total, message)

        steps = 4 + len(passages)
        tick(0, steps, "Preparing the draft")

        queries = _search_queries(passages)

        tick(1, steps, "Searching public pages")
        candidates: list[dict] = []
        seen_pages: set[str] = set()
        for query in queries:
            for item in _search_public(query):
                key = _page_key(item["url"])
                if key in seen_pages:
                    continue
                seen_pages.add(key)
                candidates.append(item)
                if len(candidates) >= MAX_SOURCES:
                    break
            if len(candidates) >= MAX_SOURCES:
                break

        tick(2, steps, "Reading candidate pages")
        sources_raw: list[dict] = []
        for item in candidates:
            body = _fetch_page(item)
            if word_count(body) < 40:
                continue
            sources_raw.append({**item, "text": body, "windows": _source_windows(body)})

        tick(3, steps, "Comparing passages")
        with self._lock:
            draft_vectors = self._embed(passages)
            matches: list[dict] = []
            matched_passage_ids: set[int] = set()
            source_scores: dict[str, dict] = {}

            for source in sources_raw:
                windows = source["windows"]
                full_text = source["text"]
                source_vectors = self._embed(windows) if windows else torch.zeros((0, 384))
                for p_index, passage in enumerate(passages):
                    best_score = 0.0
                    best_window = ""
                    literal, literal_window = _literal_overlap(passage, full_text)
                    if literal >= best_score:
                        best_score = literal
                        best_window = literal_window or (windows[0] if windows else "")
                    for w_index, window in enumerate(windows):
                        cosine = float(torch.dot(draft_vectors[p_index], source_vectors[w_index]))
                        ngram = _ngram_overlap(passage, window)
                        score = max(cosine, ngram)
                        if score > best_score:
                            best_score = score
                            best_window = window
                    if (
                        best_score < SIM_FLOOR
                        and literal < LITERAL_FLOOR
                        and _ngram_overlap(passage, best_window or full_text[:800]) < NGRAM_FLOOR
                    ):
                        continue
                    matched_passage_ids.add(p_index)
                    entry = source_scores.setdefault(
                        source["url"],
                        {
                            "url": source["url"],
                            "title": source["title"],
                            "host": source["host"],
                            "matched_words": 0,
                            "best_score": 0.0,
                        },
                    )
                    entry["matched_words"] += word_count(passage)
                    entry["best_score"] = max(entry["best_score"], best_score)
                    matches.append(
                        {
                            "draft_excerpt": passage[:420],
                            "source_excerpt": (best_window or "")[:420],
                            "url": source["url"],
                            "title": source["title"],
                            "score": round(best_score, 4),
                        }
                    )
                tick(3 + len(matched_passage_ids), steps, "Comparing passages")

        matched_words = sum(word_count(passages[index]) for index in matched_passage_ids)
        overall = round(100 * matched_words / max(total_words, 1))
        sources = sorted(source_scores.values(), key=lambda row: (-row["matched_words"], -row["best_score"]))
        for row in sources:
            row["share"] = round(100 * row["matched_words"] / max(total_words, 1))
            row["score"] = round(row.pop("best_score"), 4)
            del row["matched_words"]

        matches.sort(key=lambda row: -row["score"])
        warnings = []
        if total_words < 300:
            warnings.append(
                "Under 300 words. Treat the percentage as a rough reading of this passage, not a document finding."
            )
        if not sources_raw:
            warnings.append("No public pages could be fetched for this draft. Try again in a minute.")
        elif not matches:
            warnings.append("No close public-web matches were found for the pages that were reached.")

        tick(steps, steps, "Similarity ready")
        return {
            "kind": "similarity",
            "word_count": total_words,
            "overall_percent": overall,
            "matched_words": matched_words,
            "passage_count": len(passages),
            "source_count": len(sources),
            "sources": sources[:12],
            "matches": matches[:40],
            "warnings": warnings,
            "model": self.model_name,
            "disclaimer": (
                "This estimate comes from public web pages found for this draft. "
                "It is not a finding of misconduct, and it does not search publication or student-paper databases."
            ),
        }


similarity = SimilarityChecker()
