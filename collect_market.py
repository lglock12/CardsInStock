import json
import statistics
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests

from ebay_utils import canonical_terms, fallback_seasons, quoted_query, search_url
from matching import product_match

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
MAP = ROOT / "config" / "collectaio_map.json"
OUT = ROOT / "data" / "ebay_latest.json"
MARKET_OUT = ROOT / "data" / "market_latest.json"
BASE = "https://www.collectaio.com"
SEARCH_URL = f"{BASE}/api/v2/search"
ITEM_URL = f"{BASE}/api/v1/items/{{slug}}"
HEADERS = {
    "User-Agent": "CardsInStock/1.1 (+https://github.com/lglock12/CardsInStock)",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

SOLD_DATE_KEYS = ("sold_at", "soldAt", "sold_date", "sale_date", "ended_at")
PRICE_KEYS = ("price", "sold_price", "sale_price", "item_price")
SHIPPING_KEYS = ("shipping", "shipping_price", "shipping_cost")
FRESHNESS_KEY_MARKERS = (
    "refresh", "snapshot", "updated_at", "last_updated", "fetched_at",
    "observed_at", "checked_at", "evidence_age",
)


def now_utc():
    return datetime.now(timezone.utc)


def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def money(value):
    try:
        if value is None or isinstance(value, bool):
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
            payload = request_json(SEARCH_URL, params={"q": query, "page": 1, "per_page": 48})
        except Exception as exc:
            errors.append(f"{query}: {type(exc).__name__}: {exc}")
            continue

        for result in payload.get("items") or []:
            title = result.get("display_name") or result.get("name") or ""
            matched, _ = product_match(product, title)
            if matched and result.get("slug"):
                return result["slug"], title, query, None
        errors.append(f"{query}: no exact catalog match")
        time.sleep(0.12)
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
    title = listing.get("title") or listing.get("name") or item_title or ""
    return product_match(product, title)[0]


def first_money(d, keys):
    for key in keys:
        if key in d:
            value = money(d.get(key))
            if value is not None:
                return value
    return None


def first_sold_at(d):
    for key in SOLD_DATE_KEYS:
        dt = parse_dt(d.get(key))
        if dt:
            return dt
    return None


def listing_total(listing):
    price = first_money(listing, PRICE_KEYS)
    shipping = first_money(listing, SHIPPING_KEYS)
    if price is None:
        return None, None, None
    if shipping is None:
        return price, None, None
    return price, shipping, round(price + shipping, 2)


def walk_dicts(obj, path="root"):
    if isinstance(obj, dict):
        yield path, obj
        for key, value in obj.items():
            yield from walk_dicts(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from walk_dicts(value, f"{path}[{index}]")


def node_timestamp(node):
    for key in (
        "snapshot_at", "refreshed_at", "updated_at", "last_refreshed_at",
        "fetched_at", "observed_at", "checked_at", "created_at"
    ):
        dt = parse_dt(node.get(key))
        if dt:
            return dt.isoformat()
    return None


def active_candidates(product, item):
    item_title = item.get("display_name") or item.get("name") or ""
    candidates = []
    seen = set()
    for listing in item.get("listings") or []:
        if listing.get("include_in_price") is False:
            continue
        if first_sold_at(listing):
            continue
        state = str(listing.get("market_state") or "").lower()
        if any(word in state for word in ["sold", "ended", "complete", "expired"]):
            continue
        if not is_ebay_url(listing.get("url")):
            continue
        if not listing_matches(product, listing, item_title):
            continue

        price, shipping, delivered = listing_total(listing)
        if price is None or shipping is None or delivered is None:
            continue
        key = (listing.get("url"), price, shipping)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "title": listing.get("title") or item_title,
            "url": listing.get("url"),
            "item_price": price,
            "shipping": shipping,
            "delivered_price": delivered,
            "shipping_text": "FREE" if shipping == 0 else f"${shipping:.2f}",
            "market_state": listing.get("market_state"),
            "listing_id": listing.get("id"),
            "source_updated_at": node_timestamp(listing),
        })
    candidates.sort(key=lambda x: (x["delivered_price"], x["item_price"]))
    return candidates


