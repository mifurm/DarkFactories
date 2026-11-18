"""Mock back-office (CRM / OMS / billing) for the fictional Contoso Home Retail: deterministic synthetic seed + service API.
The tool layer (engine/tools.py) is the ONLY writer in the agent path; policy is enforced there, not here."""

from __future__ import annotations

import random
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from ..core.collections import BACKOFFICE_COLLECTIONS
from ..core.repo import Repository

DAY = 86400.0
MARKETS = {"DE": "de", "UK": "en", "FR": "fr", "ES": "es", "IT": "it", "NL": "nl", "PL": "pl", "PT": "pt"}
CARRIERS = ["NordFreight", "SwiftHaul", "BlueRoute"]
CURRENCY = "EUR"

CATALOG = [
    ("SKU-SOFA-2", "Nordby 2-seater sofa (grey)", "sofa", 379.0, 24),
    ("SKU-SOFA-3", "Fjord 3-seater sofa (sand)", "sofa", 799.0, 24),
    ("SKU-SOFA-SEC", "Malmö corner sectional (anthracite)", "sofa", 1899.0, 24),
    ("SKU-MAT-160", "Luna memory-foam mattress 160x200", "mattress", 899.0, 36),
    ("SKU-MAT-140", "Nube pocket-spring mattress 140x200", "mattress", 549.0, 36),
    ("SKU-WM-8", "Vera washing machine 8 kg", "washing machine", 649.0, 24),
    ("SKU-DW-60", "Clarity dishwasher 60 cm", "dishwasher", 799.0, 24),
    ("SKU-FR-300", "Frost fridge-freezer 300 L", "fridge", 579.0, 24),
    ("SKU-TB-OSLO", "Oslo oak dining table", "table", 420.0, 24),
    ("SKU-CH-LUND", "Lund dining chairs (set of 4)", "chair", 240.0, 24),
    ("SKU-WD-ARDEN", "Arden 3-door wardrobe", "wardrobe", 529.0, 24),
    ("SKU-BED-SKOG", "Skog bed frame 160 cm", "bed", 389.0, 24),
    ("SKU-LAMP-AURA", "Aura floor lamp", "lamp", 79.9, 24),
    ("SKU-DESK-TAG", "Tåg height-adjustable desk", "desk", 349.0, 24),
    ("SKU-ARM-FJ", "Fjella recliner armchair", "armchair", 389.0, 24),
    ("SKU-BL-MIXO", "Mixo Pro blender", "blender", 129.0, 24),
    ("SKU-OV-HEAT", "Heat built-in oven 60 cm", "oven", 699.0, 24),
]
BY_SKU = {c[0]: c for c in CATALOG}

NAMES = {
    "DE": [("Anna", "Becker"), ("Lukas", "Schneider"), ("Mia", "Hoffmann"), ("Jonas", "Wagner"), ("Emma", "Koch")],
    "UK": [("Mark", "Thompson"), ("Olivia", "Hughes"), ("Harry", "Walker"), ("Amelia", "Evans"), ("George", "Turner")],
    "FR": [("Sophie", "Laurent"), ("Lucas", "Moreau"), ("Chloé", "Girard"), ("Hugo", "Lambert"), ("Léa", "Fontaine")],
    "ES": [("Carlos", "Ruiz"), ("Lucía", "Navarro"), ("Pablo", "Herrera"), ("Marta", "Gil"), ("Diego", "Molina")],
    "IT": [("Elena", "Rossi"), ("Marco", "Bianchi"), ("Giulia", "Conti"), ("Luca", "Greco"), ("Sara", "Ferri")],
    "NL": [("Jan", "de Vries"), ("Sanne", "Bakker"), ("Daan", "Visser"), ("Eva", "Smit"), ("Thijs", "Mulder")],
    "PL": [("Marta", "Kowalska"), ("Piotr", "Nowak"), ("Zofia", "Wójcik"), ("Jakub", "Kamiński"), ("Ola", "Lewandowska")],
    "PT": [("Inês", "Carvalho"), ("Tiago", "Ferreira"), ("Beatriz", "Sousa"), ("Miguel", "Costa"), ("Rita", "Almeida")],
}
CITIES = {
    "DE": [("Berlin", "10969", "Lindenstraße"), ("Hamburg", "20095", "Mönckebergstraße"), ("München", "80331", "Sendlinger Straße")],
    "UK": [("London", "E8 3QL", "Elm Road"), ("Manchester", "M1 4BT", "Oxford Road"), ("Leeds", "LS1 4AP", "Park Row")],
    "FR": [("Lyon", "69003", "Rue Garibaldi"), ("Paris", "75011", "Rue Oberkampf"), ("Lille", "59000", "Rue Nationale")],
    "ES": [("Madrid", "28004", "Calle Fuencarral"), ("Barcelona", "08001", "Carrer de Pelai"), ("Valencia", "46001", "Calle Colón")],
    "IT": [("Milano", "20121", "Via Brera"), ("Roma", "00184", "Via Cavour"), ("Torino", "10121", "Via Roma")],
    "NL": [("Amsterdam", "1011", "Nieuwmarkt"), ("Utrecht", "3511", "Oudegracht"), ("Rotterdam", "3011", "Witte de Withstraat")],
    "PL": [("Warszawa", "00-001", "ul. Marszałkowska"), ("Kraków", "30-001", "ul. Floriańska"), ("Gdańsk", "80-001", "ul. Długa")],
    "PT": [("Lisboa", "1100-148", "Rua Augusta"), ("Porto", "4050-123", "Rua de Santa Catarina"), ("Braga", "4700-001", "Avenida da Liberdade")],
}

