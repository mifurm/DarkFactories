"""Voice-of-customer analytics (CC-12): embedding clustering (k-means on L2-normalised vectors, seeded), cluster labelling, sentiment trends,
contact-driver Pareto (volume and cost), repeat-contact and churn-risk signals, and robust anomaly detection for emerging issues with carrier
attribution. Pure numpy; embeddings are supplied by the caller (Azure OpenAI embeddings in azure mode, hashed embeddings offline)."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

import numpy as np

STOP = set(
    ["a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "he", "her", "his", "i", "if", "in", "into", "is", "it", "its", "of", "on", "or", "our", "she", "so", "than", "that", "the", "their", "them", "then", "there", "these", "they", "this", "to", "was", "we", "were", "what", "when", "where", "which", "who", "will", "with", "you", "your", "customer", "customers", "asks", "ask", "asked", "wants", "want", "wanted", "reports", "report", "about", "after", "before", "because", "not", "no", "yes", "also", "still", "can", "could", "would", "should", "need", "needs", "needed", "has", "had", "been", "being", "new", "one", "two"]
)
HUMAN_COST_PER_MIN_USD = 0.96  # loaded agent cost / productive minutes (derived from business-case assumptions, see metrics module)


# ------------------------------------------------------------------------------------------------------ clustering
def _normalise(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    return x / np.where(n == 0, 1, n)


def kmeans(x: np.ndarray, k: int, *, seed: int = 7, iters: int = 60) -> tuple[np.ndarray, np.ndarray, float]:
    """Spherical k-means with k-means++ seeding. Returns (labels, centroids, inertia)."""
    rng = np.random.default_rng(seed)
    x = _normalise(x.astype(np.float64))
    n = len(x)
    centres = [x[rng.integers(n)]]
    for _ in range(1, k):
        d2 = np.min(1 - x @ np.array(centres).T, axis=1) ** 2
        total = d2.sum()
        centres.append(x[rng.choice(n, p=d2 / total)] if total > 0 else x[rng.integers(n)])
    c = np.array(centres)
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        new = np.argmax(x @ c.T, axis=1)
        if _ and np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            members = x[labels == j]
            if len(members):
                c[j] = members.mean(axis=0)
        c = _normalise(c)
    inertia = float(np.sum(1 - np.max(x @ c.T, axis=1)))
    return labels, c, inertia


def silhouette(x: np.ndarray, labels: np.ndarray, sample: int = 500, seed: int = 3) -> float:
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(x), size=min(sample, len(x)), replace=False)
    xs, ls = _normalise(x[idx].astype(np.float64)), labels[idx]
    dist = 1 - xs @ xs.T
    scores = []
    for i in range(len(idx)):
        same = (ls == ls[i]) & (np.arange(len(idx)) != i)
        if not same.any():
            continue
        a = dist[i][same].mean()
        b = min((dist[i][ls == other].mean() for other in set(ls.tolist()) if other != ls[i]), default=a)
        scores.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(scores)) if scores else 0.0


def choose_k(x: np.ndarray, candidates: tuple[int, ...] = (12, 14, 16, 18, 20)) -> tuple[int, dict[int, float]]:
    scores = {}
    for k in candidates:
        if k < len(x):
            labels, _, _ = kmeans(x, k)
            scores[k] = round(silhouette(x, labels), 4)
    best = max(scores, key=lambda q: scores[q]) if scores else 2
    return best, scores


def purity(labels: np.ndarray | list[int], truth: list[str]) -> float:
    groups: dict[int, Counter] = defaultdict(Counter)
    for lab, t in zip(labels, truth, strict=True):
        groups[int(lab)][t] += 1
    return sum(max(c.values()) for c in groups.values()) / max(len(truth), 1)


def top_terms(texts_by_cluster: dict[int, list[str]], n: int = 4) -> dict[int, list[str]]:
    """c-TF-IDF: terms that characterise a cluster relative to the others."""
    tf: dict[int, Counter] = {}
    for c, texts in texts_by_cluster.items():
        cnt: Counter = Counter()
        for t in texts:
            cnt.update(w for w in re.findall(r"[a-z]{3,}", t.lower()) if w not in STOP)
        tf[c] = cnt
    df: Counter = Counter()
    for cnt in tf.values():
        df.update(cnt.keys())
    out = {}
    for c, cnt in tf.items():
        total = sum(cnt.values()) or 1
        scored = {w: (v / total) * math.log(1 + len(tf) / df[w]) for w, v in cnt.items()}
        out[c] = [w for w, _ in sorted(scored.items(), key=lambda kv: -kv[1])[:n]]
    return out


# ------------------------------------------------------------------------------------------------------ signals
def repeat_flags(records: list[dict[str, Any]]) -> dict[str, bool]:
    """A contact is a repeat when the same customer contacted about the same intent within the previous 7 days."""
    last: dict[tuple[str, str], float] = {}
    flags: dict[str, bool] = {}
    for r in sorted(records, key=lambda r: r["ts"]):
        key = (r["customer_id"], r["intent"])
        flags[r["id"]] = key in last and r["ts"] - last[key] <= 7 * 86400
        last[key] = r["ts"]
    return flags


def churn_score(r: dict[str, Any], repeat: bool) -> float:
    """Transparent heuristic (documented in the UI): unhappy ending, unresolved, repeat, escalated, angry start, abandoned."""
    return round(
        0.30 * (r["sentiment_end"] <= -0.3) + 0.25 * (not r["resolved"]) + 0.20 * repeat + 0.10 * r["escalated"] + 0.10 * (r["sentiment_start"] <= -0.5) + 0.05 * r["abandoned"],
        3,
    )


def handled_minutes(r: dict[str, Any]) -> float:
    return (r["aht_s"] + r["acw_s"]) / 60.0 if r["handled_by"] == "human" else 0.0


def record_cost(r: dict[str, Any], cost_per_min: float = HUMAN_COST_PER_MIN_USD) -> float:
    return handled_minutes(r) * cost_per_min + r.get("ai_cost_usd", 0.0)


# ------------------------------------------------------------------------------------------------------ anomalies
def detect_anomalies(
    records: list[dict[str, Any]], labels: list[int] | np.ndarray, names: dict[int, str], as_of_ts: float, *,
    recent_days: int = 7, baseline_days: int = 60, z_min: float = 4.0, ratio_min: float = 2.0, min_recent: int = 10, centroids: np.ndarray | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    """Robust (median/MAD) volume anomaly detection per cluster; the recent window is compared with the preceding baseline window."""
    by_cluster: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r, lab in zip(records, labels, strict=True):
        by_cluster[int(lab)].append(r)
    alerts = []
    for c, recs in by_cluster.items():
        daily = np.zeros(recent_days + baseline_days)
        for r in recs:
            d = int((as_of_ts - r["ts"]) // 86400)
            if 0 <= d < len(daily):
                daily[d] += 1
        recent, base = daily[:recent_days], daily[recent_days:]
        m = float(np.median(base))
        mad = float(np.median(np.abs(base - m)))
        sigma = max(1.4826 * mad, math.sqrt(max(m, 0.5)))
        mean_recent = float(recent.mean())
        z = (mean_recent - m) / (sigma / math.sqrt(recent_days))
        ratio = mean_recent / max(m, 0.25)
        total_recent = int(recent.sum())
        if z < z_min or ratio < ratio_min or total_recent < min_recent:
            continue
        window = [r for r in recs if as_of_ts - r["ts"] < recent_days * 86400]
        before = [r for r in recs if recent_days * 86400 <= as_of_ts - r["ts"] < (recent_days + baseline_days) * 86400]
        share_r, share_b = Counter(r["carrier"] for r in window if r.get("carrier")), Counter(r["carrier"] for r in before if r.get("carrier"))
        n_r, n_b = sum(share_r.values()) or 1, sum(share_b.values()) or 1
        carriers = sorted(({"name": k, "share_recent": round(v / n_r, 3), "share_baseline": round(share_b.get(k, 0) / n_b, 3), "lift": round(v / n_r - share_b.get(k, 0) / n_b, 3), "count_recent": v} for k, v in share_r.items()), key=lambda x: -x["lift"])
        attributed = carriers[0] if carriers and carriers[0]["lift"] >= 0.25 and carriers[0]["count_recent"] >= 5 else None
        evidence_pool = [r for r in window if (not attributed or r.get("carrier") == attributed["name"])]
        evidence = sorted(evidence_pool, key=lambda r: r["sentiment_start"])[:8]
        daily_z = [(float(daily[i]) - m) / sigma for i in range(recent_days)]
        hot = [i for i, dz in enumerate(daily_z) if dz >= 3]  # index 0 = most recent day
        first_seen = datetime.fromtimestamp(as_of_ts - (max(hot) + 1) * 86400, UTC).strftime("%Y-%m-%d") if hot else None
        alerts.append(
            {
                "id": f"voc-spike-{c}", "type": "volume_spike", "cluster": c, "label": names.get(c, f"cluster {c}"),
                "severity": "critical" if z >= 8 or ratio >= 4 else "warning", "recent_per_day": round(mean_recent, 2), "baseline_per_day": round(m, 2),
                "ratio": round(ratio, 1), "z": round(z, 1), "window_days": recent_days, "recent_total": total_recent, "carrier": attributed, "carriers": carriers[:3],
                "first_seen": first_seen, "evidence": [e["id"] for e in evidence], "evidence_summaries": [e["summary"] for e in evidence[:3]], "evidence_summaries_pl": [e.get("summary_pl") or e["summary"] for e in evidence[:3]],
                "markets": [m_ for m_, _ in Counter(r["market"] for r in window).most_common(4)],
                "message": (f"'{names.get(c, c)}' is running at {mean_recent:.1f}/day vs {m:.1f}/day baseline ({ratio:.1f}x)" + (f" - {attributed['name']} accounts for {round(100 * attributed['share_recent'])}% of the recent contacts (baseline {round(100 * attributed['share_baseline'])}%)." if attributed else ".")),
            }
        )  # fmt: skip
    return _merge_related(sorted(alerts, key=lambda a: -a["z"]), centroids)


def _merge_related(alerts: list[dict[str, Any]], centroids: np.ndarray | None = None, min_cosine: float = 0.45) -> list[dict[str, Any]]:
    """Over-segmented sibling clusters that spike together are one operational issue: alerts are grouped when they point at the same carrier or
    their cluster centroids are similar, and reported once with the combined volume."""

    def related(a: dict[str, Any], b: dict[str, Any]) -> bool:
        if a["carrier"] and b["carrier"] and a["carrier"]["name"] == b["carrier"]["name"]:
            return True
        return centroids is not None and float(centroids[a["cluster"]] @ centroids[b["cluster"]]) >= min_cosine

    groups: list[list[dict[str, Any]]] = []
    for a in alerts:
        for g in groups:
            if any(related(a, b) for b in g):
                g.append(a)
                break
        else:
            groups.append([a])
    merged: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        head = max(group, key=lambda a: a["recent_total"])
        carrier = max((a["carrier"] for a in group if a["carrier"]), key=lambda c: c["lift"], default=None)
        recent, base = sum(a["recent_per_day"] for a in group), sum(a["baseline_per_day"] for a in group)
        evidence = list(dict.fromkeys(e for a in group for e in a["evidence"]))[:8]
        msg = f"'{head['label']}' (+{len(group) - 1} related topic clusters) is running at {recent:.1f}/day vs {base:.1f}/day baseline ({recent / max(base, 0.25):.1f}x)"
        if carrier:
            msg += f" - {carrier['name']} accounts for {round(100 * carrier['share_recent'])}% of the recent contacts (baseline {round(100 * carrier['share_baseline'])}%)."
        merged.append(
            {
                **head, "id": f"voc-spike-{head['cluster']}", "clusters": sorted(a["cluster"] for a in group), "recent_per_day": round(recent, 2), "baseline_per_day": round(base, 2),
                "ratio": round(recent / max(base, 0.25), 1), "z": max(a["z"] for a in group), "recent_total": sum(a["recent_total"] for a in group), "evidence": evidence, "carrier": carrier,
                "severity": "critical" if any(a["severity"] == "critical" for a in group) else "warning", "message": msg,
            }
        )  # fmt: skip
    return sorted(merged, key=lambda a: -a["z"])


# ------------------------------------------------------------------------------------------------------ aggregate builder
def build_voc(records: list[dict[str, Any]], vectors: np.ndarray, *, k: int | None = None, cost_per_min: float = HUMAN_COST_PER_MIN_USD, as_of_ts: float | None = None) -> dict[str, Any]:
    """Everything the VoC dashboards need, computed once and stored (dashboards read the stored aggregates)."""
    x = _normalise(np.asarray(vectors, dtype=np.float64))
    if k is None:
        k, k_scores = choose_k(x)
    else:
        k_scores = {}
    labels, centroids, _ = kmeans(x, k)
    as_of = as_of_ts if as_of_ts is not None else max(r["ts"] for r in records) // 86400 * 86400 + 86400
    repeats = repeat_flags(records)
    texts: dict[int, list[str]] = defaultdict(list)
    for r, lab in zip(records, labels, strict=True):
        texts[int(lab)].append(r["summary"])
    terms = top_terms(texts)
    names = {c: " · ".join(t[:3]).title() or f"Cluster {c}" for c, t in terms.items()}
    clusters = []
    for c in sorted(texts):
        recs = [r for r, lab in zip(records, labels, strict=True) if int(lab) == c]
        n = len(recs)
        churn = [churn_score(r, repeats[r["id"]]) for r in recs]
        truth = Counter(r["topic"] for r in recs).most_common(1)[0]
        weekly: dict[str, int] = defaultdict(int)
        for r in recs:
            weekly[r["week"]] += 1
        cost = sum(record_cost(r, cost_per_min) for r in recs)
        clusters.append(
            {
                "id": c, "label": names[c], "terms": terms[c], "volume": n, "share": round(n / len(records), 4),
                "sentiment_start": round(sum(r["sentiment_start"] for r in recs) / n, 3), "sentiment_end": round(sum(r["sentiment_end"] for r in recs) / n, 3),
                "csat_pred": round(sum(r["csat_pred"] for r in recs) / n, 2), "resolved_pct": round(100 * sum(r["resolved"] for r in recs) / n, 1),
                "escalated_pct": round(100 * sum(r["escalated"] for r in recs) / n, 1), "containment_pct": round(100 * sum(r["contained"] for r in recs) / n, 1),
                "repeat_rate": round(sum(repeats[r["id"]] for r in recs) / n, 3), "churn_risk_avg": round(sum(churn) / n, 3), "churn_high_pct": round(100 * sum(1 for s in churn if s >= 0.5) / n, 1),
                "human_minutes": round(sum(handled_minutes(r) for r in recs), 1), "cost_usd": round(cost, 2), "cost_per_contact_usd": round(cost / n, 2),
                "dominant_driver": truth[0], "driver_purity": round(truth[1] / n, 3), "weekly": dict(sorted(weekly.items())),
                "examples": [{"id": r["id"], "summary": r["summary"], "text": r["text"], "language": r["language"], "sentiment": r["sentiment_start"], **({"summary_pl": r["summary_pl"]} if r.get("summary_pl") else {})} for r in sorted(recs, key=lambda r: r["sentiment_start"])[:4]],
                "carriers": dict(Counter(r["carrier"] for r in recs if r.get("carrier")).most_common(3)),
            }
        )  # fmt: skip
    by_vol = sorted(clusters, key=lambda c: -c["volume"])
    by_cost = sorted(clusters, key=lambda c: -c["cost_usd"])

    def pareto(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
        total, acc, out = sum(r[key] for r in rows) or 1, 0.0, []
        for r in rows:
            acc += r[key]
            out.append({"id": r["id"], "label": r["label"], key: r[key], "cum_pct": round(100 * acc / total, 1)})
        return out

    weeks = sorted({r["week"] for r in records})
    trend = []
    for w in weeks:
        rs = [r for r in records if r["week"] == w]
        trend.append({"week": w, "n": len(rs), "sentiment": round(sum(r["sentiment_end"] for r in rs) / len(rs), 3), "negative_pct": round(100 * sum(1 for r in rs if r["sentiment_end"] < -0.2) / len(rs), 1), "emotions": dict(Counter(r["emotion"] for r in rs))})
    alerts = detect_anomalies(records, labels, names, as_of, centroids=centroids)
    pur = purity(labels, [r["topic"] for r in records])
    return {
        "records": len(records), "k": k, "k_silhouette": k_scores, "purity": round(pur, 4), "as_of": as_of, "clusters": by_vol, "pareto_volume": pareto(by_vol, "volume"), "pareto_cost": pareto(by_cost, "cost_usd"),
        "trend": trend, "alerts": alerts, "assignments": {r["id"]: int(lab) for r, lab in zip(records, labels, strict=True)}, "cost_per_min_usd": cost_per_min,
        "totals": {"repeat_rate": round(sum(repeats.values()) / len(records), 4), "high_churn_pct": round(100 * sum(1 for r in records if churn_score(r, repeats[r["id"]]) >= 0.5) / len(records), 1)},
    }  # fmt: skip
