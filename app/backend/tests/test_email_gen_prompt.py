"""S-7 icebreaker prompt builders + output sanitizer (pure, no I/O)."""

from __future__ import annotations

import json

from app.email_gen import prompt as p


def test_extract_context_pulls_signals_from_scrape_raw():
    raw = json.dumps({"headline": "Drone fleet ops at AgriWings", "noise": 1})
    ctx = p.extract_context(
        {"first_name": "Asha", "title": "Ops Lead", "company": "AgriWings", "location": "Pune"},
        raw,
    )
    assert ctx["first_name"] == "Asha"
    assert "Drone fleet ops at AgriWings" in ctx["signals"]
    assert p.has_signal(ctx) is True


def test_has_signal_false_when_only_a_name():
    ctx = p.extract_context({"first_name": "Bob", "title": "", "company": "", "location": ""}, None)
    assert ctx["signals"] == []
    assert p.has_signal(ctx) is False


def test_has_signal_true_with_title_or_company_even_without_scrape():
    ctx = p.extract_context({"first_name": "Bob", "title": "Founder", "company": "", "location": ""}, None)
    assert p.has_signal(ctx) is True


def test_extract_context_survives_bad_json():
    ctx = p.extract_context({"first_name": "X", "title": "T", "company": "C", "location": ""}, "{not json")
    assert ctx["signals"] == []  # bad blob ignored, no crash


def test_sanitize_strips_quotes_and_collapses_lines():
    assert p.sanitize('  "saw your drone work.\nnice."  ') == "saw your drone work. nice."


def test_sanitize_replaces_em_dash_with_comma():
    out = p.sanitize("your fleet — biggest in the region")
    assert "—" not in out
    assert "," in out


def test_sanitize_drops_leading_label():
    assert p.sanitize("Icebreaker: hey, quick note") == "hey, quick note"


def test_looks_human_rejects_ai_tell_words():
    assert p.looks_human("noticed your team runs a big drone fleet") is True
    assert p.looks_human("your work is a testament to robust synergy") is False


def test_build_user_prompt_includes_real_fields_only():
    ctx = p.extract_context({"first_name": "Asha", "title": "Ops", "company": "AgriWings", "location": ""}, None)
    up = p.build_user_prompt(ctx)
    assert "Asha" in up and "AgriWings" in up
    assert "Location:" not in up  # empty field omitted
