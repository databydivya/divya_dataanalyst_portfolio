"""Multimodal evidence reading: PDFs and screenshots -> plain text.

PDFs: the embedded text layer is extracted (pdftotext, falling back to pypdf).
Images: a vision model (Claude) transcribes every visible label/value pair; when
no API key is available we fall back to local Tesseract OCR.  Results are cached
in code/cache/media/ so repeated runs do not re-read the same file.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess

from . import llm
from .util import CACHE_DIR

VISION_PROMPT = (
    "You are transcribing an internal admin-console screenshot for a privacy audit. "
    "Transcribe ALL visible text faithfully, preserving the label -> value structure, one "
    "item per line, e.g. 'Email: x@y.com'. Include every table row (one line per row, "
    "cells separated by ' | '), every resource identifier (like account_123, backup_9, "
    "data_flow_7, support_4, user_12), every status badge, toggle state (enabled/disabled, "
    "restore allowed/blocked) and every date. Do not summarise and do not add commentary."
)


def _cache_file(path: str, mode: str) -> str:
    h = hashlib.sha256(open(path, "rb").read()).hexdigest()[:24]
    d = os.path.join(CACHE_DIR, "media")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{os.path.basename(path)}.{mode}.{h}.json")


def pdf_text(path: str) -> str:
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    try:
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    except Exception:
        return ""


def ocr_text(path: str) -> str:
    if shutil.which("tesseract"):
        src = path
        try:  # 2x grayscale upscale noticeably improves identifier recognition
            from PIL import Image
            import tempfile
            im = Image.open(path).convert("L")
            im = im.resize((im.width * 2, im.height * 2))
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            im.save(tmp.name)
            src = tmp.name
        except Exception:
            pass
        r = subprocess.run(["tesseract", src, "-", "--psm", "4"], capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
    return ""


def extract_text(path: str, use_llm: bool = True) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return pdf_text(path)
    # image
    if use_llm:
        cf = _cache_file(path, "vision")
        if os.path.exists(cf):
            d = json.load(open(cf, encoding="utf-8"))
            llm._record(d["model"], d.get("input_tokens", 0), d.get("output_tokens", 0), cached=True)
            return d["text"]
        txt = llm.call(llm.MODEL_VISION, VISION_PROMPT,
                       [llm.image_block(path), {"type": "text", "text": "Transcribe this screenshot."}],
                       max_tokens=2000)
        if txt:
            return txt
    cf = _cache_file(path, "ocr")
    if os.path.exists(cf):
        return json.load(open(cf, encoding="utf-8"))["text"]
    txt = ocr_text(path)
    json.dump({"text": txt}, open(cf, "w", encoding="utf-8"))
    return txt
