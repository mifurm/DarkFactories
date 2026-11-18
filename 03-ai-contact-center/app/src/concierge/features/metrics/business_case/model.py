#!/usr/bin/env python3
"""SwarmAI Contact Center ("Concierge") - customer ROI and Azure Consumed Revenue (ACR) model.

Pure standard library, deterministic, no I/O inside compute(). Interface (stable; vendored by the live app):

    compute(assumptions: dict, scenario: str = "base", overrides: dict | None = None) -> dict
    compute_all(assumptions: dict) -> {"conservative": {...}, "base": {...}, "upside": {...}}

Time axis: index 0 = "Year 0" (build + pilot, one-time costs), indexes 1..3 = production years.
All money is USD at Azure list prices (pay-as-you-go, no EA discount). See README.md for formulas.
Run `python model.py` to (re)write outputs.json and outputs.md; `python model.py --check` verifies them.
"""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

MODEL_VERSION = "1.0.0"
SCENARIOS = ("conservative", "base", "upside")
STRESS_SCENARIOS = ("stacked_downside", "stacked_upside")  # every uncertain driver at its bound at once
ALL_SCENARIOS = SCENARIOS + STRESS_SCENARIOS
HORIZON = 3
HOURS_PER_YEAR = 8760.0
MINUTES_PER_YEAR = 525600.0
SECONDS_PER_YEAR = 31536000.0
SCENARIO_KINDS = ("outcome", "cost")  # kinds whose value moves with the scenario; others stay at base

# (key, label, group)
FAMILIES = (
    ("openai_realtime", "Azure OpenAI - realtime audio (voice agent)", "ai"),
    ("openai_text", "Azure OpenAI - chat, reasoning & embedding tokens", "ai"),
    ("speech", "Azure AI Speech - STT / TTS", "ai"),
    ("language", "Azure AI Language - PII & sentiment", "ai"),
    ("content_safety", "Azure AI Content Safety", "ai"),
    ("ai_search", "Azure AI Search", "ai"),
    ("comms", "Communications platform billed through Azure (ACS meters; share set by comms_azure_billed_share)", "comms"),
    ("cosmos", "Azure Cosmos DB", "data"),
    ("storage", "Blob / ADLS storage - recordings & transcripts", "data"),
    ("analytics", "Fabric Real-Time Intelligence, OneLake & Event Hubs", "data"),
    ("compute", "Container Apps compute", "platform"),
    ("networking", "Front Door, API Management & private networking", "platform"),
    ("monitoring_security", "Monitor, Defender, Key Vault & Purview", "platform"),
)
FAMILY_KEYS = tuple(f[0] for f in FAMILIES)
GROUPS = {
    "ai": "AI models & services",
    "comms": "Communications",
    "data": "Data & analytics",
    "platform": "Platform, network & security",
}
BENEFITS = (
    ("ai_containment", "AI containment & resolution of Tier-1 contacts"),
    ("aht_reduction", "AHT reduction (Agent Assist, auto wrap-up, warm handoff)"),
    ("qa_quality", "100 % auto-QA & quality uplift"),
    ("attrition", "Attrition, hiring & training avoidance"),
    ("abandonment_csat_retention", "Abandonment, CSAT & retention (revenue effect)"),
    ("peak_resilience", "Peak resilience (overflow outsourcing avoided)"),
    ("compliance_risk", "Compliance-risk reduction"),
    ("multilingual", "Multilingual coverage without hiring"),
)
BENEFIT_KEYS = tuple(b[0] for b in BENEFITS)
OTHER_COSTS = (
    ("implementation_integration", "Implementation, integration & pilot (one-time)"),
    ("change_management", "Change management & training (one-time)"),
    ("contingency", "Contingency on one-time costs"),
    ("ai_operations_team", "AI operations team (LLMOps, knowledge, evaluation)"),
    ("licences_and_telephony_interop", "Third-party licences, SBC / telephony interop"),
    ("support_and_maintenance", "Solution support & maintenance"),
    ("communications_outside_azure", "Communications billed outside Azure (SIP/CPaaS, Teams Phone, D365, messaging providers)"),
)
OTHER_COST_KEYS = tuple(c[0] for c in OTHER_COSTS)
COST_REDUCTION_BENEFITS = (
    "ai_containment", "aht_reduction", "qa_quality", "attrition", "peak_resilience", "multilingual",
)

# Friendly aliases accepted in `overrides` (the live calculator uses these names).
OVERRIDE_ALIASES = {
    "seats": "agents",
    "contacts": "contacts_per_year",
    "voice_share": "voice_share_of_contacts",
    "containment": "ai_containment_pct",
    "containment_pct": "ai_containment_pct",
    "aht_reduction": "aht_reduction_pct",
    "attrition": "attrition_rate",
    "qa_coverage": "qa_coverage_target",
    "adoption": "adoption_ramp",
    "ramp": "adoption_ramp",
}
SPECIAL_OVERRIDES = ("cost_per_contact_usd", "digital_share")


def load_assumptions(path=None):
    """Read assumptions.json (next to this file by default)."""
    path = Path(path) if path else Path(__file__).resolve().parent / "assumptions.json"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- resolution
def _pick(entry, scenario, blend=1.0):
    """Value of one assumption entry for a scenario.

    Scenario-sensitive kinds (outcome, cost) move from base towards the unfavourable (conservative) or favourable
    (upside) bound by `blend` of the distance; the stacked_* scenarios use the full bound. List values move element-wise."""
    kind = entry.get("kind", "outcome")
    fav = entry.get("favourable", "high")
    base = entry["base"]
    if scenario == "base" or kind not in SCENARIO_KINDS or fav == "neutral":
        return list(base) if isinstance(base, list) else base
    downside = scenario in ("conservative", "stacked_downside")
    end = entry["low"] if (downside == (fav == "high")) else entry["high"]
    w = 1.0 if scenario.startswith("stacked") else blend
    if isinstance(base, list):
        return [b + w * (e - b) for b, e in zip(base, end)]
    return base + w * (end - base)


def _normalise_overrides(overrides, keys):
    out, special = {}, {}
    for raw_key, value in (overrides or {}).items():
        key = OVERRIDE_ALIASES.get(raw_key, raw_key)
        if key == "digital_share":
            out["voice_share_of_contacts"] = 1.0 - float(value)
        elif key == "cost_per_contact_usd":
            special["cost_per_contact_usd"] = float(value)
        elif key in keys:
            out[key] = list(value) if isinstance(value, (list, tuple)) else value
        else:
            raise KeyError(f"unknown override key: {raw_key!r}")
    return out, special


def resolve_params(assumptions, scenario="base", overrides=None):
    """Return (params, special_overrides) for a scenario after applying overrides."""
    if scenario not in ALL_SCENARIOS:
        raise ValueError(f"scenario must be one of {ALL_SCENARIOS}, got {scenario!r}")
    entries = assumptions["assumptions"]
    blend = assumptions["meta"].get("scenario_blend", 1.0)
    params = {k: _pick(e, scenario, blend) for k, e in entries.items()}
    ov, special = _normalise_overrides(overrides, entries.keys())
    for k, v in ov.items():
        if isinstance(params[k], list):
            if not isinstance(v, list) or len(v) != len(params[k]):
                raise ValueError(f"override {k!r} must be a list of {len(params[k])} numbers")
        params[k] = v
    return params, special


def resolve_prices(assumptions, deployment_type):
    """Flatten unit_prices: entries with `value`, or one value per deployment type, or volume tiers."""
    out = {}
    for key, e in assumptions["unit_prices"].items():
        if "tiers" in e:
            out[key] = [tuple(t) for t in e["tiers"]]
        elif "value" in e:
            out[key] = e["value"]
        else:
            out[key] = e[deployment_type]
    return out


# --------------------------------------------------------------------------- baseline economics
def _derive(p, special):
    agents, contacts = float(p["agents"]), float(p["contacts_per_year"])
    if "cost_per_contact_usd" in special:
        cpc = special["cost_per_contact_usd"]
        loaded = cpc * contacts / agents
    else:
        loaded = float(p["loaded_cost_per_agent_usd"])
        cpc = loaded * agents / contacts
    vs = p["voice_share_of_contacts"]
    weighted_aht = vs * p["aht_voice_min"] + (1 - vs) * p["aht_digital_effective_min"]
    cost_per_min = cpc / weighted_aht
    return {
        "loaded_cost_per_agent_usd": loaded,
        "cost_per_contact_usd": cpc,
        "cost_per_contact_voice_usd": cost_per_min * p["aht_voice_min"],
        "cost_per_contact_digital_usd": cost_per_min * p["aht_digital_effective_min"],
        "cost_per_handling_minute_usd": cost_per_min,
        "weighted_aht_min": weighted_aht,
        "baseline_annual_human_cost_usd": cpc * contacts,
        "contacts_per_agent_year": contacts / agents,
        "cost_per_resolved_contact_usd": cpc / (1.0 - p["repeat_contact_share"]),
        "qa_fte_baseline": agents / p["agents_per_qa_analyst"],
        "qa_coverage_gain_pp": (p["qa_coverage_target"] - p["qa_coverage_baseline"]) * 100.0,
    }


