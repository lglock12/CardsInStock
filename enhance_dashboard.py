import json
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
INDEX = ROOT / "docs" / "index.html"
PRODUCTS = ROOT / "config" / "products.json"
LATEST = ROOT / "data" / "latest.json"
MARKET = ROOT / "data" / "market_latest.json"


def money(value):
    try:
        return f"${float(value):,.2f}" if value is not None else "—"
    except (TypeError, ValueError):
        return "—"


def fragment(soup, markup):
    return BeautifulSoup(markup, "html.parser")


def market_block(soup, market):
    sold = market.get("sold_market") or {}
    if not sold:
        return None

    median_30 = sold.get("median_30d")
    count_30 = sold.get("count_30d")
    min_30 = sold.get("min_30d")
    max_30 = sold.get("max_30d")
    long_days = sold.get("long_window_days")
    long_count = sold.get("long_count")
    long_median = sold.get("long_median")
    fmv = sold.get("fmv")
    snapshot = sold.get("snapshot_date") or "unknown"
    age = sold.get("freshness_days")
    stale = bool(sold.get("stale"))
    collectaio_url = market.get("collectaio_url") or "#"

    # Never call a long-window estimate a 30-day median when there were no
    # recent sold comps. The label must describe exactly what the number is.
    if median_30 is not None and (count_30 or 0) > 0:
        headline_price = median_30
        headline_caption = f"30-day sold median · {count_30} sales"
        headline_basis = "30d"
    elif long_median is not None:
        headline_price = long_median
        window = f"{long_days}d" if long_days else "Long-window"
        comps = f" · {long_count} comps" if long_count is not None else ""
        headline_caption = f"{window} sold median{comps}"
        headline_basis = "long"
    elif fmv is not None:
        headline_price = fmv
        headline_caption = "Sold-market estimate"
        headline_basis = "estimate"
    else:
        return None

    bits = []
    if (count_30 or 0) > 0 and min_30 is not None and max_30 is not None:
        bits.append(f"30d range {money(min_30)}–{money(max_30)}")
    if headline_basis != "long" and long_days and long_median is not None:
        comp_text = f" · {long_count} comps" if long_count is not None else ""
        bits.append(f"{long_days}d median {money(long_median)}{comp_text}")
    elif headline_basis == "long" and (count_30 or 0) == 0:
        bits.append("No qualifying sales in the last 30 days")

    age_text = f" · {age}d old" if age is not None else ""
    stale_text = " · STALE SOURCE" if stale else ""
    classes = "sold-market stale" if stale else "sold-market"
    markup = f'''<div class="{classes}">
      <div class="sold-head"><span>SOLD MARKET</span><a href="{collectaio_url}" target="_blank" rel="noopener">CollectAIO ↗</a></div>
      <div class="sold-main"><div class="sold-price">{money(headline_price)}</div><div class="sold-caption">{headline_caption}</div></div>
      <div class="sold-detail">{' · '.join(bits) if bits else 'Aggregate sold-market evidence'}</div>
      <div class="sold-fresh">eBay sold snapshot {snapshot}{age_text}{stale_text}</div>
    </div>'''
    return fragment(soup, markup).div


