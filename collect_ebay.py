import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from collector import product_match
from ebay_utils import canonical_terms, fallback_seasons, quoted_query, search_url

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
OUT = ROOT / "data" / "ebay_latest.json"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


def unavailable(product, reason):
    return {
        "status": "UNAVAILABLE",
        "query": quoted_query(product),
        "search_url": search_url(product),
        "candidate_count": 0,
        "best": None,
        "reason": reason,
    }


def access_token(client_id, client_secret):
    response = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": SCOPE},
        timeout=15,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("eBay OAuth response did not contain an access token")
    return token


def api_query(product, season_override=None):
    terms = canonical_terms(product)
    if season_override:
        terms[0] = season_override
    # Browse API keyword search does not need the quote syntax used by the human
    # search page. Exact SKU validation happens again against every returned title.
    return " ".join(terms)


def shipping_cost(item):
    options = item.get("shippingOptions") or []
    costs = []
    for option in options:
        shipping_type = str(option.get("shippingCostType") or "").upper()
        if "PICKUP" in shipping_type:
            continue
        cost = option.get("shippingCost") or {}
        if cost.get("currency") != "USD" or cost.get("value") is None:
            continue
        try:
            costs.append(float(cost["value"]))
        except (TypeError, ValueError):
            continue
    return min(costs) if costs else None


def parse_candidates(product, payload):
    candidates = []
    for item in payload.get("itemSummaries") or []:
        title = item.get("title") or ""
        matched, _ = product_match(product, title)
        if not matched:
            continue

        buying = {str(x).upper() for x in item.get("buyingOptions") or []}
        if "FIXED_PRICE" not in buying:
            continue

        price_obj = item.get("price") or {}
        if price_obj.get("currency") != "USD" or price_obj.get("value") is None:
            continue
        try:
            price = float(price_obj["value"])
        except (TypeError, ValueError):
            continue

        shipping = shipping_cost(item)
        if shipping is None:
            # Do not show a delivered comparison unless eBay gives us a concrete
            # shipping amount. We never assume that an omitted cost means free.
            continue

        url = item.get("itemWebUrl") or item.get("itemHref")
        if not url:
            continue

        candidates.append({
            "title": title,
            "url": url,
            "item_id": item.get("itemId"),
            "item_price": round(price, 2),
            "shipping": round(shipping, 2),
            "delivered_price": round(price + shipping, 2),
            "shipping_text": "FREE" if shipping == 0 else f"${shipping:.2f}",
        })
    return candidates


def browse(token, product, season_override=None):
    response = requests.get(
        SEARCH_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            "Accept": "application/json",
        },
        params={
            "q": api_query(product, season_override),
            "filter": "buyingOptions:{FIXED_PRICE},conditions:{NEW}",
            "sort": "price",
            "limit": "50",
        },
        timeout=20,
    )
    response.raise_for_status()
    return parse_candidates(product, response.json())


def collect_one(token, product):
    attempts = [(None, quoted_query(product))]
    attempts.extend((alias, quoted_query(product, alias)) for alias in fallback_seasons(product))
    errors = []

    for season_override, display_query in attempts:
        try:
            candidates = browse(token, product, season_override)
            if candidates:
                candidates.sort(key=lambda x: (x["delivered_price"], x["item_price"]))
                return {
                    "status": "VERIFIED",
                    "query": display_query,
                    "search_url": search_url(product),
                    "candidate_count": len(candidates),
                    "best": candidates[0],
                    "reason": "lowest exact-match fixed-price eBay listing with API-reported shipping",
                    "source": "ebay_browse_api",
                }
            errors.append(f"{display_query}: no exact BIN with known shipping")
        except Exception as exc:
            errors.append(f"{display_query}: {type(exc).__name__}: {exc}")
            if isinstance(exc, requests.HTTPError):
                break
        time.sleep(0.15)

    return unavailable(product, " | ".join(errors[-3:]) or "no matching BIN found")


def main():
    products = json.loads(PRODUCTS.read_text())
    checked = datetime.now(timezone.utc).isoformat()
    result = {"generated_at": checked, "source": "ebay_browse_api", "products": {}}
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        reason = "eBay Browse API credentials are not configured"
        for product in products:
            result["products"][product["id"]] = unavailable(product, reason)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, indent=2) + "\n")
        print(f"eBay BIN collection skipped: {reason}")
        return

    try:
        token = access_token(client_id, client_secret)
    except Exception as exc:
        reason = f"eBay OAuth unavailable: {type(exc).__name__}: {exc}"
        for product in products:
            result["products"][product["id"]] = unavailable(product, reason)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, indent=2) + "\n")
        print(reason)
        return

    verified = 0
    for index, product in enumerate(products, start=1):
        market = collect_one(token, product)
        result["products"][product["id"]] = market
        if market["status"] == "VERIFIED":
            verified += 1
            best = market["best"]
            print(
                f"EBAY {product['id']}: ${best['delivered_price']:.2f} delivered "
                f"(${best['item_price']:.2f} + ${best['shipping']:.2f})"
            )
        else:
            print(f"EBAY {product['id']}: unavailable")
        if index < len(products):
            time.sleep(0.2)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"eBay BIN collection complete: {verified}/{len(products)} products with a verified delivered BIN")


if __name__ == "__main__":
    main()
