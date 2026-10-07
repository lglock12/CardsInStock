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
OFFICIAL_OP_PAGES = {
    "OP-01": "https://en.onepiece-cardgame.com/products/boosters/op01.php",
    "OP-02": "https://en.onepiece-cardgame.com/products/boosters/op02.php",
    "OP-03": "https://en.onepiece-cardgame.com/products/boosters/op03.php",
    "OP-04": "https://en.onepiece-cardgame.com/products/boosters/op04.php",
    "OP-05": "https://en.onepiece-cardgame.com/products/boosters/op05/",
    "OP-06": "https://en.onepiece-cardgame.com/products/boosters/op06.php",
    "OP-07": "https://en.onepiece-cardgame.com/products/boosters/op07.php",
    "OP-08": "https://en.onepiece-cardgame.com/products/boosters/op08.php",
    "OP-09": "https://en.onepiece-cardgame.com/products/boosters/op09/",
    "OP-10": "https://en.onepiece-cardgame.com/products/boosters/op10.php",
    "OP-11": "https://en.onepiece-cardgame.com/products/boosters/op11.php",
    "OP-12": "https://en.onepiece-cardgame.com/products/boosters/op12.php",
    "OP-13": "https://en.onepiece-cardgame.com/products/boosters/op13/",
    "OP-14": "https://en.onepiece-cardgame.com/products/boosters/op14-eb04.php",
    "OP-15": "https://en.onepiece-cardgame.com/products/boosters/op15-eb04.php",
    "OP-16": "https://en.onepiece-cardgame.com/products/op16.html",
    "OP-17": "https://en.onepiece-cardgame.com/products/boosters/op17/",
    "EB-01": "https://en.onepiece-cardgame.com/products/boosters/eb01.php",
    "EB-02": "https://en.onepiece-cardgame.com/products/boosters/eb02.php",
    "EB-03": "https://en.onepiece-cardgame.com/products/boosters/eb03.php",
    "PRB-01": "https://en.onepiece-cardgame.com/products/boosters/prb01.php",
    "PRB-02": "https://en.onepiece-cardgame.com/products/boosters/prb02.php",
}

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



def slugify(text):
    text = str(text or "").lower().replace("’", "").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def gamenerdz_urls(product):
    code = str(product.get("season") or "").lower()
    name = slugify(product.get("product"))
    base = "https://www.gamenerdz.com/"
    if code.startswith("eb-"):
        forms = [
            f"one-piece-tcg-{name}-extra-booster-box-{code}",
            f"one-piece-tcg-{name}-booster-box-{code}",
        ]
    elif code.startswith("prb-"):
        forms = [
            f"one-piece-tcg-{name}-premium-booster-box-{code}",
            f"one-piece-tcg-{name}-booster-box-{code}",
        ]
    else:
        forms = [f"one-piece-tcg-{name}-booster-box-{code}"]
    return [base + x for x in forms]


def trusted_retailer_box_image(product):
    code = str(product.get("season") or "").lower()
    for page_url in gamenerdz_urls(product):
        try:
            r = requests.get(page_url, headers=HEADERS, timeout=20, allow_redirects=True)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
            body_title = " ".join(x.get_text(" ", strip=True) for x in soup.select("h1")[:2]).lower()
            check = title + " " + body_title
            if "booster box" not in check or code.replace("-", "") not in check.replace("-", ""):
                continue
            for selector, attr in [
                ('meta[property="og:image"]', "content"),
                ('meta[name="twitter:image"]', "content"),
            ]:
                tag = soup.select_one(selector)
                if tag and tag.get(attr):
                    return page_url, urljoin(r.url, tag.get(attr).strip())
        except Exception:
            continue
    return None, None


def official_one_piece_package_image(page_url, code):
    """English official packaging fallback when no display-box photo is available."""
    if not page_url:
        return None
    try:
        r = requests.get(page_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        scored = []
        for img in soup.find_all("img"):
            url = img_url(img, r.url)
            if not url:
                continue
            alt = (img.get("alt") or "").lower()
            low = url.lower()
            score = 0
            if "product packaging image" in alt:
                score += 100
            if "booster pack" in alt or "booster" in alt:
                score += 40
            if code.replace("-", "").lower() in (alt + low).replace("-", ""):
                score += 30
            if "mv_01" in low:
                score += 20
            if score:
                scored.append((score, url))
        return max(scored)[1] if scored else None
    except Exception:
        return None


def source_marker(pid):
    return ASSETS / f"{pid}.source.txt"


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
    return source_marker(pid)


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
    official_pages = OFFICIAL_OP_PAGES

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
            source_page, trusted_url = trusted_retailer_box_image(product)
            page_url = official_pages.get(code)
            official_box_url = official_one_piece_box_image(page_url, code)
            official_pack_url = official_one_piece_package_image(page_url, code)

            chosen_url = trusted_url or official_box_url or official_pack_url
            chosen_page = source_page or page_url
            if chosen_url:
                local = download_image(chosen_url, pid)
                if local:
                    marker.parent.mkdir(parents=True, exist_ok=True)
                    marker.write_text((chosen_page or "") + "\n" + chosen_url + "\n")
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
    print(f"Image cache: {len(images)}/{len(products)} products populated ({downloaded} new, {reused} reused); {official_count} One Piece trusted English images")

if __name__ == "__main__":
    main()