def sold_comps(product, item):
    """Find sold records anywhere in the public item payload.

    The documented Listing schema has sold_at, but some products expose historical
    evidence outside the top-level active listings array. Walking the public item
    payload lets us consume documented sold records without assuming their nesting.
    """
    item_title = item.get("display_name") or item.get("name") or ""
    comps = []
    seen = set()
    for path, node in walk_dicts(item):
        sold_at = first_sold_at(node)
        if not sold_at:
            continue
        if node.get("include_in_price") is False:
            continue
        if not listing_matches(product, node, item_title):
            continue
        url = node.get("url")
        if url and not is_ebay_url(url):
            continue
        price, shipping, delivered = listing_total(node)
        if price is None:
            continue
        title = node.get("title") or node.get("name") or item_title
        key = (node.get("id"), sold_at.isoformat(), price, shipping, title)
        if key in seen:
            continue
        seen.add(key)
        comps.append({
            "title": title,
            "sold_at": sold_at.isoformat(),
            "item_price": price,
            "shipping": shipping,
            "delivered_price": delivered,
            "url": url,
            "listing_id": node.get("id"),
            "payload_path": path,
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


def compact_evidence(item):
    """Preserve public aggregate signals so we can validate CollectAIO's exact schema.

    This is intentionally bounded. It helps distinguish active asks, sold evidence,
    and CollectAIO estimates without flattening them into one price.
    """
    variation_values = []
    for variation in item.get("variations") or []:
        value = variation.get("collectaio_value")
        if value:
            variation_values.append({
                "id": variation.get("id"),
                "name": variation.get("name"),
                "display_price": variation.get("display_price"),
                "pricing_source": variation.get("pricing_source"),
                "collectaio_value": value,
            })
        if len(variation_values) >= 8:
            break

    freshness = {}
    sold_signals = {}
    for path, node in walk_dicts(item):
        for key, value in node.items():
            key_l = str(key).lower()
            full = f"{path}.{key}"
            if any(marker in key_l for marker in FRESHNESS_KEY_MARKERS):
                if isinstance(value, (str, int, float, bool)) or value is None:
                    if len(freshness) < 40:
                        freshness[full] = value
            if "sold" in key_l and isinstance(value, (str, int, float, bool)):
                if len(sold_signals) < 40:
                    sold_signals[full] = value

    return {
        "variation_values": variation_values,
        "listing_summaries": (item.get("listing_summaries") or [])[:20],
        "freshness_fields": freshness,
        "sold_signal_fields": sold_signals,
    }


def collect_product(product, mapping, checked):
    pid = product["id"]
    slug = mapping.get(pid)
    item = None
    discovered_by = None
    previous_error = None

    if slug:
        try:
            candidate = fetch_item(slug)
            if exact_item_match(product, candidate):
                item = candidate
            else:
                previous_error = "cached CollectAIO slug no longer matches exact product"
                mapping.pop(pid, None)
                slug = None
        except Exception as exc:
            previous_error = f"cached slug fetch failed: {type(exc).__name__}: {exc}"
            mapping.pop(pid, None)
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
                "reason": discover_error or previous_error or "no CollectAIO catalog match",
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
        mapping[pid] = slug

    candidates = active_candidates(product, item)
    comps = sold_comps(product, item)
    sold = summarize_sold(comps, checked)
    best = candidates[0] if candidates else None
    evidence = compact_evidence(item)

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
        "evidence_debug": evidence,
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
        sold_count = result.get("sold", {}).get("count", 0)
        if sold_count:
            sold_products += 1
            print(f"  SOLD {sold_count} detailed comps; latest {result['sold'].get('latest_sale_at')}")
        evidence = result.get("evidence_debug") or {}
        if result.get("collectaio_slug") and not sold_count:
            sold_fields = evidence.get("sold_signal_fields") or {}
            summaries = evidence.get("listing_summaries") or []
            variation_values = evidence.get("variation_values") or []
            if sold_fields or summaries or variation_values:
                print(
                    f"  EVIDENCE debug: {len(sold_fields)} sold fields, "
                    f"{len(summaries)} listing summaries, {len(variation_values)} variation values"
                )
        if index < len(products):
            time.sleep(0.12)

    save_map(mapping)
    MARKET_OUT.parent.mkdir(parents=True, exist_ok=True)
    MARKET_OUT.write_text(json.dumps(market, indent=2) + "\n")
    OUT.write_text(json.dumps(market, indent=2) + "\n")
    print(
        f"CollectAIO market collection complete: {mapped}/{len(products)} catalog matches; "
        f"{verified} active eBay delivered snapshots; {sold_products} products with detailed sold comps"
    )


if __name__ == "__main__":
    main()
