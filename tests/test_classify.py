"""Domain classification is Jev's first slot inside the harness: a Choice
over the ten domains plus `general`, with the keyword classifier as the
fallback whenever there is no key, an error, or a malformed answer. The
distribution feeds the believability blend; it never picks a lead."""
from caduceus import classify, config
from caduceus.jev import JevError


class StubClient:
    def __init__(self, answers=None, exc=None):
        self.answers, self.exc, self.calls = answers, exc, 0

    def ask(self, state, questions):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.answers


def _choice(probs, confidence):
    top = max(probs, key=probs.get)
    return {"domain": {"type": "choice", "choice": top, "confidence": confidence,
                       "probabilities": probs}}


def test_keyword_fallback_without_client(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    c = classify.domain_distribution("please review and audit this diff", client=None, allow_jev=False)
    assert c.source == "keyword" and c.top == "review"
    assert c.probabilities == {"review": 1.0} and c.confidence == 1.0
    assert c.blend_domains() == [("review", 1.0)]


def test_no_key_means_keyword_even_when_allowed(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    c = classify.domain_distribution("fix the bug", client=None, allow_jev=True)
    assert c.source == "keyword" and c.top == "implementation"


def test_jev_choice_used_when_available():
    st = StubClient(_choice({"strategy": 0.55, "research": 0.40, "general": 0.05}, 0.55))
    c = classify.domain_distribution("which market next?", client=st)
    assert st.calls == 1
    assert c.source == "jev" and c.top == "strategy" and c.confidence == 0.55
    (d1, w1), (d2, w2) = c.blend_domains()
    assert d1 == "strategy" and abs(w1 - 0.55 / 0.95) < 1e-9
    assert d2 == "research" and abs(w2 - 0.40 / 0.95) < 1e-9


def test_jev_error_falls_back():
    c = classify.domain_distribution("fix the bug", client=StubClient(exc=JevError("boom")))
    assert c.source == "keyword" and c.top == "implementation"


def test_malformed_answer_falls_back():
    c = classify.domain_distribution("fix the bug", client=StubClient({"domain": {"type": "choice"}}))
    assert c.source == "keyword"
    c2 = classify.domain_distribution("fix the bug", client=StubClient({"domain": {"probabilities": {"bogus": 1.0}}}))
    assert c2.source == "keyword"


def test_partial_probabilities_renormalised():
    st = StubClient({"domain": {"type": "choice", "choice": "comms", "confidence": 0.8,
                                "probabilities": {"comms": 0.77, "general": 0.20}}})
    c = classify.domain_distribution("rewrite this email", client=st)
    assert abs(sum(c.probabilities.values()) - 1.0) < 1e-9 and c.top == "comms"
    assert set(c.probabilities) == {"comms", "general"}


def test_question_covers_every_domain_plus_general():
    q = classify.build_question()
    assert q["domain"]["type"] == "choice"
    assert set(q["domain"]["criteria"]) == set(config.DOMAIN_KEYWORDS) | {"general"}
    assert all(isinstance(v, str) and v for v in q["domain"]["criteria"].values())


def test_blend_only_below_threshold():
    hi = classify.Classification("review", {"review": 0.9, "testing": 0.1}, 0.9, "jev")
    lo = classify.Classification("review", {"review": 0.5, "testing": 0.5}, 0.5, "jev")
    assert hi.needs_blend is False and lo.needs_blend is True
    assert classify.BLEND_BELOW == 0.6
