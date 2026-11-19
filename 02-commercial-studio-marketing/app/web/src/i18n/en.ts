/**
 * English: the source language. Message texts are their own keys (t("Save") → "Save"), so this file only holds the ID-keyed tables whose English
 * wording the UI owns (statuses, roles, gate names, …). Raw API values keep their exact historical English rendering
 * (e.g. `zoom_in`, `eu_health_claims`); `pl.ts` must define the same ids — enforced by i18n.test.ts.
 *
 * Tables keyed by ids the API owns (feature names/epics by feature id, ROI model labels by model key) have no English table: the API's English text is used.
 */
import type { EnumTable } from "./core";

const same = (...ids: string[]): EnumTable => Object.fromEntries(ids.map((i) => [i, i]));
const humanized = (...ids: string[]): EnumTable => Object.fromEntries(ids.map((i) => [i, i.replace(/_/g, " ")]));

export const en = {
  enums: {
    navGroup: same("Studio", "Brand Brain", "Review", "Performance", "Operate"),
    role: { admin: "Admin", brand_manager: "Brand Manager", creative_director: "Creative Director", creative: "Creative", legal: "Legal / Compliance", agency_guest: "Agency (guest)", system: "System" },
    roleChip: humanized("admin", "brand_manager", "creative_director", "creative", "legal", "agency_guest", "system"),
    roleId: same("admin", "brand_manager", "creative_director", "creative", "legal", "agency_guest", "system"),
    versionState: same("active"),
    variantStatus: same("active", "paused"),
    status: humanized(
      "approved", "pass", "passed", "succeeded", "implemented", "active", "ok", "ready", "verified", "licensed", "done", "valid",
      "warn", "warning", "pending", "in_review", "running", "queued", "draft", "changes_requested", "expiring", "needs_substantiation", "planned", "paused",
      "block", "blocked", "failed", "rejected", "expired", "prohibited", "invalid", "tampered", "unlicensed", "error",
      "completed", "published", "archived", "revoked", "cancelled", "closed", "final", "in_progress", "analyzed", "briefing",
    ),
    verdict: same("block", "warn", "pass"),
    severity: same("block", "warn", "info", "waived"),
    guardianCheck: {
      brand_voice: "Brand voice",
      visual_identity: "Visual identity",
      claims: "Claims",
      regulated: "Regulated rules",
      rights: "Rights & consent",
      content_safety: "Content Safety",
      disclosure: "AI disclosure",
      accessibility: "Accessibility",
    },
    fixOp: same("append_text", "enable_captions", "llm_rewrite", "remove_stock", "remove_text", "replace_text", "resize_logo", "set_disclosure", "snap_colors", "swap_music", "swap_talent"),
    sla: humanized("on_track", "due_soon", "overdue", "closed"),
    gate: { brief: "Brief", concept: "Concept (strategy)", script: "Script", storyboard: "Storyboard", final: "Final spot" },
    pipelineState: same("approved", "blocked", "pending", "draft", "empty"),
    artifactKind: same("brief", "strategy", "script", "copy", "storyboard", "spot", "voice", "localization", "scorecard"),
    lineage: same("master", "format", "cutdown", "localized"),
    rightsKind: same("music", "talent", "stock", "font", "other"),
    category: same("*", "alcohol", "beverage", "finance", "food", "pharma"),
    rulePack: same("alcohol", "eu_health_claims", "finance", "food_beverage", "pharma"),
    territory: same("*", "WW", "EU", "US", "DE", "FR", "PL", "ES", "IT", "GB", "NL", "UK", "PT", "CA", "MX", "EEA"),
    channel: same("youtube", "meta", "tiktok", "ctv", "linkedin", "display", "email", "ooh", "web"),
    platform: same("google", "meta", "simulated", "tiktok", "youtube", "linkedin"),
    tone: same("warm", "playful", "premium", "minimal"),
    copyKind: humanized("headline", "caption", "email_subject", "email_body"),
    providerKind: same("compositor", "keyframes+motion compositor", "generative video (stub)"),
    // why a shot played its keyframe with camera moves: the backend's codes (spotlight/motion/models.py FALLBACK_REASONS), then the codes of an earlier revision (kept as aliases: older artifacts carry them)
    motionFallback: {
      oom: "out of GPU memory",
      timeout: "timed out",
      safety: "blocked by Content Safety",
      budget: "budget limit",
      worker_unavailable: "GPU unavailable",
      bad_request: "invalid request",
      internal: "internal generation error",
      disabled: "AI motion turned off on the server",
      unavailable: "GPU unavailable",
      failed: "generation failed",
      bad_clip: "unreadable clip",
    },
    // the motion-quality gate's verdict on a clip (render.motion.shots[i].motion.level); `unknown` has no label: nothing is shown for a clip that was not measured
    motionLevel: { rich: "Rich motion", subtle: "Subtle motion", low: "Low motion" },
    provCheck: same("asset_hash", "manifest_hash", "signature", "audit_anchor", "ingredients"),
    jurisdiction: { EU: "European Union", UK: "United Kingdom", US: "United States" },
    roiScenario: { conservative: "Conservative", base: "Base", upside: "Upside" },
    beatRole: same("hook", "product", "proof", "brand", "cta"),
    movement: same("zoom_in", "zoom_out", "pan_left", "pan_right", "parallax", "static"),
    styleKey: humanized("look", "lighting", "lens", "product_description", "character_description", "palette_notes"),
    briefField: humanized(
      "objective", "audience", "channels", "markets", "product", "kpis", "budget", "timeline", "tone", "key_message", "cta", "duration_targets", "mandatories", "music_reference", "talent",
    ),
    scorePart: { hook: "Hook (first 3 s)", brand: "Brand presence", clarity: "Clarity", cta: "Call to action", accessibility: "Accessibility", compliance: "Compliance" },
    musicMood: same("calm", "uplifting", "warm"),
    assetKind: same("image", "video", "audio", "subtitle", "document", "archive"),
    groupBy: same("platform", "variant_id", "date", "hook", "cta", "visual", "source"),
    variantDim: same("hook", "cta", "visual"),
    variantOption: same("Human moment first", "Product first", "Question hook", "Sensory close-up", "Find it near you", "Try it today", "Learn more", "Warm kitchen", "Macro pour", "Street at dawn"),
    costKind: same("llm", "image", "tts", "embedding", "safety", "render", "motion"),
    costFeature: same(
      "experiments", "scorecard", "guardian", "brief", "claims", "brand", "rights", "library", "provenance", "performance", "planner", "approvals",
      "strategy", "script", "storyboard", "audio", "spot", "formats", "localization", "copy",
    ),
    webhookFormat: same("teams", "slack", "generic"),
    perfSource: same("csv", "experiment-sim", "seed-history", "simulated"),
    learningSource: same("performance", "manual", "seed"),
    opsDependency: same("repository", "blob_storage", "openai_chat", "content_safety", "speech", "ffmpeg", "embeddings"),
    opsMode: same("azure", "offline"),
    backend: same("memory", "localdir", "stub", "cosmos", "azure", "compositor", "blob", "azure-blob", "azure-openai", "azure-content-safety", "azure-speech"),
    auditAction: same(
      "admin.reseed", "approval.approve", "approval.approved", "approval.commented", "approval.refused_guardian", "approval.reject", "approval.rejected", "approval.request_changes", "approval.requested",
      "audio.music_selected", "audio.voice_generated", "brand.document_deleted", "brand.document_ingested", "brand.document_quarantined", "brand.kit_updated", "brand.version_activated",
      "brief.analyzed", "brief.finalized", "budget.campaign_cap_changed", "budget.daily_cap_changed", "budget.premium_approved", "budget.premium_revoked",
      "campaign.created", "campaign.deleted", "campaign.exported", "campaign.updated", "claims.created", "claims.deleted", "claims.updated",
      "experiment.created", "experiment.simulated", "formats.generated", "formats.version_approved", "guardian.auto_revised", "guardian.run", "guardian.waived",
      "library.asset_deleted", "library.asset_uploaded", "library.asset_versioned", "library.rights_linked", "localization.generated",
      "performance.connector_synced", "performance.csv_ingested", "performance.insights_generated", "premium.approve", "provenance.manifest_created",
      "rights.created", "rights.revoked", "rights.updated", "script.edited", "script.generated", "spot.motion_generated", "spot.rendered",
      "storyboard.frames_generated", "storyboard.shot_edited", "storyboard.shots_generated", "strategy.generated", "strategy.territory_selected", "webhook.created",
    ),
  },
} satisfies { enums: Record<string, EnumTable> };

export type EnumGroup = keyof typeof en.enums | "feature" | "featureSummary" | "epic" | `roi${string}` | "jobKind" | "jobStep";
