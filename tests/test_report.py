from functools import cache

import pytest
import synth
from audio_zones_delay.model import Speaker
from audio_zones_delay.report import fit_flag, render_html, render_summary
from synth import SynthOptions


@cache
def clean():
    return synth.run_analysis(SynthOptions())


def fresh():
    """A clean result that a test may modify."""
    return synth.run_analysis(SynthOptions())


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


def test_how_to_read_explains_the_fit_flags():
    html = render_html(clean())
    assert ("✔ under 30 ms / 80 ms means the dial value fits a delay device whose maximum "
            "delay is 30 / 80 ms.") in html
    assert "lands within" not in html


def test_headline_is_labelled_as_context():
    r = clean()
    text, html = render_summary(r), render_html(r)
    for out in (text, html):
        assert f"Context: Zone 2 plays {r.answers.headline_ms:.1f} ms earlier than zone 1" in out
        assert "farthest Anthem distance" in out and "subwoofers included" in out
        assert "dial values in the table are the numbers to act on" in out


def test_speaker_detail_shows_distance_and_arrival():
    r = clean()
    html = render_html(r)
    assert "Distance" in html and "Arrival at seat (A1/A2)" in html
    assert "3.60 m" in html and "6.30 m" in html
    for arrival in list(r.answers.a1_ms.values()) + list(r.answers.a2_ms.values()):
        assert f"{arrival:.2f} ms" in html


def test_failed_zone1_consistency_shows_the_a1_values():
    p = synth.test_profile()
    p.speaker("center").anthem_distance_m = 2.0  # real setting is 3.4 m
    r = synth.run_analysis(SynthOptions(), profile=p)
    assert not r.reliable
    html = render_html(r)
    assert f"{r.answers.a1_ms['center']:.2f} ms" in html
    assert f"{r.answers.a1_ms['front-left']:.2f} ms" in html


def test_speaker_detail_uses_a_dash_without_distances():
    p = synth.test_profile()
    p.speaker("rear-left").seat_distance_m = None
    html = render_html(synth.run_analysis(SynthOptions(), profile=p))
    row = html.split("<td>Rear Left</td>")[1].split("</tr>")[0]
    assert row.count("—") == 2  # no distance, no arrival


@pytest.mark.parametrize("dial, u, flags", [
    (25.0, 0.5, ("ok", "ok")),
    (36.0, 0.5, ("no", "ok")),
    (29.8, 0.5, ("borderline", "ok")),
    (30.3, 0.5, ("borderline", "ok")),
    (79.6, 0.5, ("no", "borderline")),
    (0.3, 0.5, ("borderline", "borderline")),
    (-0.3, 0.5, ("borderline", "borderline")),
    (-2.0, 0.5, ("no", "no")),
    (85.0, 0.5, ("no", "no")),
])
def test_fit_flag(dial, u, flags):
    assert (fit_flag(dial, 30.0, u), fit_flag(dial, 80.0, u)) == flags


def test_borderline_fit_is_shown_in_table_and_summary():
    r = fresh()
    r.answers.uncertainty_ms = 6.5  # L dials 36.1 ms and R 35.2 ms: both within 6.5 ms of 30 ms
    text, html = render_summary(r), render_html(r)
    assert "30 ms borderline, 80 ms ok" in text
    assert html.count("<span class='warn'>borderline</span>") == 2
    left = next(c for c in r.answers.channels if c.channel == "L")
    assert (left.fits_30, left.fits_80) == (False, True)  # the flags themselves are unchanged


def test_raw_mode_gap_wording():
    p = synth.test_profile()
    p.speaker("rear-left").seat_distance_m = None
    r = synth.run_analysis(SynthOptions(), profile=p)
    g, u = r.answers.raw_gap_ms, r.answers.uncertainty_ms
    assert r.reliable and g > 0
    text = render_summary(r)
    assert f"Zone 2 fires at least {g:.1f} ms before zone 1 (±{u:.1f} ms)" in text
    r.answers.raw_gap_ms = -4.2
    assert f"Zone 2 fires at most 4.2 ms after zone 1 (±{u:.1f} ms)" in render_summary(r)


def test_unmeasured_zone2_speakers_count_as_outputs():
    r = fresh()
    r.session.profile.speakers += [
        Speaker("rear-center", "Rear Center", 2, measured=False, delay_channel="C"),
        Speaker("rear-extra", "Rear Extra", 2, measured=False, delay_channel="L"),
    ]
    text, html = render_summary(r), render_html(r)
    assert "Delay device outputs needed: 3" in text and "Delay device outputs needed: 3" in html
    for out in (text, html):
        assert "Rear Center" in out and "not measured" in out
        assert "partial: Rear Extra not measured" in out
