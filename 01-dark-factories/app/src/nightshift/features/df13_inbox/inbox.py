"""Human-on-the-loop approval inbox (DF-13): options, impact, SLA timers, auto-escalation, Teams Adaptive Card notifier."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

_List = list  # the Inbox class has a method named list()

log = logging.getLogger("nightshift.inbox")
ROLE_CHAIN = ["engineer", "plant_manager", "admin"]
ALLOWED_WEBHOOK_SUFFIXES = (".webhook.office.com", ".logic.azure.com", ".powerplatform.com", ".office.com")


@dataclass
class InboxItem:
    id: str
    plan_id: str
    plant: str
    title: str
    decision_class: str
    explanation: str
    options: list[dict[str, str]]
    impact: dict[str, Any]
    risk_score: float
    reasons: list[str]
    created_t: int
    sla_min: int
    sla_deadline_t: int
    expires_t: int
    advisory: bool = False  # L1: recommendation for a human to carry out
    level: int = 0
    assigned_role: str = "engineer"
    status: str = "pending"  # pending | approved | rejected | expired | deferred | applied
    history: list[dict[str, Any]] = field(default_factory=list)
    resolved_by: str = ""
    resolved_t: int | None = None
    resolution: str = ""
    comment: str = ""
    plan: dict[str, Any] = field(default_factory=dict)
    whatif: dict[str, Any] | None = None

    def public(self, now_t: int | None = None) -> dict[str, Any]:
        d = asdict(self)
        if now_t is not None:
            d["sla_remaining_min"] = self.sla_deadline_t - now_t
            d["breached"] = now_t > self.sla_deadline_t
        return d


def adaptive_card(item: InboxItem, base_url: str = "") -> dict[str, Any]:
    """Teams-compatible Adaptive Card (v1.4) for an approval request."""
    facts = [
        {"title": "Plant", "value": item.plant},
        {"title": "Class", "value": item.decision_class},
        {"title": "Risk score", "value": f"{item.risk_score:.2f}"},
        {"title": "Assigned", "value": item.assigned_role.replace("_", " ")},
        {"title": "SLA", "value": f"{item.sla_min} min (sim)"},
    ]
    for k, v in list(item.impact.items())[:4]:
        facts.append({"title": k.replace("_", " "), "value": str(round(v, 1) if isinstance(v, float) else v)})
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "size": "Medium",
                "weight": "Bolder",
                "wrap": True,
                "text": f"Nightshift approval: {item.title}",
            },
            {"type": "TextBlock", "wrap": True, "isSubtle": True, "text": item.explanation[:600]},
            {"type": "FactSet", "facts": facts},
        ],
        "actions": [
            {"type": "Action.OpenUrl", "title": "Review in Control Tower", "url": f"{base_url}/inbox?item={item.id}"}
        ],
    }


class TeamsNotifier:
    def __init__(self, webhook_url: str = "", base_url: str = "", http: Any = None) -> None:
        self.url, self.base_url, self.http = webhook_url, base_url, http
        self.sent = self.failed = 0

    @property
    def configured(self) -> bool:
        return bool(self.url)

    def valid_url(self) -> bool:
        u = urlparse(self.url)
        return u.scheme == "https" and bool(u.hostname) and (u.hostname or "").endswith(ALLOWED_WEBHOOK_SUFFIXES)

    async def notify(self, item: InboxItem) -> dict[str, Any]:
        card = adaptive_card(item, self.base_url)
        payload = {
            "type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}],
        }
        if not self.configured:
            return {"sent": False, "reason": "TEAMS_WEBHOOK_URL not configured", "card": card}
        if not self.valid_url():
            return {"sent": False, "reason": "webhook host not on the allow-list", "card": card}
        try:
            import httpx

            client = self.http or httpx.AsyncClient(timeout=5.0)
            r = await client.post(self.url, json=payload)
            ok = r.status_code < 300
            self.sent += 1 if ok else 0
            self.failed += 0 if ok else 1
            return {"sent": ok, "status": r.status_code}
        except Exception as exc:
            self.failed += 1
            log.warning("teams notify failed: %s", type(exc).__name__)
            return {"sent": False, "reason": type(exc).__name__}


class Inbox:
    def __init__(self, plant_id: str) -> None:
        self.plant_id = plant_id
        self.items: dict[str, InboxItem] = {}
        self._seq = 0
        self.escalations = 0
        self.expired = 0
        self.decision_minutes: list[int] = []

    def add(
        self,
        plan: Any,
        decision: Any,
        now_t: int,
        explanation: str,
        *,
        advisory: bool = False,
        validity_min: int | None = None,
    ) -> InboxItem:
        self._seq += 1
        impact: dict[str, Any] = {}
        for p in plan.proposals:
            for k, v in p.impact.items():
                impact[k] = round(impact.get(k, 0.0) + float(v), 2) if isinstance(v, int | float) else v
        expires = min((p.expires_t for p in plan.proposals), default=now_t + 240)
        if validity_min is not None:  # live mode: the proposal clock is simulated time, the inbox clock is not
            expires = now_t + validity_min
        options = [
            {"id": "approve", "label": "Mark as done" if advisory else "Approve & execute"},
            {"id": "reject", "label": "Reject"},
            {"id": "defer", "label": "Defer 30 min"},
        ]
        item = InboxItem(
            id=f"INB-{self._seq:04d}",
            plan_id=plan.id,
            plant=self.plant_id,
            title=plan.proposals[0].title if plan.proposals else plan.id,
            decision_class=plan.decision_class,
            explanation=explanation,
            options=options,
            impact=impact,
            risk_score=decision.risk_score,
            reasons=list(decision.reasons),
            created_t=now_t,
            sla_min=decision.sla_min,
            sla_deadline_t=now_t + decision.sla_min,
            expires_t=expires,
            advisory=advisory,
            plan=plan.public(),
            whatif=plan.whatif,
        )
        item.history.append({"t": now_t, "event": "created", "role": item.assigned_role})
        self.items[item.id] = item
        return item

    def pending(self) -> list[InboxItem]:
        return [i for i in self.items.values() if i.status == "pending"]

    def list(self, status: str | None = None, limit: int = 200) -> list[InboxItem]:
        rows = [i for i in self.items.values() if status in (None, "all") or i.status == status]
        return sorted(rows, key=lambda i: (i.status != "pending", -i.created_t))[:limit]

    def get(self, item_id: str) -> InboxItem | None:
        return self.items.get(item_id)

    def resolve(self, item_id: str, option: str, actor: str, now_t: int, comment: str = "") -> InboxItem:
        item = self.items.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if item.status not in ("pending", "deferred"):
            raise ValueError(f"item already {item.status}")
        if option not in {o["id"] for o in item.options}:
            raise ValueError(f"unknown option {option!r}")
        if option == "defer":
            item.status = "pending"
            item.sla_deadline_t = now_t + 30
            item.history.append({"t": now_t, "event": "deferred", "by": actor})
            return item
        item.status = {"approve": "applied" if item.advisory else "approved", "reject": "rejected"}[option]
        item.resolved_by, item.resolved_t, item.resolution, item.comment = actor, now_t, option, comment
        item.history.append({"t": now_t, "event": item.status, "by": actor})
        self.decision_minutes.append(now_t - item.created_t)
        return item

    def tick(self, now_t: int) -> _List[tuple[str, InboxItem]]:
        """Advance SLA timers: escalate along the role chain, then expire fail-safe (nothing is executed)."""
        events: _List[tuple[str, InboxItem]] = []
        for item in self.pending():
            if now_t >= item.expires_t:
                item.status, item.resolution, item.resolved_t = "expired", "proposal_expired", now_t
                item.history.append({"t": now_t, "event": "expired", "reason": "proposal validity elapsed"})
                self.expired += 1
                events.append(("expired", item))
            elif now_t > item.sla_deadline_t:
                if item.level + 1 < len(ROLE_CHAIN):
                    item.level += 1
                    item.assigned_role = ROLE_CHAIN[item.level]
                    item.sla_deadline_t = now_t + max(5, item.sla_min // 2)
                    item.history.append({"t": now_t, "event": "escalated", "role": item.assigned_role})
                    self.escalations += 1
                    events.append(("escalated", item))
                else:
                    item.status, item.resolution, item.resolved_t = "expired", "sla_exhausted", now_t
                    item.history.append(
                        {"t": now_t, "event": "expired", "reason": "SLA exhausted at final escalation level"}
                    )
                    self.expired += 1
                    events.append(("expired", item))
        return events

    def stats(self, now_t: int) -> dict[str, Any]:
        pend = self.pending()
        return {
            "pending": len(pend),
            "breached": sum(1 for i in pend if now_t > i.sla_deadline_t),
            "escalations": self.escalations,
            "expired": self.expired,
            "total": len(self.items),
            "mean_decision_min": round(sum(self.decision_minutes) / len(self.decision_minutes), 1)
            if self.decision_minutes
            else None,
        }
