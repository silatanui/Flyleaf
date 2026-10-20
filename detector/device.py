"""Pick CPU or CUDA for local runs. Shared hosts stay on CPU."""

from __future__ import annotations

import os

import torch


def inference_device() -> torch.device:
    """Return the torch device Flyleaf should run models on.

    Override with FLYLEAF_DEVICE=cpu|cuda. Default is cuda when available,
    otherwise cpu. The current install is often the CPU wheel of PyTorch, so
    a GPU in the machine is not enough by itself.
    """
    choice = os.environ.get("FLYLEAF_DEVICE", "auto").strip().lower()
    if choice in {"cpu", "cuda"}:
        if choice == "cuda" and not torch.cuda.is_available():
            return torch.device("cpu")
        return torch.device(choice)
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")
