import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from collector import product_match

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
DISCOVERY_RETAILERS = ROOT / "config" / "discovery_retailers.json"
DISCOVERED = ROOT / "config" / "discovered_sources.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CardsInStock/0.7; +https://github.com/lglock12/CardsInStock)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def product_url(catalog_url, handle):
    parsed = urlparse(catalog_url)
    return f"{parsed.scheme}://{parsed.netloc}/products/{handle}"


def price_hint(item):
    prices = []
    for v in item.get("variants") or []:
        if not v.get("available"):
            continue
        raw = v.get("price")
        try:
            prices.append(float(raw))
        except (TypeError, ValueError):
            pass
    return min(prices) if prices else None


def discover_store(store, products):
    found = []
    max_pages = int(store.get("max_pages", 4))
    catalog = store["catalog_url"]
    for page in range(1, max_pages + 1):
        joiner = "&" if "?" in catalog else "?"
        url = f"{catalog}{joiner}limit=250&page={page}"
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code != 200:
                print(f"DISCOVERY {store['name']}: HTTP {response.status_code} on page {page}")
                break
            data = response.json()
        except Exception as exc:
            print(f"DISCOVERY {store['name']}: {type(exc).__name__}: {exc}")
            break

        items = data.get("products") if isinstance(data, dict) else None
        if not items:
            break

        for item in items:
            title = str(item.get("title") or "")
            handle = item.get("handle")
            if not title or not handle:
                continue
            variants = item.get("variants") or []
            if variants and not any(v.get("available") for v in variants):
                # Discovery is for expanding live buying coverage. Existing mappings remain
                # in the file and the normal collector continues monitoring them for restocks.
                continue
            for product in products:
                matched, _ = product_match(product, title)
                if not matched:
                    continue
                price = price_hint(item)
                note = "auto-discovered from live retailer catalog"
                if price is not None:
                    note += f"; catalog price ${price:.2f}"
                found.append({
                    "product_id": product["id"],
                    "seller": store["name"],
                    "url": product_url(catalog, handle),
                    "discovered": datetime.now(timezone.utc).date().isoformat(),
                    "evidence": note,
                })
                break

        if len(items) < 250:
            break
        time.sleep(0.25)
    return found


def main():
    products = json.loads(PRODUCTS.read_text())
    stores = json.loads(DISCOVERY_RETAILERS.read_text())
    existing = json.loads(DISCOVERED.read_text()) if DISCOVERED.exists() else []

    by_key = {(x["product_id"], x["seller"], x["url"]): x for x in existing}
    before = len(by_key)
    store_counts = {}

    for store in stores:
        matches = discover_store(store, products)
        store_counts[store["name"]] = len(matches)
        for entry in matches:
            key = (entry["product_id"], entry["seller"], entry["url"])
            if key not in by_key:
                by_key[key] = entry

    output = sorted(by_key.values(), key=lambda x: (x["product_id"], x["seller"], x["url"]))
    DISCOVERED.write_text(json.dumps(output, indent=2) + "\n")
    added = len(output) - before
    print(f"Discovery complete: {len(output)} exact discovered mappings ({added:+d} new)")
    for seller, count in store_counts.items():
        if count:
            print(f"  {seller}: {count} live catalog matches")


if __name__ == "__main__":
    main()