def main():
    if not INDEX.exists() or not PRODUCTS.exists():
        print("Dashboard enhancement skipped: generated dashboard missing")
        return

    products = json.loads(PRODUCTS.read_text())
    latest = json.loads(LATEST.read_text()) if LATEST.exists() else {"observations": []}
    market_data = json.loads(MARKET.read_text()) if MARKET.exists() else {"products": {}}
    markets = market_data.get("products") or {}

    obs_by_product = {}
    for row in latest.get("observations") or []:
        obs_by_product.setdefault(row.get("product_id"), []).append(row)

    search_to_product = {
        f"{p['product']} {p['season']} {p['format']}".lower(): p for p in products
    }

    soup = BeautifulSoup(INDEX.read_text(), "html.parser")

    # Centered collector-style brand lockup with a simple stacked-card/check logo.
    header = soup.find("header")
    if header:
        header["class"] = list(dict.fromkeys((header.get("class") or []) + ["site-header"]))
        center = header.find("div", recursive=False)
        if center:
            center["class"] = list(dict.fromkeys((center.get("class") or []) + ["header-center"]))
            h1 = center.find("h1")
            if h1:
                h1.clear()
                logo = fragment(soup, '''<span class="brand-lockup"><svg class="cis-logo" viewBox="0 0 48 48" aria-hidden="true"><rect x="13" y="6" width="25" height="33" rx="6" fill="#65e6b5" opacity=".95"/><rect x="7" y="11" width="25" height="31" rx="6" fill="#101827" stroke="#f5f7fb" stroke-width="2.4"/><path d="M13 26l5 5 9-12" fill="none" stroke="#65e6b5" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/></svg><span>CardsInStock</span></span>''')
                h1.append(logo.span)

    enhanced = 0
    sold_blocks = 0
    stale_active = 0
    image_upgrades = 0
    fresh_coverage = set()

    for article in soup.select("article.format-card"):
        product = search_to_product.get(str(article.get("data-search") or "").strip())
        if not product:
            continue
        pid = product["id"]
        article["data-product-id"] = pid
        market = markets.get(pid) or {}
        observations = obs_by_product.get(pid, [])
        retail_verified = any(o.get("status") == "VERIFIED" for o in observations)
        best = market.get("best") if market.get("status") == "VERIFIED" else None
        active = market.get("active_market") or {}
        active_is_fresh = bool(best) and bool(active) and not active.get("stale")

        # Correct availability semantics: a stale eBay snapshot is useful context,
        # not proof that the product is currently buyable.
        for cls in ("available", "soldout", "unverified"):
            classes = article.get("class") or []
            if cls in classes:
                classes.remove(cls)
        statuses = [o.get("status") for o in observations]
        if retail_verified or active_is_fresh:
            article["class"].append("available")
            fresh_coverage.add(pid)
        elif statuses and all(s == "OUT_OF_STOCK" for s in statuses):
            article["class"].append("soldout")
        else:
            article["class"].append("unverified")

        # Prefer a standardized CollectAIO product image where its catalog match
        # has passed our exact SKU matcher. This also upgrades IMAGE PENDING cards.
        image = market.get("collectaio_image_url")
        visual = article.select_one(".product-visual")
        if image and visual:
            img_tag = visual.find("img", recursive=False)
            if not img_tag:
                placeholder = visual.select_one(".image-placeholder")
                img_tag = soup.new_tag("img")
                img_tag["alt"] = f"{product['product']} {product['format']}"
                img_tag["loading"] = "lazy"
                if placeholder:
                    placeholder.replace_with(img_tag)
                else:
                    visual.insert(0, img_tag)
            img_tag["src"] = image
            img_tag["data-image-source"] = "collectaio"
            image_upgrades += 1

        ebay_card = article.select_one(".ebay-card")
        if ebay_card and best:
            head_label = ebay_card.select_one(".ebay-head > span")
            if head_label:
                head_label.string = "LOWEST BIN + SHIPPING SNAPSHOT"
            if active:
                age = active.get("freshness_days")
                snapshot = active.get("snapshot_date") or "unknown"
                if active.get("stale"):
                    stale_active += 1
                    ebay_card["class"] = list(dict.fromkeys((ebay_card.get("class") or []) + ["stale"]))
                    buy = ebay_card.select_one(".ebay-buy")
                    if buy:
                        buy.string = "CHECK ↗"
                    notice = fragment(
                        soup,
                        f'<div class="snapshot-warning">STALE SNAPSHOT · eBay active data {snapshot}'
                        f'{f" · {age}d old" if age is not None else ""} · verify before buying</div>'
                    ).div
                    main_row = ebay_card.select_one(".ebay-main")
                    if main_row:
                        main_row.insert_after(notice)
                else:
                    note = fragment(
                        soup,
                        f'<div class="snapshot-fresh">Active-market snapshot {snapshot}'
                        f'{f" · {age}d old" if age is not None else ""}</div>'
                    ).div
                    main_row = ebay_card.select_one(".ebay-main")
                    if main_row:
                        main_row.insert_after(note)

        if ebay_card:
            sold = market_block(soup, market)
            if sold:
                ebay_card.insert_after(sold)
                sold_blocks += 1

        enhanced += 1

    # The builder's initial coverage count includes any eBay snapshot. Recalculate
    # after applying freshness semantics so the headline never overstates live stock.
    coverage = soup.select_one(".coverage")
    if coverage:
        coverage.clear()
        strong = soup.new_tag("b")
        strong.string = f"{len(fresh_coverage)}/{len(products)}"
        coverage.append(strong)
        coverage.append(
            f" formats currently have verified retail or fresh eBay inventory · "
            f"{len(products) - len(fresh_coverage)} coverage gaps"
        )

    style = soup.find("style")
    if style:
        style.append('''
/* CardsInStock post-build enhancements */
.site-header{position:relative!important;display:block!important;text-align:center;padding:8px 210px 2px;min-height:104px}
.header-center{max-width:820px;margin:0 auto}
.brand-lockup{display:inline-flex;align-items:center;justify-content:center;gap:10px;font-family:"Arial Black","Inter Tight",Inter,system-ui,sans-serif;font-weight:950;letter-spacing:-2.2px;font-size:40px;line-height:1}
.cis-logo{width:42px;height:42px;filter:drop-shadow(0 5px 14px rgba(101,230,181,.18))}
.site-header .subtitle{margin-top:7px;font-size:13px}
.site-header .updated{position:absolute;right:0;bottom:8px;text-align:right}
.product-visual img{image-orientation:from-image}
.ebay-card.stale{border-color:#8b6a31;background:linear-gradient(135deg,#171720,#211b12)}
.snapshot-warning{margin-top:7px;padding:6px 7px;border-radius:6px;background:#2b2213;color:#f4c86a;font-size:8px;font-weight:850;line-height:1.35}
.snapshot-fresh{margin-top:6px;color:#7fbda8;font-size:8px}
.sold-market{margin:10px 0 12px;padding:10px 11px;border:1px solid #28594d;border-radius:10px;background:linear-gradient(135deg,#101b1a,#111824)}
.sold-market.stale{border-color:#66552d}
.sold-head{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:8px;font-weight:950;letter-spacing:.1em;color:#65e6b5}
.sold-head a{color:#8fb8ff;text-decoration:none;letter-spacing:0;font-weight:800}
.sold-main{display:flex;justify-content:space-between;align-items:end;gap:8px;margin-top:6px}
.sold-price{font-size:20px;font-weight:950}
.sold-caption,.sold-detail,.sold-fresh{font-size:8px;color:#93a2b8}
.sold-caption{text-align:right}.sold-detail{margin-top:4px}.sold-fresh{margin-top:5px;padding-top:5px;border-top:1px dashed #2b3749}
.sold-market.stale .sold-fresh{color:#d5b361}
@media(max-width:650px){.site-header{padding:4px 0 0}.site-header .updated{position:static!important;text-align:center!important;margin-top:8px}.brand-lockup{font-size:33px}.cis-logo{width:36px;height:36px}}
''')

    INDEX.write_text(str(soup))
    print(
        f"Enhanced dashboard: {enhanced} product cards, {sold_blocks} sold-market blocks, "
        f"{stale_active} stale eBay warnings, {image_upgrades} standardized image upgrades, "
        f"{len(fresh_coverage)}/{len(products)} live-covered formats"
    )


if __name__ == "__main__":
    main()
