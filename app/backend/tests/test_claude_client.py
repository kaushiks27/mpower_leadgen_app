"""S-7 Anthropic client — pure payload/response helpers (no network)."""

from __future__ import annotations

from app.email_gen import claude_client as cc


def test_build_payload_shape():
    p = cc.build_payload("SYS", "USER", model="claude-test")
    assert p["model"] == "claude-test"
    assert p["system"] == "SYS"
    assert p["messages"] == [{"role": "user", "content": "USER"}]
    assert p["max_tokens"] == 120


def test_build_payload_defaults_model():
    p = cc.build_payload("s", "u")
    assert p["model"] == cc.DEFAULT_MODEL


def test_extract_text_pulls_first_text_block():
    body = {"content": [{"type": "text", "text": "hello line"}]}
    assert cc.extract_text(body) == "hello line"


def test_extract_text_defensive_on_bad_body():
    assert cc.extract_text({}) == ""
    assert cc.extract_text({"content": "nope"}) == ""
    assert cc.extract_text(None) == ""
