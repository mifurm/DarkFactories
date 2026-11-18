"""Tool policy (brief §5): caps and approvals, idempotent retries, authentication gate, cross-customer rejection, allow-lists, confirmations, audit."""

from __future__ import annotations

import asyncio

from concierge.engine.tools import ToolContext


async def make_ctx(svc, customer="CU-1001", level=1, agent="resolution", actor="ai", approved=False, lang="en"):
    conv = await svc.orchestrator.start(language=lang, recording_consent="granted")
    if customer:
        conv.identity.verified, conv.identity.level, conv.identity.customer_id, conv.identity.method = True, level, customer, "otp"
    return ToolContext(svc=svc, conv=conv, agent=agent, actor=actor, cfg=await svc.configs.active(), approved=approved)


async def call(ctx, name, **args):
    return await ctx.svc.tools.execute(ctx, name, args)


async def confirmed(ctx, name, **args):
    r = await call(ctx, name, **args)
    if r.status == "confirmation_required":
        for p in ctx.conv.pending:
            p.confirmed = True
        r = await call(ctx, name, **args)
    return r


async def test_unauthenticated_session_cannot_read_account_data(svc):
    ctx = await make_ctx(svc, customer=None)
    for name, args in [("lookup_customer", {}), ("list_orders", {}), ("lookup_order", {"order_id": "CH-100231"}), ("track_shipment", {"order_id": "CH-100231"})]:
        r = await call(ctx, name, **args)
        assert r.status == "blocked" and r.data["error"] == "authentication_required", name
        assert r.switch_agent == "authentication"
        assert "Becker" not in str(r.data) and "Nordby" not in str(r.data)


async def test_cross_customer_access_is_rejected_uniformly_and_audited(svc):
    ctx = await make_ctx(svc, customer="CU-1002")  # Mark Thompson asks about Anna Becker's order
    r = await call(ctx, "lookup_order", order_id="CH-100231")
    ghost = await call(ctx, "lookup_order", order_id="CH-999999")
    assert r.status == "blocked" and r.data["error"] == "order_not_found"
    assert r.data == ghost.data, "foreign and non-existent orders must be indistinguishable (no enumeration)"
    assert "Nordby" not in str(r.data) and "Anna" not in str(r.data)
    assert "fraud_suspected" not in ctx.conv.risk_flags
    await call(ctx, "lookup_order", order_id="CH-100232")
    assert "fraud_suspected" in ctx.conv.risk_flags, "repeated probing raises a fraud risk flag"
    actions = [a["action"] for a in await svc.audit.recent(50)]
    assert "security.cross_customer_access" in actions


async def test_allow_list_is_enforced_in_code_not_only_in_prompts(svc):
    ctx = await make_ctx(svc, agent="greeter")
    r = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged sofa")
    assert r.status == "blocked" and r.data["error"] == "tool_not_allowed"
    assert ctx.conv.counters["forbidden_tool_attempts"] == 1
    unknown = await call(ctx, "wire_transfer", amount=1)
    assert unknown.status == "blocked"
    assert await svc.backoffice.refunds_for("CH-100231") == []
    assert any(a["action"] == "tool.blocked" for a in await svc.audit.recent(10))


async def test_refund_needs_return_and_explicit_customer_confirmation_then_executes_once(svc):
    ctx = await make_ctx(svc)
    no_return = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged on delivery")
    assert no_return.status == "error" and no_return.data["error"] == "return_required"

    first = await call(ctx, "initiate_return", order_id="CH-100231", reason="damaged", resolution="refund")
    assert first.status == "error" and first.data["error"] == "customer_choice_required", "the model may not pick replacement or refund for the customer"
    ctx.conv.entities["choice"] = "refund"
    first = await call(ctx, "initiate_return", order_id="CH-100231", reason="damaged", resolution="refund")
    assert first.status == "confirmation_required" and not await svc.backoffice.returns_for("CH-100231")
    plan = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged on delivery")
    assert plan.status == "confirmation_required" and await svc.backoffice.refunds_for("CH-100231") == []

    for p in ctx.conv.pending:
        p.confirmed = True
    assert (await call(ctx, "initiate_return", order_id="CH-100231", reason="damaged", resolution="refund")).status == "ok"
    done = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged on delivery")
    assert done.status == "ok" and done.data["amount_eur"] == 379.0
    again = await call(ctx, "issue_refund", order_id="CH-100231", amount=379.0, reason="damaged on delivery")
    assert again.status == "error", "a second refund for the same return is rejected by policy"
    assert len(await svc.backoffice.refunds_for("CH-100231")) == 1
    assert any(a["action"] == "tool.issue_refund" and a["detail"]["idempotency_key"] for a in await svc.audit.recent(30)), "audit trail carries the idempotency key"


async def test_customer_not_the_model_chooses_between_replacement_and_refund(svc):
    """Live regression: the model started a replacement on its own while the customer wanted a refund."""
    ctx = await make_ctx(svc)
    ctx.conv.entities["choice"] = "refund"
    wrong = await call(ctx, "initiate_return", order_id="CH-100231", reason="damaged", resolution="replacement")
    assert wrong.status == "error" and wrong.data["error"] == "choice_mismatch" and "refund" in wrong.data["message"]
    right = await call(ctx, "initiate_return", order_id="CH-100231", reason="damaged", resolution="refund")
    assert right.status == "confirmation_required"
    human = await make_ctx(svc, actor="human")
    assert (await call(human, "initiate_return", order_id="CH-100231", reason="damaged", resolution="replacement")).status != "error", "a human colleague decides together with the customer"


