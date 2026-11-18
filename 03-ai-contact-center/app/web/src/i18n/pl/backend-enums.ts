import type { Dict } from '../types'

/**
 * Values the backend sends only in some modes or states (azure mode, real model calls, metering, provider ids, outbound check codes). The offline stub never
 * produces them, so they are listed in `../backend-enums.json` and `npm test` checks that each one has an entry here (or in the partial that owns the group).
 * This file only adds the keys that were missing in groups defined elsewhere (quarantine, summarySource, masking, vocTerm, server) and owns the new groups.
 */
const backendEnums: Partial<Dict> = {
  t: {
    'Red team (PL): {category}': 'Red team (PL): {category}',
  },
  k: {
    // Azure Content Safety Prompt Shields flags an attack that the local rules did not
    quarantine: {
      azure_prompt_shields: 'atak na prompt wykryty przez Azure Prompt Shields',
      override_instructions_bare_pl: 'nadpisywanie instrukcji',
      override_instructions_mixed_pl: 'nadpisywanie instrukcji',
      reveal_prompt_pl_2: 'ujawnianie promptu systemowego',
    },
    // outbound messages are composed by the model (guarded) or from a template; hand-off summaries by the model or by extraction
    summarySource: { template: 'szablon', 'template (guard fallback)': 'szablon (zastępczy po kontroli strażnika)', 'llm+guard': 'model językowy (LLM) + kontrola strażnika' },
    masking: { 'masked (role has no PII access)': 'zamaskowane (rola bez dostępu do danych osobowych)' },
    vocTerm: { link: 'link', replacement: 'wymiana', returned: 'zwrócone' },
    // the compact Polish suites (offered in the Polish UI) and the Polish red-team suite of the API
    suite: { 'pl-smoke': 'pakiet polski — test dymny', 'pl-gate': 'pakiet polski — bramka', 'pl-redteam': 'pakiet polski — red team' },
    // why a customer returns an item (the initiate_return tool's reason, shown on the CRM timeline)
    returnReason: { damaged: 'uszkodzony towar', defective: 'wada towaru', changed_mind: 'rezygnacja z zakupu', wrong_item: 'otrzymano inny towar', other: 'inny powód' },
    // QA: deterministic rules alone (offline, or when the model failed) or rules plus the model judge
    qaScorer: { rules: 'reguły', 'rules+llm': 'reguły + model językowy (LLM)' },
    // VoC topic labels: c-TF-IDF terms alone, or named by the model
    vocLabeller: { 'c-tf-idf': 'c-tf-idf', llm: 'model językowy (LLM)' },
    // AI metering: what a call was made for (chart axis of "usage by feature")
    meterFeature: {
      chat: 'czat',
      embed: 'embeddingi',
      kb_embed: 'embeddingi KB',
      voc_embed: 'embeddingi VoC',
      speech: 'mowa',
      wrapup: 'podsumowanie',
      voice: 'głos',
      voc_label: 'etykiety VoC',
      understanding: 'rozumienie',
      translate: 'tłumaczenie',
      simulator: 'symulator',
      readyz: 'gotowość',
      qa: 'ocena QA',
      outbound: 'proaktywny',
      kb_query: 'zapytania KB',
      kb_ask: 'odpowiedzi KB',
      handoff: 'przekazanie',
      assist: 'Assist',
      language: 'Azure AI Language',
      content_safety: 'Content Safety',
    },
    // AI metering: model deployments keep their names (gpt-…); the Azure AI services metered as "models" get a readable name
    meterModel: { 'speech-stt': 'rozpoznawanie mowy (Azure Speech)', 'speech-tts': 'synteza mowy (Azure Speech)', language: 'Azure AI Language', content_safety: 'Azure AI Content Safety' },
    // /readyz dependency checks
    readyCheck: { cosmos: 'Cosmos DB', storage: 'Blob Storage', openai: 'Azure OpenAI', cognitive: 'Azure AI', seed: 'dane startowe' },
    // who produced a language detection / translation
    i18nProvider: {
      offline: 'reguły offline',
      rules: 'reguły',
      azure: 'Azure AI',
      'azure+rules': 'Azure AI Language + reguły',
      none: 'bez tłumaczenia',
      'offline-glossary': 'słownik offline',
      'azure-openai': 'Azure OpenAI',
    },
    telephonyProvider: {
      acs: 'Azure Communication Services',
      teams: 'Teams Phone Extensibility',
      sip: 'Azure OpenAI Realtime SIP',
      neutral: 'neutralny',
    },
    voiceMode: { realtime: 'realtime', pipeline: 'potok STT → LLM → TTS' },
    // outbound decision checks arrive as "name:value"
    outboundCheck: {
      kill_switch: 'wyłącznik awaryjny',
      campaign: 'kampania',
      prefs: 'preferencje kontaktu',
      opt_out: 'rezygnacja z kontaktu',
      consent: 'zgoda na kanał',
      frequency: 'limit częstotliwości',
      quiet_hours: 'godziny ciszy',
      daily_cap: 'limit dzienny',
    },
    outboundCheckValue: {
      on: 'włączony',
      off: 'wyłączony',
      active: 'aktywna',
      paused: 'wstrzymana',
      killed: 'zatrzymana',
      none: 'brak',
      all: 'wszystkie kanały',
      cap: 'osiągnięty',
      ok: 'w normie',
      deferred: 'odroczono',
      sms: 'SMS',
      email: 'e-mail',
      voice: 'głos',
    },
    server: {
      'azure-monitor-opentelemetry (managed identity ingestion)': 'azure-monitor-opentelemetry (przesyłanie danych przez tożsamość zarządzaną)',
    },
  },
}

export default backendEnums
