"""GJ-1 offline: damaged sofa in German, resolved by the AI swarm (auth -> RAG -> tools -> confirmation -> wrap-up -> QA)."""

from __future__ import annotations

from conftest import otp_of, say


async def test_damaged_sofa_german_end_to_end(svc):
    conv = await svc.orchestrator.start(language="de", recording_consent="granted")
    assert conv.messages[0].flags == ["disclosure"]  # AI disclosure first, always
    assert conv.consent.recording == "granted" and conv.consent.ai_disclosure_shown_at

    r1 = await say(svc, conv.id, "Hallo, mein Sofa ist beschädigt angekommen. Bestellnummer CH-100231.")
    conv = await svc.store.get(conv.id)
    assert conv.language == "de" and conv.active_agent == "authentication"
    assert "start_verification" in r1["tools"] and not conv.identity.verified

    r2 = await say(svc, conv.id, f"Der Code ist {otp_of(conv)}")
    conv = await svc.store.get(conv.id)
    assert conv.identity.verified and conv.identity.level == 1
    assert "verify_otp" in r2["tools"] and "lookup_order" in r2["tools"]
    assert r2["message"]["citations"], "damage policy must be cited"
    assert "379" in r2["message"]["text"] and "[K1]" in r2["message"]["text"]

    await say(svc, conv.id, "Ich möchte eine Erstattung bitte, der erste Termin passt.")
    conv = await svc.store.get(conv.id)
    assert {p.tool for p in conv.pending} == {"initiate_return", "schedule_pickup", "issue_refund"}
    assert not any(s["tool"] == "issue_refund" for s in conv.steps), "nothing executes before the customer confirms"

    r4 = await say(svc, conv.id, "Ja, bitte so machen.")
    conv = await svc.store.get(conv.id)
    done = [s["tool"] for s in conv.steps if s["status"] == "ok"]
    assert "initiate_return" in done and "schedule_pickup" in done and "issue_refund" in done
    refunds = await svc.backoffice.refunds_for("CH-100231")
    assert len(refunds) == 1 and refunds[0]["amount"] == 379.0
    assert "send_confirmation" in r4["tools"]

    r5 = await say(svc, conv.id, "Nein danke, das war's.")
    await svc.drain()
    conv = await svc.store.get(conv.id)
    assert conv.status == "resolved" and conv.handler == "ai"
    assert conv.wrapup["disposition"] == "RESOLVED_REFUND_ISSUED" and conv.qa["overall"] >= 70
    assert r5["status"] == "resolved"


async def test_platform_requests_the_refund_the_model_forgot(svc):
    """Live regression: the model booked return + pickup, announced the refund and never called issue_refund - the platform requests it itself."""
    from concierge.engine.stub_brain import brain as stub

    def forgetful(messages, tools, hints):
        res = stub(messages, tools, hints)
        if any(tc.name == "issue_refund" for tc in res.tool_calls):
            res.tool_calls = [tc for tc in res.tool_calls if tc.name != "issue_refund"]
            res.text = res.text or "Die Abholung wird gebucht. Gibt es sonst noch etwas?"
        return res

    svc.llm.brain = forgetful
    conv = await svc.orchestrator.start(language="de", recording_consent="granted")
    await say(svc, conv.id, "Hallo, mein Sofa ist beschädigt angekommen. Bestellnummer CH-100231.")
    await say(svc, conv.id, f"Der Code ist {otp_of(await svc.store.get(conv.id))}")
    await say(svc, conv.id, "Ich möchte eine Erstattung bitte, der erste Termin passt.")
    await say(svc, conv.id, "Ja, bitte so machen.")
    conv = await svc.store.get(conv.id)
    done = [s["tool"] for s in conv.steps if s["status"] == "ok"]
    assert "initiate_return" in done and "schedule_pickup" in done and "issue_refund" not in done
    assert [p.tool for p in conv.pending] == ["issue_refund"], "the refund is requested by the platform and waits for the customer's confirmation"
    assert await svc.backoffice.refunds_for("CH-100231") == []
    assert any(a["action"] == "agent.refund_step_enforced" for a in await svc.audit.recent(50))

    await say(svc, conv.id, "Ja, bitte erstatten.")
    refunds = await svc.backoffice.refunds_for("CH-100231")
    assert len(refunds) == 1 and refunds[0]["amount"] == 379.0
