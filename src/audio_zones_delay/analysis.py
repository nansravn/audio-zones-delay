"""The whole analysis pipeline: detect, assign, fit, answer, check."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .answers import Answers, compute_answers
from .assign import Assignment, assign_detections
from .checks import Check, is_reliable, run_checks
from .detect import detect_signatures
from .model import SessionLog
from .signature import ANALYSIS_RATE, SignatureParams, make_signature
from .timeline import Timeline, fit_timeline


@dataclass
class AnalysisResult:
    session: SessionLog
    assignment: Assignment
    timeline: Timeline
    answers: Answers
    checks: list[Check]
    reliable: bool


def analyze(session: SessionLog, recording: np.ndarray,
            sample_rate: int = ANALYSIS_RATE) -> AnalysisResult:
    """Analyze a recording of ``session``. Raises AlignmentError if they do not match."""
    template = make_signature(sample_rate, SignatureParams(**session.signature))
    detections = detect_signatures(recording, sample_rate, template, session.period_s)
    assignment = assign_detections(detections, session)
    timeline = fit_timeline(assignment, session)
    answers = compute_answers(timeline, session.profile)
    checks = run_checks(assignment, timeline, answers, session)
    return AnalysisResult(session, assignment, timeline, answers, checks, is_reliable(checks))
