"""Builds the .ass subtitle file: word-by-word pop captions, hook banner, credit."""
from __future__ import annotations

import re

W, H = 1080, 1920


def _t(s: float) -> str:
    s = max(0.0, s)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{sec:05.2f}"


def _bgr(hex_rgb: str, alpha: str = "00") -> str:
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def _esc(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")")


def chunk(words: list[dict], max_words: int = 3, max_chars: int = 18) -> list[list[dict]]:
    """Group words into 1-3 word bursts, breaking on pauses and punctuation."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        chars = sum(len(x["w"]) + 1 for x in cur)
        if (nxt is None or len(cur) >= max_words or chars >= max_chars
                or nxt["s"] - w["e"] > 0.35 or re.search(r"[.!?,]$", w["w"])):
            out.append(cur)
            cur = []
    return out


def layout_positions(layout: str) -> dict:
    if layout == "split":
        return {"caption_y": 790, "hook_y": 70}
    return {"caption_y": 1380, "hook_y": 300}


def build(words: list[dict], start: float, end: float, cfg: dict, layout: str,
          hook: str | None, credit: str | None) -> str:
    dur = end - start
    pos = layout_positions(layout)
    hi = _bgr(cfg.get("highlight", "FFE500"))
    font = cfg.get("font", "Inter Display Black")
    upper = cfg.get("uppercase", True)

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},96,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,1,7,4,5,60,60,0,1
Style: Hook,{font},62,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,16,0,8,90,90,0,1
Style: Credit,{font},34,&H33FFFFFF,&H33FFFFFF,&H99000000,&H00000000,-1,0,0,0,100,100,1,0,1,3,0,2,40,40,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    clip_words = [{**w, "s": w["s"] - start, "e": w["e"] - start}
                  for w in words if w["e"] > start and w["s"] < end]
    for group in chunk(clip_words, cfg.get("words_per_line", 3)):
        texts = [_esc(w["w"].upper() if upper else w["w"]) for w in group]
        g_end = min(dur, group[-1]["e"] + 0.15)
        for i, w in enumerate(group):
            s = max(0.0, w["s"])
            e = group[i + 1]["s"] if i + 1 < len(group) else g_end
            if e <= s:
                continue
            parts = [(f"{{\\c{hi}}}{t}{{\\c&H00FFFFFF&}}" if j == i else t) for j, t in enumerate(texts)]
            # small pop-in on the first word of each burst
            pop = "{\\fscx112\\fscy112\\t(0,90,\\fscx100\\fscy100)}" if i == 0 else ""
            ev.append(f"Dialogue: 1,{_t(s)},{_t(e)},Cap,,0,0,0,,{{\\pos(540,{pos['caption_y']})}}{pop}{' '.join(parts)}")
    if hook:
        ev.append(f"Dialogue: 2,{_t(0)},{_t(min(dur, 3.5))},Hook,,0,0,0,,"
                  f"{{\\pos(540,{pos['hook_y']})\\fad(0,250)}}{_esc(hook.upper())}")
    if credit:
        ev.append(f"Dialogue: 0,{_t(0)},{_t(dur)},Credit,,0,0,0,,{_esc(credit)}")
    return head + "\n".join(ev) + "\n"
