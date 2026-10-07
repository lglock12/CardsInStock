import os
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ebay_utils import fallback_seasons, search_url
from matching import product_match

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
MARKET = ROOT / "data" / "market_latest.json"
EBAY = ROOT / "data" / "ebay_latest.json"
ACTIVE_CACHE = ROOT / "data" / "active_ebay_cache.json"
API = "https://api.ebaysoldlistingsapi.com/scrape"
KEY = os.getenv("EBAY_SOLD_API_KEY", "").strip()
FULL_REFRESH = os.getenv("EBAY_ACTIVE_FULL_REFRESH", "").strip().lower() in {"1","true","yes"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}
BLOCK_MARKERS = (
    "pardon our interruption",
    "security measure",
    "verify you are a human",
    "captcha",
    "access denied",
)


def money_text(text):
    if not text:
        return None
    # Avoid deceptive variation/range listings such as "$20.00 to $299.99".
    low = str(text).lower()
    if " to " in low or re.search(r"\$[\d,.]+\s*[-–]\s*\$", low):
        return None
    match = re.search(r"\$\s*([\d,]+(?:\.\d{1,2})?)", str(text))
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", "")), 2)
    except ValueError:
        return None


def shipping_money(text):
    if not text:
        return None
    low = str(text).lower()
    if "free shipping" in low or "free delivery" in low or low.strip() == "free":
        return 0.0
    match = re.search(r"(?:\+\s*)?\$\s*([\d,]+(?:\.\d{1,2})?)", str(text))
    if not match:
        return None
    try:
        return round(float(match.group(1).replace(",", "")), 2)
    except ValueError:
        return None


def node_text(node):
    return " ".join(node.stripped_strings) if node else ""


def parse_search(product, page_html):
    soup = BeautifulSoup(page_html, "html.parser")
    candidates = []
    seen = set()

    cards = soup.select("li.s-item, div.s-item")
    for card in cards:
        title_node = card.select_one(".s-item__title")
        price_node = card.select_one(".s-item__price")
        link_node = card.select_one("a.s-item__link")
        ship_node = card.select_one(".s-item__shipping, .s-item__logisticsCost, .s-item__deliveryOptions")

        title = node_text(title_node)
        if not title or title.lower() in {"shop on ebay", "new listing"}:
            continue
        title = re.sub(r"^New Listing\s*", "", title, flags=re.I)
        matched, _ = product_match(product, title)
        if not matched:
            continue

        card_text = node_text(card).lower()
        # Search URL requests BIN only, but reject anything that still looks auction-only.
        if " bids" in card_text or re.search(r"\b\d+\s+bid\b", card_text):
            continue

        item_price = money_text(node_text(price_node))
        shipping_text = node_text(ship_node)
        shipping = shipping_money(shipping_text)
        href = link_node.get("href") if link_node else None
        if item_price is None or shipping is None or not href:
            continue

        delivered = round(item_price + shipping, 2)
        key = (href.split("?")[0], item_price, shipping)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "title": title,
            "url": href,
            "item_price": item_price,
            "shipping": shipping,
            "delivered_price": delivered,
            "shipping_text": "FREE" if shipping == 0 else f"${shipping:.2f}",
            "market_state": "ACTIVE_BIN_PUBLIC_SEARCH",
            "source": "ebay_public_search",
        })

    candidates.sort(key=lambda x: (x["delivered_price"], x["item_price"]))
    return candidates


def fetch_once(product, season_override=None):
    url = search_url(product, season_override)
    try:
        response = requests.get(url, headers=HEADERS, timeout=14)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}", False

    text = response.text or ""
    low = text.lower()
    blocked = response.status_code in (403, 429, 472, 503) or any(marker in low for marker in BLOCK_MARKERS)
    if blocked:
        return [], f"blocked/limited HTTP {response.status_code}", True
    if response.status_code != 200:
        return [], f"HTTP {response.status_code}", False

    candidates = parse_search(product, text)
    return candidates, None if candidates else "no exact BIN with known shipping parsed", False