def _tiered_cost(tiers, units_per_month):
    """Volume-tiered unit price: tiers = [(min_units_per_month_in_thousands, price_per_1k), ...]."""
    cost, units_k = 0.0, units_per_month / 1000.0
    ordered = sorted(tiers)
    for i, (lo, price) in enumerate(ordered):
        hi = ordered[i + 1][0] if i + 1 < len(ordered) else float("inf")
        if units_k > lo:
            cost += (min(units_k, hi) - lo) * price
    return cost


def _next_in_ladder(value, ladder):
    for step in ladder:
        if value <= step:
            return step
    return ladder[-1]


FABRIC_CU_LADDER = (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048)
M = 1_000_000.0


def _tier_for(assumptions, seats_in_scope):
    cfg = assumptions["tiers"]
    idx = sum(1 for t in cfg["thresholds_seats_in_scope"] if seats_in_scope > t)
    return cfg["definitions"][idx]


def _turn_cost(pr, prefix, unc, cached, out):
    """USD for one LLM call: uncached input + cached input + output tokens at list price."""
    return (unc * pr[prefix + "_in"] + cached * pr[prefix + "_cached"] + out * pr[prefix + "_out"]) / M


def _azure(p, pr, assumptions, ctx):
    """Bottom-up Azure consumption for one period. Returns line items, family/purpose roll-ups, sizing, volumes."""
    mult = p["azure_usage_multiplier"]
    uplift = 1.0 + p["nonprod_environment_uplift_pct"]
    per = ctx["period_years"]
    tier = ctx["tier"]
    regions = tier["regions"]
    items = []
    billed = p["comms_azure_billed_share"]

    def add(family, purpose, name, qty, unit, price, fixed=False, tag=None, basis=""):
        factor = mult * (uplift if fixed else 1.0)
        usd = qty * price * factor
        items.append({"family": family, "purpose": purpose, "name": name, "quantity": qty, "unit": unit,
                      "unit_price": price, "factor": factor, "fixed": fixed, "tag": tag, "basis": basis,
                      "usd": usd, "azure_usd": usd * (billed if family == "comms" else 1.0)})

    C, a, m, s, qs = ctx["contacts"], ctx["adoption"], ctx["maturity"], ctx["assist"], ctx["qa_share"]
    vs = p["voice_share_of_contacts"]
    ds = 1.0 - vs
    contain = min(1.0, p["ai_containment_pct"] * m)
    ai_first = C * a
    resolved = ai_first * contain
    ai_v, ai_d = ai_first * vs, ai_first * (1 - vs)
    res_v, res_d = resolved * vs, resolved * ds
    esc_v, esc_d = ai_v - res_v, ai_d - res_d
    hum_v, hum_d = C * vs - res_v, C * ds - res_d
    ass_v, ass_d = hum_v * s, hum_d * s
    assisted = ass_v + ass_d
    analyzed = C * max(a + (1 - a) * s, qs)  # contacts whose transcript is analysed (AI-first, assisted, QA-scored)
    qa_scored = C * qs
    wrapups = ai_first + (C - ai_first) * s
    ai_voice_min = ai_v * (contain * p["voice_min_per_contained_contact"] + (1 - contain) * p["voice_min_per_escalated_contact"])
    fb = p["rt_fallback_pipeline_share"]
    rt_min, fb_min = ai_voice_min * (1 - fb), ai_voice_min * fb
    talk = p["aht_voice_min"] * p["talk_share_of_aht"]
    human_acs_min = esc_v * talk * p["human_leg_anchored_share"]
    stt_min_human = hum_v * talk * max(s, qs)
    annual = 1.0 / per

    # ---- Azure OpenAI realtime (voice agent)
    cust, agt, turns = p["rt_customer_speech_share"], p["rt_agent_speech_share"], p["rt_turns_per_min"]
    new_in = p["audio_in_tokens_per_sec"] * 60.0 * cust
    new_out = p["audio_out_tokens_per_sec"] * 60.0 * agt
    f = p["rt_full_model_share"]

    def blend(k):
        return (1 - f) * pr["rt_mini_" + k] + f * pr["rt_full_" + k]

    mix = f"{(1 - f) * 100:.0f}% gpt-realtime-2.1-mini / {f * 100:.0f}% gpt-realtime-2.1"
    add("openai_realtime", "ai_first", "Realtime audio input: new customer audio + assistant audio re-sent once (uncached)",
        rt_min * (new_in + new_out) / M, "M tokens", blend("audio_in"), tag="voice_ai", basis=mix)
    add("openai_realtime", "ai_first", "Realtime audio output (agent speech)", rt_min * new_out / M, "M tokens",
        blend("audio_out"), tag="voice_ai", basis=mix)
    add("openai_realtime", "ai_first", "Realtime cached audio context re-read each turn",
        rt_min * turns * p["rt_avg_audio_context_tokens"] / M, "M tokens", blend("audio_cached"), tag="voice_ai", basis=mix)
    add("openai_realtime", "ai_first", "Realtime cached system prompt and tool schemas (text)",
        rt_min * turns * p["rt_system_tokens"] / M, "M tokens", blend("text_cached"), tag="voice_ai", basis=mix)
    add("openai_realtime", "ai_first", "Realtime reasoning / text output", rt_min * turns * p["rt_reasoning_tokens_per_turn"] / M,
        "M tokens", blend("text_out"), tag="voice_ai", basis=mix)
    add("openai_realtime", "ai_first", "Realtime tool-result text input", rt_min * p["rt_tool_text_in_tokens_per_min"] / M,
        "M tokens", blend("text_in"), tag="voice_ai", basis=mix)
    add("openai_realtime", "ai_first", "Realtime input transcription - audio tokens (gpt-4o-mini-transcribe)",
        rt_min * p["audio_in_tokens_per_sec"] * 60.0 * cust / M, "M tokens", pr["transcribe_audio_in"], tag="voice_ai")
    add("openai_realtime", "ai_first", "Realtime input transcription - text tokens out",
        rt_min * p["speech_text_tokens_per_min"] * cust / M, "M tokens", pr["transcribe_text_out"], tag="voice_ai")

    # ---- Azure OpenAI text models (chat agent, assist, wrap-up, QA, classification, embeddings, evaluation)
    unc, cac, out = p["chat_uncached_in_tokens_per_turn"], p["chat_cached_in_tokens_per_turn"], p["chat_out_tokens_per_turn"]
    chat_turn = _turn_cost(pr, "chat_mini", unc, cac, out)
    chat_basis = f"{unc:.0f} uncached + {cac:.0f} cached input + {out:.0f} output tokens, gpt-5.4-mini"
    turns_d = ai_d * (contain * p["chat_turns_per_contained_contact"] + (1 - contain) * p["chat_turns_per_escalated_contact"])
    add("openai_text", "ai_first", "Digital AI agent turns (chat, messaging, e-mail)", turns_d, "turns", chat_turn, tag="digital_ai", basis=chat_basis)
    add("openai_text", "ai_first", "Voice fallback pipeline LLM turns (STT > LLM > TTS)", fb_min * turns, "turns", chat_turn,
        tag="voice_ai", basis=chat_basis)
    au, ac, ao = p["assist_uncached_in_tokens"], p["assist_cached_in_tokens"], p["assist_out_tokens"]
    assist_call = _turn_cost(pr, "chat_mini", au, ac, ao)
    add("openai_text", "human_assist", "Agent Assist suggestions (next-best-action, replies, compliance prompts)",
        ass_v * p["assist_calls_per_human_voice_contact"] + ass_d * p["assist_calls_per_human_digital_contact"], "calls",
        assist_call, basis=f"{au:.0f} uncached + {ac:.0f} cached input + {ao:.0f} output tokens, gpt-5.4-mini")
    wc = _turn_cost({"w_in": pr["chat_mini_in"], "w_cached": 0.0, "w_out": pr["chat_mini_out"]}, "w",
                    p["wrapup_in_tokens"], 0.0, p["wrapup_out_tokens"])
    add("openai_text", "human_assist", "Auto wrap-up: summary, disposition, CRM note, follow-ups", wrapups, "contacts", wc,
        basis=f"{p['wrapup_in_tokens']:.0f} input + {p['wrapup_out_tokens']:.0f} output tokens, gpt-5.4-mini")
    qf = p["qa_full_model_share"]
    qa_mini = _turn_cost(pr, "chat_mini", p["qa_uncached_in_tokens"], p["qa_cached_in_tokens"], p["qa_out_tokens"])
    qa_full = _turn_cost(pr, "chat_full", p["qa_uncached_in_tokens"], p["qa_cached_in_tokens"], p["qa_out_tokens"])
    add("openai_text", "quality_insight", "100 % auto-QA scoring with evidence (rubric)", qa_scored, "conversations",
        (1 - qf) * qa_mini + qf * qa_full,
        basis=f"{p['qa_uncached_in_tokens']:.0f} uncached + {p['qa_cached_in_tokens']:.0f} cached in + {p['qa_out_tokens']:.0f} out; "
              f"{(1 - qf) * 100:.0f}% gpt-5.4-mini / {qf * 100:.0f}% gpt-5.4")
    cls = _turn_cost(pr, "nano", p["classify_in_tokens"], 0.0, p["classify_out_tokens"])
    add("openai_text", "ai_first", "Intent / sentiment / risk classification (routing)", (ai_first + (C - ai_first) * s) * p["classify_calls_per_contact"],
        "calls", cls, basis=f"{p['classify_in_tokens']:.0f} in + {p['classify_out_tokens']:.0f} out tokens, gpt-5.4-nano")
    emb_tokens = analyzed * p["embed_tokens_per_contact"] + (ai_first * p["search_queries_per_ai_contact"] + assisted * p["search_queries_per_assisted_contact"]) * p["embed_tokens_per_search_query"]
    add("openai_text", "quality_insight", "Embeddings: retrieval queries and VoC clustering", emb_tokens / M, "M tokens", pr["embed_in"],
        basis="text-embedding-3-small")
    ev = (p["eval_conversations_per_month"] * 12 * per)
    add("openai_text", "llmops", "Evaluation harness and red-team runs (simulated customers + judges)", ev, "conversations",
        (p["eval_in_tokens_per_conversation"] * pr["chat_mini_in"] + p["eval_out_tokens_per_conversation"] * pr["chat_mini_out"]) / M,
        basis=f"{p['eval_in_tokens_per_conversation']:.0f} in + {p['eval_out_tokens_per_conversation']:.0f} out tokens, gpt-5.4-mini")

    # ---- Azure AI Speech
    stt_hr = pr["stt_hour"] + pr["stt_enhanced_hour"]
    add("speech", "human_assist", "Streaming STT with diarization: human-handled voice (Agent Assist + QA transcripts)", stt_min_human / 60.0,
        "audio hours", stt_hr, basis="S1 real-time + enhanced add-on")
    add("speech", "ai_first", "Fallback pipeline STT (when the realtime path is unavailable)", fb_min / 60.0, "audio hours", stt_hr, tag="voice_ai")
    add("speech", "ai_first", "Fallback pipeline neural TTS", fb_min * p["tts_chars_per_speech_min"] * agt / M, "M characters",
        pr["tts_per_1m_chars"], tag="voice_ai")

    # ---- Azure AI Language (PII + sentiment on transcripts), volume-tiered
    lang_records = analyzed * p["language_records_per_contact"]
    lang_cost = _tiered_cost(pr["language_text_records"], lang_records / (12.0 * per)) * 12.0 * per
    eff = lang_cost / (lang_records / 1000.0) if lang_records else 0.0
    add("language", "quality_insight", "PII detection and sentiment (1,000-character text records, monthly volume tiers)", lang_records / 1000.0,
        "K records", eff, basis="effective price after tiering")

    # ---- Azure AI Content Safety
    cs = ai_first * p["content_safety_records_per_ai_contact"] + assisted * p["content_safety_records_per_assisted_contact"]
    add("content_safety", "ai_first", "Prompt Shields, text moderation and groundedness checks (text records)", cs / 1000.0, "K records",
        pr["content_safety_per_1k"])

    # ---- Azure AI Search
    q_total = ai_first * p["search_queries_per_ai_contact"] + assisted * p["search_queries_per_assisted_contact"]
    peak_qps = q_total * annual / SECONDS_PER_YEAR * p["search_peak_factor"]
    replicas = max(tier["search_min_replicas"], math.ceil(peak_qps / p["search_qps_per_replica"]))
    add("ai_search", "platform", "Search units (S1) = replicas x regions", replicas * regions * HOURS_PER_YEAR * per, "unit-hours",
        pr["search_s1_hour"], fixed=True, basis=f"{replicas} replicas per region")
    add("ai_search", "ai_first", "Semantic ranker queries", q_total / 1000.0, "K queries", pr["search_semantic_per_1k"])

    # ---- Communications platform (priced at Azure Communication Services list rates as a proxy; see comms_azure_billed_share)
    anch = p["human_leg_anchored_share"]
    add("comms", "ai_first", "SIP / direct-routing inbound leg: AI-handled minutes", ai_voice_min, "minutes", pr["acs_direct_routing_min"], tag="voice_ai")
    add("comms", "ai_first", "Audio streaming to the realtime relay or fork: AI minutes", ai_voice_min, "minutes",
        pr["acs_audio_streaming_min"], tag="voice_ai")
    add("comms", "quality_insight", "Call recording (dual-channel stereo): AI minutes", ai_voice_min, "minutes", pr["acs_recording_stereo_min"], tag="voice_ai")
    add("comms", "human_assist", "SIP / direct-routing leg: human-handled minutes anchored on the platform", human_acs_min, "minutes", pr["acs_direct_routing_min"])
    add("comms", "human_assist", "VoIP leg of the human agent (softphone, Teams or D365 agent desktop)", human_acs_min, "minutes", pr["acs_voip_leg_min"])
    add("comms", "human_assist", "Audio streaming for Agent Assist STT: anchored human minutes", human_acs_min, "minutes", pr["acs_audio_streaming_min"])
    add("comms", "quality_insight", "Call recording (stereo): anchored human minutes", human_acs_min, "minutes", pr["acs_recording_stereo_min"])
    add("comms", "human_assist", "SIP REFER transfers to the customer's existing CCaaS", esc_v * (1 - anch), "transfers", pr["acs_refer_unit"])
    msgs_ai = 2.0 * turns_d
    msgs_h = esc_d * p["human_digital_messages_per_contact"] * anch
    msgs = msgs_ai + msgs_h
    add("comms", "ai_first", "Chat messages sent (web chat share of digital)", msgs * p["digital_mix_chat"], "messages", pr["acs_chat_message"], tag="digital_ai")
    add("comms", "ai_first", "Messaging-app (WhatsApp-class) messages incl. connect fee", msgs * p["digital_mix_messaging"], "messages",
        pr["acs_adv_message"] + pr["acs_adv_connect"], tag="digital_ai", basis="excludes Meta conversation fees (pass-through)")
    add("comms", "ai_first", "E-mails sent (one outbound per AI turn on the e-mail channel)", turns_d * p["digital_mix_email"], "e-mails",
        pr["acs_email"], tag="digital_ai")
    otp = ai_first * p["otp_required_share"]
    add("comms", "ai_first", "OTP via SMS (EU alphanumeric sender, blended per segment)", otp * p["otp_sms_share"], "SMS", pr["acs_sms_eu"])
    add("comms", "ai_first", "OTP via e-mail", otp * p["otp_email_share"], "e-mails", pr["acs_email"])
    add("comms", "ai_first", "Confirmation SMS after a resolved contact", resolved * p["confirmation_sms_share_of_resolved"], "SMS", pr["acs_sms_eu"])
    add("comms", "ai_first", "Confirmation e-mail after a resolved contact", resolved * p["confirmation_email_share_of_resolved"], "e-mails", pr["acs_email"])

    # ---- Cosmos DB
    contacts_year = C * annual
    ru_avg = contacts_year * p["cosmos_ru_per_contact"] / SECONDS_PER_YEAR
    ru_max = max(1000.0, math.ceil(ru_avg * p["cosmos_peak_factor"] / 1000.0) * 1000.0)
    add("cosmos", "platform", "Autoscale throughput: max RU/s x average utilisation x regions", ru_max / 100.0 * p["cosmos_autoscale_avg_utilisation"] * regions * HOURS_PER_YEAR * per,
        "100 RU/s-hours", pr["cosmos_autoscale_100ru_hour"], fixed=True, basis=f"max {ru_max:,.0f} RU/s")
    cosmos_gb = contacts_year * p["cosmos_kb_per_contact"] * (p["cosmos_retention_days"] / 365.0) / 1e6
    add("cosmos", "platform", "Transactional storage (hot window) x regions", cosmos_gb * regions * 12.0 * per, "GB-months", pr["cosmos_storage_gb_month"])

    # ---- Blob / ADLS storage
    rec_gb_year = (ai_voice_min + human_acs_min) * annual * p["recording_mb_per_min"] / 1000.0
    tr_gb_year = contacts_year * p["transcript_kb_per_contact"] / 1e6
    hot_days, ret_days = p["recording_hot_days"], p["recording_retention_months"] * 30.4
    hot_gb = (rec_gb_year + tr_gb_year) * hot_days / 365.0
    cool_gb = (rec_gb_year + tr_gb_year) * max(0.0, ret_days - hot_days) / 365.0
    add("storage", "quality_insight", "Recordings and transcripts - hot tier (GRS)", hot_gb * 12.0 * per, "GB-months", pr["blob_hot_grs_gb_month"])
    add("storage", "quality_insight", "Recordings and transcripts - cool tier (GRS)", cool_gb * 12.0 * per, "GB-months", pr["blob_cool_grs_gb_month"])
    cap = hot_gb * pr["blob_hot_grs_gb_month"] + cool_gb * pr["blob_cool_grs_gb_month"]
    add("storage", "quality_insight", "Storage transactions (uplift on capacity cost)", cap * 12.0 * per * p["storage_transactions_uplift_pct"], "USD", 1.0)

    # ---- Analytics (Fabric RTI, OneLake, Event Hubs)
    seats = ctx["seats_in_scope"]
    cu = _next_in_ladder(max(2.0, seats * p["fabric_cu_per_seat"]), FABRIC_CU_LADDER)
    add("analytics", "platform", "Fabric capacity (F-SKU, always on)", cu * HOURS_PER_YEAR * per, "CU-hours", pr["fabric_cu_hour"], fixed=True, basis=f"F{cu}")
    lake_gb = contacts_year * p["lake_kb_per_contact"] * (p["analytics_retention_months"] / 12.0) / 1e6
    add("analytics", "platform", "OneLake storage (hot)", lake_gb * 12.0 * per, "GB-months", pr["onelake_hot_gb_month"])
    events = C * p["events_per_contact"]
    eh_mb_s = events * annual / SECONDS_PER_YEAR * p["peak_to_average_factor"] * p["avg_event_kb"] / 1000.0
    eh_sku = tier["event_hubs_sku"]
    eh_units = max(tier["event_hubs_units_per_region"], math.ceil(eh_mb_s / (1.0 if eh_sku == "standard" else 5.0)))
    add("analytics", "platform", f"Event Hubs {eh_sku} units x regions", eh_units * regions * HOURS_PER_YEAR * per, "unit-hours",
        pr["eventhubs_standard_tu_hour"] if eh_sku == "standard" else pr["eventhubs_premium_pu_hour"], fixed=True)
    add("analytics", "platform", "Event Hubs ingress events", events / M, "M events", pr["eventhubs_ingress_per_1m"])

    # ---- Compute (Container Apps)
    peak = p["peak_to_average_factor"]
    voice_conc = ai_voice_min * annual / MINUTES_PER_YEAR * peak
    chat_conc = ai_d * annual * p["chat_avg_session_min"] / MINUTES_PER_YEAR * peak
    vcpu = (voice_conc / p["voice_sessions_per_vcpu"] + chat_conc / p["chat_sessions_per_vcpu"]
            + p["worker_vcpu_per_1000_seats"] * seats / 1000.0 + p["platform_base_vcpu"]) * p["compute_headroom"] * regions
    add("compute", "platform", "Container Apps vCPU (always-on incl. headroom, all regions)", vcpu * 3600.0 * HOURS_PER_YEAR * per, "vCPU-seconds",
        pr["aca_vcpu_second"], fixed=True, basis=f"{vcpu:.1f} vCPU")
    add("compute", "platform", "Container Apps memory", vcpu * p["memory_gib_per_vcpu"] * 3600.0 * HOURS_PER_YEAR * per, "GiB-seconds",
        pr["aca_gib_second"], fixed=True)
    add("compute", "platform", "Container Apps requests", C * p["requests_per_contact"] / M, "M requests", pr["aca_requests_per_1m"])

    # ---- Networking
    fd = tier["front_door"]
    add("networking", "platform", f"Front Door {fd} base fee", 12.0 * per, "months", pr[f"fd_{fd}_base_month"], fixed=True)
    add("networking", "platform", "Front Door requests", C * p["requests_per_contact"] / 1e4, "10k requests", pr[f"fd_{fd}_requests_per_10k"])
    add("networking", "platform", "Front Door data transfer out", C * p["egress_mb_per_contact"] / 1000.0, "GB", pr["fd_egress_gb"])
    apim = tier["apim_sku"]
    add("networking", "platform", f"API Management {apim}", tier["apim_units_per_region"] * regions * HOURS_PER_YEAR * per, "unit-hours",
        pr[f"apim_{apim}_hour"], fixed=True)
    add("networking", "platform", "Private endpoints (Private Link)", tier["private_endpoints_per_region"] * regions * HOURS_PER_YEAR * per,
        "endpoint-hours", pr["private_endpoint_hour"], fixed=True)

    # ---- Monitoring & security
    log_gb_month = contacts_year * p["telemetry_kb_per_contact"] / 1e6 / 12.0
    add("monitoring_security", "platform", "Log Analytics / Application Insights ingestion", max(0.0, log_gb_month - 5.0) * 12.0 * per, "GB",
        pr["loganalytics_ingestion_gb"])
    add("monitoring_security", "platform", "Log retention beyond 31 days", log_gb_month * max(0.0, (p["log_retention_days"] - 31.0) / 30.4) * 12.0 * per,
        "GB-months", pr["loganalytics_retention_gb_month"])
    add("monitoring_security", "platform", "Defender for Cosmos DB", ru_max / 100.0 * regions * HOURS_PER_YEAR * per, "100 RU/s-hours",
        pr["defender_cosmos_100ru_hour"], fixed=True)
    add("monitoring_security", "platform", "Defender for Storage", tier["storage_accounts_per_region"] * regions * HOURS_PER_YEAR * per,
        "account-hours", pr["defender_storage_account_hour"], fixed=True)
    add("monitoring_security", "platform", "Defender for Key Vault", tier["key_vaults_per_region"] * regions * HOURS_PER_YEAR * per,
        "vault-hours", pr["defender_keyvault_hour"], fixed=True)
    add("monitoring_security", "platform", "Defender for Resource Manager", HOURS_PER_YEAR * per, "subscription-hours", pr["defender_arm_hour"], fixed=True)
    add("monitoring_security", "platform", "Key Vault operations", ai_first * p["keyvault_ops_per_ai_contact"] / 1e4, "10k operations", pr["keyvault_ops_per_10k"])
    add("monitoring_security", "platform", "Purview Data Map capacity units", tier["purview_capacity_units"] * HOURS_PER_YEAR * per, "CU-hours",
        pr["purview_capacity_unit_hour"], fixed=True)

    by_family = {k: 0.0 for k in FAMILY_KEYS}
    by_family_all = {k: 0.0 for k in FAMILY_KEYS}
    by_purpose = {}
    by_purpose_azure = {}
    for it in items:
        by_family[it["family"]] += it["azure_usd"]
        by_family_all[it["family"]] += it["usd"]
        by_purpose[it["purpose"]] = by_purpose.get(it["purpose"], 0.0) + it["usd"]
        by_purpose_azure[it["purpose"]] = by_purpose_azure.get(it["purpose"], 0.0) + it["azure_usd"]
    volumes = {
        "contacts": C, "ai_first_contacts": ai_first, "ai_resolved_contacts": resolved, "human_handled_contacts": C - resolved,
        "ai_first_voice_contacts": ai_v, "ai_first_digital_contacts": ai_d, "assisted_human_contacts": assisted,
        "qa_scored_contacts": qa_scored, "ai_voice_minutes": ai_voice_min, "human_voice_minutes_anchored": human_acs_min,
        "human_voice_minutes_transcribed": stt_min_human, "effective_containment_rate": contain,
    }
    sizing = {
        "tier": tier["label"], "regions": regions, "peak_concurrent_voice_sessions": voice_conc, "peak_concurrent_chat_sessions": chat_conc,
        "vcpu_total": vcpu, "fabric_cu": cu, "search_replicas_per_region": replicas, "cosmos_max_ru_per_s": ru_max,
        "event_hubs_units_per_region": eh_units,
    }
    total = sum(by_family.values())
    total_all = sum(by_family_all.values())
    return {"items": items, "by_family": by_family, "by_family_all": by_family_all, "by_purpose": by_purpose,
            "by_purpose_azure": by_purpose_azure, "total": total, "total_all": total_all, "passthrough": total_all - total,
            "volumes": volumes, "sizing": sizing}


