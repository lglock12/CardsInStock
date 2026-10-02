import json
import statistics
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests

from collector import product_match
from ebay_utils import canonical_terms, fallback_seasons, quoted_query, search_url

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
MAP = ROOT / "config" / "collectaio_map.json"
OUT = ROOT / "data" / "ebay_latest.json"
MARKET_OUT = ROOT / "data" / "market_latest.json"
BASE = "https://www.collectaio.com"
SEARCH_URL = f"{BASE}/api/v2/search"
ITEM_URL = f"{BASE}/api/v1/items/{{slug}}"
HEADERS = {
    "User-Agent": "CardsInStock/1.0 (+https://github.com/lglock12/CardsInStock)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def now_utc():
    return datetime.now(timezone.utc)


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def money(value):
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def load_map():
    if not MAP.exists():
        return {}
    try:
        data = json.loads(MAP.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_map(mapping):
    MAP.parent.mkdir(parents=True, exist_ok=True)
    MAP.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n")


def request_json(url, *, params=None, timeout=20):
    response = requests.get(url, headers=HEADERS, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def search_queries(product):
    # Start with the user's preferred precise terminology, then try common season aliases.
    queries = []
    seen = set()
    for season in [None] + fallback_seasons(product):
        terms = canonical_terms(product)
        if season:
            terms[0] = season
        query = " ".join(terms)
        if query not in seen:
            seen.add(query)
            queries.append(query)
    return queries


def discover_slug(product):
    errors = []
    for query in search_queries(product):
        try:
            payload = request_json(SEARCH_URL, params={"q": query, "page": 1, "per_page": 24})
        except Exception as exc:
            errors.append(f"{query}: {type(exc).__name__}: {exc}")
            continue

        for result in payload.get("items") or []:
            title = result.get("display_name") or result.get("name") or ""
            matched, _ = product_match(product, title)
            if matched and result.get("slug"):
                return result["slug"], title, query, None
        errors.append(f"{query}: no exact catalog match")
        time.sleep(0.15)
    return None, None, None, " | ".join(errors[-3:]) or "no CollectAIO catalog match"


def fetch_item(slug):
    return request_json(ITEM_URL.format(slug=slug))


def exact_item_match(product, item):
    title = item.get("display_name") or item.get("name") or ""
    return product_match(product, title)[0]


def is_ebay_url(url):
    if not url:
        return False
    host = urlparse(str(url)).netloc.lower()
    return "ebay." in host or host.endswith("ebay.com")


def listing_matches(product, listing, item_title):
    title = listing.get("title") or item_title or ""
    return product_match(product, title)[0]


def listing_total(listing):
    price = money(listing.get("price"))
    shipping = money(listing.get("shipping"))
    if price is None:
        return None, None, None
    if shipping is None:
        return price, None, None
    return price, shipping, round(price + shipping, 2)


def active_candidates(product, item):
    item_title = item.get("display_name") or item.get("name") or ""
    candidates = []
    for listing in item.get("listings") or []:
        if listing.get("include_in_price") is False:
            continue
        if listing.get("sold_at"):
            continue
        state = str(listing.get("market_state") or "").lower()
        if any(word in state for word in ["sold", "ended", "complete", "expired"]):
            continue
        if not is_ebay_url(listing.get("url")):
            continue
        if not listing_matches(product, listing, item_title):
            continue

        price, shipping, delivered = listing_total(listing)
        # The card promises delivered comparison, so unknown shipping is not showcased.
        if price is None or shipping is None or delivered is None:
            continue
        candidates.append({
            "title": listing.get("title") or item_title,
            "url": listing.get("url"),
            "item_price": price,
            "shipping": shipping,
            "delivered_price": delivered,
            "shipping_text": "FREE" if shipping == 0 else f"${shipping:.2f}",
            "market_state": listing.get("market_state"),
            "listing_id": listing.get("id"),
        })
    candidates.sort(key=lambda x: (x["delivered_price"], x["item_price"]))
    return candidates


def sold_comps(product, item):
    item_title = item.get("display_name") or item.get("name") or ""
    comps = []
    for listing in item.get("listings") or []:
        sold_at = parse_dt(listing.get("sold_at"))
        if not sold_at:
            continue
        if listing.get("include_in_price") is False:
            continue
        if not listing_matches(product, listing, item_title):
            continue
        # Sold rows may not retain a clickable eBay URL, so URL is evidence when present,
        # not a requirement for historical comps.
        if listing.get("url") and not is_ebay_url(listing.get("url")):
            continue
        price, shipping, delivered = listing_total(listing)
        if price is None:
            continue
        comps.append({
            "title": listing.get("title") or item_title,
            "sold_at": sold_at.isoformat(),
            "item_price": price,
            "shipping": shipping,
            "delivered_price": delivered,
            "url": listing.get("url"),
            "listing_id": listing.get("id"),
        })
    comps.sort(key=lambda x: x["sold_at"], reverse=True)
    return comps


def median(values):
    vals = [float(v) for v in values if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def summarize_sold(comps, checked):
    summary = {
        "count": len(comps),
        "latest_sale_at": comps[0]["sold_at"] if comps else None,
        "median_all_item_price": median([c["item_price"] for c in comps]),
        "median_all_delivered": median([c["delivered_price"] for c in comps]),
        "windows": {},
        "recent": comps[:12],
    }
    for days in (30, 90, 180, 365):
        cutoff = checked - timedelta(days=days)
        rows = [c for c in comps if parse_dt(c["sold_at"]) and parse_dt(c["sold_at"]) >= cutoff]
        summary["windows"][str(days)] = {
            "count": len(rows),
            "median_item_price": median([c["item_price"] for c in rows]),
            "median_delivered": median([c["delivered_price"] for c in rows]),
        }
    return summary


def collect_product(product, mapping, checked):
    slug = mapping.get(product["id"])
    item = None
    discovered_by = None
    error = None

    if slug:
        try:
            candidate = fetch_item(slug)
            if exact_item_match(product, candidate):
                item = candidate
            else:
                error = "cached CollectAIO slug no longer matches exact product"
                slug = None
        except Exception as exc:
            error = f"cached slug fetch failed: {type(exc).__name__}: {exc}"
            slug = None

    if not slug:
        slug, _, discovered_by, discover_error = discover_slug(product)
        if not slug:
            return {
                "status": "UNAVAILABLE",
                "query": quoted_query(product),
                "search_url": search_url(product),
                "candidate_count": 0,
                "best": None,
                "reason": discover_error or error or "no CollectAIO catalog match",
                "source": "collectaio_public_api",
                "sold": summarize_sold([], checked),
            }
        try:
            item = fetch_item(slug)
        except Exception as exc:
            return {
                "status": "UNAVAILABLE",
                "query": quoted_query(product),
                "search_url": search_url(product),
                "candidate_count": 0,
                "best": None,
                "reason": f"CollectAIO item fetch failed: {type(exc).__name__}: {exc}",
                "source": "collectaio_public_api",
                "collectaio_slug": slug,
                "collectaio_url": f"{BASE}/item/{slug}",
                "sold": summarize_sold([], checked),
            }
        if not exact_item_match(product, item):
            return {
                "status": "UNAVAILABLE",
                "query": quoted_query(product),
                "search_url": search_url(product),
                "candidate_count": 0,
                "best": None,
                "reason": "CollectAIO search result failed exact product validation",
                "source": "collectaio_public_api",
                "collectaio_slug": slug,
                "collectaio_url": f"{BASE}/item/{slug}",
                "sold": summarize_sold([], checked),
            }
        mapping[product["id"]] = slug

    candidates = active_candidates(product, item)
    comps = sold_comps(product, item)
    sold = summarize_sold(comps, checked)
    best = candidates[0] if candidates else None

    result = {
        "status": "VERIFIED" if best else "UNAVAILABLE",
        "query": quoted_query(product),
        "search_url": search_url(product),
        "candidate_count": len(candidates),
        "best": best,
        "reason": (
            "lowest exact-match active eBay listing in CollectAIO with known listed shipping"
            if best else
            "CollectAIO item matched, but no exact active eBay listing with known shipping was available"
        ),
        "source": "collectaio_public_api",
        "collectaio_slug": slug,
        "collectaio_url": f"{BASE}/item/{slug}",
        "collectaio_item_name": item.get("display_name") or item.get("name"),
        "collectaio_retail_msrp": money(item.get("retail_msrp")),
        "collectaio_image_url": item.get("preferred_image_url") or item.get("cover_url"),
        "sold": sold,
        "daily_prices": (item.get("daily_prices") or [])[-400:],
    }
    if discovered_by:
        result["discovered_by_query"] = discovered_by
    return result


def main():
    products = json.loads(PRODUCTS.read_text())
    checked = now_utc()
    checked_iso = checked.isoformat()
    mapping = load_map()
    market = {
        "generated_at": checked_iso,
        "source": "collectaio_public_api",
        "source_docs": "https://www.collectaio.com/developers",
        "products": {},
    }

    verified = 0
    mapped = 0
    sold_products = 0
    for index, product in enumerate(products, start=1):
        result = collect_product(product, mapping, checked)
        market["products"][product["id"]] = result
        if result.get("collectaio_slug"):
            mapped += 1
        if result.get("status") == "VERIFIED":
            verified += 1
            best = result["best"]
            print(
                f"MARKET {product['id']}: ${best['delivered_price']:.2f} delivered eBay snapshot "
                f"({result.get('candidate_count', 0)} active matched)"
            )
        else:
            print(f"MARKET {product['id']}: no active delivered eBay snapshot")
        if result.get("sold", {}).get("count", 0):
            sold_products += 1
        if index < len(products):
            time.sleep(0.15)

    save_map(mapping)
    MARKET_OUT.parent.mkdir(parents=True, exist_ok=True)
    MARKET_OUT.write_text(json.dumps(market, indent=2) + "\n")
    # Keep this compatibility output so the existing dashboard can immediately render
    # the best eBay snapshot without waiting for a dashboard rewrite.
    OUT.write_text(json.dumps(market, indent=2) + "\n")
    print(
        f"CollectAIO market collection complete: {mapped}/{len(products)} catalog matches; "
        f"{verified} active eBay delivered snapshots; {sold_products} products with sold comps"
    )


if __name__ == "__main__":
    main()
