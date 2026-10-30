"""S-8 Instantly mapper — pure deterministic payload transforms (no DB/network).

Locks the load-bearing mappings: schedule day-index ("0"=Sun..="6"=Sat), send
window timing, sequence wait_days→delay shift, placeholder remap, HTML body, and
the full campaign + lead payload shapes. Word-for-word content fidelity.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.instantly import mapper


def _step(wait_days, subject, body):
    return SimpleNamespace(wait_days=wait_days, subject=subject, body=body)


def test_remap_placeholders_only_touches_known_chips():
    src = "Hi {first_name} at {company}. {icebreaker} — best, {sender_name}"
    out = mapper.remap_placeholders(src)
    assert out == "Hi {{firstName}} at {{companyName}}. {{icebreaker}} — best, {sender_name}"


def test_to_html_escapes_text_but_keeps_merge_tags_and_breaks():
    out = mapper._body_html("Line 1 & <ok>\nHi {first_name}")
    # & and < are escaped; newline -> <br>; merge tag survives.
    assert out == "Line 1 &amp; &lt;ok&gt;<br>\nHi {{firstName}}"


def test_timezone_normalizes_deprecated_alias_to_canonical():
    # Instantly's enum is canonical IANA — the deprecated India alias must map.
    assert mapper.to_instantly_timezone("Asia/Calcutta") == "Asia/Kolkata"
    # already-canonical zones pass through unchanged.
    assert mapper.to_instantly_timezone("Asia/Kolkata") == "Asia/Kolkata"
    assert mapper.to_instantly_timezone("America/Chicago") == "America/Chicago"


def test_days_object_is_full_sunday_first_set():
    days = mapper.to_days_object("mon,tue,wed,thu,fri")
    assert days == {
        "0": False,  # sun
        "1": True,   # mon
        "2": True,   # tue
        "3": True,   # wed
        "4": True,   # thu
        "5": True,   # fri
        "6": False,  # sat
    }


def test_days_object_handles_weekend_and_casing():
    assert mapper.to_days_object("Sat,SUN")["0"] is True
    assert mapper.to_days_object("Sat,SUN")["6"] is True
    assert mapper.to_days_object("")["1"] is False


def test_sequence_delay_is_next_step_wait_days():
    steps = [
        _step(0, "S1", "Body 1"),
        _step(3, "S2", "Body 2"),
        _step(5, "S3", "Body 3"),
    ]
    out = mapper.to_sequence_steps(steps)
    # step i delay = wait_days of step i+1; last = 0.
    assert [s["delay"] for s in out] == [3, 5, 0]
    assert all(s["type"] == "email" for s in out)
    assert out[0]["variants"][0]["subject"] == "S1"


def test_campaign_payload_shape_matches_instantly_v2():
    campaign = SimpleNamespace(
        name="Drone OEMs — India",
        send_start_hour=9,
        send_end_hour=17,
        send_days="mon,wed,fri",
        timezone="Asia/Calcutta",  # deprecated alias → normalized on push
    )
    steps = [_step(0, "Quick one {first_name}", "Hi {first_name}\n{icebreaker}")]
    payload = mapper.to_campaign_payload(campaign, steps)

    assert payload["name"] == "Drone OEMs — India"
    sched = payload["campaign_schedule"]["schedules"][0]
    assert sched["timing"] == {"from": "09:00", "to": "17:00"}
    assert sched["timezone"] == "Asia/Kolkata"  # normalized to Instantly's enum
    assert sched["days"]["1"] is True and sched["days"]["3"] is True
    variant = payload["sequences"][0]["steps"][0]["variants"][0]
    assert variant["subject"] == "Quick one {{firstName}}"
    assert variant["body"] == "Hi {{firstName}}<br>\n{{icebreaker}}"


def test_lead_payload_carries_icebreaker_as_custom_variable():
    lead = SimpleNamespace(
        email="a@b.com",
        first_name="Asha",
        last_name="Rao",
        icebreaker="saw your fleet work",
        company=SimpleNamespace(name="DroneCo"),
    )
    payload = mapper.to_lead_payload(lead)
    assert payload == {
        "email": "a@b.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "company_name": "DroneCo",
        "personalization": "saw your fleet work",
        "custom_variables": {"icebreaker": "saw your fleet work"},
    }
