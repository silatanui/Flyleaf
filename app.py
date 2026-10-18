"""Flyleaf, a free writing review by Tanui Kipngetich Sila."""

from __future__ import annotations

import os

# Cap math libraries before torch is imported. Shared hosts kill a 64-thread pool.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["RAYON_NUM_THREADS"] = "1"

import io
import json
import re
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import HTTPException

from accounts import can_upload_pdf, current_user, init_accounts, saved_id_for_review
from detector.engine import detector
from detector.humanizer import humanizer
from detector.plagiarism import similarity
from detector.plagiarism_pdf import build_similarity_pdf
from detector.report_pdf import build_reviewed_pdf, pdf_text, write_preview_images

ROOT = Path(__file__).resolve().parent
REVIEW_DIR = ROOT / "storage" / "reviews"
JOB_DIR = ROOT / "storage" / "jobs"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True
init_accounts(app)

_jobs: dict[str, dict] = {}
_reviews: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def _job_percent(job: dict, done: int, total: int) -> int:
    """Progress only moves forward so the UI bar never jumps backward."""
    calc = 6 if total <= 0 else max(6, min(99, round(100 * done / total)))
    if done >= total > 0:
        calc = 100
    return max(int(job.get("percent") or 6), calc)


def _safe_name(name: str) -> str:
    base = Path(name or "draft").name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "", base).strip() or "draft"
    return cleaned[:80]


def _read_upload(storage) -> tuple[str, bytes | None, str]:
    filename = _safe_name(storage.filename or "draft.txt")
    raw = storage.read()
    lower = filename.lower()
    if lower.endswith(".docx"):
        from docx import Document

        document = Document(io.BytesIO(raw))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return text, None, filename
    if lower.endswith(".pdf"):
        return pdf_text(raw), raw, filename
    return raw.decode("utf-8", errors="replace"), None, filename


def _run_job(job_id: str, text: str, pdf_bytes: bytes | None, filename: str, prefix: str = "") -> None:
    def progress(done: int, total: int, message: str) -> None:
        del message
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job["done"] = done
            job["total"] = total
            job["percent"] = _job_percent(job, done, total)
            job["message"] = "Reviewing the draft"
        _publish_job(job_id)

    stop_heartbeat = threading.Event()

    def heartbeat() -> None:
        while not stop_heartbeat.wait(5):
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None or job.get("status") in {"done", "error"}:
                    return
            _publish_job(job_id)

    try:
        threading.Thread(target=heartbeat, daemon=True).start()
    except RuntimeError:
        pass
    try:
        result = detector.score(text, progress=progress)
        if pdf_bytes is not None:
            review_id = uuid.uuid4().hex
            REVIEW_DIR.mkdir(parents=True, exist_ok=True)
            path = REVIEW_DIR / f"{review_id}.pdf"
            report = build_reviewed_pdf(pdf_bytes, result, filename, file_size=len(pdf_bytes))
            path.write_bytes(report)
            page_count = write_preview_images(report, REVIEW_DIR / review_id)
            summary = {
                "filename": filename,
                "flagged_percent": result["flagged_percent"],
                "uncertain_percent": result["uncertain_percent"],
                "detected_percent": result["detected_percent"],
                "ai_probability": result["ai_probability"],
                "confidence": result["confidence"],
                "warnings": result["warnings"],
                "word_count": result["word_count"],
                "scored_words": result["scored_words"],
                "page_count": page_count,
            }
            (REVIEW_DIR / f"{review_id}.json").write_text(json.dumps(summary), encoding="utf-8")
            with _jobs_lock:
                _reviews[review_id] = {"path": path, "summary": summary}
            result["review_id"] = review_id
            result["review_url"] = f"{prefix}/review/{review_id}"
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["percent"] = 100
            _jobs[job_id]["result"] = result
            _jobs[job_id]["message"] = "Report ready"
        _publish_job(job_id)
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["message"] = "The review could not be finished"
        _publish_job(job_id)
    finally:
        stop_heartbeat.set()


@app.get("/")
def home():
    return render_template("home.html")


@app.get("/privacy")
def privacy():
    return render_template("privacy.html")


@app.get("/terms")
def terms():
    return render_template("terms.html")


@app.get("/help")
def help_page():
    return render_template("help.html")


@app.get("/check")
def check():
    return redirect(url_for("home") + "#check")


@app.get("/humanize")
def humanize_page():
    return redirect(url_for("home") + "#humanize")


@app.get("/similarity")
def similarity_page():
    return redirect(url_for("home") + "#similarity")


@app.get("/review/<review_id>/pages/<int:number>")
def review_page(review_id: str, number: int):
    path = REVIEW_DIR / review_id / f"{number}.png"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="image/png")


