"""DevX cell-5 fix batch: UA header, credential-less mode, worker-profile auth,
review_criteria normalization (fail-closed), register() PoW flow."""
import hashlib
import json

import pytest

from getterdone import GetterDone, __version__
from getterdone.client import _normalize_review_criteria, _solve_pow
from getterdone.exceptions import AuthenticationError


def _mock_response(mocker, payload):
    resp = mocker.MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = mocker.MagicMock(return_value=False)
    return mocker.patch("urllib.request.urlopen", return_value=resp)


# ── User-Agent (the WAF fix) ─────────────────────────────────────────────────

def test_every_request_sends_a_user_agent(mocker):
    """No UA → Cloudflare 403 error 1010 on every call (cell-5 blocker #1)."""
    urlopen = _mock_response(mocker, {"data": {"available": True}})
    GetterDone(api_key="gd_a:b").check_agent_name("Probe")
    req = urlopen.call_args[0][0]
    ua = req.get_header("User-agent")
    assert ua == f"getterdone-python/{__version__}"
    assert "urllib" not in (ua or "")


# ── Credential-less mode ─────────────────────────────────────────────────────

def test_credentialless_client_allows_unauthenticated_calls(mocker, monkeypatch):
    monkeypatch.delenv("GETTERDONE_API_KEY", raising=False)
    _mock_response(mocker, {"data": {"available": False}})
    gd = GetterDone()  # must NOT raise (cell-5 finding #5)
    assert gd.check_agent_name("Taken") is False


def test_credentialless_client_raises_on_authenticated_call(monkeypatch):
    monkeypatch.delenv("GETTERDONE_API_KEY", raising=False)
    gd = GetterDone()
    with pytest.raises(AuthenticationError, match="No API key"):
        gd.get_balance()


def test_malformed_key_still_rejected():
    with pytest.raises(AuthenticationError, match="Invalid GETTERDONE_API_KEY"):
        GetterDone(api_key="no-colon-here")


# ── Worker profile is authenticated ──────────────────────────────────────────

def test_get_worker_profile_sends_bearer_token(mocker):
    gd = GetterDone(api_key="gd_a:b")
    mocker.patch.object(gd, "_get_token", return_value="tok")
    urlopen = _mock_response(mocker, {"data": {"nickname": "w"}})
    gd.get_worker_profile("w1")
    req = urlopen.call_args[0][0]
    assert req.get_header("Authorization") == "Bearer tok"


# ── review_criteria fail-closed normalization ────────────────────────────────

def test_review_criteria_snake_case_normalized(mocker):
    gd = GetterDone(api_key="gd_a:b")
    mocker.patch.object(gd, "_get_token", return_value="tok")
    urlopen = _mock_response(mocker, {"data": {"id": "t1"}})
    gd.create_task(
        title="Valid title here", description="A sufficiently long description.",
        reward=5.0, location={"remote": True},
        review_criteria={"min_images": 1, "min_text_length": 20, "keywords": ["x"]},
    )
    sent = json.loads(urlopen.call_args[0][0].data)
    assert sent["reviewCriteria"] == {"minImages": 1, "minTextLength": 20, "keywords": ["x"]}


def test_review_criteria_unknown_key_raises_not_silently_dropped():
    """The server drops unknown keys → proof requirement silently disabled.
    The SDK must refuse instead (fail closed) — cell-5 finding #2."""
    with pytest.raises(ValueError, match="Unknown review_criteria key"):
        _normalize_review_criteria({"min_imgaes": 1})


# ── register() PoW flow ──────────────────────────────────────────────────────

def test_solve_pow_satisfies_difficulty():
    sol = _solve_pow("nonce123", 12)
    d = hashlib.sha256(("nonce123" + sol).encode()).digest()
    assert d[0] == 0 and (d[1] >> 4) == 0


def test_register_solves_challenge_and_posts(mocker, monkeypatch):
    # Ambient (even malformed) env key must not break registration.
    monkeypatch.setenv("GETTERDONE_API_KEY", "malformed-no-colon")
    responses = [
        {"data": {"challengeId": "ch1", "nonce": "n0", "difficulty": 8, "expiresAt": 1}},
        {"data": {"agent": {"id": "a1"}, "clientId": "gd_agent_x",
                  "clientSecret": "gd_secret_y", "apiKey": "gd_agent_x:gd_secret_y"}},
    ]
    resp = mocker.MagicMock()
    resp.read.side_effect = [json.dumps(r).encode() for r in responses]
    resp.__enter__ = lambda s: s
    resp.__exit__ = mocker.MagicMock(return_value=False)
    urlopen = mocker.patch("urllib.request.urlopen", return_value=resp)

    creds = GetterDone.register("MyAgent")
    assert creds["apiKey"] == "gd_agent_x:gd_secret_y"

    reg_req = urlopen.call_args_list[1][0][0]
    sent = json.loads(reg_req.data)
    assert sent["name"] == "MyAgent"
    assert sent["challengeId"] == "ch1"
    # Solution actually satisfies the challenge difficulty.
    d = hashlib.sha256(("n0" + sent["solution"]).encode()).digest()
    assert d[0] == 0
    # Honest measured timing — no >=50 clamp.
    assert isinstance(sent["timing"], int) and sent["timing"] >= 0
    assert sent["environment"].startswith("python:")
