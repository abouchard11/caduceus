"""Domain classification: Jev's first slot inside the harness.

A council question gets one Choice question over the ten domains plus
`general`. The answer is a calibrated distribution; the top entry is the
run's domain (what the ledger settles against) and, when confidence is
below BLEND_BELOW, the top two weight the believability blend in
Council._finish (docs/compile-design.md §4.1, Decision 13). With no key, on
any error, or on a malformed answer the keyword classifier answers instead,
so a council never waits on Jev.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import config, jev

BLEND_BELOW = 0.6
QUESTION_ID = "domain"


@dataclass
class Classification:
    top: str
    probabilities: Dict[str, float]
    confidence: float
    source: str                       # "jev" | "keyword"
    warnings: List[str] = field(default_factory=list)

    @property
    def needs_blend(self) -> bool:
        return self.source == "jev" and self.confidence < BLEND_BELOW

    def blend_domains(self, k: int = 2) -> List[Tuple[str, float]]:
        """Top-k domains with weights renormalised to sum to 1."""
        top = sorted(self.probabilities.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
        total = sum(w for _, w in top) or 1.0
        return [(d, w / total) for d, w in top]


def build_question() -> Dict[str, dict]:
    return {QUESTION_ID: {
        "type": "choice",
        "instructions": "Which domain is this council question in?",
        "criteria": dict(config.DOMAIN_DESCRIPTIONS),
    }}


def _keyword(text: str) -> Classification:
    top = config.classify_domain(text)
    return Classification(top=top, probabilities={top: 1.0}, confidence=1.0, source="keyword")


def domain_distribution(text: str, client=None, allow_jev: bool = True) -> Classification:
    if client is None:
        if not allow_jev or not jev.available():
            return _keyword(text)
        client = jev.Client()
    try:
        answers = client.ask(text, build_question())
        answer = answers[QUESTION_ID]
        raw = answer["probabilities"]
        known = set(config.DOMAIN_DESCRIPTIONS)
        probs = {str(d): float(p) for d, p in raw.items() if str(d) in known and float(p) >= 0.0}
        total = sum(probs.values())
        if not probs or total <= 0.0:
            raise ValueError("no usable probabilities")
        probs = {d: p / total for d, p in probs.items()}
        top = max(probs.items(), key=lambda kv: (kv[1], kv[0]))[0]
        confidence = float(answer.get("confidence", probs[top]))
        return Classification(top=top, probabilities=probs, confidence=confidence, source="jev")
    except (jev.JevError, KeyError, TypeError, ValueError, AttributeError) as e:
        out = _keyword(text)
        out.warnings.append(f"jev classifier fell back to keywords: {e.__class__.__name__}: {e}")
        return out