def _stored_review(review_id: str) -> dict | None:
    with _jobs_lock:
        item = _reviews.get(review_id)
    if item is not None:
        return item
    meta = REVIEW_DIR / f"{review_id}.json"
    pdf = REVIEW_DIR / f"{review_id}.pdf"
    if not meta.is_file() or not pdf.is_file():
        return None
    summary = json.loads(meta.read_text(encoding="utf-8"))
    item = {"path": pdf, "summary": summary}
    with _jobs_lock:
        _reviews[review_id] = item
    return item


@app.get("/review/<review_id>")
def review(review_id: str):
    item = _stored_review(review_id)
    if item is None:
        abort(404)
    user = current_user()
    saved_id = saved_id_for_review(user["id"], review_id) if user else None
    return render_template(
        "review.html",
        review_id=review_id,
        summary=item["summary"],
        saved_id=saved_id,
    )


@app.get("/review/<review_id>/file")
def review_file(review_id: str):
    item = _stored_review(review_id)
    if item is None:
        abort(404)
    name = Path(item["summary"]["filename"]).stem or "draft"
    return send_file(item["path"], mimetype="application/pdf", download_name=f"flyleaf-review-{name}.pdf", as_attachment=False)


@app.get("/review/<review_id>/download")
def review_download(review_id: str):
    item = _stored_review(review_id)
    if item is None:
        abort(404)
    name = Path(item["summary"]["filename"]).stem or "draft"
    return send_file(
        item["path"],
        mimetype="application/pdf",
        download_name=f"flyleaf-review-{name}.pdf",
        as_attachment=True,
    )


@app.get("/api/status")
def status():
    _start_model_load()
    return jsonify({"status": detector.status, "error": detector.error, "model": "desklib/ai-text-detector-v1.01"})


@app.get("/api/humanize/status")
def humanize_status():
    _start_model_load()
    return jsonify({"status": humanizer.status, "error": humanizer.error, "model": humanizer.model_name})


@app.get("/api/similarity/status")
def similarity_status():
    _start_similarity_load()
    return jsonify({"status": similarity.status, "error": similarity.error, "model": similarity.model_name})


def _run_humanize(job_id: str, text: str) -> None:
    stop = threading.Event()

    def progress(done: int, total: int) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job["done"] = done
            job["total"] = total
            job["percent"] = _job_percent(job, done, total)
        _publish_job(job_id)

    def beat() -> None:
        while not stop.wait(10):
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None or job.get("status") != "running":
                    return
            _publish_job(job_id)

    threading.Thread(target=beat, daemon=True).start()
    try:
        result = humanizer.rewrite(text, progress=progress)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["percent"] = 100
            _jobs[job_id]["result"] = result
            _jobs[job_id]["message"] = "Rewrite ready"
        _publish_job(job_id)
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["message"] = "The rewrite could not be finished"
        _publish_job(job_id)
    finally:
        stop.set()


@app.post("/api/humanize")
def humanize_api():
    if humanizer.status == "loading":
        return jsonify({"error": "The humanizer is still getting ready. Try again in a minute."}), 503
    if humanizer.status == "error":
        return jsonify({"error": humanizer.error or "The humanizer failed to load."}), 500
    text = ""
    if request.is_json:
        text = (request.get_json(silent=True) or {}).get("text") or ""
    else:
        text = request.form.get("text") or ""
    text = text.strip()
    if not text:
        return jsonify({"error": "Add some text to humanize."}), 400
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        if any(item.get("kind") == "humanize" and item.get("status") == "running" for item in _jobs.values()):
            return jsonify({"error": "A rewrite is already running. Give it a moment, then try again."}), 503
        _jobs[job_id] = {
            "status": "running",
            "kind": "humanize",
            "done": 0,
            "total": 1,
            "percent": 6,
            "message": "Rewriting the draft",
            "result": None,
            "error": None,
        }
    _publish_job(job_id)
    if not _spawn(_run_humanize, (job_id, text)):
        return jsonify({"error": "The host could not start the rewrite. Wait a minute and try again."}), 503
    prefix = request.script_root.rstrip("/")
    return jsonify({"job_id": job_id, "status": "running", "watch_url": f"{prefix}/jobs/{job_id}.json"})


@app.get("/api/upload-quota")
def upload_quota():
    user = current_user()
    allowed, message = can_upload_pdf(user)
    return jsonify({"allowed": allowed, "error": message or None, "signed_in": user is not None})


