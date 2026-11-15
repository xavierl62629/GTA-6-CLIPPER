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


def _words_from_segments(segments) -> tuple[list[dict], list[dict]]:
    words, segs = [], []
    for s in segments:
        segs.append({"s": round(s.start, 2), "e": round(s.end, 2), "text": s.text.strip()})
        if s.words:
            for w in s.words:
                text = w.word.strip()
                if text:
                    words.append({"w": text, "s": round(w.start, 3), "e": round(w.end, 3),
                                  "p": round(w.probability, 3)})
        else:  # no word timings: spread the segment's words evenly across it
            toks = s.text.split()
            step = (s.end - s.start) / max(1, len(toks))
            for i, t in enumerate(toks):
                words.append({"w": t, "s": round(s.start + i * step, 3),
                              "e": round(s.start + (i + 1) * step, 3), "p": 0.5})
    return words, segs


def transcribe(job: Path, model: str | None = None, language: str | None = None) -> dict:
    out = job / "words.json"
    cached = load_json(out)
    if cached is not None:
        return cached
    model = model or os.environ.get("CLIPPER_MODEL", "small")
    print(f"  transcribing {job.name}")
    audio = load_audio(job / "source.mp4")
    m = _model(model)
    # faster-whisper's word alignment occasionally crashes on odd audio (IndexError in
    # find_alignment). Retry with safer settings, then fall back to segment-level timing.
    attempts = [
        dict(word_timestamps=True, vad_filter=True),
        dict(word_timestamps=True, vad_filter=False, condition_on_previous_text=False),
        dict(word_timestamps=False, vad_filter=True),
    ]
    for i, opts in enumerate(attempts):
        try:
            segments, info = m.transcribe(audio, language=language, **opts)
            words, segs = _words_from_segments(list(segments))
            break
        except (IndexError, ValueError) as exc:
            if i == len(attempts) - 1:
                raise
            print(f"    speech model hiccup ({type(exc).__name__}); retrying with safer settings")
    data = {"language": info.language, "words": words, "segments": segs}
    save_json(out, data)
    return data
