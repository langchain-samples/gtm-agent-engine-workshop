from types import SimpleNamespace
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from gtm_agent import data_service
from gtm_agent.gtm_agent import send_prospect_email


RUNTIME = SimpleNamespace(config={"metadata": {}})


def call_send(prospect, *, override=False):
    return send_prospect_email.func(
        prospect,
        "Hello",
        "Checking in.",
        RUNTIME,
        from_rep={"email": "rep@example.com", "name": "Rep"},
        override=override,
    )


def test_supplied_disqualified_prospect_is_blocked(monkeypatch):
    monkeypatch.setattr(data_service, "get_prospect_record", lambda _: {})

    result = call_send({"prospect_id": "LEAD-1", "email": "lead@example.com", "disqualified": True})

    assert result == {
        "status": "blocked",
        "reason": "prospect_disqualified",
        "prospect_id": "LEAD-1",
        "to": "lead@example.com",
    }
    assert "message_id" not in result


def test_canonical_disqualified_prospect_is_blocked(monkeypatch):
    monkeypatch.setattr(
        data_service,
        "get_prospect_record",
        lambda _: {"disqualified": True},
    )

    result = call_send({"prospect_id": "LEAD-1", "email": "lead@example.com"})

    assert result["status"] == "blocked"
    assert "message_id" not in result


def test_override_sends_canonical_disqualified_prospect(monkeypatch):
    monkeypatch.setattr(
        data_service,
        "get_prospect_record",
        lambda _: {"disqualified": True},
    )

    result = call_send({"prospect_id": "LEAD-1", "email": "lead@example.com"}, override=True)

    assert result["status"] == "sent"
    assert result["message_id"].startswith("msg-")


def test_qualified_prospect_is_sent(monkeypatch):
    monkeypatch.setattr(
        data_service,
        "get_prospect_record",
        lambda _: {"disqualified": False},
    )

    result = call_send({"prospect_id": "LEAD-1", "email": "lead@example.com", "disqualified": False})

    assert result["status"] == "sent"
    assert result["message_id"].startswith("msg-")