async def test_idempotent_retry_never_double_credits_even_when_concurrent(svc):
    ctx = await make_ctx(svc, customer="CU-1005")  # delayed wardrobe -> goodwill applies
    args = {"order_id": "CH-100280", "amount": 30.0, "reason": "late delivery", "idempotency_key": "retry-1"}
    assert (await call(ctx, "goodwill_credit", **args)).status == "confirmation_required"
    for p in ctx.conv.pending:
        p.confirmed = True
    results = await asyncio.gather(*(call(ctx, "goodwill_credit", **args) for _ in range(4)))
    assert sorted(r.status for r in results).count("ok") == 1 and {r.status for r in results} <= {"ok", "replayed"}
    assert len(await svc.backoffice.credits_for("CU-1005", 0)) == 1
    assert all(r.data.get("credit_id") for r in results)


async def test_goodwill_above_cap_requires_approval(svc):
    ctx = await make_ctx(svc, customer="CU-1005")
    r = await call(ctx, "goodwill_credit", order_id="CH-100280", amount=80.0, reason="late delivery")
    assert r.status == "approval_required" and r.escalate["code"] == "policy_block"
    assert await svc.backoffice.credits_for("CU-1005", 0) == []


async def test_refund_above_cap_requires_approval_and_escalates(svc):
    ctx = await make_ctx(svc, customer="CU-1004", level=2)
    ctx.conv.entities["choice"] = "refund"
    assert (await confirmed(ctx, "initiate_return", order_id="CH-100340", reason="damaged", resolution="refund")).status == "ok"
    r = await call(ctx, "issue_refund", order_id="CH-100340", amount=1899.0, reason="damaged on delivery")
    assert r.status == "approval_required" and r.escalate["code"] == "policy_block"
    assert r.data["approval_id"].startswith("APR-")
    assert await svc.backoffice.refunds_for("CH-100340") == []
    appr = await svc.repo.get("approvals", r.data["approval_id"])
    assert appr["status"] == "pending" and appr["amount"] == 1899.0
    again = await call(ctx, "issue_refund", order_id="CH-100340", amount=1899.0, reason="damaged on delivery")
    assert again.data["approval_id"] == r.data["approval_id"], "no duplicate approval requests"


async def test_large_refund_needs_step_up_identity(svc):
    ctx = await make_ctx(svc, customer="CU-1004", level=1)
    r = await call(ctx, "issue_refund", order_id="CH-100270", amount=899.0, reason="damaged mattress")
    assert r.status == "blocked" and r.data["error"] == "step_up_required" and r.data["required_level"] == 2


async def test_human_agent_refund_within_human_cap_executes_without_customer_confirmation(svc):
    ctx = await make_ctx(svc, customer="CU-1004", level=0, agent="human", actor="human:AG-08")
    assert (await call(ctx, "initiate_return", order_id="CH-100340", reason="damaged", resolution="refund")).status == "ok"
    r = await call(ctx, "issue_refund", order_id="CH-100340", amount=1899.0, reason="damaged on delivery")
    assert r.status == "ok"
    assert (await svc.backoffice.refunds_for("CH-100340"))[0]["amount"] == 1899.0


async def test_card_data_never_reaches_tools(svc):
    ctx = await make_ctx(svc)
    r = await call(ctx, "create_ticket", summary="my card is 4111 1111 1111 1111 please charge it", category="billing")
    assert r.status == "blocked" and r.data["error"] == "card_data_not_allowed"
    assert any(a["action"] == "tool.blocked" and a["detail"]["reason"] == "card_data_in_arguments" for a in await svc.audit.recent(10))


async def test_invalid_arguments_are_reported_not_executed(svc):
    ctx = await make_ctx(svc)
    r = await call(ctx, "issue_refund", order_id="CH-100231", amount=-5, reason="x")
    assert r.status == "error" and r.data["error"] == "invalid_arguments"
    assert ctx.conv.counters["tool_failures"] == 1


async def test_return_outside_window_is_declined_and_not_refundable(svc):
    ctx = await make_ctx(svc, customer="CU-1007")  # blender delivered 300 days ago
    r = await call(ctx, "check_return_eligibility", order_id="CH-100300", reason="changed_mind")
    assert r.data["eligible"] is False and r.data["code"] == "outside_window"
    blocked = await call(ctx, "initiate_return", order_id="CH-100300", reason="changed_mind", resolution="refund")
    assert blocked.status == "error" and blocked.data["error"] == "outside_window"


async def test_tool_arguments_and_results_are_redacted_in_records(svc):
    ctx = await make_ctx(svc)
    r = await call(ctx, "create_ticket", summary="please call me back on +44 7700 900123 about the sofa", category="delivery")
    assert "900123" not in str(r.record.args)
    assert "7700" not in str(r.record.result)
