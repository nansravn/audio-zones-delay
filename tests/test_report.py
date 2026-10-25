import synth
from audio_zones_delay.report import render_html, render_summary
from synth import SynthOptions


def test_reliable_report_has_verdict_and_table():
    r = synth.run_analysis(SynthOptions())
    html, text = render_html(r), render_summary(r)
    verdict = f"Zone 2 plays {r.answers.headline_ms:.1f} ms earlier than zone 1"
    left = next(c for c in r.answers.channels if c.channel == "L")
    assert verdict in text and f"{left.dial_ms:.1f} ms" in text
    assert verdict in html and "<svg" in html
    assert "Delay device outputs needed: 2" in text


def test_withheld_report_hides_verdict():
    r = synth.run_analysis(SynthOptions(glitch_after_visit=2, glitch_ms=1.5))
    assert not r.reliable
    text, html = render_summary(r), render_html(r)
    assert "Verdict withheld" in text and "earlier than zone 1" not in html
    assert "delay to dial in" not in html.lower() and "Delay device outputs" not in text
    assert "Diagnostics (verdict withheld" in html and "<svg" in html


def test_names_are_escaped():
    p = synth.test_profile()
    p.speaker("rear-left").name = "<b>Rear</b>"
    p.speaker("rear-right").delay_channel = "<i>R</i>"
    html = render_html(synth.run_analysis(SynthOptions(), profile=p))
    assert "<b>Rear</b>" not in html and "<i>R</i>" not in html
    assert "&lt;b&gt;Rear&lt;/b&gt;" in html


def test_silent_zone2_speaker_is_a_missing_channel():
    r = synth.run_analysis(SynthOptions(silent_speakers=frozenset({"rear-right"})))
    text = render_summary(r)
    assert r.reliable
    assert "no signal" in text.lower()
    assert "Delay device outputs needed: 2" in text


def test_partial_channel_is_marked():
    p = synth.test_profile()
    p.speaker("rear-right").delay_channel = "L"
    r = synth.run_analysis(SynthOptions(silent_speakers=frozenset({"rear-right"})), profile=p)
    assert r.reliable
    dial = next(c for c in r.answers.channels if c.channel == "L").dial_ms
    text, html = render_summary(r), render_html(r)
    for out in (text, html):
        assert "partial:" in out and "Rear Right" in out
        assert f"{dial:.1f} ms" in out
    assert "Delay device outputs needed: 1" in text
