import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from collector import product_match
from ebay_utils import fallback_seasons, quoted_query, search_url

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
OUT = ROOT / "data" / "ebay_latest.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def money(text):
    if not text:
        return None
    match = re.search(r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def shipping_cost(text):
    text = (text or "").strip().lower()
    if not text:
        return None
    if "free shipping" in text or "free delivery" in text:
        return 0.0
    if "local pickup" in text and "$" not in text:
        return None
    return money(text)


def clean_title(title):
    title = re.sub(r"^New Listing\s*", "", title or "", flags=re.I)
    title = re.sub(r"^Sponsored\s*", "", title, flags=re.I)
    return " ".join(title.split())


def cards_from_page(soup):
    # eBay has used both s-item and s-card markup. Support both so a front-end
    # class rename does not immediately kill the comparison.
    cards = soup.select("li.s-item")
    if not cards:
        cards = soup.select("li.s-card, div.s-card")
    return cards[:80]


def parse_candidates(product, response):
    lower = response.text[:150000].lower()
    if any(marker in lower for marker in ["pardon our interruption", "verify yourself", "captcha", "robot check"]):
        raise RuntimeError("eBay bot/interstitial detected")

    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []
    for card in cards_from_page(soup):
        title_el = card.select_one(".s-item__title, .s-card__title")
        link_el = card.select_one("a.s-item__link, a.s-card__link")
        price_el = card.select_one(".s-item__price, .s-card__price")
        shipping_el = card.select_one(".s-item__shipping, .s-item__logisticsCost, .s-card__shipping, .s-card__delivery")
        if not title_el or not link_el or not price_el:
            continue

        title = clean_title(title_el.get_text(" ", strip=True))
        href = link_el.get("href") or ""
        if not title or "/itm/" not in href:
            continue

        card_text = card.get_text(" ", strip=True).lower()
        if "bid" in card_text and "buy it now" not in card_text:
            continue

        matched, _ = product_match(product, title)
        if not matched:
            continue

        price = money(price_el.get_text(" ", strip=True))
        shipping_text = shipping_el.get_text(" ", strip=True) if shipping_el else ""
        shipping = shipping_cost(shipping_text)
        if price is None or shipping is None:
            # We only showcase eBay when the delivered comparison is known.
            continue

        direct = href.split("?")[0]
        candidates.append({
            "title": title,
            "url": direct,
            "item_price": round(price, 2),
            "shipping": round(shipping, 2),
            "delivered_price": round(price + shipping, 2),
            "shipping_text": shipping_text,
        })
    return candidates


def fetch_search(product, season_override=None):
    url = search_url(product, season_override)
    response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
    response.raise_for_status()
    return url, parse_candidates(product, response)


def collect_one(product):
    attempts = [(None, quoted_query(product))]
    attempts.extend((alias, quoted_query(product, alias)) for alias in fallback_seasons(product))
    errors = []

    for season_override, query in attempts:
        try:
            url, candidates = fetch_search(product, season_override)
            if candidates:
                candidates.sort(key=lambda x: (x["delivered_price"], x["item_price"]))
                return {
                    "status": "VERIFIED",
                    "query": query,
                    "search_url": url,
                    "candidate_count": len(candidates),
                    "best": candidates[0],
                    "reason": "lowest matching Buy It Now listing with known listed shipping",
                }
            errors.append(f"{query}: no matched BIN with known shipping")
        except Exception as exc:
            errors.append(f"{query}: {type(exc).__name__}: {exc}")
            # A bot wall on the primary search is likely to affect aliases too.
            if "interstitial" in str(exc).lower() or isinstance(exc, requests.HTTPError):
                break
        time.sleep(0.25)

    return {
        "status": "UNAVAILABLE",
        "query": quoted_query(product),
        "search_url": search_url(product),
        "candidate_count": 0,
        "best": None,
        "reason": " | ".join(errors[-3:]) or "no matching BIN found",
    }


def main():
    products = json.loads(PRODUCTS.read_text())
    checked = datetime.now(timezone.utc).isoformat()
    result = {"generated_at": checked, "products": {}}
    verified = 0

    for index, product in enumerate(products, start=1):
        market = collect_one(product)
        result["products"][product["id"]] = market
        if market["status"] == "VERIFIED":
            verified += 1
            best = market["best"]
            print(f"EBAY {product['id']}: ${best['delivered_price']:.2f} delivered ({best['item_price']:.2f} + {best['shipping']:.2f})")
        else:
            print(f"EBAY {product['id']}: unavailable")
        if index < len(products):
            time.sleep(0.35)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n")
    print(f"eBay BIN collection complete: {verified}/{len(products)} products with a verified delivered BIN")


if __name__ == "__main__":
    main()
