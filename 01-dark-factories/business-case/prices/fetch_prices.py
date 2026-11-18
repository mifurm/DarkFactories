#!/usr/bin/env python3
"""Azure Retail Prices API helper for the Nightshift business case (stdlib only).

Two sub-commands:

  search    explore the public Retail Prices API (https://prices.azure.com/api/retail/prices)
            python fetch_prices.py search --service "Event Hubs" --region swedencentral [--product X] [--sku Y] [--meter Z]

  snapshot  resolve every query in queries.json to ONE meter row and write prices-snapshot.json
            (the file the unit prices in ../assumptions.json are copied from; a unit test checks they agree)
            python fetch_prices.py snapshot --queries queries.json --out prices-snapshot.json

List prices only: USD, pay-as-you-go ("Consumption" type), no EA/CSP discount, no reservations or savings plans.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://prices.azure.com/api/retail/prices"


def _get(url: str, retries: int = 4) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed public https endpoint
                return json.load(resp)
        except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Retail Prices API failed: {last}")


def query(filter_: str, max_pages: int = 60, currency: str = "USD") -> list[dict]:
    params = {"$filter": filter_, "currencyCode": currency}
    url = f"{API}?{urllib.parse.urlencode(params)}"
    items: list[dict] = []
    for _ in range(max_pages):
        data = _get(url)
        items.extend(data.get("Items", []))
        url = data.get("NextPageLink") or ""
        if not url:
            break
    return items


def build_filter(service: str | None, region: str | None, extra: str | None = None) -> str:
    parts = []
    if region:
        parts.append(f"armRegionName eq '{region}'")
    if service:
        parts.append(f"serviceName eq '{service}'")
    if extra:
        parts.append(extra)
    return " and ".join(parts)


def _match(row: dict, sel: dict) -> bool:
    for key, pattern in sel.items():
        if key in ("note",):
            continue
        value = str(row.get(key, ""))
        if not re.search(pattern, value, flags=re.IGNORECASE):
            return False
    return True


def cmd_search(args: argparse.Namespace) -> int:
    rows = query(build_filter(args.service, args.region, args.extra))
    shown = 0
    for r in rows:
        if r.get("type") != "Consumption" and not args.all_types:
            continue
        if args.product and not re.search(args.product, r["productName"], re.I):
            continue
        if args.sku and not re.search(args.sku, r["skuName"], re.I):
            continue
        if args.meter and not re.search(args.meter, r["meterName"], re.I):
            continue
        print(
            f'{r["serviceName"]} | {r["productName"]} | {r["skuName"]} | {r["meterName"]} | '
            f'{r["unitOfMeasure"]} | {r["retailPrice"]} {r["currencyCode"]} | tier {r.get("tierMinimumUnits", 0)} | {r["armRegionName"]}'
        )
        shown += 1
        if shown >= args.limit:
            break
    print(f"-- {shown} rows shown of {len(rows)} returned", file=sys.stderr)
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    with open(args.queries, encoding="utf-8") as fh:
        spec = json.load(fh)
    retrieved = args.date or dt.date.today().isoformat()
    out = {
        "retrieved_on": retrieved,
        "api": API,
        "currency": "USD",
        "pricing_basis": "Azure Retail Prices API list price, pay-as-you-go (type=Consumption), no EA/CSP discount, no reservations/savings plans",
        "items": {},
    }
    cache: dict[str, list[dict]] = {}
    failures = 0
    for q in spec["queries"]:
        flt = build_filter(q.get("serviceName"), q.get("region"), q.get("extra"))
        if flt not in cache:
            cache[flt] = query(flt)
        rows = [r for r in cache[flt] if r.get("type") == "Consumption" and _match(r, q.get("select", {}))]
        # the API returns tiers; keep the first tier (tierMinimumUnits == 0) unless a tier is asked for
        tier = float(q.get("tierMinimumUnits", 0))
        rows = [r for r in rows if float(r.get("tierMinimumUnits", 0)) == tier]
        if len(rows) != 1:
            failures += 1
            print(f'!! {q["id"]}: expected exactly 1 row, got {len(rows)} for filter [{flt}] select {q.get("select")}', file=sys.stderr)
            for r in rows[:8]:
                print(f'     {r["productName"]} | {r["skuName"]} | {r["meterName"]} | {r["unitOfMeasure"]} | {r["retailPrice"]}', file=sys.stderr)
            continue
        r = rows[0]
        out["items"][q["id"]] = {
            "family": q.get("family"),
            "serviceName": r["serviceName"],
            "productName": r["productName"],
            "skuName": r["skuName"],
            "meterName": r["meterName"],
            "meterId": r["meterId"],
            "unitOfMeasure": r["unitOfMeasure"],
            "retailPrice": r["retailPrice"],
            "currencyCode": r["currencyCode"],
            "armRegionName": r["armRegionName"],
            "effectiveStartDate": r["effectiveStartDate"],
            "filter": flt,
        }
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {args.out}: {len(out['items'])} items, {failures} failures", file=sys.stderr)
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("--service")
    s.add_argument("--region", default="swedencentral")
    s.add_argument("--extra", help="extra OData filter clause, e.g. \"contains(productName,'Gateway')\"")
    s.add_argument("--product")
    s.add_argument("--sku")
    s.add_argument("--meter")
    s.add_argument("--limit", type=int, default=60)
    s.add_argument("--all-types", action="store_true")
    s.set_defaults(fn=cmd_search)
    t = sub.add_parser("snapshot")
    t.add_argument("--queries", default="queries.json")
    t.add_argument("--out", default="prices-snapshot.json")
    t.add_argument("--date")
    t.set_defaults(fn=cmd_snapshot)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
