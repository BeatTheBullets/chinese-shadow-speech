"""The rescore sanity report (Phase 2 spec §5.4): per take, the verdicts next to the audio, for a listener to skim."""
from __future__ import annotations
from dataclasses import dataclass
from html import escape

_BG = {"ok": "#17442d", "close": "#4d3a12", "wrong": "#4a1d22", "unvoiced": "#1a1f26", "missing": "transparent"}


@dataclass
class ReportItem:
    attempt_id: int
    segment_id: int
    lesson_title: str
    text: str
    created_at: str
    score: dict | None


def _cell(s: dict) -> str:
    mark = (f"{s['target_tone']}→{s['heard_tone']}" if s["status"] == "wrong"
            else "∅" if s["status"] == "unvoiced" else "–" if s.get("tone_score") is None
            else str(round(s["tone_score"] * 100)))
    return (f'<span class="c" style="background:{_BG.get(s["status"], "#222")}" title="{escape(s["status"])}">'
            f'{escape(s["ch"])}<small>{escape(mark)}</small></span>')


def render_report(items: list[ReportItem], api_base: str) -> str:
    rows = []
    for it in items:
        sc = it.score or {}
        overall = sc.get("overall")
        head = str(round(overall * 100)) if overall is not None else escape(", ".join(sc.get("warnings") or ["not scored"]))
        rows.append(
            f"<tr><td>{it.attempt_id}<br><small>{escape(it.created_at)}</small></td>"
            f"<td>{escape(it.lesson_title)}<br>{escape(it.text)}</td><td>{head}</td>"
            f"<td>{''.join(_cell(s) for s in sc.get('syllables') or [])}</td>"
            f'<td><audio controls preload="none" src="{api_base}/segments/{it.segment_id}/audio?fmt=wav"></audio><br>'
            f'<audio controls preload="none" src="{api_base}/attempts/{it.attempt_id}/audio"></audio></td></tr>')
    return ("<!doctype html><meta charset=utf-8><title>Rescore report</title><style>"
            "body{background:#0f1215;color:#cfd6dd;font:14px system-ui}td{border-bottom:1px solid #2a3139;padding:6px;vertical-align:top}"
            ".c{display:inline-block;margin:1px;padding:2px 4px;border:1px solid #2a3139;border-radius:3px;text-align:center}"
            ".c small{display:block;font-size:10px}</style>"
            "<p>Reference (top) and your take (bottom) per row; the backend must be running for the audio.</p>"
            f"<table>{''.join(rows)}</table>")
