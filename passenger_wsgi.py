"""cPanel runs this file. The public site stays in app.py."""
import os
import sys
from pathlib import Path

# Shared hosting kills a 64-thread OpenBLAS pool. Set this before torch loads.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["RAYON_NUM_THREADS"] = "1"

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _one_process() -> None:
    """Two Passenger processes each load the model and the host returns 503."""
    try:
        public = Path.home() / "public_html" / "Flyleaf" / ".htaccess"
        if not public.is_file():
            return
        text = public.read_text(encoding="utf-8", errors="replace")
        extra = []
        if "PassengerMaxPoolSize" not in text:
            extra.append("PassengerMaxPoolSize 1")
        if "PassengerMaxRequestTime" not in text:
            extra.append("PassengerMaxRequestTime 0")
        if not extra:
            return
        public.write_text(text.rstrip() + "\n" + "\n".join(extra) + "\n", encoding="utf-8")
    except OSError:
        return


_one_process()

from app import app as application
