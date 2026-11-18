import type { EnumTable, PluralForms } from "../core";

/**
 * Cinematic motion (generative image→video): render quality, GPU worker status + warm-up, cost estimate, spot chip, storyboard motion prompts (CS-07 / CS-08).
 * Terms: tryb renderu (render quality) = podgląd / filmowy (Preview / Cinematic), ruch AI (AI motion), klip (clip), serwer GPU (GPU worker),
 * uśpiony / rozgrzewa się / gotowy (cold / warming up / ready), rozgrzać GPU (warm up), pamięć podręczna (cache). Units are separated by a no-break space (\u00A0).
 */
export const motionMessages: Record<string, string> = {
  // render quality
  "Render quality": "Tryb renderu",
  Preview: "Podgląd",
  "stills with camera moves (free, ~30 s)": "ruch kamery na nieruchomych klatkach (bezpłatnie, ok. 30\u00A0s)",
  Cinematic: "Filmowy",
  "AI video, real motion": "wideo AI z prawdziwym ruchem",
  "AI video, real motion (est. {cost} · ~{minutes} min)": "wideo AI z prawdziwym ruchem (szac. {cost} · ok. {minutes}\u00A0min)",
  "AI motion is not available on this server — only Preview can be rendered.": "Ruch AI nie jest dostępny na tym serwerze — można renderować tylko w trybie podglądu.",
  "The motion service cannot be reached right now — only Preview can be rendered.": "Usługa ruchu AI jest chwilowo nieosiągalna — można renderować tylko w trybie podglądu.",

  // GPU worker
  "GPU worker: ready": "Serwer GPU: gotowy",
  "GPU worker: warming up…": "Serwer GPU: rozgrzewa się…",
  "GPU worker: cold": "Serwer GPU: uśpiony",
  "Offline motion simulator": "Symulator ruchu offline",
  "Warm up GPU": "Rozgrzej GPU",
  "GPU warm-up requested": "Zlecono rozgrzanie GPU",
  "Starting from cold takes about {minutes} min — the GPU status on this page updates by itself.": "Uruchomienie z uśpienia trwa ok. {minutes}\u00A0min — stan GPU na tej stronie odświeży się samodzielnie.",
  "Starting from cold takes about {minutes} min ({cost} of GPU time) — the GPU status on this page updates by itself.":
    "Uruchomienie z uśpienia trwa ok. {minutes}\u00A0min (czas GPU: {cost}) — stan GPU na tej stronie odświeży się samodzielnie.",
  "No warm-up needed": "Rozgrzewanie niepotrzebne",
  "The GPU worker is already warming up or ready.": "Serwer GPU już się rozgrzewa lub jest gotowy.",

  // estimate
  "Cinematic estimate": "Szacunek dla trybu filmowego",
  "One AI clip per shot, generated one at a time on a single GPU. Clips already generated for the same keyframe and motion prompt are reused at no cost.":
    "Jeden klip AI na ujęcie, generowany po kolei na jednym GPU. Klipy wygenerowane wcześniej dla tej samej klatki kluczowej i opisu ruchu są używane ponownie bez kosztów.",
  "Estimate per shot": "Szacunek dla poszczególnych ujęć",
  Shot: "Ujęcie",
  "Shot {n}": "Ujęcie {n}",
  "Est. cost": "Szac. koszt",
  cached: "z pamięci podręcznej",
  "to generate": "do wygenerowania",
  Total: "Razem",
  "cached: {cached}/{total}": "z pamięci podręcznej: {cached}/{total}",
  "GPU time": "Czas GPU",
  "Estimated render time": "Szacowany czas renderu",
  "~{minutes} min": "ok. {minutes}\u00A0min",
  "GPU cold start (~{minutes} min)": "Uruchomienie GPU z uśpienia (ok. {minutes}\u00A0min)",
  "Budget left today": "Pozostały budżet na dziś",
  "Budget left for this campaign": "Pozostały budżet kampanii",
  "The GPU worker is warming up — rendering starts as soon as it is ready.": "Serwer GPU się rozgrzewa — renderowanie ruszy, gdy tylko będzie gotowy.",
  "The GPU worker is cold: the first shot also waits for the GPU to start (about {minutes} min). Warm it up now to skip that wait.":
    "Serwer GPU jest uśpiony: pierwsze ujęcie czeka dodatkowo na uruchomienie GPU (ok. {minutes}\u00A0min). Rozgrzej go teraz, aby pominąć to oczekiwanie.",
  "Estimate unavailable: {reason}": "Szacunek niedostępny: {reason}",
  "The estimate is not available right now — you can still render.": "Szacunek jest chwilowo niedostępny — nadal możesz uruchomić render.",

  // budget refusal / render failure
  "Not enough AI budget for a Cinematic render": "Za mało budżetu AI na render filmowy",
  "The daily AI budget would be exceeded.": "Przekroczony zostałby dzienny limit budżetu AI.",
  "The AI budget of this campaign would be exceeded.": "Przekroczony zostałby limit budżetu AI tej kampanii.",
  "The daily or per-campaign AI cap would be exceeded.": "Przekroczony zostałby dzienny limit AI lub limit kampanii.",
  "Choose Preview, or raise the cap on the <cost>cost meter</cost> (admin only).": "Wybierz podgląd albo zwiększ limit w <cost>liczniku kosztów</cost> (tylko administrator).",
  "Render refused by the AI budget": "Render odrzucony przez limit budżetu AI",
  "Render failed": "Render nie powiódł się",

  // spot card
  "Cinematic · AI motion {ai}/{total} shots": "Filmowy · ruch AI: {ai}/{total} ujęć",
  "Motion model: {model} · licence {license}": "Model ruchu: {model} · licencja {license}",
  "self-hosted on serverless GPU in your Azure environment": "uruchomiony na bezserwerowym GPU w Twoim środowisku Azure",
  "local motion worker": "lokalny serwer generowania ruchu",
  "offline motion simulator": "symulator ruchu offline",
  "New clips: {fresh} · reused from cache: {cached}": "Nowe klipy: {fresh} · użyto z pamięci podręcznej: {cached}",
  "GPU time: {n} s · {cost}": "Czas GPU: {n}\u00A0s · {cost}",
  "incl. {cost} for the GPU cold start": "w tym {cost} za uruchomienie GPU z uśpienia",
  "no GPU time used": "bez zużycia czasu GPU",
  "Fell back to camera moves on the keyframe: {list}": "Zamiast AI zastosowano ruch kamery na klatce kluczowej: {list}",

  // provenance: the generative_video assertion of a cinematic spot
  "{n} hashed (keyframes, AI clips, voice-over)": "skróty: {n} (klatki kluczowe, klipy AI, lektor)",
  "Generative video": "Wideo generatywne",
  "{model} · licence {license} · {shots}/{total} shots with AI motion": "{model} · licencja {license} · {shots}/{total} ujęć z\u00A0ruchem AI",

  // storyboard motion prompt
  "Motion · shot {n}": "Ruch · ujęcie {n}",
  "motion prompt edited": "opis ruchu zmieniony",
  "e.g. She lifts the mug and sips; slow push-in; steam drifts up.": "np. Podnosi kubek i upija łyk; powolny najazd kamery; unosi się para.",
  "The keyframe is the opening frame. Describe what moves after it: the subject, the camera, steam or light.":
    "Klatka kluczowa jest pierwszą klatką ujęcia. Opisz, co porusza się dalej: postać lub produkt, kamerę, parę albo światło.",
  "Model prompt (EN):": "Prompt dla modelu (EN):",
  "{count}/{max} characters": "{count}/{max} znaków",
  "Save motion": "Zapisz ruch",
  "Motion prompt saved": "Zapisano opis ruchu",
  "The keyframe stays; the clip is generated again on the next Cinematic render.": "Klatka kluczowa pozostaje bez zmian; klip zostanie wygenerowany ponownie przy następnym renderze filmowym.",
};

