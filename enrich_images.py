import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
LATEST = ROOT / "data" / "latest.json"
MARKET = ROOT / "data" / "market_latest.json"
SOLD = ROOT / "data" / "sold_latest.json"
PRODUCTS = ROOT / "config" / "products.json"
ACTIVE_CACHE = ROOT / "data" / "active_ebay_cache.json"
ASSETS = ROOT / "docs" / "assets" / "products"
OFFICIAL_OP_PRODUCTS = "https://en.onepiece-cardgame.com/products/?subcategory=boosters"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; CardsInStock/1.0; +https://github.com/lglock12/CardsInStock)",
    "Accept-Language": "en-US,en;q=0.9",
}


def code_key(text):
    raw = str(text or "").upper().replace("–", "-").replace("—", "-")
    for kind in ("PRB", "OP", "EB"):
        m = re.search(rf"\\b{kind}\\s*-?\\s*(\\d{{1,2}})\\b", raw)
        if m:
            return f"{kind}-{int(m.group(1)):02d}"
    return None


def official_one_piece_pages():
    pages = {}
    for page in (1, 2, 3):
        url = OFFICIAL_OP_PRODUCTS if page == 1 else f"{OFFICIAL_OP_PRODUCTS}&page={page}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=25)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                key = code_key(a.get_text(" ", strip=True))
                href = a.get("href")
                resolved = urljoin(r.url, href) if href else None
                if key and resolved and "/products/" in resolved:
                    pages[key] = resolved
        except Exception as exc:
            print(f"Official One Piece catalog page {page} failed: {type(exc).__name__}: {exc}")
    return pages


def img_url(tag, base_url):
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        value = tag.get(attr)
        if value:
            return urljoin(base_url, str(value).strip())
    srcset = tag.get("srcset") or tag.get("data-srcset")
    if srcset:
        value = str(srcset).split(",")[-1].strip().split(" ")[0]
        if value:
            return urljoin(base_url, value)
    return None


def official_one_piece_box_image(page_url, code):
    if not page_url:
        return None
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        packaging = []
        all_candidates = []
        for img in soup.find_all("img"):
            url = img_url(img, r.url)
            if not url:
                continue
            alt = (img.get("alt") or "").lower()
            low_url = url.lower()
            score = 0
            if "product packaging image" in alt:
                score += 100
            if "booster" in alt:
                score += 25
            if code.replace("-", "").lower() in (alt + low_url).replace("-", ""):
                score += 20
            if any(x in low_url for x in ("img_item02", "item02", "item_02", "box", "display")):
                score += 80
            if any(x in low_url for x in ("img_item01", "item01", "item_01")):
                score -= 10
            if score > 0:
                all_candidates.append((score, url, alt))
                if "product packaging image" in alt:
                    packaging.append((score, url, alt))

        # Official pages commonly expose pack as item01 and display box as item02.
        # Prefer item02/display/box; otherwise use the second packaging image.
        pool = packaging or all_candidates
        for _, url, _ in sorted(pool, reverse=True):
            low = url.lower()
            if any(x in low for x in ("img_item02", "item02", "item_02", "box", "display")):
                return url
        unique = []
        for _, url, _ in pool:
            if url not in unique:
                unique.append(url)
        if len(unique) >= 2:
            return unique[1]
        return unique[0] if unique else None
    except Exception as exc:
        print(f"Official One Piece image failed {code}: {type(exc).__name__}: {exc}")
        return None


def official_marker(pid):
    return ASSETS / f"{pid}.official.txt"


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
    active_cache = json.loads(ACTIVE_CACHE.read_text()) if ACTIVE_CACHE.exists() else {"products": {}}
    observations = data.get("observations", [])
    official_pages = official_one_piece_pages() if any(p.get("category") == "one-piece" for p in products) else {}

    by_product = {}
    for o in observations:
        by_product.setdefault(o.get("product_id"), []).append(o)

    images = {}
    downloaded = 0
    reused = 0

    official_count = 0
    for product in products:
        pid = product["id"]

        if product.get("category") == "one-piece":
            marker = official_marker(pid)
            local = existing_local(pid)
            if local and marker.exists():
                images[pid] = local
                reused += 1
                official_count += 1
                continue

            code = product.get("season")
            page_url = official_pages.get(code)
            official_url = official_one_piece_box_image(page_url, code)
            if official_url:
                local = download_image(official_url, pid)
                if local:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text(page_url + "\n" + official_url + "\n")
                    images[pid] = local
                    downloaded += 1
                    official_count += 1
                    continue

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

        snap = (active_cache.get("products") or {}).get(pid) or {}
        for row in (snap.get("candidates") or [])[:5]:
            if row.get("thumbnail_url"):
                candidates.append(row.get("thumbnail_url"))

        s = (sold.get("products") or {}).get(pid) or {}
        recent = ((s.get("stats") or {}).get("recent_sales") or [])
        for sale in recent[:5]:
            if sale.get("thumbnail_url"):
                candidates.append(sale.get("thumbnail_url"))

        # Product-page images are useful even if the listing is currently OOS.
        # Once downloaded, the site uses the local copy and no longer depends on it.
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
    print(f"Image cache: {len(images)}/{len(products)} products populated ({downloaded} new, {reused} reused); {official_count} One Piece official English images")

if __name__ == "__main__":
    main()
