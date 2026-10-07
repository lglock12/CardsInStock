import json
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
LATEST = ROOT / "data" / "latest.json"
MARKET = ROOT / "data" / "market_latest.json"
SOLD = ROOT / "data" / "sold_latest.json"
PRODUCTS = ROOT / "config" / "products.json"
ASSETS = ROOT / "docs" / "assets" / "products"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CardsInStock/1.0; +https://github.com/lglock12/CardsInStock)",
    "Accept-Language": "en-US,en;q=0.9",
}

def image_from(url):
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for selector, attr in [
            ('meta[property="og:image"]', "content"),
            ('meta[name="twitter:image"]', "content"),
            ('meta[property="twitter:image"]', "content"),
        ]:
            tag = soup.select_one(selector)
            if tag and tag.get(attr):
                return urljoin(r.url, tag.get(attr).strip())
    except Exception:
        pass
    return None

def existing_local(pid):
    for ext in ("jpg", "jpeg", "png", "webp"):
        path = ASSETS / f"{pid}.{ext}"
        if path.exists() and path.stat().st_size > 1000:
            return f"assets/products/{path.name}"
    return None

def download_image(url, pid):
    if not url:
        return None
    try:
        r = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "").lower()
        if "png" in ctype:
            ext = "png"
        elif "webp" in ctype:
            ext = "webp"
        else:
            ext = "jpg"
        if len(r.content) < 1000:
            return None
        ASSETS.mkdir(parents=True, exist_ok=True)
        for old in ASSETS.glob(f"{pid}.*"):
            try:
                old.unlink()
            except Exception:
                pass
        path = ASSETS / f"{pid}.{ext}"
        path.write_bytes(r.content)
        return f"assets/products/{path.name}"
    except Exception:
        return None

def main():
    if not LATEST.exists() or not PRODUCTS.exists():
        return

    data = json.loads(LATEST.read_text())
    market = json.loads(MARKET.read_text()) if MARKET.exists() else {"products": {}}
    sold = json.loads(SOLD.read_text()) if SOLD.exists() else {"products": {}}
    products = json.loads(PRODUCTS.read_text())
    observations = data.get("observations", [])

    by_product = {}
    for o in observations:
        if o.get("status") == "VERIFIED":
            by_product.setdefault(o["product_id"], []).append(o)

    images = {}
    downloaded = 0
    reused = 0

    for product in products:
        pid = product["id"]
        local = existing_local(pid)
        if local:
            images[pid] = local
            reused += 1
            continue

        candidates = []
        m = (market.get("products") or {}).get(pid) or {}
        best = m.get("best") or {}
        if best.get("thumbnail_url"):
            candidates.append(best.get("thumbnail_url"))
        if m.get("collectaio_image_url"):
            candidates.append(m.get("collectaio_image_url"))

        s = (sold.get("products") or {}).get(pid) or {}
        recent = ((s.get("stats") or {}).get("recent_sales") or [])
        for sale in recent[:5]:
            if sale.get("thumbnail_url"):
                candidates.append(sale.get("thumbnail_url"))

        for o in by_product.get(pid, []):
            img = image_from(o.get("final_url") or o.get("url"))
            if img:
                candidates.append(img)

        seen = set()
        for url in candidates:
            if not url or url in seen:
                continue
            seen.add(url)
            local = download_image(url, pid)
            if local:
                images[pid] = local
                downloaded += 1
                break

    data["product_images"] = images
    LATEST.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Image cache: {len(images)}/{len(products)} products populated ({downloaded} new, {reused} reused)")

if __name__ == "__main__":
    main()
