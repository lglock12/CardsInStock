import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
SOURCES = ROOT / "config" / "sources.json"
OUT = ROOT / "data" / "latest.json"
HISTORY = ROOT / "data" / "history.jsonl"

HEADERS = {
    "User-Agent": "CardsInStock/0.1 (+https://github.com/lglock12/CardsInStock; accuracy-first personal price tracker)"
}


def normalize(text):
    text = (text or "").lower().replace("/", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_jsonld(soup):
    items = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(tag.string or tag.get_text())
            if isinstance(payload, list):
                items.extend(payload)
            else:
                items.append(payload)
        except Exception:
            continue
    return items


def walk_json(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk_json(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk_json(value)


def product_match(product, title):
    title_n = normalize(title)
    required = [normalize(x) for x in product["required_terms"]]
    rejected = [normalize(x) for x in product["reject_terms"]]
    if not all(term in title_n for term in required):
        return False, "missing required product terms"
    if any(term in title_n for term in rejected):
        return False, "matched rejected format term"
    return True, "exact canonical terms matched"


def parse_page(url):
    r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    title = ""
    price = None
    currency = "USD"
    availability = "UNKNOWN"

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()
    elif soup.title:
        title = soup.title.get_text(" ", strip=True)

    for root in extract_jsonld(soup):
        for node in walk_json(root):
            if node.get("@type") == "Product" or "offers" in node:
                title = node.get("name") or title
                offers = node.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else None
                if isinstance(offers, dict):
                    raw_price = offers.get("price") or offers.get("lowPrice")
                    try:
                        price = float(str(raw_price).replace(",", "")) if raw_price is not None else price
                    except ValueError:
                        pass
                    currency = offers.get("priceCurrency") or currency
                    av = normalize(offers.get("availability", ""))
                    if "instock" in av or "in stock" in av:
                        availability = "IN_STOCK"
                    elif "outofstock" in av or "out of stock" in av or "soldout" in av:
                        availability = "OUT_OF_STOCK"

    page_text = normalize(soup.get_text(" ", strip=True))
    if availability == "UNKNOWN":
        if any(x in page_text for x in ["sold out", "out of stock", "currently unavailable", "no longer available"]):
            availability = "OUT_OF_STOCK"
        elif any(x in page_text for x in ["add to cart", "add to bag", "buy it now", "in stock"]):
            availability = "IN_STOCK"

    if price is None:
        meta_price = soup.find("meta", property="product:price:amount")
        if meta_price and meta_price.get("content"):
            try:
                price = float(meta_price["content"].replace(",", ""))
            except ValueError:
                pass

    return {
        "title": title,
        "price": price,
        "currency": currency,
        "availability": availability,
        "final_url": r.url,
        "http_status": r.status_code,
    }


def main():
    products = json.loads(PRODUCTS.read_text())
    sources = json.loads(SOURCES.read_text())
    product_by_id = {p["id"]: p for p in products}
    checked = datetime.now(timezone.utc).isoformat()
    observations = []

    for source in sources:
        product = product_by_id[source["product_id"]]
        obs = {
            "checked_at": checked,
            "product_id": product["id"],
            "seller": source["seller"],
            "url": source["url"],
            "status": "UNKNOWN",
            "price": None,
            "currency": "USD",
            "reason": "",
        }
        try:
            page = parse_page(source["url"])
            matched, reason = product_match(product, page["title"])
            obs.update({
                "title": page["title"],
                "price": page["price"],
                "currency": page["currency"],
                "availability": page["availability"],
                "final_url": page["final_url"],
                "http_status": page["http_status"],
            })
            if not matched:
                obs["status"] = "REJECTED"
                obs["reason"] = reason
            elif page["availability"] == "OUT_OF_STOCK":
                obs["status"] = "OUT_OF_STOCK"
                obs["reason"] = "exact product matched but not purchasable"
            elif page["availability"] == "IN_STOCK" and page["price"] is not None:
                obs["status"] = "VERIFIED"
                obs["reason"] = reason
            else:
                obs["status"] = "UNKNOWN"
                obs["reason"] = "could not verify both current price and purchasable stock"
        except Exception as exc:
            obs["reason"] = f"collector error: {type(exc).__name__}: {exc}"
        observations.append(obs)

    verified = [x for x in observations if x["status"] == "VERIFIED"]
    lowest = {}
    for obs in verified:
        current = lowest.get(obs["product_id"])
        if current is None or obs["price"] < current["price"]:
            lowest[obs["product_id"]] = obs

    result = {
        "generated_at": checked,
        "verified_count": len(verified),
        "observation_count": len(observations),
        "lowest_verified": lowest,
        "observations": observations,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    with HISTORY.open("a", encoding="utf-8") as f:
        for obs in observations:
            f.write(json.dumps(obs) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
