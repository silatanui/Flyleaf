"""Download the detector weights, resume after drops, and keep the file only if the hash matches."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
DEST = ROOT / "models" / "desklib" / "model.safetensors"
PARTIAL = DEST.with_suffix(".safetensors.part")
STAMP = DEST.with_suffix(".safetensors.ok")
URL = "https://huggingface.co/desklib/ai-text-detector-v1.01/resolve/main/model.safetensors"
EXPECTED_SHA256 = "c024a1704c65f5a4bffeda58745c58fc0ed67d6ca07b158b068a257238815265"
EXPECTED_SIZE = 1_736_100_972


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def pull_more() -> None:
    have = PARTIAL.stat().st_size if PARTIAL.exists() else 0
    if have > EXPECTED_SIZE:
        PARTIAL.unlink()
        have = 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with requests.get(URL, headers=headers, stream=True, timeout=(30, 180)) as response:
        if have and response.status_code == 200:
            have = 0
            mode = "wb"
        elif have and response.status_code == 206:
            mode = "ab"
        else:
            response.raise_for_status()
            mode = "wb"
            have = 0
        with PARTIAL.open(mode) as handle:
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                room = EXPECTED_SIZE - have
                if room <= 0:
                    break
                if len(chunk) > room:
                    chunk = chunk[:room]
                handle.write(chunk)
                have += len(chunk)
                if have % (50 * 1024 * 1024) < 1024 * 1024:
                    print(f"{have / 1_048_576:.0f} MB", flush=True)
                if have >= EXPECTED_SIZE:
                    break


def main() -> None:
    if DEST.exists() and STAMP.exists() and STAMP.read_text(encoding="utf-8").strip() == EXPECTED_SHA256:
        print("weights already verified")
        return
    PARTIAL.parent.mkdir(parents=True, exist_ok=True)
    if DEST.exists() and not PARTIAL.exists():
        DEST.replace(PARTIAL)

    failures = 0
    while not PARTIAL.exists() or PARTIAL.stat().st_size < EXPECTED_SIZE:
        before = PARTIAL.stat().st_size if PARTIAL.exists() else 0
        try:
            pull_more()
        except Exception as exc:
            failures += 1
            print(f"retry {failures}: {exc}", flush=True)
            if failures > 40:
                raise
            time.sleep(min(5 * failures, 30))
            continue
        after = PARTIAL.stat().st_size if PARTIAL.exists() else 0
        if after <= before:
            failures += 1
            print(f"retry {failures}: no new bytes", flush=True)
            if failures > 40:
                raise SystemExit("Download stalled.")
            time.sleep(min(5 * failures, 30))
        else:
            failures = 0

    print("checking hash", flush=True)
    digest = sha256_file(PARTIAL)
    print(f"sha256 {digest}", flush=True)
    if digest != EXPECTED_SHA256:
        PARTIAL.unlink(missing_ok=True)
        raise SystemExit("Downloaded file does not match the published hash.")
    os.replace(PARTIAL, DEST)
    STAMP.write_text(EXPECTED_SHA256 + "\n", encoding="utf-8")
    print("verified", flush=True)


if __name__ == "__main__":
    main()