DEMO_CUSTOMERS = [
    {"id": "CU-1001", "market": "DE", "name": "Anna Becker", "tier": "standard", "phone": "+49 30 5550 4412", "email": "anna.becker@example.com", "city_idx": 0, "note": "Demo persona: damaged sofa (German)"},
    {"id": "CU-1002", "market": "UK", "name": "Mark Thompson", "tier": "standard", "phone": "+44 20 7946 0123", "email": "mark.thompson@example.com", "city_idx": 0, "note": "Demo persona: missed installations, legal threat"},
    {"id": "CU-1003", "market": "FR", "name": "Sophie Laurent", "tier": "vip", "phone": "+33 4 72 55 01 88", "email": "sophie.laurent@example.com", "city_idx": 0, "note": "VIP"},
    {"id": "CU-1004", "market": "ES", "name": "Carlos Ruiz", "tier": "standard", "phone": "+34 91 555 01 24", "email": "carlos.ruiz@example.com", "city_idx": 0, "note": "Damaged mattress above refund cap"},
    {"id": "CU-1005", "market": "IT", "name": "Elena Rossi", "tier": "standard", "phone": "+39 02 5550 1177", "email": "elena.rossi@example.com", "city_idx": 0, "note": "Delayed wardrobe"},
    {"id": "CU-1006", "market": "NL", "name": "Jan de Vries", "tier": "standard", "phone": "+31 20 555 0199", "email": "jan.devries@example.com", "city_idx": 0, "vulnerable": True, "note": "Vulnerable (elderly, prefers phone)"},
    {"id": "CU-1007", "market": "PL", "name": "Marta Kowalska", "tier": "standard", "phone": "+48 22 555 01 66", "email": "marta.kowalska@example.com", "city_idx": 0, "note": "Warranty claim"},
    {"id": "CU-1008", "market": "PT", "name": "Inês Carvalho", "tier": "standard", "phone": "+351 21 555 0130", "email": "ines.carvalho@example.com", "city_idx": 0, "note": "Address change"},
]

# (id, customer, sku list, status, delivered_days_ago | None, carrier, extra)
DEMO_ORDERS = [
    ("CH-100231", "CU-1001", ["SKU-SOFA-2"], "delivered", 2, "NordFreight", {}),
    ("CH-100232", "CU-1001", ["SKU-LAMP-AURA"], "shipped", None, "SwiftHaul", {"eta_days": 1}),
    ("CH-100320", "CU-1001", ["SKU-CH-LUND"], "delivered", 45, "BlueRoute", {}),
    ("CH-100250", "CU-1002", ["SKU-WM-8"], "delivered", 5, "BlueRoute", {"installation": True, "missed_installs": 2}),
    ("CH-100330", "CU-1002", ["SKU-TB-OSLO"], "delivered", 40, "SwiftHaul", {}),
    ("CH-100260", "CU-1003", ["SKU-DW-60"], "delivered", 20, "SwiftHaul", {"installation": True}),
    ("CH-100270", "CU-1004", ["SKU-MAT-160"], "delivered", 3, "NordFreight", {}),
    ("CH-100280", "CU-1005", ["SKU-WD-ARDEN"], "delayed", None, "BlueRoute", {"eta_days": -3}),
    ("CH-100290", "CU-1006", ["SKU-ARM-FJ"], "out_for_delivery", None, "SwiftHaul", {"eta_days": 0}),
    ("CH-100300", "CU-1007", ["SKU-BL-MIXO"], "delivered", 300, "SwiftHaul", {}),
    ("CH-100310", "CU-1008", ["SKU-DESK-TAG"], "processing", None, "BlueRoute", {"eta_days": 6}),
    ("CH-100340", "CU-1004", ["SKU-SOFA-SEC"], "delivered", 4, "NordFreight", {}),
]


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d") if ts else None


