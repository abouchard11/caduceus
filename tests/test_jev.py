"""Jev (TypeSafe System One) client: the request body is the documented
{state, model, questions} envelope with a Bearer header, the first-party
endpoint only, every failure mode becomes JevError, usage is accumulated,
and the key is never part of any message."""
import json

import pytest

from caduceus import jev


class FakeOpener:
    def __init__(self, status=200, body=None, raise_exc=None):
        self.status, self.body, self.raise_exc = status, body, raise_exc
        self.requests = []

    def __call__(self, req, timeout):
        self.requests.append((req, timeout))
        if self.raise_exc:
            raise self.raise_exc
        status, body = self.status, self.body

        class R:
            def read(self_inner, n=-1):
                data = json.dumps(body).encode()
                return data if n is None or n < 0 else data[:n]

            def getcode(self_inner):
                return status

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

        R.status = status
        return R()


GOOD = {"model": "jev-latest",
        "answers": {"d": {"type": "choice", "choice": "review", "confidence": 0.9,
                          "probabilities": {"review": 0.9, "general": 0.1}}},
        "usage": {"input_tokens": 100, "output_tokens": 5}}


def test_request_shape_and_auth():
    op = FakeOpener(body=GOOD)
    c = jev.Client(key="k-test", opener=op)
    q = {"d": {"type": "choice", "instructions": "?", "criteria": {"review": "r", "general": "g"}}}
    ans = c.ask("some state", q)
    req, timeout = op.requests[0]
    assert json.loads(req.data.decode()) == {"state": "some state", "model": "jev-latest", "questions": q}
    assert req.get_header("Authorization") == "Bearer k-test"
    assert req.get_header("Content-type") == "application/json"
    assert req.full_url == jev.ENDPOINT and timeout == 10.0 and req.get_method() == "POST"
    assert ans["d"]["choice"] == "review" and c.usage["input_tokens"] == 100 and c.calls == 1
    c.ask({"name": "x"}, q)
    assert c.usage["input_tokens"] == 200 and c.calls == 2


def test_non_200_and_malformed_raise():
    with pytest.raises(jev.JevError) as e:
        jev.Client(key="k-test", opener=FakeOpener(status=400, body={"error": "Invalid request."})).ask("s", {})
    assert "400" in str(e.value) and "k-test" not in str(e.value)
    with pytest.raises(jev.JevError):
        jev.Client(key="k-test", opener=FakeOpener(body={"nope": 1})).ask("s", {})
    with pytest.raises(jev.JevError):
        jev.Client(key="k-test", opener=FakeOpener(raise_exc=TimeoutError())).ask("s", {})
    with pytest.raises(jev.JevError):
        jev.Client(key="k-test", opener=FakeOpener(raise_exc=OSError("conn refused"))).ask("s", {})


def test_http_error_from_urllib_is_wrapped():
    import urllib.error
    import io
    exc = urllib.error.HTTPError(jev.ENDPOINT, 402, "Payment Required", {}, io.BytesIO(b'{"error":"credits"}'))
    with pytest.raises(jev.JevError) as e:
        jev.Client(key="k-test", opener=FakeOpener(raise_exc=exc)).ask("s", {})
    assert "402" in str(e.value)


def test_no_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert jev.available() is False
    with pytest.raises(jev.JevError):
        jev.Client(key="").ask("s", {})


def test_key_from_caduceus_env_file(monkeypatch):
    from caduceus import config
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    config.env_file().write_text("OPENROUTER_API_KEY=x\nTYPESAFE_API_KEY=from-file\n")
    assert jev.available() is True and jev.api_key() == "from-file"


def test_estimate_usd():
    assert jev.estimate_usd({"input_tokens": 1_000_000, "output_tokens": 9}) == pytest.approx(0.042)
    assert jev.estimate_usd({}) == 0.0


def test_oversized_body_is_refused():
    big = {"answers": {"x": {"type": "noul", "noul": 0.5}}, "pad": "z" * (jev.MAX_BODY + 10)}
    with pytest.raises(jev.JevError) as e:
        jev.Client(key="k-test", opener=FakeOpener(body=big)).ask("s", {})
    assert "too large" in str(e.value)
