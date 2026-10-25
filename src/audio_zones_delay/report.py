"""Render an analysis as a self-contained HTML report and a terminal summary."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from .analysis import AnalysisResult
from .answers import FIT_30_MS, FIT_80_MS, ChannelDelay
from .model import Speaker

HOW_TO_READ = (
    "Dial the delay values below into the delay device, one per output. "
    "✔ under 30 ms / 80 ms means the dial value fits a delay device whose maximum delay "
    "is 30 / 80 ms. “borderline” means the dial value is within its uncertainty "
    "of that limit or of zero, so the fit could go either way."
)
HEADLINE_NOTE = (
    "Context only: this depends on the farthest Anthem distance entered (subwoofers "
    "included). The dial values in the table are the numbers to act on."
)


@dataclass
class ChannelRow:
    """One expected delay-device output, with what the analysis found for it."""
    channel: str
    names: list[str]
    found: ChannelDelay | None
    silent_names: list[str]
    unmeasured_names: list[str] = field(default_factory=list)

    @property
    def partial(self) -> bool:
        return self.found is not None and bool(self.silent_names or self.unmeasured_names)


def fit_flag(dial_ms: float, limit_ms: float, uncertainty_ms: float) -> str:
    """"ok", "no", or "borderline" when the uncertainty reaches zero or the limit."""
    if abs(dial_ms) < uncertainty_ms or abs(dial_ms - limit_ms) < uncertainty_ms:
        return "borderline"
    return "ok" if 0.0 <= dial_ms <= limit_ms else "no"


def verdict_lines(result: AnalysisResult) -> list[str]:
    """The verdict copy; only a reliable result has any."""
    if not result.reliable:
        return []
    a = result.answers
    u = a.uncertainty_ms
    if a.mode == "raw":
        g = a.raw_gap_ms
        # The gap is measured against the earliest zone 1 speaker.
        if g >= 0:
            first = f"Zone 2 fires at least {g:.1f} ms before zone 1 (±{u:.1f} ms)"
        else:
            first = f"Zone 2 fires at most {abs(g):.1f} ms after zone 1 (±{u:.1f} ms)"
        return [first, "Raw estimate: enter Anthem and seat distances for per-speaker delays."]
    h = a.headline_ms
    when = "earlier" if h > 0 else "later"
    lines = [f"Context: Zone 2 plays {abs(h):.1f} ms {when} than zone 1 (±{u:.1f} ms)",
             HEADLINE_NOTE]
    for c in a.channels:
        if c.delay_ms < 0:
            lines.append(f"A delay device on zone 2 cannot fix channel {c.channel}: "
                         "zone 2 is already late there.")
        elif c.dial_ms < 0:
            lines.append(f"The delay device's own latency already over-delays channel {c.channel}.")
    return lines


def channel_rows(result: AnalysisResult) -> list[ChannelRow]:
    """Expected channels from the profile (every zone 2 speaker), in profile order."""
    profile = result.session.profile
    found = {c.channel: c for c in result.answers.channels}
    silent = set(result.timeline.no_signal)
    groups: dict[str, list[Speaker]] = {}
    for s in profile.speakers:
        if s.zone == 2:
            groups.setdefault(s.delay_channel or s.id, []).append(s)
    return [
        ChannelRow(ch, [s.name for s in sp], found.get(ch),
                   [s.name for s in sp if s.measured and s.id in silent],
                   [s.name for s in sp if not s.measured])
        for ch, sp in groups.items()
    ]


def _show_table(result: AnalysisResult) -> bool:
    return result.reliable and result.answers.mode == "full"


def _failed_messages(result: AnalysisResult) -> list[str]:
    return [c.message for c in result.checks if c.status == "fail"]


def _tally(result: AnalysisResult) -> str:
    n = {s: sum(c.status == s for c in result.checks) for s in ("pass", "warn", "fail")}
    return f"Checks: {n['pass']} passed, {n['warn']} warnings, {n['fail']} failed"


def _latency_note(result: AnalysisResult) -> str | None:
    lat = result.session.profile.device_latency_ms
    if not lat:
        return None
    return f"dial values already subtract {lat:.1f} ms of device latency"


def _partial_note(row: ChannelRow) -> str:
    parts = []
    if row.silent_names:
        parts.append(f"{', '.join(row.silent_names)} had no signal")
    if row.unmeasured_names:
        parts.append(f"{', '.join(row.unmeasured_names)} not measured")
    return "partial: " + "; ".join(parts)


def _missing_note(row: ChannelRow) -> str:
    """Why a channel has no value."""
    if not row.silent_names:
        return "not measured"
    note = "no signal — cannot compute"
    if row.unmeasured_names:
        note += f" ({', '.join(row.unmeasured_names)} not measured)"
    return note


def _flags(result: AnalysisResult, c: ChannelDelay) -> tuple[str, str]:
    u = result.answers.uncertainty_ms
    return fit_flag(c.dial_ms, FIT_30_MS, u), fit_flag(c.dial_ms, FIT_80_MS, u)


def render_summary(result: AnalysisResult, report_path: Path | None = None) -> str:
    out: list[str] = []
    if result.reliable:
        out += verdict_lines(result)
    else:
        out.append("Verdict withheld")
        out += [f"  - {m}" for m in _failed_messages(result)]
    if _show_table(result):
        rows = channel_rows(result)
        out.append("")
        out.append(f"Delay device outputs needed: {len(rows)}")
        note = _latency_note(result)
        if note:
            out.append(f"({note})")
        for r in rows:
            who = ", ".join(r.names)
            if r.found is None:
                out.append(f"  {r.channel} ({who}): {_missing_note(r)}")
                continue
            c = r.found
            f30, f80 = _flags(result, c)
            line = (f"  {r.channel} ({who}): dial {c.dial_ms:.1f} ms "
                    f"(delay {c.delay_ms:.1f} ms), "
                    f"{FIT_30_MS:.0f} ms {f30}, {FIT_80_MS:.0f} ms {f80}")
            if r.partial:
                line += f" [{_partial_note(r)}]"
            out.append(line)
    out.append("")
    out.append(_tally(result))
    if report_path is not None:
        out.append(f"Report: {report_path}")
    return "\n".join(out)


# ---------------------------------------------------------------- HTML

_CSS = """
:root {
  --bg: #f7f7f5; --fg: #1d1d1b; --muted: #5f5f5a; --card: #ffffff; --line: #d9d9d3;
  --zone1: #2a6fb0; --zone2: #c2570c; --pass: #1e7a3c; --warn: #9a6a00; --fail: #b3261e;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --fg: #ececE8; --muted: #a2a29b; --card: #212120; --line: #3a3a37;
    --zone1: #6aa8e6; --zone2: #f0975a; --pass: #5cc07d; --warn: #e0b24a; --fail: #f08077;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.5 system-ui, sans-serif; }
main { max-width: 760px; margin: 0 auto; padding: 16px; }
h1 { font-size: 1.4rem; margin: 0 0 4px; }
h2 { font-size: 1.15rem; margin: 28px 0 8px; }
.meta, .hint { color: var(--muted); font-size: .9rem; margin: 2px 0; }
.verdict { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  padding: 12px 14px; margin: 16px 0; }
.verdict p { margin: 4px 0; }
.verdict .main { font-size: 1.2rem; font-weight: 600; }
.withheld { border-color: var(--fail); }
.withheld .main { color: var(--fail); }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .9rem; background: var(--card); }
th, td { border-bottom: 1px solid var(--line); padding: 6px 8px; text-align: left;
  white-space: nowrap; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.pass { color: var(--pass); } .warn { color: var(--warn); } .fail { color: var(--fail); }
.legend { display: flex; gap: 16px; font-size: .9rem; margin: 6px 0; }
.sw { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
.sw.z1 { background: var(--zone1); } .sw.z2 { background: var(--zone2); }
svg { width: 100%; height: auto; display: block; background: var(--card);
  border: 1px solid var(--line); border-radius: 8px; }
svg text { fill: var(--fg); font: 12px system-ui, sans-serif; }
svg .axis { stroke: var(--line); } svg .z1 { stroke: var(--zone1); fill: var(--zone1); }
svg .z2 { stroke: var(--zone2); fill: var(--zone2); }
ul.checks { list-style: none; padding: 0; }
ul.checks li { padding: 4px 0; }
"""


def _e(s: object) -> str:
    return escape(str(s))


def _timeline_svg(result: AnalysisResult) -> str:
    t, profile = result.timeline, result.session.profile
    rows = [s for s in profile.speakers if s.id in t.emission_ms]
    if not rows:
        return "<p class='hint'>No speaker was heard.</p>"
    lo = min(t.emission_ms[s.id] - 2 * t.emission_se_ms[s.id] for s in rows)
    hi = max(t.emission_ms[s.id] + 2 * t.emission_se_ms[s.id] for s in rows)
    if hi - lo < 1.0:
        lo, hi = lo - 0.5, hi + 0.5
    pad = (hi - lo) * 0.05
    lo, hi = lo - pad, hi + pad
    width, left, right, top, row_h = 720, 170, 20, 12, 26
    height = top + row_h * len(rows) + 34
    plot_w = width - left - right

    def x(v: float) -> float:
        return left + (v - lo) / (hi - lo) * plot_w

    parts = [f"<svg viewBox='0 0 {width} {height}' role='img' "
             "aria-label='Emission time per speaker'>"]
    base = top + row_h * len(rows)
    parts.append(f"<line class='axis' x1='{left}' x2='{width - right}' y1='{base}' y2='{base}'/>")
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        parts.append(f"<line class='axis' x1='{x(v):.1f}' x2='{x(v):.1f}' "
                     f"y1='{base}' y2='{base + 4}'/>")
        parts.append(f"<text x='{x(v):.1f}' y='{base + 18}' text-anchor='middle'>{v:.1f}</text>")
    parts.append(f"<text x='{width - right}' y='{height - 2}' text-anchor='end'>"
                 "emission time (ms)</text>")
    for i, s in enumerate(rows):
        y = top + row_h * i + row_h / 2
        v, se = t.emission_ms[s.id], t.emission_se_ms[s.id]
        cls = f"z{s.zone}"
        parts.append(f"<text x='{left - 8}' y='{y + 4:.1f}' text-anchor='end'>{_e(s.name)}</text>")
        parts.append(f"<line class='{cls}' x1='{x(v - se):.1f}' x2='{x(v + se):.1f}' "
                     f"y1='{y:.1f}' y2='{y:.1f}' stroke-width='2'/>")
        parts.append(f"<circle class='{cls}' cx='{x(v):.1f}' cy='{y:.1f}' r='5'>"
                     f"<title>{_e(s.name)}: {v:.1f} ms (±{se:.1f})</title></circle>")
    parts.append("</svg>")
    legend = ("<div class='legend'><span><span class='sw z1'></span>Zone 1</span>"
              "<span><span class='sw z2'></span>Zone 2</span></div>")
    return legend + "".join(parts)


_MARKS = {
    "ok": "<span class='pass'>✔</span>",
    "no": "<span class='fail'>✘</span>",
    "borderline": "<span class='warn'>borderline</span>",
}


def _channel_table(result: AnalysisResult) -> str:
    rows = channel_rows(result)
    body = []
    for r in rows:
        who = _e(", ".join(r.names))
        if r.found is None:
            body.append(f"<tr><td>{_e(r.channel)}</td><td>{who}</td>"
                        f"<td colspan='5'>{_e(_missing_note(r))}</td></tr>")
            continue
        c = r.found
        f30, f80 = _flags(result, c)
        left = "; ".join(f"{_e(result.session.profile.speaker(i).name)} {v:+.1f} ms"
                         for i, v in c.residual_ms.items())
        if r.partial:
            left += f"<br><span class='warn'>{_e(_partial_note(r))}</span>"
        body.append(
            f"<tr><td>{_e(r.channel)}</td><td>{who}</td>"
            f"<td class='num'>{c.delay_ms:.1f} ms</td><td class='num'><b>{c.dial_ms:.1f} ms</b></td>"
            f"<td>{_MARKS[f30]}</td><td>{_MARKS[f80]}</td><td>{left}</td></tr>")
    note = _latency_note(result)
    return (
        f"<h2>Delay to dial in</h2><p>Delay device outputs needed: {len(rows)}</p>"
        + (f"<p class='hint'>{_e(note)}</p>" if note else "")
        + "<div class='scroll'><table><tr><th>Channel</th><th>Speakers</th>"
        "<th class='num'>Delay</th><th class='num'>Dial</th>"
        f"<th>{FIT_30_MS:.0f} ms</th><th>{FIT_80_MS:.0f} ms</th><th>Leftover misalignment</th></tr>"
        + "".join(body) + "</table></div>")


def _distance_and_arrival(result: AnalysisResult, s: Speaker) -> str:
    """Table cells: the Anthem (zone 1) or seat (zone 2) distance, and A1_i or A2_j."""
    if s.zone == 1:
        d, arrival = s.anthem_distance_m, result.answers.a1_ms.get(s.id)
    else:
        d, arrival = s.seat_distance_m, result.answers.a2_ms.get(s.id)
    distance = "—" if d is None else f"{d:.2f} m"
    at_seat = "—" if arrival is None else f"{arrival:.2f} ms"
    return f"<td class='num'>{distance}</td><td class='num'>{at_seat}</td>"


def _speaker_detail(result: AnalysisResult) -> str:
    t, profile = result.timeline, result.session.profile
    body = []
    for v in t.visits:
        s = profile.speaker(v.speaker_id)
        e, se = t.emission_ms.get(s.id), t.emission_se_ms.get(s.id)
        emission = "—" if e is None else f"{e:.1f} ms (±{se:.1f})"
        body.append(
            f"<tr><td>{v.visit}</td><td>{_e(s.name)}</td><td>{s.zone}</td>"
            f"<td class='num'>{emission}</td>{_distance_and_arrival(result, s)}"
            f"<td class='num'>{v.n}</td>"
            f"<td class='num'>{v.mean_residual_ms:+.2f} ms</td>"
            f"<td class='num'>{v.spread_ms:.2f} ms</td><td class='num'>{v.dominance:.1f}</td></tr>")
    for sid in t.no_signal:
        s = profile.speaker(sid)
        body.append(f"<tr><td>—</td><td>{_e(s.name)}</td><td>{s.zone}</td>"
                    f"<td>no signal</td>{_distance_and_arrival(result, s)}"
                    "<td colspan='4'></td></tr>")
    return ("<h3>Per-speaker detail</h3><div class='scroll'><table><tr><th>Visit</th>"
            "<th>Speaker</th><th>Zone</th><th class='num'>Emission</th>"
            "<th class='num'>Distance</th><th class='num'>Arrival at seat (A1/A2)</th>"
            "<th class='num'>n</th>"
            "<th class='num'>Mean residual</th><th class='num'>Spread</th>"
            "<th class='num'>Dominance</th></tr>" + "".join(body) + "</table></div>")


def _checks_list(result: AnalysisResult) -> str:
    sym = {"pass": "✔", "warn": "!", "fail": "✘"}
    items = "".join(f"<li class='{c.status}'>{sym[c.status]} {_e(c.message)}</li>"
                    for c in result.checks)
    return f"<h2>Checks</h2><ul class='checks'>{items}</ul><p class='hint'>{_e(_tally(result))}</p>"


def render_html(result: AnalysisResult) -> str:
    s = result.session
    drift = result.timeline.drift_ppm
    if result.reliable:
        lines = verdict_lines(result)
        verdict = ("<div class='verdict'>"
                   f"<p class='main'>{_e(lines[0])}</p>"
                   + "".join(f"<p>{_e(l)}</p>" for l in lines[1:]) + "</div>")
        sections = (_channel_table(result) if _show_table(result) else "")
        sections += "<h2>Timeline</h2>" + _timeline_svg(result) + _speaker_detail(result)
    else:
        verdict = ("<div class='verdict withheld'><p class='main'>Verdict withheld</p>"
                   + "".join(f"<p>{_e(m)}</p>" for m in _failed_messages(result)) + "</div>")
        sections = ("<h2>Diagnostics (verdict withheld — not reliable)</h2>"
                    + _timeline_svg(result) + _speaker_detail(result))
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>Zone delay report — {_e(s.label)}</title><style>{_CSS}</style></head><body><main>"
        f"<h1>{_e(s.label)}</h1>"
        f"<p class='meta'>Session {_e(s.session_id)} · created {_e(s.created_at)} · "
        f"clock drift {drift:+.1f} ppm</p>"
        f"<p class='hint'>How to read: {_e(HOW_TO_READ)}</p>"
        + verdict + sections + _checks_list(result) + "</main></body></html>")
