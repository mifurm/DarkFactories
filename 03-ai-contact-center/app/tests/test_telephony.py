"""Telephony (brief §5): simulated provider events drive one neutral state machine through three adapters; native commands are rendered per provider."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from concierge.core.config import Settings
from concierge.features.voice.telephony import (
    ADAPTERS,
    AcsCallAutomationAdapter,
    Action,
    CallMachine,
    RealtimeSipAdapter,
    TeamsPhoneExtensibilityAdapter,
    TelephonyEvent,
    acs_event,
    acs_media_to_pcm,
    acs_metadata_frame,
    adapter_for,
    pcm_to_acs_media,
    sip_event,
    teams_event,
)
from concierge.main import create_app


def acs_script(cid, digit="1"):
    return [acs_event("IncomingCall", cid, **{"from": {"rawId": "4:+4915550001234"}, "incomingCallContext": "ctx-1"}), acs_event("CallConnected", cid), acs_event("PlayCompleted", cid),
            acs_event("RecognizeCompleted", cid, dtmfResult={"tones": [digit]}), acs_event("CallDisconnected", cid)]  # fmt: skip


def teams_script(cid, digit="1"):
    return [teams_event("incoming", cid, source={"identity": {"phone": {"id": "+4915550001234"}}}), teams_event("established", cid), teams_event("play_completed", cid), teams_event("tone", cid, digit=digit), teams_event("terminated", cid)]  # fmt: skip


def sip_script(cid, digit="1"):
    return [sip_event("incoming", cid), sip_event("connected", cid), sip_event("prompt_done", cid), sip_event("consent", cid, recording="granted" if digit == "1" else "declined"), sip_event("ended", cid)]  # fmt: skip


SCRIPTS = {"acs": acs_script, "teams": teams_script, "sip": sip_script}


@pytest.mark.parametrize("provider", ["acs", "teams", "sip"])
def test_every_adapter_drives_the_same_state_machine(provider):
    adapter, machine = ADAPTERS[provider], CallMachine("c1", "wss://x/ws/telephony/c1", provider=provider)
    states, kinds = [], []
    for raw in SCRIPTS[provider]("c1"):
        ev = adapter.translate(raw)
        kinds.append(ev.kind)
        machine.on(ev)
        states.append(machine.state)
    assert states == ["answering", "connected", "consent", "listening", "disconnected"]
    assert machine.consent == "granted" and machine.caller and "4915550001234" in machine.caller
    assert [a.kind for a in machine.actions][:4] == ["answer", "bind_voice_session", "play", "recognize_dtmf"]
    assert machine.actions[-1].kind == "close_conversation"
    assert kinds[0] == "incoming_call" and kinds[-1] == "call_disconnected"


@pytest.mark.parametrize("provider", ["acs", "teams", "sip"])
def test_consent_is_only_granted_by_an_explicit_yes(provider):
    adapter = ADAPTERS[provider]
    for digit, expect in (("1", "granted"), ("2", "declined"), ("7", "declined")):
        m = CallMachine("c", "wss://x", provider=provider)
        for raw in SCRIPTS[provider]("c", digit)[:4]:
            m.on(adapter.translate(raw))
        assert m.consent == expect, (provider, digit)
    m = CallMachine("c", "wss://x")  # silence / timeout never grants recording consent
    for ev in (TelephonyEvent("incoming_call", "c"), TelephonyEvent("call_connected", "c"), TelephonyEvent("play_completed", "c"), TelephonyEvent("recognize_failed", "c")):
        m.on(ev)
    assert m.consent == "declined" and m.state == "listening"
    assert any(a.kind == "record_consent" and a.params["via"] == "timeout-declined" for a in m.actions)


def test_machine_ignores_out_of_order_duplicate_and_late_events():
    m = CallMachine("c", "wss://x")
    assert m.on(TelephonyEvent("play_completed", "c")) == [] and m.state == "idle"
    assert m.on(TelephonyEvent("recognize_completed", "c", {"tone": "1"})) == [] and m.consent is None
    assert [a.kind for a in m.on(TelephonyEvent("incoming_call", "c", {"from": "+49"}))] == ["answer"]
    assert m.on(TelephonyEvent("incoming_call", "c", {"from": "+49"})) == [], "an at-least-once webhook redelivery must not answer the call twice"
    m.on(TelephonyEvent("call_connected", "c"))
    assert m.on(TelephonyEvent("call_connected", "c")) == []
    assert [a.kind for a in m.on(TelephonyEvent("call_disconnected", "c"))] == ["close_conversation"]
    assert m.on(TelephonyEvent("call_connected", "c")) == [] and m.state == "disconnected", "a late event never resurrects a finished call"
    assert m.on(TelephonyEvent("call_disconnected", "c")) == []
    assert sum("ignored" in entry for entry in m.log) >= 5


def test_transfer_requires_a_listening_call_and_ends_with_hangup():
    m = CallMachine("c", "wss://x")
    assert m.on(TelephonyEvent("transfer_requested", "c")) == []
    for ev in (TelephonyEvent("incoming_call", "c"), TelephonyEvent("call_connected", "c"), TelephonyEvent("play_completed", "c"), TelephonyEvent("consent_captured", "c", {"recording": "granted"})):
        m.on(ev)
    assert m.on(TelephonyEvent("transfer_requested", "c", {"target": "sip:escalations@contoso-home.example"}))[0].kind == "transfer" and m.state == "transferring"
    assert m.on(TelephonyEvent("transfer_accepted", "c"))[0].kind == "hangup" and m.state == "disconnected"


def test_native_commands_are_rendered_per_provider():
    call = {"call_id": "c1", "context": "ctx-1", "caller": "+4915550001234", "model": "gpt-realtime-2.1-mini"}
    answer = Action("answer", {"callback_uri": "/cb", "media_streaming": {"transport_url": "wss://x/ws", "audio_channel": "unmixed"}})
    transfer = Action("transfer", {"target": "sip:escalations@contoso-home.example"})
    acs, teams, sip = ADAPTERS["acs"], ADAPTERS["teams"], ADAPTERS["sip"]
    a = acs.render(answer, call)
    assert a["op"] == "AnswerCall" and a["body"]["mediaStreamingOptions"]["audioFormat"] == "pcm24KMono" and a["body"]["incomingCallContext"] == "ctx-1"
    assert acs.render(transfer, call)["path"].endswith(":transferToParticipant")
    t = teams.render(answer, call)
    assert t["path"] == "/communications/calls/c1/answer" and teams.render(Action("hangup"), call)["method"] == "DELETE"
    s = sip.render(answer, call)
    assert s["path"] == "/openai/v1/realtime/calls/c1/accept" and s["body"]["model"] == "gpt-realtime-2.1-mini"
    assert sip.render(transfer, call)["body"] == {"target_uri": "sip:escalations@contoso-home.example"} and sip.render(transfer, call)["op"] == "refer"
    for ad in (acs, teams, sip):
        assert ad.render(Action("bind_voice_session"), call) is None, "internal actions are never sent to a provider"


def test_adapter_selection_by_payload_shape_and_explicit_provider():
    assert adapter_for(acs_event("IncomingCall", "c")).id == "acs"
    assert adapter_for(teams_event("incoming", "c")).id == "teams"
    assert adapter_for(sip_event("incoming", "c")).id == "sip"
    assert adapter_for({}, "teams").id == "teams"
    with pytest.raises(ValueError):
        adapter_for({"hello": "world"})
    with pytest.raises(ValueError):
        adapter_for({}, "carrier-pigeon")
    with pytest.raises(ValueError):
        AcsCallAutomationAdapter().translate({"type": "Microsoft.Communication.Unknown"})
    with pytest.raises(ValueError):
        TeamsPhoneExtensibilityAdapter().translate({"resourceData": {"@odata.type": "#microsoft.graph.chatMessage"}, "resource": "/x"})
    with pytest.raises(ValueError):
        RealtimeSipAdapter().translate({"type": "realtime.call.unknown"})


def test_providers_are_labelled_honestly():
    assert ADAPTERS["acs"].info["strategic"] is False and "30 Sep 2028" in ADAPTERS["acs"].info["status"]
    assert ADAPTERS["teams"].info["strategic"] and "Simulator-backed" in ADAPTERS["teams"].info["status"]
    assert ADAPTERS["sip"].info["strategic"] and "preview" in ADAPTERS["sip"].info["status"]


def test_acs_media_frames_round_trip_pcm():
    pcm = bytes(range(256)) * 4
    assert acs_media_to_pcm(pcm_to_acs_media(pcm)) == pcm
    assert acs_media_to_pcm({"kind": "AudioData", "audioData": {"silent": True}}) == b"\x00\x00" * 480
    assert acs_media_to_pcm(acs_metadata_frame()) is None


@pytest.fixture
def client():
    with TestClient(create_app(Settings(mode="offline"))) as c:
        yield c


@pytest.mark.parametrize("provider", ["sip", "teams", "acs"])
def test_simulated_call_end_to_end_through_the_api(client, provider):
    r = client.post("/api/voice/telephony/simulate", json={"scenario": "damaged_sofa", "provider": provider})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provisioned_pstn"] is False and body["provider"] == provider
    assert [t["state"] for t in body["timeline"]] == ["answering", "connected", "consent", "listening", "disconnected"]
    assert body["timeline"][0]["commands"], "the answer command is rendered natively"
    assert body["final"]["consent"] == "granted"
    assert body["exchange"]["agent_lines"], "the voice session answered the caller (text input)"
    calls = client.get("/api/voice/telephony/calls").json()
    assert any(c["call_id"] == body["call_id"] for c in calls)


def test_declined_and_silent_consent_and_early_hangup_and_transfer(client):
    assert client.post("/api/voice/telephony/simulate", json={"scenario": "decline_consent", "provider": "acs"}).json()["final"]["consent"] == "declined"
    assert client.post("/api/voice/telephony/simulate", json={"scenario": "silent_consent", "provider": "teams"}).json()["final"]["consent"] == "declined"
    early = client.post("/api/voice/telephony/simulate", json={"scenario": "hangup_early", "provider": "sip"}).json()
    assert early["final"]["state"] == "disconnected" and early["final"]["consent"] is None
    tr = client.post("/api/voice/telephony/simulate", json={"scenario": "transfer", "provider": "sip"}).json()
    assert [t["event"] for t in tr["timeline"]][-2:] == ["transfer requested (escalation)", "transfer accepted"]
    assert any("refer" in t["commands"] for t in tr["timeline"]) and tr["final"]["state"] == "disconnected"


def test_webhook_accepts_provider_payloads_and_validation_handshakes(client):
    assert client.post("/api/voice/telephony/events", json=sip_event("incoming", "wh-1")).json()["calls"][0]["state"] == "answering"
    graph = {"value": [teams_event("incoming", "wh-2")]}
    assert client.post("/api/voice/telephony/events", json=graph).json()["calls"][0]["provider"] == "teams"
    assert client.post("/api/voice/telephony/events?validationToken=abc123", json={}).text == "abc123"
    eg = [{"eventType": "Microsoft.EventGrid.SubscriptionValidationEvent", "data": {"validationCode": "code-1"}}]
    assert client.post("/api/voice/telephony/events", json=eg).json() == {"validationResponse": "code-1"}
    bad = client.post("/api/voice/telephony/events", json={"type": "Microsoft.Communication.Nope"})
    assert bad.status_code == 422 and bad.json()["detail"]["error"] == "unsupported_event"
    cfg = client.get("/api/voice/telephony/adapters").json()
    assert cfg["pstn_provisioned"] is False and {a["id"] for a in cfg["adapters"]} == {"sip", "teams", "acs"}
