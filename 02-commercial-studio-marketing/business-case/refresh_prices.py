"""Verify or refresh the Azure Retail Prices snapshot embedded in assumptions.json (pure standard library).

    python refresh_prices.py            # compare the snapshot with the live API; exit code 1 if anything differs
    python refresh_prices.py --write    # update api_price / price and pricing.meta.retrieved_at in assumptions.json

Each price item records the exact selector (service, product, sku, meter, region, tier) used against
https://prices.azure.com/api/retail/prices; `factor` converts the API unit into the unit named in the item.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "assumptions.json")
API = "https://prices.azure.com/api/retail/prices"


def quote(value: str) -> str:
    return value.replace("'", "''")


def query(item: dict) -> list:
    flt = (f"serviceName eq '{quote(item['service'])}' and armRegionName eq '{quote(item['region'])}' "
           f"and meterName eq '{quote(item['meter'])}' and priceType eq 'Consumption'")
    if item.get("product"):
        flt += f" and productName eq '{quote(item['product'])}'"
    if item.get("sku"):
        flt += f" and skuName eq '{quote(item['sku'])}'"
    url = API + "?" + urllib.parse.urlencode({"$filter": flt})
    rows = []
    while url:
        with urllib.request.urlopen(url, timeout=60) as resp:
            data = json.load(resp)
        rows.extend(data.get("Items", []))
        url = data.get("NextPageLink")
    return rows


def pick(item: dict, rows: list):
    rows = [r for r in rows if float(r.get("tierMinimumUnits", 0)) == float(item.get("tier_min", 0))]
    rows.sort(key=lambda r: r.get("effectiveStartDate", ""), reverse=True)
    return rows[0] if rows else None


def main(argv: list) -> int:
    write = "--write" in argv
    with open(PATH, "r", encoding="utf-8") as fh:
        text = fh.read()
    data = json.loads(text)
    diffs, missing, updated = [], [], {}
    for key, item in data["pricing"]["items"].items():
        try:
            row = pick(item, query(item))
        except Exception as exc:  # network or API failure
            print(f"ERROR {key}: {exc}")
            return 2
        if row is None:
            missing.append(key)
            print(f"MISSING {key}: {item['service']} / {item['meter']} / {item['region']}")
            continue
        live = float(row["retailPrice"])
        if abs(live - float(item["api_price"])) > 1e-12 + 1e-9 * abs(live):
            diffs.append((key, item["api_price"], live))
            updated[key] = live
        status = "ok" if key not in updated else f"CHANGED {item['api_price']} -> {live}"
        print(f"{key:30s} {live:>12g} {row['unitOfMeasure']:<12s} {status}")
    print(f"\n{len(data['pricing']['items'])} items, {len(diffs)} changed, {len(missing)} missing")
    if write and diffs:
        for key, _old, live in diffs:
            item = data["pricing"]["items"][key]
            new_price = live * float(item["factor"])
            pattern = re.compile(r'("%s": \{.*?"api_price": )[^,]+(, "api_unit".*?"price": )[^,]+(,)' % re.escape(key))
            text, n = pattern.subn(lambda m: f"{m.group(1)}{live!r}{m.group(2)}{new_price!r}{m.group(3)}", text, count=1)
            if n != 1:
                print(f"could not rewrite {key}")
                return 2
        text = re.sub(r'("retrieved_at": )"[0-9-]+"', lambda m: f'{m.group(1)}"{datetime.date.today().isoformat()}"', text, count=1)
        with open(PATH, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("assumptions.json updated - re-run `python model.py` to regenerate outputs.json / outputs.md")
    return 1 if (diffs or missing) and not write else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
