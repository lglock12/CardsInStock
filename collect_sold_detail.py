import json
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from ebay_utils import quoted_query
from matching import product_match, is_plausible_sealed_listing

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
LATEST = ROOT / "data" / "sold_latest.json"
HISTORY = ROOT / "data" / "sold_history.jsonl"
API = "https://api.ebaysoldlistingsapi.com/scrape"
KEY = os.getenv("EBAY_SOLD_API_KEY", "").strip()


def now_utc():
    return datetime.now(timezone.utc)


def parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except Exception:
            return None


def number(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    text = str(value).replace("$", "").replace(",", "").strip()
    try:
        return round(float(text), 2)
    except Exception:
        return None


def pick(row, *keys):
    for key in keys:
        if row.get(key) not in (None, ""):
            return row.get(key)
    return None


def normalize_sale(product, row):
    title = str(pick(row, "title", "itemTitle", "name") or "").strip()
    if not title:
        return None

    exact = product_match(product, title)[0]
    plausible = is_plausible_sealed_listing(product, title)
    if not exact and not plausible:
        return None

    condition = str(pick(row, "condition", "conditionName") or "").lower()
    if condition and not any(x in condition for x in ["new", "brand new", "factory sealed", "sealed"]):
        return None

    price = number(pick(row, "soldPrice", "sold_price", "price", "itemPrice"))
    shipping = number(pick(row, "shippingPrice", "shipping", "shipping_cost"))
    total = number(pick(row, "totalPrice", "total", "deliveredPrice"))
    if total is None and price is not None and shipping is not None:
        total = round(price + shipping, 2)

    best_offer = bool(pick(row, "bestOfferAccepted", "best_offer_accepted"))
    buying_format = str(pick(row, "buyingFormat", "listingType", "listing_type") or "unknown").lower()
    if "best" in buying_format and "offer" in buying_format:
        best_offer = True

    sold_at = pick(row, "endedAt", "soldAt", "soldDate", "sold_date")
    dt = parse_date(sold_at)
    if not dt:
        return None

    listing_id = str(pick(row, "itemId", "listingId", "id") or "").strip()
    url = str(pick(row, "url", "itemUrl", "listingUrl") or "").strip()
    seller = pick(row, "sellerUsername", "seller", "sellerName")
    if isinstance(seller, dict):
        seller = seller.get("username") or seller.get("name")

    # Accepted Best Offer sales are still useful evidence that a sale occurred,
    # but eBay often does not reveal the actual negotiated amount. Keep them in
    # history while excluding them from price medians.
    price_usable = price is not None and not best_offer

    dedupe = listing_id or url or f"{dt.date().isoformat()}|{title}|{price}|{shipping}"
    return {
        "dedupe_key": dedupe,
        "product_id": product["id"],
        "title": title,
        "sold_at": dt.isoformat(),
        "sold_price": price,
        "shipping": shipping,
        "delivered_price": total,
        "currency": pick(row, "soldCurrency", "currency", "priceCurrency") or "USD",
        "buying_format": buying_format,
        "best_offer_accepted": best_offer,
        "price_usable": price_usable,
        "bid_count": pick(row, "bidCount", "bids"),
        "condition": pick(row, "condition", "conditionName"),
        "seller": seller,
        "url": url,
        "listing_id": listing_id,
        "source": "ebaysoldlistingsapi.com",
    }


def median(values):
    values = [float(v) for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def percentile(values, p):
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return round(vals[0], 2)
    pos = (len(vals) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(vals) - 1)
    frac = pos - lo
    return round(vals[lo] * (1 - frac) + vals[hi] * frac, 2)


def summarize(rows, checked):
    usable = [r for r in rows if r.get("price_usable") and r.get("sold_price") is not None]
    windows = {}
    for days in (7, 30, 90, 180, 365):
        cutoff = checked - timedelta(days=days)
        w = [r for r in usable if parse_date(r.get("sold_at")) and parse_date(r["sold_at"]) >= cutoff]
        prices = [r["sold_price"] for r in w]
        delivered = [r["delivered_price"] for r in w if r.get("delivered_price") is not None]
        windows[str(days)] = {
            "count": len(w),
            "median": median(prices),
            "median_delivered": median(delivered),
            "low": min(prices) if prices else None,
            "high": max(prices) if prices else None,
            "p25": percentile(prices, .25),
            "p75": percentile(prices, .75),
        }

    auction_count = sum(1 for r in usable if "auction" in str(r.get("buying_format", "")).lower())
    bin_count = sum(1 for r in usable if any(x in str(r.get("buying_format", "")).lower() for x in ["buy", "fixed"]))
    best_offer_count = sum(1 for r in rows if r.get("best_offer_accepted"))

    return {
        "matched_sales": len(rows),
        "priced_sales": len(usable),
        "best_offer_hidden_count": best_offer_count,
        "auction_count": auction_count,
        "bin_count": bin_count,
        "latest_sale_at": rows[0]["sold_at"] if rows else None,
        "windows": windows,
        "recent_sales": rows[:20],
    }


def load_history():
    rows = {}
    if not HISTORY.exists():
        return rows
    for line in HISTORY.read_text().splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        key = (row.get("product_id"), row.get("dedupe_key"))
        if all(key):
            rows[key] = row
    return rows


def request_sales(product):
    # This independent API accepts the same kind of keyword string a user would
    # type into eBay. Our quoted query keeps season/family/format tight.
    query = quoted_query(product)
    response = requests.get(
        API,
        headers={"Authorization": f"Bearer {KEY}", "Accept": "application/json"},
        params={
            "keyword": query,
            "ebaySite": "ebay.com",
            "count": 240,
            "itemCondition": "new",
            "sortOrder": "endedRecently",
        },
        timeout=100,
    )
    remaining = response.headers.get("X-Usage-Remaining")
    response.raise_for_status()
    payload = response.json()
    raw = payload.get("results") if isinstance(payload, dict) else payload
    return query, (raw or []), remaining


def main():
    if not KEY:
        print("EBAY_SOLD_API_KEY is not configured; detailed sold collection skipped cleanly.")
        return

    products = json.loads(PRODUCTS.read_text())
    history = load_history()
    checked = now_utc()
    latest = {
        "generated_at": checked.isoformat(),
        "source": "ebaysoldlistingsapi.com",
        "products": {},
    }

    new_rows = 0
    remaining = None
    for index, product in enumerate(products, start=1):
        try:
            query, raw_rows, remaining = request_sales(product)
            matched = []
            for raw in raw_rows:
                sale = normalize_sale(product, raw)
                if not sale:
                    continue
                matched.append(sale)
                key = (sale["product_id"], sale["dedupe_key"])
                if key not in history:
                    history[key] = sale
                    new_rows += 1

            # Build each product summary from our persistent local history, not
            # merely today's API response. This is how CardsInStock grows beyond
            # the provider/eBay rolling window over time.
            all_rows = [r for (pid, _), r in history.items() if pid == product["id"]]
            all_rows.sort(key=lambda r: r.get("sold_at") or "", reverse=True)
            latest["products"][product["id"]] = {
                "query": query,
                "raw_result_count": len(raw_rows),
                "matched_this_run": len(matched),
                "stats": summarize(all_rows, checked),
            }
            print(
                f"SOLD {product['id']}: {len(raw_rows)} raw / {len(matched)} matched / "
                f"{len(all_rows)} stored; usage remaining={remaining}"
            )
        except Exception as exc:
            print(f"SOLD {product['id']}: ERROR {type(exc).__name__}: {exc}")
            all_rows = [r for (pid, _), r in history.items() if pid == product["id"]]
            all_rows.sort(key=lambda r: r.get("sold_at") or "", reverse=True)
            latest["products"][product["id"]] = {
                "query": quoted_query(product),
                "error": f"{type(exc).__name__}: {exc}",
                "stats": summarize(all_rows, checked),
            }

        if remaining == "0":
            print("API monthly allowance exhausted; stopping without losing stored history.")
            break
        if index < len(products):
            time.sleep(1.05)

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(history.values(), key=lambda r: (r.get("product_id", ""), r.get("sold_at", ""), r.get("dedupe_key", "")))
    HISTORY.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in ordered))
    LATEST.write_text(json.dumps(latest, indent=2) + "\n")

    print(
        f"Detailed sold collection complete: {new_rows} new unique transactions; "
        f"{len(history)} total stored transactions."
    )


if __name__ == "__main__":
    main()
