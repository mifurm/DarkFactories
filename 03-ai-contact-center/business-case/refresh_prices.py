#!/usr/bin/env python3
"""Refresh and verify the Azure list prices used by the business-case model (stdlib only).

    python refresh_prices.py            # query the Azure Retail Prices API, rewrite pricing_snapshot.json, report drift vs assumptions.json
    python refresh_prices.py --check    # offline: verify assumptions.json against pricing_snapshot.json (used by test_model.py)

Every unit price in assumptions.json that has a `ref` is matched to the exact API row(s) (serviceName, productName,
armRegionName, skuName, optional meterName and tierMinimumUnits). The snapshot is the audit trail behind the ACR numbers.
"""
from __future__ import annotations

import datetime
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://prices.azure.com/api/retail/prices"
API_VERSION = "2023-01-01-preview"
HERE = Path(__file__).resolve().parent
ROW_FIELDS = ("serviceName", "productName", "skuName", "meterName", "armRegionName", "unitOfMeasure", "retailPrice",
              "tierMinimumUnits", "effectiveStartDate", "meterId", "currencyCode", "type")


def iter_refs(assumptions):
    """Yield (price_key, variant, ref, expected_value, scale). variant is a deployment type, 'value' or 'tiers'."""
    for key, entry in assumptions["unit_prices"].items():
        ref = entry.get("ref")
        if not ref:
            continue
        scale = ref.get("scale", 1)
        if ref.get("tiers"):
            yield key, "tiers", ref, [tuple(t) for t in entry["tiers"]], scale
        elif isinstance(ref["sku"], dict):
            for variant, sku in ref["sku"].items():
                yield key, variant, dict(ref, sku=sku), entry[variant], scale
        else:
            yield key, "value", ref, entry["value"], scale


def _matches(row, ref):
    if row["productName"] != ref["product"] or row["armRegionName"] != ref["region"] or row["skuName"] != ref["sku"]:
        return False
    if "meter" in ref and row["meterName"] != ref["meter"]:
        return False
    if "tier" in ref and float(row.get("tierMinimumUnits", 0)) != float(ref["tier"]):
        return False
    return True


def select_rows(rows, ref):
    return [r for r in rows if _matches(r, ref)]


def _trim(row):
    return {k: row.get(k) for k in ROW_FIELDS}


def verify_snapshot(assumptions, snapshot):
    """Return a list of human-readable problems (empty list = every priced line matches the snapshot)."""
    problems = []
    for key, variant, ref, expected, scale in iter_refs(assumptions):
        snap = snapshot["rows"].get(key, {}).get(variant)
        if snap is None:
            problems.append(f"{key}/{variant}: missing from snapshot")
            continue
        if variant == "tiers":
            got = sorted((float(r["tierMinimumUnits"]), r["retailPrice"] * scale) for r in snap)
            want = sorted((float(a), float(b)) for a, b in expected)
            if len(got) != len(want) or any(abs(g[0] - w[0]) > 1e-9 or abs(g[1] - w[1]) > 1e-9 for g, w in zip(got, want)):
                problems.append(f"{key}: tiers {want} != snapshot {got}")
        else:
            got = snap["retailPrice"] * scale
            if abs(got - expected) > max(1e-9, abs(expected) * 1e-6):
                problems.append(f"{key}/{variant}: assumptions {expected} != snapshot {got}")
    return problems


def _fetch(filter_expr):
    url = API + "?" + urllib.parse.urlencode({"$filter": filter_expr, "api-version": API_VERSION})
    items = []
    while url:
        with urllib.request.urlopen(url, timeout=120) as resp:
            page = json.load(resp)
        items.extend(page.get("Items", []))
        url = page.get("NextPageLink")
    return items


def refresh(assumptions):
    groups = {}
    for key, variant, ref, expected, scale in iter_refs(assumptions):
        groups.setdefault((ref["service"], ref["region"], ref["product"]), []).append((key, variant, ref))
    cache = {}
    for (service, region, product) in groups:
        flt = f"serviceName eq '{service}' and armRegionName eq '{region}' and productName eq '{product}'"
        cache[(service, region, product)] = _fetch(flt)
        print(f"  fetched {len(cache[(service, region, product)]):5d} rows: {service} / {product} / {region}")
    rows = {}
    for (service, region, product), refs in groups.items():
        for key, variant, ref in refs:
            matched = select_rows(cache[(service, region, product)], ref)
            if not matched:
                raise SystemExit(f"no API row for {key}/{variant}: {ref}")
            if ref.get("tiers"):
                rows.setdefault(key, {})["tiers"] = [_trim(r) for r in matched]
            else:
                if len({r["retailPrice"] for r in matched}) > 1:
                    raise SystemExit(f"ambiguous API rows for {key}/{variant}: {ref}")
                rows.setdefault(key, {})[variant] = _trim(matched[0])
    return {"retrieved": datetime.date.today().isoformat(), "api": API, "api_version": API_VERSION,
            "note": "Exact Azure Retail Prices API rows behind every unit price in assumptions.json that has a ref (USD, list price).",
            "rows": rows}


def main(argv):
    assumptions = json.loads((HERE / "assumptions.json").read_text(encoding="utf-8"))
    snap_path = HERE / "pricing_snapshot.json"
    if "--check" in argv:
        problems = verify_snapshot(assumptions, json.loads(snap_path.read_text(encoding="utf-8")))
        print("\n".join(problems) if problems else "assumptions.json matches pricing_snapshot.json")
        return 1 if problems else 0
    snapshot = refresh(assumptions)
    problems = verify_snapshot(assumptions, snapshot)
    snap_path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {snap_path.name} ({len(snapshot['rows'])} priced lines, retrieved {snapshot['retrieved']})")
    if problems:
        print("PRICE DRIFT - update assumptions.json unit_prices:")
        print("\n".join("  " + p for p in problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