def day_start(ts: float) -> float:
    return ts - (ts % DAY)


def _customer(c: dict[str, Any], rng: random.Random, idx: int) -> dict[str, Any]:
    market = c["market"]
    city, postal, street = CITIES[market][c.get("city_idx", idx % 3)]
    first, _, _last = c["name"].partition(" ")
    return {
        "id": c["id"],
        "name": c["name"],
        "first_name": first,
        "email": c["email"],
        "phone": c["phone"],
        "language": MARKETS[market],
        "market": market,
        "tier": c.get("tier", "standard"),
        "vulnerable": bool(c.get("vulnerable")),
        "address": {"street": f"{street} {rng.randint(2, 98)}", "postal_code": postal, "city": city, "country": market},
        "marketing_consent": {"sms": rng.random() < 0.6, "email": rng.random() < 0.7, "voice": rng.random() < 0.25},
        "created_at": 0.0,
        "note": c.get("note", ""),
        "demo": "note" in c,
    }


def generate_seed(anchor: float | None = None, seed: int = 20260317) -> dict[str, list[dict[str, Any]]]:
    """Deterministic synthetic back-office data; all dates are offsets from the anchor day."""
    anchor = day_start(anchor or time.time())
    rng = random.Random(seed)
    customers = [_customer(c, rng, i) for i, c in enumerate(DEMO_CUSTOMERS)]
    n = 1100
    for market, names in NAMES.items():
        for j, (first, last) in enumerate(names):
            if any(c["name"] == f"{first} {last}" for c in customers):
                continue
            n += 1
            email = f"{first}.{last}".lower().replace(" ", "").replace("é", "e").replace("ó", "o").replace("ł", "l").replace("ń", "n").replace("ö", "o").replace("ü", "u").replace("ä", "a").replace("ã", "a")
            customers.append(
                _customer(
                    {"id": f"CU-{n}", "market": market, "name": f"{first} {last}", "tier": "vip" if rng.random() < 0.12 else "standard", "phone": f"+{rng.randint(30, 49)} {rng.randint(20, 99)} 555 {rng.randint(1000, 9999)}", "email": f"{email}@example.com", "city_idx": j % 3},
                    rng,
                    j,
                )
            )
    for c in customers:
        c["created_at"] = anchor - rng.randint(30, 900) * DAY
    cust_by_id = {c["id"]: c for c in customers}

    orders: list[dict[str, Any]] = []
    shipments: list[dict[str, Any]] = []
    appointments: list[dict[str, Any]] = []

    def build_order(oid: str, cid: str, skus: list[str], status: str, delivered_days: int | None, carrier: str, extra: dict[str, Any]) -> None:
        cust = cust_by_id[cid]
        items = []
        for k, sku in enumerate(skus):
            _, name, cat, price, warranty = BY_SKU[sku]
            items.append({"item_id": f"{oid}-L{k + 1}", "sku": sku, "name": name, "category": cat, "qty": 1, "unit_price": price, "warranty_months": warranty})
        total = round(sum(i["unit_price"] * i["qty"] for i in items), 2)
        placed = anchor - ((delivered_days or 0) + rng.randint(4, 9)) * DAY if delivered_days is not None else anchor - rng.randint(2, 6) * DAY
        delivered_at = anchor - delivered_days * DAY + 11 * 3600 if delivered_days is not None else None
        eta = anchor + extra["eta_days"] * DAY if "eta_days" in extra else None
        orders.append(
            {
                "id": oid, "customer_id": cid, "placed_at": placed, "status": status, "currency": CURRENCY, "items": items, "total": total,
                "payment": {"method": "card", "brand": rng.choice(["Visa", "Mastercard"]), "last4": f"{rng.randint(1000, 9999)}"},
                "shipping_address": cust["address"], "delivered_at": delivered_at, "carrier": carrier, "tracking_id": f"{carrier[:2].upper()}{rng.randint(10**9, 10**10 - 1)}",
                "installation_required": bool(extra.get("installation")), "dispatched": status in ("shipped", "out_for_delivery", "delivered", "delayed"),
            }
        )
        events = [{"ts": placed + 3600, "status": "order_received", "location": "Contoso Home OMS", "note": ""}]
        if status != "processing":
            events.append({"ts": placed + DAY, "status": "label_created", "location": "Contoso DC North", "note": ""})
            events.append({"ts": placed + 2 * DAY, "status": "in_transit", "location": f"{carrier} hub", "note": ""})
        if status == "out_for_delivery":
            events.append({"ts": anchor + 6 * 3600, "status": "out_for_delivery", "location": cust["address"]["city"], "note": "Delivery window 12:00-16:00"})
        if status == "delayed":
            events.append({"ts": anchor - 2 * DAY, "status": "delayed", "location": f"{carrier} hub", "note": "Capacity shortage at hub - new date pending"})
        if status == "delivered" and delivered_at:
            events.append({"ts": delivered_at, "status": "delivered", "location": cust["address"]["city"], "note": "Signed for at door"})
        shipments.append({"id": f"SH-{oid[3:]}", "order_id": oid, "carrier": carrier, "tracking_id": orders[-1]["tracking_id"], "status": status, "eta": eta, "events": events})
        if extra.get("installation"):
            for m in range(extra.get("missed_installs", 0)):
                appointments.append({"id": f"AP-{oid[3:]}-M{m + 1}", "order_id": oid, "customer_id": cid, "kind": "installation", "slot_id": f"ins-missed-{m}", "date": iso(anchor - (4 - m) * DAY), "window": "08:00-12:00", "status": "missed", "created_at": anchor - 7 * DAY})

    for spec in DEMO_ORDERS:
        build_order(*spec)

    onum = 100400
    for c in customers:
        if c["demo"]:
            continue
        for _ in range(rng.randint(1, 3)):
            onum += 1
            sku = rng.choice(CATALOG)[0]
            r = rng.random()
            if r < 0.7:
                build_order(f"CH-{onum}", c["id"], [sku], "delivered", rng.randint(1, 80), rng.choice(CARRIERS), {"installation": rng.random() < 0.2})
            elif r < 0.85:
                build_order(f"CH-{onum}", c["id"], [sku], "shipped", None, rng.choice(CARRIERS), {"eta_days": rng.randint(0, 4)})
            elif r < 0.93:
                build_order(f"CH-{onum}", c["id"], [sku], "processing", None, rng.choice(CARRIERS), {"eta_days": rng.randint(3, 9)})
            else:
                build_order(f"CH-{onum}", c["id"], [sku], "delayed", None, rng.choice(CARRIERS), {"eta_days": -rng.randint(1, 4)})
    return {"bo_customers": customers, "bo_orders": orders, "bo_shipments": shipments, "bo_appointments": appointments}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class BackOffice:
    """Async service facade over the back-office collections (works on Cosmos or in-memory)."""

    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    async def seed(self, anchor: float | None = None, force: bool = False) -> dict[str, int]:
        existing = await self.repo.get("bo_customers", "CU-1001")
        if existing and not force:
            return {"skipped": 1}
        data = generate_seed(anchor)
        counts = {}
        for coll, docs in data.items():
            counts[coll] = await self.repo.put_many(coll, docs)
        return counts

    async def reset(self, anchor: float | None = None) -> dict[str, int]:
        for coll in BACKOFFICE_COLLECTIONS:
            await self.repo.clear(coll)
        return await self.seed(anchor, force=True)

    # -- customers / orders ------------------------------------------------------------------
    async def get_customer(self, cid: str) -> dict[str, Any] | None:
        return await self.repo.get("bo_customers", cid)

    async def find_customer(self, identifier: str) -> dict[str, Any] | None:
        """Locate a customer from an order id, e-mail or phone (used by verification; never disclosed to the caller)."""
        ident = identifier.strip()
        if not ident:
            return None
        if "-" in ident and ident.upper().startswith("CH-"):
            order = await self.get_order(ident.upper())
            return await self.get_customer(order["customer_id"]) if order else None
        low = ident.lower()
        digits = "".join(ch for ch in ident if ch.isdigit())
        for c in await self.repo.query("bo_customers"):
            if c["email"].lower() == low or (len(digits) >= 7 and "".join(ch for ch in c["phone"] if ch.isdigit()).endswith(digits[-9:])):
                return c
        return None

    async def get_order(self, oid: str) -> dict[str, Any] | None:
        return await self.repo.get("bo_orders", oid.upper())

    async def list_orders(self, cid: str) -> list[dict[str, Any]]:
        return await self.repo.query("bo_orders", {"customer_id": cid}, order_by="placed_at", desc=True)

    async def shipment(self, oid: str) -> dict[str, Any] | None:
        rows = await self.repo.query("bo_shipments", {"order_id": oid.upper()})
        return rows[0] if rows else None

    async def appointments(self, oid: str) -> list[dict[str, Any]]:
        return await self.repo.query("bo_appointments", {"order_id": oid.upper()})

    async def slots(self, kind: str, oid: str, now: float | None = None) -> list[dict[str, Any]]:
        """Deterministic upcoming slots (next 5 business days x windows) minus already-booked ones."""
        start = day_start(now or time.time())
        booked = {a["slot_id"] for a in await self.appointments(oid) if a["status"] == "booked"}
        windows = {"pickup": ["09:00-13:00", "13:00-17:00"], "delivery": ["08:00-12:00", "12:00-16:00", "16:00-20:00"], "installation": ["08:00-12:00", "12:00-16:00"]}[kind if kind in ("pickup", "delivery", "installation") else "delivery"]
        out: list[dict[str, Any]] = []
        d = 1
        while len(out) < 6 and d < 15:
            day = start + d * DAY
            if datetime.fromtimestamp(day, UTC).weekday() < 5:
                for w in windows:
                    sid = f"{kind[:3]}-{iso(day)}-{w[:2]}"
                    if sid not in booked:
                        out.append({"slot_id": sid, "date": iso(day), "window": w, "weekday": datetime.fromtimestamp(day, UTC).strftime("%A")})
            d += 1
        return out[:6]

    # -- mutations (called by the tool layer after policy checks) ---------------------------------
    async def create_return(self, order: dict[str, Any], item_id: str, reason: str, resolution: str, conv_id: str) -> dict[str, Any]:
        doc = {"id": _id("RT"), "order_id": order["id"], "customer_id": order["customer_id"], "item_id": item_id, "reason": reason, "resolution": resolution, "status": "initiated", "created_at": time.time(), "conv_id": conv_id, "pickup_appointment_id": None}
        await self.repo.put("bo_returns", doc)
        return doc

    async def returns_for(self, oid: str) -> list[dict[str, Any]]:
        return await self.repo.query("bo_returns", {"order_id": oid.upper()})

    async def book_appointment(self, order: dict[str, Any], kind: str, slot: dict[str, Any], conv_id: str, return_id: str | None = None) -> dict[str, Any]:
        doc = {"id": _id("AP"), "order_id": order["id"], "customer_id": order["customer_id"], "kind": kind, "slot_id": slot["slot_id"], "date": slot["date"], "window": slot["window"], "status": "booked", "created_at": time.time(), "conv_id": conv_id, "return_id": return_id}
        await self.repo.put("bo_appointments", doc)
        if return_id:
            ret = await self.repo.get("bo_returns", return_id)
            if ret:
                ret.update({"status": "pickup_scheduled", "pickup_appointment_id": doc["id"]})
                await self.repo.put("bo_returns", ret)
        if kind == "delivery":
            sh = await self.shipment(order["id"])
            if sh:
                sh["eta"] = datetime.strptime(slot["date"], "%Y-%m-%d").replace(tzinfo=UTC).timestamp()
                sh["events"].append({"ts": time.time(), "status": "rescheduled", "location": "Customer service", "note": f"New delivery slot {slot['date']} {slot['window']}"})
                await self.repo.put("bo_shipments", sh)
        return doc

    async def refunds_for(self, oid: str) -> list[dict[str, Any]]:
        return await self.repo.query("bo_refunds", {"order_id": oid.upper()})

    async def create_refund(self, doc: dict[str, Any]) -> dict[str, Any]:
        doc = {"id": _id("RF"), "created_at": time.time(), **doc}
        await self.repo.put("bo_refunds", doc)
        return doc

    async def create_credit(self, customer_id: str, amount: float, reason: str, conv_id: str, **extra: Any) -> dict[str, Any]:
        doc = {"id": _id("GC"), "customer_id": customer_id, "amount": round(amount, 2), "currency": CURRENCY, "reason": reason, "conv_id": conv_id, "created_at": time.time(), "status": "issued", **extra}
        await self.repo.put("bo_credits", doc)
        return doc

    async def credits_for(self, customer_id: str, since: float | None = None) -> list[dict[str, Any]]:
        where: dict[str, Any] = {"customer_id": customer_id}
        if since:
            where["created_at"] = {"$gte": since}
        return await self.repo.query("bo_credits", where)

    async def update_address(self, order: dict[str, Any], address: dict[str, str]) -> dict[str, Any]:
        order["shipping_address"] = address
        await self.repo.put("bo_orders", order)
        return order

    async def create_warranty(self, order: dict[str, Any], item_id: str, description: str, status: str, conv_id: str) -> dict[str, Any]:
        doc = {"id": _id("WC"), "order_id": order["id"], "customer_id": order["customer_id"], "item_id": item_id, "description": description[:500], "status": status, "created_at": time.time(), "conv_id": conv_id}
        await self.repo.put("bo_warranty", doc)
        return doc

    async def create_ticket(self, customer_id: str | None, summary: str, category: str, priority: str, conv_id: str, order_id: str | None = None, notes: list[str] | None = None) -> dict[str, Any]:
        doc = {"id": _id("TK"), "customer_id": customer_id, "order_id": order_id, "summary": summary[:300], "category": category, "priority": priority, "status": "open", "notes": [{"ts": time.time(), "text": n} for n in (notes or [])], "created_at": time.time(), "conv_id": conv_id}
        await self.repo.put("bo_tickets", doc)
        return doc

    async def update_ticket(self, ticket_id: str, note: str | None = None, status: str | None = None) -> dict[str, Any] | None:
        t = await self.repo.get("bo_tickets", ticket_id)
        if not t:
            return None
        if note:
            t["notes"].append({"ts": time.time(), "text": note[:500]})
        if status:
            t["status"] = status
        await self.repo.put("bo_tickets", t)
        return t

    async def tickets_for(self, customer_id: str) -> list[dict[str, Any]]:
        rows = await self.repo.query("bo_tickets", {"customer_id": customer_id}, order_by="created_at", desc=True)
        return [r for r in rows if r.get("kind", "ticket") == "ticket"]

    async def timeline(self, customer_id: str) -> list[dict[str, Any]]:
        """Unified customer timeline (orders, shipments, returns, refunds, credits, tickets)."""
        events: list[dict[str, Any]] = []
        for o in await self.list_orders(customer_id):
            events.append({"ts": o["placed_at"], "type": "order", "id": o["id"], "title": f"Order {o['id']} placed", "detail": f"{', '.join(i['name'] for i in o['items'])} - €{o['total']:.2f}"})
            if o.get("delivered_at"):
                events.append({"ts": o["delivered_at"], "type": "delivery", "id": o["id"], "title": f"Order {o['id']} delivered", "detail": o["carrier"]})
            for r in await self.returns_for(o["id"]):
                events.append({"ts": r["created_at"], "type": "return", "id": r["id"], "title": f"Return {r['id']} ({r['resolution']})", "detail": r["reason"]})
            for rf in await self.refunds_for(o["id"]):
                events.append({"ts": rf["created_at"], "type": "refund", "id": rf["id"], "title": f"Refund €{rf['amount']:.2f} {rf['status']}", "detail": rf.get("reason", "")})
            for a in await self.appointments(o["id"]):
                events.append({"ts": a["created_at"], "type": "appointment", "id": a["id"], "title": f"{a['kind'].title()} {a['status']} {a['date']} {a['window']}", "detail": o["id"]})
        for c in await self.credits_for(customer_id):
            events.append({"ts": c["created_at"], "type": "credit", "id": c["id"], "title": f"Goodwill credit €{c['amount']:.2f}", "detail": c["reason"]})
        for t in await self.tickets_for(customer_id):
            events.append({"ts": t["created_at"], "type": "ticket", "id": t["id"], "title": f"Ticket {t['id']} {t['status']}", "detail": t["summary"]})
        events.sort(key=lambda e: e["ts"], reverse=True)
        return events