const p = (one: string, few: string, many: string, other: string): PluralForms => ({ one, few, many, other });

export const motionPlurals: Record<string, PluralForms> = {
  "{n} jobs in the GPU queue": p("{n} zadanie w kolejce GPU", "{n} zadania w kolejce GPU", "{n} zadań w kolejce GPU", "{n} zadania w kolejce GPU"),
  "{n} fallbacks": p("{n} ujęcie zastępcze", "{n} ujęcia zastępcze", "{n} ujęć zastępczych", "{n} ujęcia zastępczego"),
};

export const motionEnums: Record<string, EnumTable> = {
  // the cost meter's "motion" kind: GPU seconds of the generative video model
  costKind: { motion: "wideo AI" },
  // why a shot fell back to camera moves on its keyframe: the backend's reason codes (the server also sends a localized `reason_text`, which wins; an unknown code is shown as received)
  motionFallback: {
    timeout: "przekroczono czas",
    failed: "generowanie nie powiodło się",
    unavailable: "GPU niedostępne",
    oom: "brak pamięci GPU",
    bad_request: "nieprawidłowe żądanie",
    bad_clip: "nieczytelny klip",
    safety: "zablokowane przez Content Safety",
    budget: "limit budżetu",
  },
  // the clips the generative model produces are library assets tagged "motion-clip"
  assetTag: { "motion-clip": "klip ruchu AI" },
  // audit trail: a cinematic render recorded its AI motion
  auditAction: { "spot.motion_generated": "Wygenerowano ruch AI dla spotu" },
};