@app.post("/api/analyze")
def analyze():
    if detector.status == "loading":
        return jsonify({"error": "Flyleaf is still getting ready. Try again in a minute."}), 503
    if detector.status == "error":
        return jsonify({"error": detector.error or "Flyleaf failed to load."}), 500

    pdf_bytes = None
    filename = "draft.txt"
    if request.files.get("file"):
        text, pdf_bytes, filename = _read_upload(request.files["file"])
    elif request.is_json:
        text = (request.get_json(silent=True) or {}).get("text") or ""
    else:
        text = request.form.get("text") or ""

    text = text.strip()
    if pdf_bytes is not None:
        allowed, message = can_upload_pdf(current_user())
        if not allowed:
            return jsonify({"error": message}), 403
    if pdf_bytes is not None and not text:
        return jsonify({"error": "This PDF has no selectable text. Flyleaf can review text-based PDFs."}), 400
    if not text:
        return jsonify({"error": "Add some text or choose a .txt, .docx, or .pdf file."}), 400

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "done": 0,
            "total": 1,
            "percent": 6,
            "message": "Reviewing the draft",
            "result": None,
            "error": None,
        }
    prefix = request.script_root.rstrip("/")
    _publish_job(job_id)
    if not _spawn(_run_job, (job_id, text, pdf_bytes, filename, prefix)):
        return jsonify({"error": "The host could not start the check. Wait a minute and try again."}), 503
    return jsonify({"job_id": job_id, "status": "running", "watch_url": f"{prefix}/jobs/{job_id}.json"})


def _run_similarity(
    job_id: str,
    text: str,
    filename: str,
    prefix: str = "",
    open_report: bool = False,
    pdf_bytes: bytes | None = None,
) -> None:
    def progress(done: int, total: int, message: str) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job["done"] = done
            job["total"] = total
            job["percent"] = _job_percent(job, done, total)
            job["message"] = message
        _publish_job(job_id)

    stop = threading.Event()

    def beat() -> None:
        while not stop.wait(8):
            with _jobs_lock:
                job = _jobs.get(job_id)
                if job is None or job.get("status") != "running":
                    return
            _publish_job(job_id)

    try:
        threading.Thread(target=beat, daemon=True).start()
    except RuntimeError:
        pass
    try:
        result = similarity.check(text, progress=progress)
        review_id = uuid.uuid4().hex
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        path = REVIEW_DIR / f"{review_id}.pdf"
        report = build_similarity_pdf(result, filename, draft_text=text, pdf_bytes=pdf_bytes)
        path.write_bytes(report)
        # Always build preview pages so the report view can show the full submission.
        page_count = write_preview_images(report, REVIEW_DIR / review_id)
        summary = {
            "filename": filename,
            "kind": "similarity",
            "overall_percent": result["overall_percent"],
            "flagged_percent": result["overall_percent"],
            "uncertain_percent": 0,
            "word_count": result["word_count"],
            "source_count": result["source_count"],
            "warnings": result.get("warnings") or [],
            "page_count": page_count,
        }
        (REVIEW_DIR / f"{review_id}.json").write_text(json.dumps(summary), encoding="utf-8")
        with _jobs_lock:
            _reviews[review_id] = {"path": path, "summary": summary}
        result["review_id"] = review_id
        if open_report:
            result["download_url"] = f"{prefix}/review/{review_id}/download"
            result["review_url"] = f"{prefix}/review/{review_id}"
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["percent"] = 100
            _jobs[job_id]["result"] = result
            _jobs[job_id]["message"] = "Opening the report" if open_report else "Similarity ready"
        _publish_job(job_id)
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["message"] = "The similarity check could not be finished"
        _publish_job(job_id)
    finally:
        stop.set()


@app.post("/api/plagiarism")
def plagiarism_api():
    _start_similarity_load()
    if similarity.status == "loading":
        return jsonify({"error": "The similarity checker is still getting ready. Try again in a minute."}), 503
    if similarity.status == "error":
        return jsonify({"error": similarity.error or "The similarity checker failed to load."}), 500

    filename = "draft.txt"
    pdf_bytes = None
    if request.files.get("file"):
        text, pdf_bytes, filename = _read_upload(request.files["file"])
    elif request.is_json:
        payload = request.get_json(silent=True) or {}
        text = payload.get("text") or ""
        filename = _safe_name(payload.get("filename") or filename)
    else:
        text = request.form.get("text") or ""
        filename = _safe_name(request.form.get("filename") or filename)

    text = text.strip()
    if pdf_bytes is not None:
        allowed, message = can_upload_pdf(current_user())
        if not allowed:
            return jsonify({"error": message}), 403
    if pdf_bytes is not None and not text:
        return jsonify({"error": "This PDF has no selectable text. Flyleaf can compare text-based PDFs."}), 400
    if not text:
        return jsonify({"error": "Add some text for a similarity check."}), 400

    open_report = pdf_bytes is not None
    job_id = uuid.uuid4().hex
    with _jobs_lock:
        if any(item.get("kind") == "similarity" and item.get("status") == "running" for item in _jobs.values()):
            return jsonify({"error": "A similarity check is already running. Give it a moment, then try again."}), 503
        _jobs[job_id] = {
            "status": "running",
            "kind": "similarity",
            "done": 0,
            "total": 1,
            "percent": 6,
            "message": "Searching public pages",
            "result": None,
            "error": None,
        }
    prefix = request.script_root.rstrip("/")
    _publish_job(job_id)
    if not _spawn(_run_similarity, (job_id, text, filename, prefix, open_report, pdf_bytes)):
        return jsonify({"error": "The host could not start the similarity check. Wait a minute and try again."}), 503
    return jsonify({"job_id": job_id, "status": "running", "watch_url": f"{prefix}/jobs/{job_id}.json"})


