"""Word-level transcripts with faster-whisper (runs locally, free)."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .util import load_json, need, run_bytes, save_json

_MODEL = None


def _model(name: str):
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        print(f"Loading speech model '{name}'...")
        _MODEL = WhisperModel(name, device="auto", compute_type="auto")
    return _MODEL


def load_audio(path: Path) -> np.ndarray:
    """16 kHz mono float32 via ffmpeg. (faster-whisper's own decoder breaks with PyAV 19+.)"""
    need("ffmpeg")
    raw = run_bytes(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                     "-f", "f32le", "-"])
    return np.frombuffer(raw, np.float32).copy()


def transcribe(job: Path, model: str | None = None, language: str | None = None) -> dict:
    out = job / "words.json"
    cached = load_json(out)
    if cached is not None:
        return cached
    model = model or os.environ.get("CLIPPER_MODEL", "small")
    print(f"  transcribing {job.name}")
    segments, info = _model(model).transcribe(
        load_audio(job / "source.mp4"), word_timestamps=True, vad_filter=True, language=language)
    words, segs = [], []
    for s in segments:
        segs.append({"s": round(s.start, 2), "e": round(s.end, 2), "text": s.text.strip()})
        for w in s.words or []:
            text = w.word.strip()
            if text:
                words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3),
                              "p": round(w.probability, 3)})
    data = {"language": info.language, "words": words, "segments": segs}
    save_json(out, data)
    return data