def _npv(rate, flows):
    return sum(cf / (1.0 + rate) ** t for t, cf in enumerate(flows))


def _irr(flows):
    """IRR by bisection; None when no sign change (e.g. never pays back or never invests)."""
    lo, hi = -0.99, 100.0
    f_lo, f_hi = _npv(lo, flows), _npv(hi, flows)
    if f_lo == 0:
        return lo
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = _npv(mid, flows)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def _payback_months(one_time, benefits, run_costs):
    """Months after go-live until cumulative net benefit turns positive (None if > 36).

    Annual benefits are spread over months with a ramp (rates interpolated linearly between mid-year anchors,
    starting at zero, rescaled to the annual totals); run costs are spread evenly (conservative)."""
    if one_time <= 0:
        return 0.0
    anchors = [(0.0, 0.0)] + [(12.0 * i + 6.0, benefits[i] / 12.0) for i in range(HORIZON)]
    monthly = []
    for k in range(12 * HORIZON):
        x = k + 0.5
        if x >= anchors[-1][0]:
            rate = anchors[-1][1]
        else:
            j = max(i for i in range(len(anchors) - 1) if anchors[i][0] <= x)
            (x0, y0), (x1, y1) = anchors[j], anchors[j + 1]
            rate = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        monthly.append(rate)
    for y in range(HORIZON):
        tot = sum(monthly[12 * y:12 * y + 12])
        scale = benefits[y] / tot if tot else 0.0
        for k in range(12 * y, 12 * y + 12):
            monthly[k] *= scale
    cum = -one_time
    for k in range(12 * HORIZON):
        net = monthly[k] - run_costs[k // 12] / 12.0
        if cum + net >= 0 and net > 0:
            return k + (-cum) / net
        cum += net
    return None


def _ramp_view(p):
    return {k: list(p[k]) for k in ("adoption_ramp", "maturity_ramp", "assist_ramp", "qa_ramp", "ramp_other", "attrition_ramp", "ai_ops_ramp")}


def _core(assumptions, scenario, overrides, full):
    p, special = resolve_params(assumptions, scenario, overrides)
    pr = resolve_prices(assumptions, p["openai_deployment_type"])
    d = _derive(p, special)
    C, agents, vs = float(p["contacts_per_year"]), float(p["agents"]), p["voice_share_of_contacts"]
    cpc, var, loaded, T0 = d["cost_per_contact_usd"], p["variable_cost_share"], d["loaded_cost_per_agent_usd"], d["baseline_annual_human_cost_usd"]
    yrs = range(1, HORIZON + 1)

    # ---- Azure consumption per period (index 0 = pilot)
    pilot_seats = p["pilot_seats"]
    pilot_ctx = {"contacts": pilot_seats * d["contacts_per_agent_year"] * p["pilot_months"] / 12.0, "period_years": p["pilot_months"] / 12.0,
                 "adoption": 1.0, "maturity": p["pilot_maturity"], "assist": 1.0, "qa_share": p["qa_coverage_target"],
                 "seats_in_scope": float(pilot_seats), "tier": _tier_for(assumptions, pilot_seats)}
    az = [_azure(p, pr, assumptions, pilot_ctx)]
    for t in yrs:
        a = p["adoption_ramp"][t - 1]
        ctx = {"contacts": C, "period_years": 1.0, "adoption": a, "maturity": p["maturity_ramp"][t - 1], "assist": p["assist_ramp"][t - 1],
               "qa_share": p["qa_coverage_target"] * p["qa_ramp"][t - 1], "seats_in_scope": agents * a, "tier": _tier_for(assumptions, agents * a)}
        az.append(_azure(p, pr, assumptions, ctx))

    # ---- benefits (gross = before confidence factor)
    conf = {"ai_containment": p["confidence_containment"], "aht_reduction": p["confidence_aht"], "qa_quality": p["confidence_qa"],
            "attrition": p["confidence_attrition"], "abandonment_csat_retention": p["confidence_revenue"],
            "peak_resilience": p["confidence_peak"], "compliance_risk": p["confidence_compliance"], "multilingual": p["confidence_multilingual"]}
    gross = {k: [0.0] * (HORIZON + 1) for k in BENEFIT_KEYS}
    fte_gross, fte_adj, avoided_contacts = [0.0] * (HORIZON + 1), [0.0] * (HORIZON + 1), [0.0] * (HORIZON + 1)
    qa_cov = p["qa_coverage_target"]
    frag = p["fragmentation_overhead_pct"]
    for t in yrs:
        a, m, s = p["adoption_ramp"][t - 1], p["maturity_ramp"][t - 1], p["assist_ramp"][t - 1]
        o, at, qr = p["ramp_other"][t - 1], p["attrition_ramp"][t - 1], p["qa_ramp"][t - 1]
        resolved = C * a * min(1.0, p["ai_containment_pct"] * m)
        avoided = resolved * cpc * p["tier1_aht_factor"]
        aht = (T0 - avoided) * s * p["aht_reduction_pct"]
        avoided_contacts[t] = resolved
        fte_gross[t] = (avoided + aht) / loaded
        fte_adj[t] = (avoided * conf["ai_containment"] + aht * conf["aht_reduction"]) / loaded
        gross["ai_containment"][t] = avoided * var
        gross["aht_reduction"][t] = aht * var
        gross["qa_quality"][t] = (d["qa_fte_baseline"] * p["qa_analyst_cost_usd"] * p["qa_effort_reduction_pct"] * qa_cov * qr
                                  + C * p["repeat_contact_share"] * p["repeat_reduction_pct"] * qa_cov * qr * cpc * var)
        gross["attrition"][t] = (agents * p["attrition_reduction_pp"] * at + fte_adj[t] * p["attrition_rate"]) * p["replacement_cost_usd"]
        gross["abandonment_csat_retention"][t] = (
            C * vs * p["abandon_rate_voice"] * p["abandon_reduction_pct"] * o * p["margin_per_recovered_contact_usd"]
            + (C / p["contacts_per_customer"]) * p["churn_reduction_pp"] * p["gross_margin_per_customer_usd"] * o)
        gross["peak_resilience"][t] = C * p["overflow_share_of_contacts"] * p["ai_overflow_absorption_pct"] * a * m * p["overflow_premium_usd_per_contact"]
        gross["compliance_risk"][t] = p["compliance_incidents_per_year"] * p["compliance_cost_per_incident_usd"] * p["compliance_risk_reduction_pct"] * o
        gross["multilingual"][t] = C * p["small_language_contact_share"] * cpc * (frag / (1 + frag)) * p["ai_pooling_recovery_pct"] * var * o
    ben = {k: [gross[k][t] * conf[k] for t in range(HORIZON + 1)] for k in BENEFIT_KEYS}
    ben_by_year = [sum(ben[k][t] for k in BENEFIT_KEYS) for t in range(HORIZON + 1)]

    # ---- costs
    impl = p["implementation_fixed_usd"] + p["implementation_per_seat_usd"] * agents
    change = p["change_mgmt_per_agent_usd"] * agents
    other = {k: [0.0] * (HORIZON + 1) for k in OTHER_COST_KEYS}
    other["implementation_integration"][0] = impl
    other["change_management"][0] = change
    other["contingency"][0] = (impl + change) * p["contingency_pct"]
    for t in yrs:
        other["ai_operations_team"][t] = p["ai_ops_fte"] * p["ai_ops_cost_per_fte_usd"] * p["ai_ops_ramp"][t - 1]
        other["licences_and_telephony_interop"][t] = p["third_party_run_usd_per_seat_year"] * agents * p["adoption_ramp"][t - 1]
        other["support_and_maintenance"][t] = p["support_pct_of_implementation"] * impl
    azure_by_family = {k: [az[t]["by_family"][k] for t in range(HORIZON + 1)] for k in FAMILY_KEYS}
    azure_by_year = [az[t]["total"] for t in range(HORIZON + 1)]
    for t in range(HORIZON + 1):
        other["communications_outside_azure"][t] = az[t]["passthrough"]
    other_by_year = [sum(other[k][t] for k in OTHER_COST_KEYS) for t in range(HORIZON + 1)]
    cost_by_year = [azure_by_year[t] + other_by_year[t] for t in range(HORIZON + 1)]

    # ---- ROI
    net = [ben_by_year[t] - cost_by_year[t] for t in range(HORIZON + 1)]
    cum, run = [], 0.0
    for v in net:
        run += v
        cum.append(run)
    rate = p["discount_rate"]
    pay_go_live = _payback_months(cost_by_year[0], ben_by_year[1:], cost_by_year[1:])
    total_cost, total_ben = sum(cost_by_year), sum(ben_by_year)
    roi = {
        "net_benefit_by_year": net, "cumulative": cum, "npv": _npv(rate, net), "discount_rate": rate,
        "roi_pct": (total_ben - total_cost) / total_cost * 100.0 if total_cost else None,
        "payback_months": None if pay_go_live is None else pay_go_live + p["implementation_months"],
        "payback_months_from_go_live": pay_go_live,
        "irr_pct": None if _irr(net) is None else _irr(net) * 100.0,
        "benefit_cost_ratio": total_ben / total_cost if total_cost else None,
        "implementation_months": p["implementation_months"],
    }
    result = {"roi": roi}
    if not full:
        return result

    # ---- ACR block
    by_group = {g: [sum(azure_by_family[f][t] for f, _, grp in FAMILIES if grp == g) for t in range(HORIZON + 1)] for g in GROUPS}
    y3 = az[HORIZON]
    ai3 = sum(y3["by_family"][f] for f, _, g in FAMILIES if g == "ai")
    attach3 = y3["total"] - ai3
    ss_adopt = p["adoption_ramp"][-1]
    tiers = []
    for td in assumptions["tiers"]["definitions"]:
        seats = float(td["seats"])
        ctx = {"contacts": seats * d["contacts_per_agent_year"], "period_years": 1.0, "adoption": ss_adopt, "maturity": 1.0, "assist": 1.0,
               "qa_share": qa_cov, "seats_in_scope": seats * ss_adopt, "tier": td}
        r = _azure(p, pr, assumptions, ctx)
        v = r["volumes"]
        tiers.append({
            "name": td["label"], "seats": td["seats"], "contacts_per_year": ctx["contacts"], "ai_first_coverage": ss_adopt,
            "annual_acr_usd": r["total"], "by_family": r["by_family"], "acr_per_seat_per_month_usd": r["total"] / seats / 12.0,
            "acr_per_contact_usd": r["total"] / ctx["contacts"], "ai_resolved_contacts": v["ai_resolved_contacts"],
            "azure_cost_per_ai_resolved_contact_usd": r["total"] / v["ai_resolved_contacts"] if v["ai_resolved_contacts"] else None,
            "communications_outside_azure_usd": r["passthrough"], "platform_cost_usd": r["total_all"],
            "platform_cost_per_ai_resolved_contact_usd": r["total_all"] / v["ai_resolved_contacts"] if v["ai_resolved_contacts"] else None,
            "fixed_platform_share": sum(i["azure_usd"] for i in r["items"] if i["fixed"]) / r["total"], "sizing": r["sizing"],
        })
    ref_tier = min(tiers, key=lambda t: abs(t["seats"] - agents))
    opp = assumptions["assumptions"]
    opportunity = {
        "global_contact_center_agents": p["global_contact_center_agents"],
        "addressable_share": p["opportunity_addressable_share"],
        "acr_per_seat_per_year_usd": ref_tier["annual_acr_usd"] / ref_tier["seats"],
        "basis_tier": ref_tier["name"],
        "scenarios": [{"penetration": pen, "seats": p["global_contact_center_agents"] * p["opportunity_addressable_share"] * pen,
                       "annual_acr_usd": p["global_contact_center_agents"] * p["opportunity_addressable_share"] * pen
                       * ref_tier["annual_acr_usd"] / ref_tier["seats"]} for pen in p["opportunity_penetration_levels"]],
        "label": "Illustrative, assumption-driven; not a forecast. " + opp["global_contact_center_agents"]["source"],
    }
    acr = {
        "by_year": azure_by_year, "by_family": azure_by_family, "by_group": by_group, "family_labels": {f: l for f, l, _ in FAMILIES},
        "group_labels": GROUPS, "run_rate_year3": y3["total"], "three_year_total": sum(azure_by_year[1:]), "pilot_year0": azure_by_year[0],
        "communications_outside_azure_by_year": [az[t]["passthrough"] for t in range(HORIZON + 1)],
        "azure_billed_share_of_communications": p["comms_azure_billed_share"],
        "tiers": tiers, "pull_through_ratio": attach3 / ai3 if ai3 else None,
        "pull_through": {"ai_services_year3": ai3, "attached_services_year3": attach3,
                         "definition": "Azure-billed spend outside AI models/services (communications billed through Azure, data, platform, security) per $1 of AI models/services spend, Year 3"},
        "by_purpose_year3": y3["by_purpose_azure"], "by_purpose_year3_incl_communications": y3["by_purpose"],
        "line_items_year3": y3["items"], "sizing_year3": y3["sizing"], "opportunity_sizing": opportunity,
    }

    # ---- unit economics (Year 3 run-rate)
    v3 = y3["volumes"]
    items3 = y3["items"]
    tag_azure = lambda tag: sum(i["azure_usd"] for i in items3 if i["tag"] == tag)
    tag_all = lambda tag: sum(i["usd"] for i in items3 if i["tag"] == tag)
    purpose, purpose_az = y3["by_purpose"], y3["by_purpose_azure"]
    recurring_other3 = sum(other[k][HORIZON] for k in OTHER_COST_KEYS)
    one_time = sum(other[k][0] for k in OTHER_COST_KEYS) + azure_by_year[0]
    resolved3 = v3["ai_resolved_contacts"]
    all_in = (y3["total"] + recurring_other3 + one_time / HORIZON) / resolved3 if resolved3 else None
    cost_red3 = sum(ben[k][HORIZON] for k in COST_REDUCTION_BENEFITS)
    with_cx = (T0 - cost_red3 + y3["total"] + recurring_other3 + one_time / HORIZON) / C

    def per(num, den):
        return num / den if den else None

    unit = {
        "basis": "Year-3 run-rate at list price. 'azure' = billed through Azure meters; 'platform' = Azure plus communications billed outside Azure. "
                 "All-in includes AI operations, licences, support and one-time costs amortised over the horizon.",
        "human_cost_per_contact_usd": cpc, "human_cost_per_voice_contact_usd": d["cost_per_contact_voice_usd"],
        "human_cost_per_digital_contact_usd": d["cost_per_contact_digital_usd"],
        "human_cost_per_resolved_contact_usd": d["cost_per_resolved_contact_usd"],
        "ai_first_leg_azure_cost_per_ai_first_contact_usd": per(purpose_az.get("ai_first", 0.0), v3["ai_first_contacts"]),
        "ai_first_leg_platform_cost_per_ai_first_contact_usd": per(purpose.get("ai_first", 0.0), v3["ai_first_contacts"]),
        "ai_first_leg_azure_cost_per_ai_resolved_contact_usd": per(purpose_az.get("ai_first", 0.0), resolved3),
        "ai_first_leg_platform_cost_per_ai_resolved_contact_usd": per(purpose.get("ai_first", 0.0), resolved3),
        "total_azure_cost_per_contact_usd": y3["total"] / C,
        "total_azure_cost_per_ai_resolved_contact_usd": per(y3["total"], resolved3),
        "total_platform_cost_per_ai_resolved_contact_usd": per(y3["total_all"], resolved3),
        "azure_cost_per_voice_ai_minute_usd": per(tag_azure("voice_ai"), v3["ai_voice_minutes"]),
        "platform_cost_per_voice_ai_minute_usd": per(tag_all("voice_ai"), v3["ai_voice_minutes"]),
        "azure_cost_per_digital_ai_contact_usd": per(tag_azure("digital_ai"), v3["ai_first_digital_contacts"]),
        "platform_cost_per_digital_ai_contact_usd": per(tag_all("digital_ai"), v3["ai_first_digital_contacts"]),
        "azure_cost_per_assisted_human_contact_usd": per(purpose_az.get("human_assist", 0.0), v3["assisted_human_contacts"]),
        "azure_cost_per_qa_scored_contact_usd": per(purpose_az.get("quality_insight", 0.0), v3["qa_scored_contacts"]),
        "all_in_ai_cost_per_resolved_contact_usd": all_in,
        "human_to_ai_cost_ratio_per_resolved_contact": per(d["cost_per_resolved_contact_usd"], all_in),
        "blended_cost_per_contact_with_concierge_usd": with_cx,
        "blended_cost_reduction_pct": (cpc - with_cx) / cpc * 100.0,
        "fte_equivalent_released_year3_gross": fte_gross[HORIZON], "fte_equivalent_released_year3_risk_adjusted": fte_adj[HORIZON],
    }
    vol_keys = list(az[0]["volumes"].keys())
    result.update({
        "scenario": scenario, "currency": assumptions["meta"]["currency"], "horizon_years": HORIZON, "model_version": MODEL_VERSION,
        "price_basis": assumptions["meta"]["price_basis"],
        "inputs": {"assumptions": p, "overrides": {k: v for k, v in (overrides or {}).items()}, "derived": d, "ramps": _ramp_view(p),
                   "time_axis": "index 0 = Year 0 (build + pilot); 1..3 = production years"},
        "volumes": {k: [az[t]["volumes"][k] for t in range(HORIZON + 1)] for k in vol_keys},
        "benefits": {"by_category": ben, "gross_by_category": gross, "confidence_factors": conf, "total_by_year": ben_by_year, "total": total_ben,
                     "labels": dict(BENEFITS), "fte_equivalent_released_gross": fte_gross, "fte_equivalent_released_risk_adjusted": fte_adj,
                     "ai_resolved_contacts": avoided_contacts},
        "costs": {"azure_by_family": azure_by_family, "other_by_category": other, "total_by_year": cost_by_year, "total": total_cost,
                  "azure_total_by_year": azure_by_year, "other_total_by_year": other_by_year, "labels": dict(OTHER_COSTS)},
        "acr": acr, "unit_economics": unit,
    })
    result["sensitivity"] = _tornado(assumptions, scenario, overrides, roi["npv"])
    return result


def _tornado(assumptions, scenario, overrides, centre_npv):
    rows = []
    for key, e in assumptions["assumptions"].items():
        if e.get("kind") in ("market",) or not isinstance(e["base"], (int, float, list)) or isinstance(e["base"], bool):
            continue
        if e["low"] == e["high"]:
            continue
        ov = {k: v for k, v in (overrides or {}).items() if OVERRIDE_ALIASES.get(k, k) != key}
        npvs = {}
        for end in ("low", "high"):
            ov2 = dict(ov)
            ov2[key] = list(e[end]) if isinstance(e[end], list) else e[end]
            npvs[end] = _core(assumptions, scenario, ov2, False)["roi"]["npv"]
        swing = abs(npvs["high"] - npvs["low"])
        if swing > 1e-9:
            rows.append({"assumption": key, "label": e.get("label", key), "unit": e.get("unit", ""), "low_value": e["low"], "high_value": e["high"],
                         "npv_at_low": npvs["low"], "npv_at_high": npvs["high"], "delta_at_low": npvs["low"] - centre_npv,
                         "delta_at_high": npvs["high"] - centre_npv, "swing": swing})
    rows.sort(key=lambda r: (-r["swing"], r["assumption"]))
    return rows


def compute(assumptions, scenario="base", overrides=None):
    """ROI + ACR for one scenario. `overrides` maps assumption keys (or aliases) to replacement values."""
    return _core(assumptions, scenario, overrides, True)


def compute_all(assumptions):
    return {s: compute(assumptions, s) for s in SCENARIOS}


def _round_tree(obj, nd=4):
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round_tree(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round_tree(v, nd) for v in obj]
    return obj


def headline(res):
    """Compact numbers quoted by the PRD, architecture and deck."""
    roi, acr, ue = res["roi"], res["acr"], res["unit_economics"]
    return {
        "npv_usd": roi["npv"], "roi_pct": roi["roi_pct"], "payback_months": roi["payback_months"],
        "payback_months_from_go_live": roi["payback_months_from_go_live"], "irr_pct": roi["irr_pct"],
        "benefits_3yr_usd": res["benefits"]["total"], "costs_3yr_usd": res["costs"]["total"],
        "benefits_year3_usd": res["benefits"]["total_by_year"][3], "net_benefit_year3_usd": roi["net_benefit_by_year"][3],
        "acr_year3_usd": acr["run_rate_year3"], "acr_3yr_total_usd": acr["three_year_total"],
        "communications_outside_azure_year3_usd": acr["communications_outside_azure_by_year"][3],
        "pull_through_ratio": acr["pull_through_ratio"],
        "human_cost_per_contact_usd": ue["human_cost_per_contact_usd"],
        "all_in_ai_cost_per_resolved_contact_usd": ue["all_in_ai_cost_per_resolved_contact_usd"],
        "azure_cost_per_voice_ai_minute_usd": ue["azure_cost_per_voice_ai_minute_usd"],
        "platform_cost_per_voice_ai_minute_usd": ue["platform_cost_per_voice_ai_minute_usd"],
        "blended_cost_reduction_pct": ue["blended_cost_reduction_pct"],
    }


def build_outputs(assumptions):
    scen = compute_all(assumptions)
    stress = {s: compute(assumptions, s) for s in STRESS_SCENARIOS}
    meta = {k: assumptions["meta"][k] for k in ("model_version", "currency", "price_basis", "price_date", "reference_customer", "disclaimer",
                                                "scenario_blend")
            if k in assumptions["meta"]}
    meta["generated_by"] = "business-case/model.py"
    meta["layout"] = ("scenarios.<conservative|base|upside> = compute(assumptions, scenario); stress.<stacked_downside|stacked_upside> = every "
                      "uncertain driver at its bound at once (headline only); headline = quoted numbers per scenario")
    return {"meta": meta, "headline": {s: headline(r) for s, r in scen.items()},
            "stress": {s: headline(r) for s, r in stress.items()}, "scenarios": scen}


# --------------------------------------------------------------------------- markdown report
def _usd(x, digits=1):
    if x is None:
        return "n/a"
    sign = "-" if x < 0 else ""
    x = abs(x)
    if x >= 1e9:
        return f"{sign}${x / 1e9:,.{digits}f}B"
    if x >= 1e6:
        return f"{sign}${x / 1e6:,.{digits}f}M"
    if x >= 1e3:
        return f"{sign}${x / 1e3:,.{digits}f}K"
    return f"{sign}${x:,.2f}"


def _fmt(v):
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    if isinstance(v, float):
        return f"{v:,.4g}"
    return str(v)


def render_markdown(assumptions, outputs):
    sc, base = outputs["scenarios"], outputs["scenarios"]["base"]
    L = []
    w = L.append
    w("# Business case outputs - SwarmAI Contact Center (Concierge)\n")
    w(f"*Generated by `model.py` v{MODEL_VERSION}. {assumptions['meta']['price_basis']} Reference customer: {assumptions['meta']['reference_customer']}. "
      f"{assumptions['meta'].get('disclaimer', '')}*\n")
    w("## 1. Scenario summary\n")
    w("| Metric | Conservative | Base | Upside |")
    w("|---|---:|---:|---:|")
    rows = [
        ("3-year NPV (discount rate in model)", lambda r: _usd(r["roi"]["npv"])),
        ("ROI % (3-year, undiscounted)", lambda r: f"{r['roi']['roi_pct']:,.0f} %"),
        ("Payback from project start (months)", lambda r: "n/a" if r["roi"]["payback_months"] is None else f"{r['roi']['payback_months']:.1f}"),
        ("Payback from go-live (months)", lambda r: "n/a" if r["roi"]["payback_months_from_go_live"] is None else f"{r['roi']['payback_months_from_go_live']:.1f}"),
        ("IRR %", lambda r: "n/a" if r["roi"]["irr_pct"] is None else f"{r['roi']['irr_pct']:,.0f} %"),
        ("3-year risk-adjusted benefits", lambda r: _usd(r["benefits"]["total"])),
        ("3-year total cost (incl. Azure)", lambda r: _usd(r["costs"]["total"])),
        ("Year-3 benefits", lambda r: _usd(r["benefits"]["total_by_year"][3])),
        ("Year-3 Azure consumption (ACR)", lambda r: _usd(r["acr"]["run_rate_year3"], 2)),
        ("3-year Azure consumption (ACR, Y1-Y3)", lambda r: _usd(r["acr"]["three_year_total"], 2)),
        ("Year-3 communications billed outside Azure (customer cost)", lambda r: _usd(r["acr"]["communications_outside_azure_by_year"][3], 2)),
        ("Pull-through (attached $ per $1 of AI services), Y3", lambda r: f"{r['acr']['pull_through_ratio']:.2f}"),
        ("Human cost per contact", lambda r: f"${r['unit_economics']['human_cost_per_contact_usd']:.2f}"),
        ("All-in AI cost per verified-resolved contact", lambda r: f"${r['unit_economics']['all_in_ai_cost_per_resolved_contact_usd']:.2f}"),
        ("Azure cost per voice AI minute", lambda r: f"${r['unit_economics']['azure_cost_per_voice_ai_minute_usd']:.3f}"),
        ("Platform cost per voice AI minute (incl. communications)", lambda r: f"${r['unit_economics']['platform_cost_per_voice_ai_minute_usd']:.3f}"),
    ]
    for label, fn in rows:
        w(f"| {label} | " + " | ".join(fn(sc[s]) for s in SCENARIOS) + " |")
    w("")
    st = outputs["stress"]
    w(f"*Scenario definitions: conservative / upside move the uncertain outcome and cost assumptions {assumptions['meta'].get('scenario_blend', 1.0) * 100:.0f} % of the way "
      f"from base to their bounds. Stress test with every uncertain driver at its bound simultaneously (not a forecast): stacked downside NPV "
      f"{_usd(st['stacked_downside']['npv_usd'])}, ROI {st['stacked_downside']['roi_pct']:,.0f} %; stacked upside NPV {_usd(st['stacked_upside']['npv_usd'])}.*\n")
    w("## 2. Base case - benefits by category (risk-adjusted)\n")
    w("| Category | Y1 | Y2 | Y3 | 3-year |")
    w("|---|---:|---:|---:|---:|")
    for k, label in BENEFITS:
        v = base["benefits"]["by_category"][k]
        w(f"| {label} | {_usd(v[1])} | {_usd(v[2])} | {_usd(v[3])} | {_usd(sum(v))} |")
    tb = base["benefits"]["total_by_year"]
    w(f"| **Total** | **{_usd(tb[1])}** | **{_usd(tb[2])}** | **{_usd(tb[3])}** | **{_usd(base['benefits']['total'])}** |\n")
    w("## 3. Base case - costs and cash flow\n")
    w("| Item | Year 0 | Y1 | Y2 | Y3 | Total |")
    w("|---|---:|---:|---:|---:|---:|")
    for k, label in OTHER_COSTS:
        v = base["costs"]["other_by_category"][k]
        w(f"| {label} | " + " | ".join(_usd(x) for x in v) + f" | {_usd(sum(v))} |")
    az = base["costs"]["azure_total_by_year"]
    w(f"| Azure consumption (ACR, list price) | " + " | ".join(_usd(x) for x in az) + f" | {_usd(sum(az))} |")
    ct = base["costs"]["total_by_year"]
    w(f"| **Total cost** | " + " | ".join(f"**{_usd(x)}**" for x in ct) + f" | **{_usd(base['costs']['total'])}** |")
    nb = base["roi"]["net_benefit_by_year"]
    w("| **Net benefit** | " + " | ".join(f"**{_usd(x)}**" for x in nb) + f" | **{_usd(sum(nb))}** |")
    w("| Cumulative net benefit | " + " | ".join(_usd(x) for x in base["roi"]["cumulative"]) + " | |\n")
    w("## 4. Base case - ACR bottom-up by Azure service family\n")
    w("| Service family | Year 0 (pilot) | Y1 | Y2 | Y3 |")
    w("|---|---:|---:|---:|---:|")
    for f, label, _ in FAMILIES:
        v = base["acr"]["by_family"][f]
        w(f"| {label} | " + " | ".join(_usd(x, 2) for x in v) + " |")
    w("| **Total** | " + " | ".join(f"**{_usd(x, 2)}**" for x in base["acr"]["by_year"]) + " |\n")
    w("### ACR by seat tier (steady state, annual, list price)\n")
    w("| Tier | Seats | Contacts / yr | ACR / yr (Azure-billed) | ACR / seat / month | ACR / contact | Azure cost / AI-resolved contact | Communications outside Azure / yr | Fixed platform share |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t in base["acr"]["tiers"]:
        w(f"| {t['name']} | {t['seats']:,} | {t['contacts_per_year']:,.0f} | {_usd(t['annual_acr_usd'], 2)} | ${t['acr_per_seat_per_month_usd']:,.0f} | "
          f"${t['acr_per_contact_usd']:.3f} | ${t['azure_cost_per_ai_resolved_contact_usd']:.2f} | {_usd(t['communications_outside_azure_usd'], 2)} | "
          f"{t['fixed_platform_share'] * 100:.0f} % |")
    w("")
    w("### Year-3 line items (base case; audit trail). `ACR (USD)` = Azure-billed part; `Cost (USD)` = total incl. communications billed elsewhere\n")
    w("| Family | Purpose | Line | Quantity | Unit | Unit price (USD) | Factor | Cost (USD) | ACR (USD) |")
    w("|---|---|---|---:|---|---:|---:|---:|---:|")
    for it in base["acr"]["line_items_year3"]:
        w(f"| {it['family']} | {it['purpose']} | {it['name']} | {it['quantity']:,.1f} | {it['unit']} | {it['unit_price']:.6g} | {it['factor']:.2f} | "
          f"{it['usd']:,.0f} | {it['azure_usd']:,.0f} |")
    w("")
    w("## 5. Unit economics (Year 3, base case)\n")
    w("| Metric | Value |")
    w("|---|---:|")
    for k, v in base["unit_economics"].items():
        if isinstance(v, (int, float)):
            w(f"| {k} | {v:,.4f} |")
    w("")
    w("## 6. Sensitivity - tornado on NPV (base case, top 12)\n")
    w("| Assumption | Low value | High value | NPV at low | NPV at high | Swing |")
    w("|---|---:|---:|---:|---:|---:|")
    for r in base["sensitivity"][:12]:
        w(f"| {r['label']} | {_fmt(r['low_value'])} | {_fmt(r['high_value'])} | {_usd(r['npv_at_low'])} | {_usd(r['npv_at_high'])} | {_usd(r['swing'])} |")
    w("")
    opp = base["acr"]["opportunity_sizing"]
    w("## 7. Illustrative opportunity sizing (assumption-driven)\n")
    w(f"Global contact-center agents: {opp['global_contact_center_agents']:,.0f}; addressable share {opp['addressable_share'] * 100:.0f} %; "
      f"ACR per seat per year at the {opp['basis_tier']} tier: ${opp['acr_per_seat_per_year_usd']:,.0f}.\n")
    w("| Penetration of addressable seats | Seats | Annual ACR |")
    w("|---:|---:|---:|")
    for s in opp["scenarios"]:
        w(f"| {s['penetration'] * 100:.0f} % | {s['seats']:,.0f} | {_usd(s['annual_acr_usd'])} |")
    w(f"\n*{opp['label']}*\n")
    w("## 8. Assumptions (base / low / high)\n")
    w("| Key | Label | Unit | Low | Base | High | Flag |")
    w("|---|---|---|---:|---:|---:|---|")
    for k, e in assumptions["assumptions"].items():
        cell = lambda x: str(x).replace("|", "/")
        w(f"| `{k}` | {cell(e.get('label', k))} | {cell(e.get('unit', ''))} | {_fmt(e['low'])} | {_fmt(e['base'])} | {_fmt(e['high'])} | {e.get('flag', '')} |")
    w("")
    return "\n".join(L) + "\n"


def main(argv):
    here = Path(__file__).resolve().parent
    assumptions = load_assumptions(here / "assumptions.json")
    outputs = _round_tree(build_outputs(assumptions))
    json_text = json.dumps(outputs, indent=1, ensure_ascii=False) + "\n"
    md_text = render_markdown(assumptions, outputs)
    if "--check" in argv:
        ok = (here / "outputs.json").read_text(encoding="utf-8") == json_text and (here / "outputs.md").read_text(encoding="utf-8") == md_text
        print("outputs.json / outputs.md are up to date" if ok else "outputs are STALE - run: python model.py")
        return 0 if ok else 1
    (here / "outputs.json").write_text(json_text, encoding="utf-8")
    (here / "outputs.md").write_text(md_text, encoding="utf-8")
    h = outputs["headline"]["base"]
    print(f"model v{MODEL_VERSION}: base NPV {_usd(h['npv_usd'])}, ROI {h['roi_pct']:.0f} %, payback {h['payback_months']:.1f} months, "
          f"Year-3 ACR {_usd(h['acr_year3_usd'], 2)}")
    print("wrote outputs.json and outputs.md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