def _publish_job(job_id: str) -> None:
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["updated"] = time.time()
        payload = dict(job)
    raw = json.dumps(payload)
    (JOB_DIR / f"{job_id}.json").write_text(raw, encoding="utf-8")
    public = Path.home() / "public_html" / "Flyleaf" / "jobs"
    try:
        if public.parent.is_dir():
            public.mkdir(parents=True, exist_ok=True)
            (public / f"{job_id}.json").write_text(raw, encoding="utf-8")
    except OSError:
        pass


def _stored_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is not None:
            return dict(job)
    path = JOB_DIR / f"{job_id}.json"
    if not path.is_file():
        return None
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return found if isinstance(found, dict) else None


@app.get("/api/jobs/<job_id>")
def job(job_id: str):
    found = _stored_job(job_id)
    if found is None:
        return jsonify({"error": "That check has expired."}), 404
    return jsonify(found)


@app.errorhandler(404)
def missing(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "That request was not found."}), 404
    return render_template("missing.html"), 404


@app.errorhandler(Exception)
def unhandled(exc):
    if isinstance(exc, HTTPException):
        return exc
    app.logger.exception("Request failed")
    if request.path.startswith("/api/"):
        return jsonify({"error": "Flyleaf could not finish that request."}), 500
    return render_template("missing.html"), 500


def _spawn(target, args) -> bool:
    try:
        threading.Thread(target=target, args=args, daemon=True).start()
    except RuntimeError:
        return False
    return True


_loader_lock = threading.Lock()
_loader_running = False
_thread_failures = 0


def _load_models() -> None:
    global _loader_running
    try:
        if detector.status != "ready":
            detector.status = "loading"
            detector.error = None
            try:
                detector.load()
            except Exception:
                app.logger.exception("Detector failed to load")
        if humanizer.status != "ready":
            humanizer.status = "loading"
            humanizer.error = None
            try:
                humanizer.load()
            except Exception:
                app.logger.exception("Humanizer failed to load")
    finally:
        with _loader_lock:
            _loader_running = False


def _start_model_load() -> None:
    """Start the loader once. A full process list should not freeze the buttons."""
    global _loader_running, _thread_failures
    if detector.status != "loading" and humanizer.status != "loading":
        return
    with _loader_lock:
        if _loader_running or (detector.status != "loading" and humanizer.status != "loading"):
            return
        _loader_running = True
        try:
            threading.Thread(target=_load_models, daemon=True).start()
        except RuntimeError:
            _loader_running = False
            _thread_failures += 1
            app.logger.exception("Flyleaf could not start the model loader")
            if detector.status != "ready":
                detector.status = "loading"
                detector.error = (
                    "The host has no free worker slot yet. Wait a minute, then reload this page."
                    if _thread_failures >= 2
                    else None
                )


_similarity_lock = threading.Lock()
_similarity_running = False


def _load_similarity() -> None:
    global _similarity_running
    try:
        if similarity.status != "ready":
            similarity.status = "loading"
            similarity.error = None
            try:
                similarity.load()
            except Exception:
                app.logger.exception("Similarity checker failed to load")
    finally:
        with _similarity_lock:
            _similarity_running = False


def _start_similarity_load() -> None:
    global _similarity_running
    if similarity.status == "ready":
        return
    with _similarity_lock:
        if _similarity_running or similarity.status == "ready":
            return
        _similarity_running = True
        if similarity.status != "error":
            similarity.status = "loading"
        try:
            threading.Thread(target=_load_similarity, daemon=True).start()
        except RuntimeError:
            _similarity_running = False
            similarity.status = "error"
            similarity.error = "The host has no free worker slot yet. Wait a minute, then reload this page."
            app.logger.exception("Flyleaf could not start the similarity loader")


_start_model_load()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, threaded=True)
