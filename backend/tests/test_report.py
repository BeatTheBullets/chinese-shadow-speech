from shadow.scoring.report import ReportItem, render_report


def test_report_lists_verdicts_audio_and_warnings():
    score = {"overall": 0.62, "warnings": [], "syllables": [
        {"ch": "你", "status": "ok", "target_tone": 2, "heard_tone": 2, "tone_score": 0.91},
        {"ch": "好", "status": "wrong", "target_tone": 3, "heard_tone": 2, "tone_score": 0.33}]}
    gated = {"overall": None, "warnings": ["too_quiet"], "syllables": []}
    html = render_report([ReportItem(7, 11, "L <1>", "你好", "2026-10-07 09:32", score),
                          ReportItem(8, 11, "L <1>", "你好", "2026-10-07 09:33", gated)], "http://127.0.0.1:8000")
    assert "L &lt;1&gt;" in html and "3→2" in html and "62" in html
    assert 'src="http://127.0.0.1:8000/segments/11/audio?fmt=wav"' in html
    assert 'src="http://127.0.0.1:8000/attempts/7/audio"' in html
    assert "too_quiet" in html
