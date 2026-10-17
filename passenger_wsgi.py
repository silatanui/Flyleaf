"""cPanel runs this file. The public site stays in app.py."""
import os
import sys
from pathlib import Path

# Shared hosting kills a 64-thread OpenBLAS pool. Set this before torch loads.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app as application
