import time
from datetime import datetime, timezone

import requests

import discover_sources
from matching import plausible_product_lead, product_match

# Reuse the existing retailer-catalog scanner but make discovery obey the same
# matcher as collection and market comparison. Premium lines are first-class
# catalog products, so their URL words must not be globally pruned.
discover_sources.product_match = product_match
discover_sources.BAD_URL_MARKERS[:] = [
    "women", "womens", "match-attax", "match_attax",
    "sticker", "starter-pack", "multipack", "multi-pack",
    "royalty", "simplicidad", "reverence", "definitive",
]


def discover_store_with_leads(store, products):
    found = []
    max_pages = int(store.get("max_pages", 4))
    catalog = store["catalog_url"]
    lead_seen = set()

    for page in range(1, max_pages + 1):
        joiner = "&" if "?" in catalog else "?"
        url = f"{catalog}{joiner}limit=250&page={page}"
        try:
            response = requests.get(url, headers=discover_sources.HEADERS, timeout=20)
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
                continue
            price = discover_sources.price_hint(item)

            exact_product = None
            for product in products:
                if product_match(product, title)[0]:
                    exact_product = product
                    break

            if exact_product:
                note = "auto-discovered from live retailer catalog"
                if price is not None:
                    note += f"; catalog price ${price:.2f}"
                found.append({
                    "product_id": exact_product["id"],
                    "seller": store["name"],
                    "url": discover_sources.product_url(catalog, handle),
                    "title": title,
                    "discovered": datetime.now(timezone.utc).date().isoformat(),
                    "evidence": note,
                })
                continue

            # Preserve a near-match only when it still looks like the correct sealed
            # product family/competition/format. Singles, women's boxes, adjacent
            # product lines, cases, breaks and loose packs are rejected here.
            for product in products:
                key = product["id"]
                if key in lead_seen or not plausible_product_lead(product, title):
                    continue
                note = "potential sealed-product lead; strict validation not satisfied"
                if price is not None:
                    note += f"; catalog price ${price:.2f}"
                found.append({
                    "product_id": product["id"],
                    "seller": store["name"],
                    "url": discover_sources.product_url(catalog, handle),
                    "title": title,
                    "discovered": datetime.now(timezone.utc).date().isoformat(),
                    "evidence": note,
                    "lead_only": True,
                })
                lead_seen.add(key)

        if len(items) < 250:
            break
        time.sleep(0.25)
    return found


_original_wrong = discover_sources.looks_obviously_wrong


def looks_obviously_wrong(entry, product_by_id):
    if entry.get("lead_only"):
        product = product_by_id.get(entry.get("product_id"))
        title = entry.get("title")
        # Revalidate saved leads every run so a bad lead never becomes permanent.
        if not product or not title:
            return True
        return not plausible_product_lead(product, title)
    return _original_wrong(entry, product_by_id)


discover_sources.looks_obviously_wrong = looks_obviously_wrong
discover_sources.discover_store = discover_store_with_leads

if __name__ == "__main__":
    discover_sources.main()
