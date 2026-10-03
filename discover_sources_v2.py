import time
from datetime import datetime, timezone

import requests

import discover_sources
from matching import normalize, product_match, term_matches

# Reuse the existing retailer-catalog scanner but make discovery obey the same
# matcher as collection and market comparison. Premium lines are first-class
# catalog products, so their URL words must not be globally pruned.
discover_sources.product_match = product_match
discover_sources.BAD_URL_MARKERS[:] = [
    "women", "womens", "match-attax", "match_attax",
    "sticker", "starter-pack", "multipack", "multi-pack",
    "royalty", "simplicidad", "reverence", "definitive",
]


def expected_family(product):
    name = normalize(product.get("product"))
    for marker in ("stadium club", "merlin", "finest", "inception", "museum", "deco", "chrome"):
        if marker in name:
            return marker
    return "flagship"


def competition_ok(product, title):
    name = normalize(product.get("product"))
    t = normalize(title)
    if "premier league" in name:
        return any(x in t for x in ["premier league", "english premier league", " epl "])
    if "uefa euro" in name:
        return "euro" in t and "uefa" in t
    if "uefa" in name:
        return any(x in t for x in ["uefa", " ucc ", "club competitions", "champions league"])
    return True


def family_ok(product, title):
    family = expected_family(product)
    t = normalize(title)
    if family == "flagship":
        return not any(x in t for x in ["stadium club", "chrome", "merlin", "finest", "sapphire", "inception", "museum", "deco"])
    return family in t


def format_conflict(product, title):
    t = normalize(title)
    fmt = product.get("format")
    if "case" in t:
        return True
    if any(x in t for x in ["sticker", "starter pack", "multipack", "multi pack", "bundle"]):
        return True
    if fmt == "Hobby":
        return any(x in t for x in ["blaster", "value box", "mega box", "mega tin", "jumbo", "sapphire", "delight", "breakers delight", "breaker's delight"])
    if fmt == "Blaster / Value":
        return any(x in t for x in ["hobby", "jumbo", "mega box", "mega tin", "sapphire", "delight"])
    if fmt == "Hobby Jumbo":
        return any(x in t for x in ["blaster", "value box", "mega box", "mega tin", "sapphire", "delight"])
    if fmt == "Sapphire":
        return "sapphire" not in t
    if fmt == "Delight":
        return not any(x in t for x in ["delight", "breaker delight", "breaker's delight", "breakers delight"])
    if fmt in ("Tin", "Mega Tin"):
        return "tin" not in t
    if fmt == "Full Box":
        return not any(x in t for x in ["full box", "full display", "display box"])
    return False


def plausible_lead(product, title):
    # Leads are intentionally looser than VERIFIED. They never feed the best-price
    # calculation; they exist so an oddly named retailer listing is not silently lost.
    if product_match(product, title)[0]:
        return False
    if not term_matches(product.get("season"), title):
        return False
    if not family_ok(product, title) or not competition_ok(product, title):
        return False
    if format_conflict(product, title):
        return False
    return True


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

            for product in products:
                key = product["id"]
                if key in lead_seen or not plausible_lead(product, title):
                    continue
                note = "potential live catalog lead; strict validation not satisfied"
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
        return False
    return _original_wrong(entry, product_by_id)


discover_sources.looks_obviously_wrong = looks_obviously_wrong
discover_sources.discover_store = discover_store_with_leads

if __name__ == "__main__":
    discover_sources.main()