def collect_product(product):
    candidates, error, blocked = fetch_once(product)
    if blocked:
        return product["id"], [], error, True
    if candidates:
        return product["id"], candidates, None, False

    last_error = error
    for season in fallback_seasons(product):
        candidates, error, blocked = fetch_once(product, season)
        if blocked:
            return product["id"], [], error, True
        if candidates:
            return product["id"], candidates, None, False
        last_error = error
    return product["id"], [], last_error, False


def api_money(value):
    try:
        if value is None or value == "":
            return None
        return round(float(str(value).replace("$","").replace(",","")), 2)
    except Exception:
        return None


def api_active(product):
    from ebay_utils import quoted_query
    query = quoted_query(product)
    r = requests.get(
        API,
        headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
        params={
            "keyword": query,
            "ebaySite": "ebay.com",
            "count": 120,
            "sold": "false",
            "itemCondition": "new",
            "buyingFormat": "buyItNow",
            "sortOrder": "pricePlusPostageLowest",
            "itemLocation": "domestic",
        },
        timeout=100,
    )
    remaining = r.headers.get("X-Usage-Remaining")
    r.raise_for_status()
    payload = r.json()
    raw = payload.get("results") if isinstance(payload, dict) else payload
    candidates = []
    seen = set()
    exact_titles = 0
    for row in raw or []:
        title = str(row.get("title") or "")
        if not product_match(product, title)[0]:
            continue
        exact_titles += 1
        item_price = api_money(row.get("currentPrice") or row.get("soldPrice") or row.get("price") or row.get("itemPrice"))
        shipping = api_money(row.get("shippingPrice") or row.get("shipping"))
        total = api_money(row.get("totalPrice") or row.get("deliveredPrice"))
        if total is None and item_price is not None and shipping is not None:
            total = round(item_price + shipping, 2)
        if item_price is None:
            continue
        comparison_price = total if total is not None else item_price
        url = row.get("url") or row.get("itemUrl") or row.get("listingUrl")
        key = (row.get("itemId") or url, item_price, shipping, total)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "title": title,
            "url": url,
            "item_price": item_price,
            "shipping": shipping,
            "delivered_price": total,
            "comparison_price": comparison_price,
            "shipping_known": shipping is not None or total is not None,
            "shipping_text": "FREE" if shipping == 0 else (f"${shipping:.2f}" if shipping is not None else "shipping TBD"),
            "market_state": "ACTIVE_BIN_API",
            "source": "ebaysoldlistingsapi_active",
            "seller": row.get("sellerUsername"),
            "listing_id": row.get("itemId"),
            "thumbnail_url": row.get("fullResThumbnailUrl") or row.get("thumbnailUrl"),
        })
    candidates.sort(key=lambda x: (x["comparison_price"], x["item_price"]))
    print(f"ACTIVE {product['id']}: {len(raw or [])} raw / {exact_titles} exact titles / {len(candidates)} priced candidates")
    return candidates, remaining


def load_active_cache():
    if not ACTIVE_CACHE.exists():
        return {"products": {}}
    try:
        data = json.loads(ACTIVE_CACHE.read_text())
        return data if isinstance(data, dict) else {"products": {}}
    except Exception:
        return {"products": {}}

