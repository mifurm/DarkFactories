"""Live-call regression: the realtime model read citation markers aloud ("this is based on [K1]", "reference K3", "według artykułu [K1]").

Causes: rule 3 of the global prompt and the Polish language guide say "cite like [K1]" / "keep the citation markers", and the search_knowledge result carried
"Cite as [K1]". On a voice call both must be overridden; chat keeps its citations."""

from __future__ import annotations

import pytest

from concierge.engine.prompts import VOICE_NO_MARKERS, build_system_prompt
from concierge.engine.tools import ToolContext


async def _ctx(svc, lang: str, agent: str) -> ToolContext:
    conv = await svc.orchestrator.start(language=lang, recording_consent="granted")
    cfg = await svc.configs.active()
    if agent == "voice":  # same tool union as features/voice/session.py::_voice_cfg
        union = sorted(set(cfg.tools.get("authentication", [])) | set(cfg.tools.get("resolution", [])))
        cfg = cfg.model_copy(update={"tools": {**cfg.tools, "voice": union}})
    return ToolContext(svc=svc, conv=conv, agent=agent, actor="ai", cfg=cfg)


@pytest.mark.parametrize("lang", ["en", "pl"])
async def test_voice_prompt_ends_with_the_no_marker_override_and_chat_prompt_is_unchanged(svc, lang):
    conv = await svc.orchestrator.start(language=lang, recording_consent="granted")
    cfg = await svc.configs.active()
    voice = build_system_prompt(cfg, conv, "resolution", voice=True)
    chat = build_system_prompt(cfg, conv, "resolution", voice=False)
    assert VOICE_NO_MARKERS in voice and VOICE_NO_MARKERS not in chat
    last_cite_instruction = max(voice.rfind("cite them like [K1]"), voice.rfind("citation markers [K1]"))
    assert last_cite_instruction >= 0, "the chat citation instructions are still in the shared prompt"
    assert voice.index(VOICE_NO_MARKERS) > last_cite_instruction, "the override must come after (and so win over) every citation instruction"
    assert "[K1]" in chat, "chat keeps its citations"


@pytest.mark.parametrize(("lang", "query"), [("en", "What is your return policy? 30 days"), ("pl", "Ile mam dni na zwrot towaru? zasady zwrotów 30 dni")])
async def test_voice_knowledge_result_carries_no_reference_markers(svc, lang, query):
    voice = await svc.tools.execute(await _ctx(svc, lang, "voice"), "search_knowledge", {"query": query, "top_k": 2})
    chat = await svc.tools.execute(await _ctx(svc, lang, "resolution"), "search_knowledge", {"query": query, "top_k": 2})
    assert voice.data["answerable"] and chat.data["answerable"]
    assert all("ref" not in r for r in voice.data["results"]) and "[K1]" not in voice.data["note"] and "Cite as" not in voice.data["note"]
    assert "never say source ids" in voice.data["note"]
    assert all(r["ref"].startswith("K") for r in chat.data["results"]) and chat.data["note"].endswith("Cite as [K1].")
    assert [r["doc_id"] for r in voice.data["results"]] == [r["doc_id"] for r in chat.data["results"]], "same retrieval, only the presentation differs"
