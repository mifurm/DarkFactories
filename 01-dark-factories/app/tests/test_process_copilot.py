"""Process-optimisation agent and the model-driven copilot loop (scripted fake Azure LLM - no network)."""

from __future__ import annotations

import json

from nightshift.core.llm import ChatResult, LLMClient, StreamEvent, ToolCall
from nightshift.core.usage import BudgetExceeded
from nightshift.features.df16_copilot import copilot as C
from nightshift.plant.core import PlantCore


# ----------------------------------------------------------------------------- process agent
def test_process_agent_tunes_the_recipe_inside_hard_bounds_with_twin_evaluation():
    c = PlantCore(
        "KAT-1",
        seed=3,
        swarm=True,
        agents={"process", "safety", "maintenance"},
        sim_first="surrogate",
        headless_latency=10,
    )
    c.process.enabled = True
    c.run(180)
    start = dict(next(iter(c.plant.assets[a].recipe for a in c.plant.assets if a.startswith("PRESS"))))
    c.run(900)
    s = c.process.summary()
    assert c.process.enabled and s["history"], "the agent never ran a trial"
    for press in (a for a in c.plant.assets if a.startswith("PRESS")):
        r = c.plant.assets[press].recipe
        for k, (lo, hi) in s["bounds"].items():
            assert lo <= r[k] <= hi, f"{press}.{k}={r[k]} outside {lo}..{hi}"
    assert c.ledger.verify()["ok"] and start


def test_process_recipe_changes_are_policy_governed(client):
    pol = client.get("/api/policy").json()["classes"]["process.recipe"]
    assert pol["level"] <= 3 and pol["sim_first"] is True  # default: never fully autonomous


# ----------------------------------------------------------------------------- copilot with a scripted model
class ScriptedLLM(LLMClient):
    mode = "azure"
    deployments = {"chat": "chat", "reasoning": "reasoning"}

    def __init__(self, script, fail=None):
        self.script, self.fail, self.round = script, fail, 0
        self.seen_messages: list[list[dict]] = []

    async def chat(self, messages, **kw):
        return ChatResult(text="ok")

    async def stream(self, messages, **kw):
        self.seen_messages.append(list(messages))
        if self.fail:
            raise self.fail
        step = self.script[min(self.round, len(self.script) - 1)]
        self.round += 1
        if step.get("calls"):
            yield StreamEvent(
                "tool_calls", tool_calls=[ToolCall(f"c{i}", n, a) for i, (n, a) in enumerate(step["calls"])]
            )
        else:
            for tok in step["text"].split(" "):
                yield StreamEvent("text", text=tok + " ")
        yield StreamEvent("done", result=ChatResult(text=step.get("text", "")))

    async def ping(self):
        return {"status": "ok"}


async def _collect(rt, pr, question):
    return [e async for e in C.chat_stream(rt, pr, [{"role": "user", "content": question}])]


async def test_model_tool_calling_loop_executes_tools_then_answers_with_citations(client):
    rt, pr = client.app.state.rt, client.app.state.rt.fleet.get("KAT-1")
    llm = ScriptedLLM(
        [
            {"calls": [("get_asset", {"asset_id": "CNC-04"}), ("get_kpis", {"window_hours": 8})]},
            {"text": "CNC-04 is fine [asset:CNC-04]"},
        ]
    )
    old, rt.llm = rt.llm, llm
    try:
        events = await _collect(rt, pr, "How is CNC-04?")
    finally:
        rt.llm = old
    names = [e for e, _ in events]
    assert names.count("tool_call") == 2 and names.count("tool_result") == 2 and names[-1] == "done"
    done = events[-1][1]
    assert done["mode"] == "azure" and done["tools"] == ["get_asset", "get_kpis"]
    cites = next(d for e, d in events if e == "citations")["citations"]
    assert {"type": "asset", "id": "CNC-04"} in cites
    tool_msgs = [m for m in llm.seen_messages[1] if m["role"] == "tool"]
    assert len(tool_msgs) == 2 and json.loads(tool_msgs[0]["content"])  # tool results are fed back to the model as data


async def test_model_failure_and_budget_exhaustion_fall_back_to_the_deterministic_planner(client):
    rt, pr = client.app.state.rt, client.app.state.rt.fleet.get("KAT-1")
    old = rt.llm
    try:
        for err, expect in (
            (RuntimeError("down"), "model unavailable"),
            (BudgetExceeded("daily cap reached"), "daily cap"),
        ):
            rt.llm = ScriptedLLM([], fail=err)
            events = await _collect(rt, pr, "What is the OEE?")
            done = events[-1][1]
            assert done["mode"] == "fallback" and expect in done["note"] and any(e == "token" for e, _ in events)
    finally:
        rt.llm = old


async def test_model_that_never_stops_calling_tools_is_cut_off_after_four_rounds(client):
    rt, pr = client.app.state.rt, client.app.state.rt.fleet.get("KAT-1")
    old, rt.llm = rt.llm, ScriptedLLM([{"calls": [("get_alerts", {})]}])
    try:
        events = await _collect(rt, pr, "loop forever")
    finally:
        rt.llm = old
    assert sum(1 for e, _ in events if e == "tool_call") >= 4
    assert events[-1][1]["mode"] == "fallback" and "round limit" in events[-1][1]["note"]


def test_answer_composition_covers_the_main_intents():
    pr_cases = {
        "what is the oee and throughput": "get_kpis",
        "why did the planner reschedule orders": "query_ledger",
        "which orders are late": "get_orders",
        "what happens if CNC-04 goes down": "run_whatif",
        "status of CNC-04": "get_asset",
        "any alerts": "get_alerts",
    }
    wi = C.plan_tools("What happens to on-time delivery if CNC-04 goes down for 2 hours?")[0]
    assert wi[0] == "run_whatif" and wi[1]["horizon_min"] == 120 and wi[1]["actions"][0]["kind"] == "safe_stop"
    for q, tool in pr_cases.items():
        planned = [n for n, _ in C.plan_tools(q)]
        assert tool in planned, f"{q!r} -> {planned}"