def main():
    if not MARKET.exists():
        print("No market_latest.json; skipping public eBay fallback")
        return

    products = json.loads(PRODUCTS.read_text())
    data = json.loads(MARKET.read_text())
    checked = datetime.now(timezone.utc)

    if KEY:
        cache = load_active_cache()
        cache.setdefault("products", {})
        slot = (checked.hour // 3) % 8
        selected = products if FULL_REFRESH else [product for i, product in enumerate(products) if i % 8 == slot]
        refreshed = 0
        matched_candidates = 0
        errors = 0
        remaining = None

        for product in selected:
            try:
                candidates, remaining = api_active(product)
                pid = product["id"]
                cache["products"][pid] = {"checked_at": checked.isoformat(), "candidates": candidates[:30]}
                refreshed += 1
                matched_candidates += len(candidates)
            except Exception as exc:
                errors += 1
                print(f"ACTIVE {product['id']}: ERROR {type(exc).__name__}: {exc}")

        for product in products:
            pid = product["id"]
            snap = (cache.get("products") or {}).get(pid) or {}
            ts = snap.get("checked_at")
            candidates = snap.get("candidates") or []
            try:
                age_days = (checked - datetime.fromisoformat(str(ts).replace("Z","+00:00"))).total_seconds()/86400 if ts else 999
            except Exception:
                age_days = 999
            if not candidates or age_days > 2.0:
                continue
            best = candidates[0]
            market = (data.get("products") or {}).setdefault(pid, {})
            market["status"] = "VERIFIED"
            market["best"] = best
            market["candidate_count"] = len(candidates)
            market["reason"] = "lowest exact-match active eBay BIN from authenticated active-listings API"
            market["active_source"] = "ebaysoldlistingsapi_active"
            market["public_ebay_reason"] = "authenticated active API snapshot"
            market["active_market"] = {
                "basis": "ebaysoldlistingsapi_active",
                "floor": best.get("comparison_price") or best.get("delivered_price") or best.get("item_price"),
                "snapshot_date": str(ts)[:10],
                "updated_at": ts,
                "listing_count": len(candidates),
                "stale": age_days > 1.25,
                "freshness_days": round(age_days, 2),
            }

        ACTIVE_CACHE.write_text(json.dumps(cache, indent=2) + "\n")
        text = json.dumps(data, indent=2) + "\n"
        MARKET.write_text(text)
        EBAY.write_text(text)
        mode = "full bootstrap" if FULL_REFRESH else f"slot {slot}/8"
        print(f"Authenticated active eBay {mode}: {refreshed}/{len(selected)} queried, {matched_candidates} exact BIN candidates, {errors} errors, usage remaining={remaining}")
        return

    by_id = {p["id"]: p for p in products}

    if products:
        _, probe_error, probe_blocked = fetch_once(products[0])
        if probe_blocked:
            print(f"Public eBay search unavailable from runner ({probe_error}); keeping CollectAIO data")
            return

    refreshed = 0
    parsed_candidates = 0
    blocked_count = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(collect_product, p) for p in products]
        for future in as_completed(futures):
            pid, candidates, error, blocked = future.result()
            market = (data.get("products") or {}).setdefault(pid, {})
            market["public_ebay_checked_at"] = checked.isoformat()
            if blocked:
                blocked_count += 1
                market["public_ebay_reason"] = error
                continue
            if not candidates:
                if error:
                    errors += 1
                    market["public_ebay_reason"] = error
                continue
            best = candidates[0]
            parsed_candidates += len(candidates)
            refreshed += 1
            market["status"] = "VERIFIED"
            market["best"] = best
            market["candidate_count"] = len(candidates)
            market["reason"] = "lowest exact-match active eBay BIN parsed from live public search with known shipping"
            market["active_source"] = "ebay_public_search"
            market["public_ebay_reason"] = "live exact BIN parsed"
            market["active_market"] = {"basis":"ebay_public_search","floor":best["delivered_price"],"snapshot_date":checked.date().isoformat(),"updated_at":checked.isoformat(),"listing_count":len(candidates),"stale":False,"freshness_days":0}

    text = json.dumps(data, indent=2) + "\n"
    MARKET.write_text(text)
    EBAY.write_text(text)
    print(f"Public eBay BIN fallback: {refreshed}/{len(by_id)} products refreshed, {parsed_candidates} exact active candidates, {blocked_count} blocked, {errors} without parseable exact BIN")

if __name__ == "__main__":
    main()
