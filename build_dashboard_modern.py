import html
import json
from pathlib import Path

from ebay_utils import search_url
from matching import is_plausible_sealed_listing

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
DETAILS = ROOT / "config" / "product_details.json"
DETAILS_EXTRA = ROOT / "config" / "product_details_extra.json"
LATEST = ROOT / "data" / "latest.json"
MARKET = ROOT / "data" / "market_latest.json"
SOLD_DETAIL = ROOT / "data" / "sold_latest.json"
INDEX = ROOT / "docs" / "index.html"


def load_json(path, fallback):
    try:
        return json.loads(path.read_text()) if path.exists() else fallback
    except Exception:
        return fallback


def esc(value):
    return html.escape(str(value or ""), quote=True)


def money(value):
    try:
        return f"${float(value):,.2f}" if value is not None else "—"
    except (TypeError, ValueError):
        return "—"


def short_product(name):
    return str(name).replace("Topps ", "", 1).replace(" Club Competitions", "")


def format_label(value):
    return {
        "Blaster / Value": "VALUE / BLASTER",
        "Hobby": "HOBBY BOX",
        "Hobby Jumbo": "JUMBO HOBBY",
        "Mega": "MEGA BOX",
        "Mega Tin": "MEGA TIN",
        "Tin": "TIN",
        "Full Box": "DISPLAY BOX",
        "Box": "BOX",
        "Delight": "BREAKER'S DELIGHT",
        "Sapphire": "SAPPHIRE",
    }.get(value, str(value).upper())


def listing_url(row):
    return row.get("final_url") or row.get("url") or "#"


def retail_rank(row):
    delivered = row.get("delivered_price")
    price = row.get("price")
    return (0, delivered) if delivered is not None else (1, price if price is not None else 10**12)


def lead_rows(product, rows):
    """Only show CHECK leads that still look like the correct sealed SKU."""
    out = []
    for row in rows:
        if row.get("status") in ("VERIFIED", "OUT_OF_STOCK"):
            continue
        if row.get("price") is None:
            continue
        title = row.get("title") or ""
        if not is_plausible_sealed_listing(product, title):
            continue
        out.append(row)
    out.sort(key=lambda r: float(r.get("price") or 10**12))
    return out


def sold_view(market, detailed=None):
    detailed = detailed or {}
    stats = detailed.get("stats") or {}
    windows = stats.get("windows") or {}
    d30 = windows.get("30") or {}
    d90 = windows.get("90") or {}
    if d30.get("count") and d30.get("median") is not None:
        return d30.get("median"), "30D SOLD", f"{d30.get('count')} sales", {
            "source": "detailed",
            "stats": stats,
            "window": d30,
        }
    if d90.get("count") and d90.get("median") is not None:
        return d90.get("median"), "90D SOLD", f"{d90.get('count')} sales", {
            "source": "detailed",
            "stats": stats,
            "window": d90,
        }

    sold = market.get("sold_market") or {}
    c30 = sold.get("count_30d") or 0
    if c30 and sold.get("median_30d") is not None:
        return sold.get("median_30d"), "30D SOLD", f"{c30} sales", sold
    if sold.get("long_median") is not None:
        count = sold.get("long_count")
        days = sold.get("long_window_days") or 390
        return sold.get("long_median"), f"{days}D SOLD", f"{count} comps" if count is not None else "market comp", sold
    if sold.get("fmv") is not None:
        return sold.get("fmv"), "SOLD FMV", "aggregate", sold
    return None, "SOLD HISTORY", "no sold data", sold


def config_text(detail):
    packs = detail.get("packs_per_box")
    cards = detail.get("cards_per_pack")
    if packs and cards:
        return f"{packs} packs × {cards} cards"
    if packs:
        return f"{packs} packs / box"
    return "Configuration being sourced"


def facts_html(detail, cost_per_pack):
    packs = detail.get("packs_per_box")
    cards = detail.get("cards_per_pack")
    facts = []
    if packs:
        facts.append((str(packs), "PACKS"))
    if cards:
        facts.append((str(cards), "CARDS / PACK"))
    if cost_per_pack is not None:
        facts.append((money(cost_per_pack), "COST / PACK"))
    if packs and cards:
        facts.append((str(int(packs) * int(cards)), "CARDS / BOX"))
    return "".join(
        f'<div class="fact"><b>{esc(value)}</b><span>{esc(label)}</span></div>'
        for value, label in facts
    )


def sold_trend(stats):
    windows = (stats or {}).get("windows") or {}
    w30 = windows.get("30") or {}
    prior = (stats or {}).get("prior_31_90") or {}
    m30 = w30.get("median")
    mprior = prior.get("median")
    if (
        m30 is None or mprior in (None, 0)
        or (w30.get("count") or 0) < 2
        or (prior.get("count") or 0) < 2
    ):
        return None
    return round((float(m30) / float(mprior) - 1) * 100, 1)

def liquidity_snapshot(rows, market, detailed_sold):
    """Keep the dashboard focused on products with both supply and real sales."""
    verified_count = sum(1 for r in rows if r.get("status") == "VERIFIED")
    active = market.get("active_market") or {}
    fresh_ebay = bool(market.get("best")) and bool(active) and not active.get("stale")
    supply_count = verified_count + (1 if fresh_ebay else 0)

    stats = (detailed_sold or {}).get("stats") or {}
    windows = stats.get("windows") or {}
    sold_90 = int((windows.get("90") or {}).get("count") or 0)

    fallback = market.get("sold_market") or {}
    if sold_90 == 0:
        sold_90 = int(fallback.get("count_30d") or fallback.get("long_count") or 0)

    # User preference: skip thin/dead products. Require at least one current
    # source plus three validated sold comps so displayed pricing is actionable.
    return supply_count, sold_90, supply_count >= 1 and sold_90 >= 3


def product_card(product, rows, detail, market, image, detailed_sold=None):
    verified = sorted([r for r in rows if r.get("status") == "VERIFIED"], key=retail_rank)
    best_retail = verified[0] if verified else None
    leads = lead_rows(product, rows)
    best_lead = leads[0] if leads else None

    active = market.get("active_market") or {}
    ebay_best = market.get("best") if market.get("status") == "VERIFIED" else None
    ebay_fresh = bool(ebay_best) and bool(active) and not active.get("stale")
    ebay_stale = bool(ebay_best) and bool(active) and bool(active.get("stale"))
    sold_price, sold_label, sold_meta, sold = sold_view(market, detailed_sold)

    statuses = [r.get("status") for r in rows]
    explicit_soldout = bool(statuses) and all(s == "OUT_OF_STOCK" for s in statuses)
    if best_retail or ebay_fresh:
        state = "live"
    elif best_lead:
        state = "lead"
    elif sold_price is not None:
        state = "market"
    elif explicit_soldout:
        state = "soldout"
    else:
        state = "unknown"

    state_label = {
        "live": "LIVE",
        "lead": "CHECK",
        "market": "MARKET ONLY",
        "soldout": "OOS",
        "unknown": "TRACKING",
    }[state]

    img = market.get("collectaio_image_url") or image
    if img:
        visual = f'<img src="{esc(img)}" alt="{esc(product["product"])}" loading="lazy">'
    else:
        visual = '<div class="ph"><div class="box-glyph">▰</div><small>IMAGE<br>PENDING</small></div>'

    retail_compare = None
    cost_per_pack = None
    if best_retail:
        retail_price = best_retail.get("delivered_price") if best_retail.get("delivered_price") is not None else best_retail.get("price")
        if best_retail.get("delivered_price") is not None:
            retail_sub = "delivered"
            retail_compare = retail_price
        elif best_retail.get("shipping") == 0:
            retail_sub = "free shipping"
            retail_compare = retail_price
        else:
            retail_sub = "shipping TBD"
        cost_per_pack = best_retail.get("cost_per_pack")
        if cost_per_pack is None and detail.get("packs_per_box") and retail_price is not None:
            cost_per_pack = round(float(retail_price) / float(detail["packs_per_box"]), 2)
        retail_html = f'''<a class="retail-primary" href="{esc(listing_url(best_retail))}" target="_blank" rel="noopener">
          <div><span class="eyebrow">BEST VERIFIED RETAIL</span><b class="retail-price">{money(retail_price)}</b></div>
          <div class="retail-meta"><strong>{esc(best_retail.get('seller'))}</strong><span>{esc(retail_sub)} · open listing ↗</span></div>
        </a>'''
    else:
        retail_html = '''<div class="retail-primary empty-price">
          <div><span class="eyebrow">BEST VERIFIED RETAIL</span><b class="retail-price">—</b></div>
          <div class="retail-meta"><strong>No verified stock</strong><span>Sources are still being checked</span></div>
        </div>'''

    ebay_compare = None
    if ebay_best:
        ebay_price = ebay_best.get("delivered_price")
        age = active.get("freshness_days")
        if ebay_fresh:
            ebay_compare = ebay_price
            ebay_title = "EBAY BIN"
            ebay_note = "fresh delivered snapshot"
        else:
            ebay_title = "LAST EBAY SNAPSHOT"
            ebay_note = f"{age}d old · verify first" if age is not None else "stale · verify first"
        ebay_html = f'''<a class="market-mini {'fresh' if ebay_fresh else 'stale'}" href="{esc(ebay_best.get('url') or search_url(product))}" target="_blank" rel="noopener">
          <span>{esc(ebay_title)}</span><b>{money(ebay_price)}</b><small>{esc(ebay_note)} ↗</small></a>'''
    else:
        ebay_html = f'''<a class="market-mini empty-market" href="{esc(search_url(product))}" target="_blank" rel="noopener">
          <span>EBAY BIN</span><b>SEARCH LIVE ↗</b><small>live price feed unavailable</small></a>'''

    if sold_price is not None:
        if sold.get("source") == "detailed":
            detail_stats = sold.get("stats") or {}
            trend = sold_trend(detail_stats)
            sold_note = sold_meta + " · individual eBay comps"
            if trend is not None:
                sold_note += f" · {trend:+.1f}% vs prior"
        else:
            sold_age = sold.get("freshness_days") if sold else None
            sold_note = sold_meta + (f" · {sold_age}d old" if sold_age is not None else "")
        sold_html = f'''<div class="market-mini sold"><span>{esc(sold_label)}</span><b>{money(sold_price)}</b><small>{esc(sold_note)}</small></div>'''
    else:
        sold_html = '''<div class="market-mini empty-market"><span>SOLD HISTORY</span><b>NO DATA</b><small>validated sold comps unavailable</small></div>'''

    live_values = [("retail", retail_compare), ("ebay", ebay_compare)]
    live_values = [(k, v) for k, v in live_values if v is not None]
    winner = min(live_values, key=lambda x: x[1])[0] if live_values else None
    if winner == "retail":
        retail_html = retail_html.replace('class="retail-primary"', 'class="retail-primary winner"', 1)
    elif winner == "ebay":
        ebay_html = ebay_html.replace('class="market-mini fresh"', 'class="market-mini fresh winner"', 1)

    lead_html = ""
    if best_lead:
        lead_price = best_lead.get("price")
        current_price = best_retail.get("price") if best_retail else None
        if current_price is None or lead_price < current_price:
            lead_html = f'''<a class="lead-line" href="{esc(listing_url(best_lead))}" target="_blank" rel="noopener">
              <span>UNVERIFIED RETAILER LEAD</span><b>{money(lead_price)}</b><em>{esc(best_lead.get('seller'))} · check listing ↗</em></a>'''

    guarantees = detail.get("guarantees") or []
    chases = detail.get("possible_hits") or []
    hits_items = "".join(f"<li>{esc(x)}</li>" for x in guarantees)
    chase_items = "".join(f"<li>{esc(x)}</li>" for x in chases)
    official = detail.get("checklist_url") or detail.get("official_product_url") or detail.get("reference_url")
    details_link = f'<a class="detail-link" href="{esc(official)}" target="_blank" rel="noopener">Official / checklist ↗</a>' if official else ""

    source_rows = []
    order = {"VERIFIED": 0, "UNKNOWN": 1, "REJECTED": 2, "OUT_OF_STOCK": 3}
    for row in sorted(rows, key=lambda r: (order.get(r.get("status"), 9), r.get("price") is None, r.get("price") or 10**12)):
        status = row.get("status") or "UNKNOWN"
        if status not in ("VERIFIED", "OUT_OF_STOCK") and row.get("price") is not None:
            if not is_plausible_sealed_listing(product, row.get("title") or ""):
                continue
        label = {"VERIFIED": "LIVE", "OUT_OF_STOCK": "OOS", "REJECTED": "CHECK", "UNKNOWN": "CHECK"}.get(status, "CHECK")
        cls = status.lower()
        p = row.get("delivered_price") if row.get("delivered_price") is not None else row.get("price")
        source_rows.append(f'''<a class="source-row {cls}" href="{esc(listing_url(row))}" target="_blank" rel="noopener">
          <span><i>{label}</i>{esc(row.get('seller'))}</span><b>{money(p)}</b></a>''')

    market_note = ""
    sold_rows_html = ""
    if sold_price is not None and sold.get("source") == "detailed":
        stats = sold.get("stats") or {}
        windows = stats.get("windows") or {}
        w30 = windows.get("30") or {}
        w90 = windows.get("90") or {}
        trend = sold_trend(stats)
        bits = []
        if w30.get("count"):
            bits.append(f"30d: {w30.get('count')} sales · median {money(w30.get('median'))} · delivered {money(w30.get('median_delivered'))}")
        if w90.get("count"):
            bits.append(f"90d: {w90.get('count')} sales · median {money(w90.get('median'))}")
        if trend is not None:
            bits.append(f"30d vs prior 31–90d: {trend:+.1f}%")
        if stats.get("best_offer_hidden_count"):
            bits.append(f"{stats.get('best_offer_hidden_count')} accepted Best Offer sales included at reported sold price")
        market_note = " · ".join(bits)
        recent = stats.get("recent_sales") or []
        sold_rows = []
        for sale in recent[:10]:
            when = str(sale.get("sold_at") or "")[:10]
            base = money(sale.get("sold_price"))
            ship = sale.get("shipping")
            delivered = sale.get("delivered_price")
            fmt = str(sale.get("buying_format") or "sale").replace("_", " ").upper()
            note = "BEST OFFER" if sale.get("best_offer_accepted") else fmt
            if sale.get("bid_count") not in (None, ""):
                note += f" · {sale.get('bid_count')} bids"
            total_text = f"{money(delivered)} delivered" if delivered is not None else (f"{base} + {money(ship)} ship" if ship is not None else base)
            href = esc(sale.get("url") or "#")
            title = esc(sale.get("title") or "eBay sold listing")
            seller = esc(sale.get("seller") or "seller unavailable")
            hidden = " · accepted Best Offer" if sale.get("best_offer_accepted") else ""
            sold_rows.append(f'<a class="sold-row" href="{href}" target="_blank" rel="noopener"><div class="sold-row-main"><span><b>{esc(when)}</b>{esc(note)}</span><strong>{esc(total_text)}</strong></div><div class="sold-row-title">{title}</div><small>{seller}{esc(hidden)}</small></a>')
        sold_rows_html = "".join(sold_rows)
    elif sold_price is not None:
        bits = []
        if sold.get("min_30d") is not None and sold.get("max_30d") is not None:
            bits.append(f"30d range {money(sold.get('min_30d'))}–{money(sold.get('max_30d'))}")
        if sold.get("long_median") is not None:
            bits.append(f"{sold.get('long_window_days') or 390}d median {money(sold.get('long_median'))} · {sold.get('long_count') or 0} comps")
        market_note = " · ".join(bits)

    facts = facts_html(detail, cost_per_pack)
    config = config_text(detail)
    ebay_search = search_url(product)
    sold_detail_html = ""
    if sold_price is not None:
        sales_block = f'<div class="sold-list">{sold_rows_html}</div>' if sold_rows_html else ""
        sold_detail_html = (
            f'<details><summary>Sold-market detail <span>{esc(sold_meta)}</span></summary>'
            f'<div class="market-detail">{esc(market_note or "No additional sold-market detail yet.")}{sales_block}</div></details>'
        )

    supply_count, sold_90_count, _ = liquidity_snapshot(rows, market, detailed_sold)
    current_candidates = [v for v in (retail_compare, ebay_compare) if v is not None]
    current_price = min(current_candidates) if current_candidates else None
    trend_value = sold_trend((detailed_sold or {}).get("stats") or {})
    trend_badge = f'<span class="compact-trend {"up" if trend_value > 0 else "down"}">{trend_value:+.1f}%</span>' if trend_value is not None else ""

    return f'''<article class="product-card state-{state}" data-state="{state}" data-season="{esc(product['season'])}" data-search="{esc((product['product']+' '+product['season']+' '+product['format']).lower())}">
      <button class="compact-head expand-toggle" type="button" aria-expanded="false">
        <div class="compact-thumb">{visual}</div>
        <div class="compact-id"><strong>{esc(product['season'])} · {esc(format_label(product['format']))}</strong><span>{esc(short_product(product['product']))}</span></div>
        <div class="compact-prices">
          <div><small>BUY NOW</small><b>{money(current_price)}</b></div>
          <div><small>{esc(sold_label)}</small><b>{money(sold_price)}</b>{trend_badge}</div>
        </div>
        <div class="compact-chevron">⌄</div>
      </button>
      <div class="card-expanded">
      <div class="card-head">
        <div class="thumb">{visual}</div>
        <div class="identity">
          <div class="sku-title"><strong>{esc(product['season'])}</strong><b>{esc(format_label(product['format']))}</b></div>
          <div class="family-name">{esc(short_product(product['product']))}</div>
          <div class="subline"><span class="state-pill {state}">{state_label}</span><span>{esc(config)}</span></div>
        </div>
      </div>
      {f'<div class="facts">{facts}</div>' if facts else ''}
      <div class="price-area">
        {retail_html}
        <div class="market-pair">{ebay_html}{sold_html}</div>
      </div>
      {lead_html}
      <div class="quick-links"><a href="{esc(ebay_search)}" target="_blank" rel="noopener">Search eBay live ↗</a></div>
      <div class="drawers">
        <details><summary>Retailer sources <span>{len(verified)} live · {len(leads)} leads · {len(source_rows)} shown</span></summary><div class="source-list">{''.join(source_rows) if source_rows else '<p class="empty">No usable mapped sources yet.</p>'}</div></details>
        <details><summary>Box hits <span>{len(guarantees)} guaranteed · {len(chases)} chase</span></summary><div class="hit-detail"><div><strong>Guaranteed / box</strong><ul>{hits_items or '<li>Not yet sourced</li>'}</ul></div><div><strong>Chase content</strong><ul>{chase_items or '<li>Not yet sourced</li>'}</ul></div>{details_link}</div></details>
        {sold_detail_html}
      </div>
      </div>
    </article>'''


def main():
    products = load_json(PRODUCTS, [])
    details = load_json(DETAILS, {})
    details.update(load_json(DETAILS_EXTRA, {}))
    latest = load_json(LATEST, {"observations": []})
    market_data = load_json(MARKET, {"products": {}})
    markets = market_data.get("products") or {}
    sold_detail_data = load_json(SOLD_DETAIL, {"products": {}})
    sold_details = sold_detail_data.get("products") or {}
    images = latest.get("product_images") or {}

    by_product = {}
    for row in latest.get("observations") or []:
        by_product.setdefault(row.get("product_id"), []).append(row)

    groups = {}
    cards_by_id = {}
    visible_products = []
    hidden_thin = 0
    states = {"live": 0, "lead": 0, "market": 0, "soldout": 0, "unknown": 0}

    for product in products:
        rows = by_product.get(product["id"], [])
        market = markets.get(product["id"], {})
        sold_detail = sold_details.get(product["id"], {})
        supply_count, sold_90_count, liquid = liquidity_snapshot(rows, market, sold_detail)
        if not liquid:
            hidden_thin += 1
            continue
        visible_products.append(product)
        cards_by_id[product["id"]] = product_card(
            product, rows, details.get(product["id"], {}), market, images.get(product["id"]), sold_detail
        )

        verified = any(r.get("status") == "VERIFIED" for r in rows)
        leads = bool(lead_rows(product, rows))
        active = market.get("active_market") or {}
        fresh_ebay = bool(market.get("best")) and bool(active) and not active.get("stale")
        sold_price = sold_view(market, sold_details.get(product["id"], {}))[0]
        statuses = [r.get("status") for r in rows]
        if verified or fresh_ebay:
            state = "live"
        elif leads:
            state = "lead"
        elif sold_price is not None:
            state = "market"
        elif statuses and all(s == "OUT_OF_STOCK" for s in statuses):
            state = "soldout"
        else:
            state = "unknown"
        states[state] += 1
        groups.setdefault(product["product"], []).append(product)

    format_order = {
        "Blaster / Value": 0, "Tin": 1, "Mega": 2, "Mega Tin": 2, "Full Box": 3,
        "Hobby": 4, "Hobby Jumbo": 5, "Delight": 6, "Sapphire": 7, "Box": 8,
    }
    family_html = []
    for family, ps in groups.items():
        ps = sorted(ps, key=lambda p: (p["season"], -format_order.get(p["format"], 99)), reverse=True)
        family_html.append(
            f'''<section class="family"><div class="family-title"><h2>{esc(short_product(family))}</h2><small>{len(ps)} tracked formats</small></div><div class="card-grid">{''.join(cards_by_id[p['id']] for p in ps)}</div></section>'''
        )

    seasons = sorted({p["season"] for p in visible_products}, reverse=True)
    season_options = ''.join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in seasons)
    generated = str(latest.get("generated_at") or "not collected")

    css = r'''
:root{--bg:#0b0d12;--panel:#141821;--panel2:#10131a;--line:#2b3140;--text:#f7f4ee;--muted:#9da4b2;--green:#77d6b6;--blue:#8eb8ff;--amber:#f3c875;--red:#f28b82;--accent:#b69cff;--accent2:#6ed7e0}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -12%,#242033 0,#0b0d12 38rem);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}a{color:inherit}.shell{width:min(1500px,100%);margin:auto;padding:14px clamp(12px,2vw,26px) 64px}.mast{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;padding:8px 0 14px}.brand{grid-column:2;display:flex;align-items:center;gap:10px}.logo{width:34px;height:40px;display:grid;place-items:center}.logo svg{width:100%;height:100%}.brand h1{margin:0;font-size:clamp(25px,3vw,38px);font-weight:950;letter-spacing:-1.6px}.statusbar{grid-column:3;justify-self:end;text-align:right;color:var(--muted);font-size:9px;line-height:1.5}.statusbar b{color:var(--green)}.controls{position:sticky;top:0;z-index:20;display:grid;grid-template-columns:minmax(220px,1fr) 170px 190px;gap:8px;padding:9px 0 12px;background:linear-gradient(#0b0d12fa,#0b0d12ee 78%,transparent);backdrop-filter:blur(12px)}input,select{min-width:0;border:1px solid var(--line);background:#151923;color:var(--text);border-radius:12px;padding:11px 13px;font:inherit;font-size:12px}.family{margin:24px 0 34px}.family-title{display:flex;align-items:end;justify-content:space-between;border-bottom:1px solid #1b293e;padding:0 2px 9px;margin-bottom:11px}.family-title h2{margin:0;font-size:20px;letter-spacing:-.5px}.family-title small{color:var(--muted);font-size:9px}.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:11px;align-items:start}.product-card{min-width:0;border:1px solid var(--line);border-radius:16px;background:linear-gradient(150deg,#181c26,#11141c);padding:12px;box-shadow:0 12px 30px rgba(0,0,0,.13)}.product-card:hover{border-color:#385070}.card-head{display:grid;grid-template-columns:84px minmax(0,1fr);gap:12px;align-items:center}.thumb{width:84px;height:82px;background:#f4f5f7;border-radius:11px;overflow:hidden;display:grid;place-items:center}.thumb img{width:100%;height:100%;object-fit:contain;padding:4px;image-orientation:from-image}.ph{text-align:center;color:#53627a}.box-glyph{font-size:24px;transform:rotate(-12deg);opacity:.7}.ph small{display:block;font-size:6px;font-weight:900;letter-spacing:.12em;line-height:1.25;margin-top:3px}.identity{min-width:0}.sku-title{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}.sku-title strong{font-size:19px;letter-spacing:-.6px}.sku-title b{font-size:11px;letter-spacing:.06em;color:#dce5f3}.family-name{font-size:12px;color:#aebbd0;margin-top:2px;font-weight:700}.subline{display:flex;align-items:center;gap:7px;color:var(--muted);font-size:8px;margin-top:7px;min-width:0}.subline>span:last-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.state-pill{font-size:7px;font-weight:950;letter-spacing:.08em;padding:4px 6px;border-radius:999px;background:#132033}.state-pill.live{color:var(--green)}.state-pill.lead{color:var(--amber)}.state-pill.market{color:var(--blue)}.state-pill.soldout{color:var(--red)}.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(70px,1fr));gap:1px;margin-top:10px;border:1px solid #1c2b41;border-radius:10px;overflow:hidden;background:#1c2b41}.fact{background:#0a1320;padding:7px 8px;min-width:0}.fact b{display:block;font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fact span{display:block;color:var(--muted);font-size:6px;font-weight:900;letter-spacing:.08em;margin-top:2px}.price-area{margin-top:9px}.retail-primary{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr);align-items:end;gap:12px;text-decoration:none;border:1px solid #315545;background:linear-gradient(135deg,#0c1b19,#0a141d);border-radius:12px;padding:9px 10px}.retail-primary.winner:after,.market-mini.winner:after{content:"BEST";position:absolute;right:7px;top:6px;font-size:6px;font-weight:950;letter-spacing:.08em;color:var(--green)}.eyebrow{display:block;color:#77c9aa;font-size:6px;font-weight:950;letter-spacing:.11em}.retail-price{display:block;font-size:23px;letter-spacing:-.8px;line-height:1.05;margin-top:2px}.retail-meta{min-width:0;padding-right:24px}.retail-meta strong,.retail-meta span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.retail-meta strong{font-size:9px}.retail-meta span{font-size:7px;color:var(--muted);margin-top:2px}.empty-price{border-color:#233149;background:#0a121e}.market-pair{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px}.market-mini{position:relative;display:flex;flex-direction:column;min-width:0;text-decoration:none;border:1px solid #263750;border-radius:10px;padding:7px 8px;background:#09111c}.market-mini>span{font-size:6px;font-weight:950;letter-spacing:.1em;color:#8394ad}.market-mini b{font-size:13px;line-height:1.2;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.market-mini small{font-size:7px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.market-mini.fresh{border-color:#345e51}.market-mini.stale{border-color:#67542f}.market-mini.sold{border-color:#29463e}.empty-market b{font-size:9px;color:#a8b6ca;letter-spacing:.02em}.lead-line{display:grid;grid-template-columns:auto auto minmax(0,1fr);align-items:center;gap:7px;text-decoration:none;border-left:2px solid #765d2c;margin-top:7px;padding:5px 7px;background:#14130f;border-radius:4px}.lead-line span{font-size:6px;font-weight:950;letter-spacing:.08em;color:var(--amber)}.lead-line b{font-size:11px}.lead-line em{font-style:normal;font-size:7px;color:#a99a7b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.quick-links{display:flex;gap:10px;margin-top:7px}.quick-links a{font-size:7px;color:#86aaf4;text-decoration:none}.drawers{margin-top:8px;border-top:1px solid #1c2a3f}.drawers details{border-bottom:1px solid #18253a}.drawers summary{list-style:none;cursor:pointer;padding:8px 1px;font-size:9px;font-weight:850;display:flex;justify-content:space-between;gap:8px}.drawers summary::-webkit-details-marker{display:none}.drawers summary span{color:var(--muted);font-weight:500;font-size:8px}.source-list{padding:0 0 5px}.source-row{display:flex;justify-content:space-between;gap:10px;align-items:center;text-decoration:none;padding:6px 4px;border-radius:6px;font-size:8px;color:#bac5d5}.source-row:hover{background:#141f31}.source-row span{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.source-row i{font-style:normal;font-size:6px;font-weight:950;padding:3px 4px;border-radius:4px;margin-right:5px;background:#1b2738;color:#91a0b5}.source-row.verified i{color:#61deb0}.source-row.out_of_stock i{color:#eb8e92}.source-row.rejected i,.source-row.unknown i{color:#e5bd69}.hit-detail{padding:2px 4px 9px;color:#bac5d5;font-size:8px;line-height:1.45}.hit-detail>div{margin-bottom:7px}.hit-detail strong{color:#e5eaf2}.hit-detail ul{margin:4px 0 0;padding-left:16px}.detail-link{font-size:8px;color:#8eb1fa}.market-detail{padding:2px 4px 10px;color:#aebbd0;font-size:8px}.sold-list{margin-top:8px;border-top:1px solid #1d2a3f}.sold-row{display:block;padding:8px 2px;border-bottom:1px solid #172338;text-decoration:none}.sold-row-main{display:flex;justify-content:space-between;gap:10px;align-items:center}.sold-row span{display:flex;gap:7px;color:#8fa0b8}.sold-row span b{color:#cbd5e4}.sold-row strong{color:#f2f5f9;font-weight:750;white-space:nowrap}.sold-row-title{margin-top:4px;color:#c1ccda;font-size:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sold-row small{display:block;margin-top:2px;color:#718099;font-size:7px}.empty{color:var(--muted);font-size:8px}.hidden{display:none!important}.footer{margin-top:30px;color:#6f7d92;font-size:8px;text-align:center}
@media(max-width:760px){.shell{padding:8px 10px 54px}.mast{grid-template-columns:1fr auto 1fr;padding:7px 2px 10px}.brand{gap:7px}.logo{width:28px;height:32px}.brand h1{font-size:23px}.statusbar{font-size:7px}.controls{grid-template-columns:1fr 1fr;padding-top:7px}.controls input{grid-column:1/-1}.family{margin:18px 0 28px}.family-title{margin-bottom:9px}.family-title h2{font-size:20px}.card-grid{grid-template-columns:1fr;gap:10px}.product-card{padding:11px;border-radius:15px}.card-head{grid-template-columns:86px minmax(0,1fr)}.thumb{width:86px;height:84px}.sku-title strong{font-size:20px}.sku-title b{font-size:11px}.facts{margin-top:9px}.fact{padding:7px}.retail-primary{padding:9px}.retail-price{font-size:24px}.market-mini{padding:7px}.market-mini b{font-size:12px}}
@media(max-width:420px){.statusbar{display:none}.mast{grid-template-columns:1fr}.brand{grid-column:1;justify-self:center}.controls{gap:6px}.market-pair{grid-template-columns:1fr 1fr}.retail-primary{grid-template-columns:1fr auto}.retail-meta{text-align:right}.fact:nth-child(4){display:none}}
.compact-head{width:100%;border:0;background:transparent;color:inherit;padding:0;display:grid;grid-template-columns:54px minmax(0,1fr) auto 18px;gap:10px;align-items:center;text-align:left;cursor:pointer}
.compact-thumb{width:54px;height:54px;border-radius:10px;overflow:hidden;background:#f3f1ec;display:grid;place-items:center}
.compact-thumb img{width:100%;height:100%;object-fit:contain;padding:3px}.compact-thumb .ph{transform:scale(.75)}
.compact-id{min-width:0}.compact-id strong,.compact-id span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.compact-id strong{font-size:11px;letter-spacing:.02em}.compact-id span{font-size:10px;color:#b9bec9;margin-top:3px}
.compact-prices{display:grid;grid-template-columns:auto auto;gap:12px;text-align:right}.compact-prices small{display:block;color:var(--muted);font-size:6px;font-weight:900;letter-spacing:.09em}.compact-prices b{display:block;font-size:16px;line-height:1.15;margin-top:2px}.compact-trend{display:inline-block;font-size:7px;font-weight:900;margin-top:2px}.compact-trend.up{color:var(--green)}.compact-trend.down{color:var(--red)}
.compact-chevron{font-size:18px;color:var(--accent);transition:transform .2s ease}.product-card.expanded .compact-chevron{transform:rotate(180deg)}
.card-expanded{display:none;margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}.product-card.expanded .card-expanded{display:block}
.product-card{transition:border-color .18s ease,background .18s ease}.product-card.expanded{border-color:#5f5577;background:linear-gradient(150deg,#1b1f2b,#12151d)}
.logo svg path:first-child{stroke:var(--accent)!important}.logo svg path:nth-child(2){stroke:var(--accent2)!important}.logo svg path:last-child{stroke:var(--accent)!important}
@media(max-width:760px){.family{margin:14px 0 20px}.family-title{margin-bottom:6px}.family-title h2{font-size:16px}.card-grid{gap:7px}.product-card{padding:8px 9px;border-radius:13px}.compact-head{grid-template-columns:46px minmax(0,1fr) auto 14px;gap:8px}.compact-thumb{width:46px;height:46px}.compact-prices{gap:8px}.compact-prices b{font-size:14px}.compact-id strong{font-size:10px}.compact-id span{font-size:9px}.card-expanded{margin-top:9px;padding-top:9px}.card-head{grid-template-columns:70px minmax(0,1fr)}.thumb{width:70px;height:68px}.facts{display:none}}
'''

    logo = '''<svg viewBox="0 0 42 50" aria-hidden="true"><path d="M5 4h24l8 8v34H5z" fill="none" stroke="#57dfad" stroke-width="3"/><path d="M11 14h16M11 21h20M11 28h14" stroke="#7ca8ff" stroke-width="3" stroke-linecap="round"/><path d="M30 4v10h7" fill="none" stroke="#57dfad" stroke-width="3"/></svg>'''

    body = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#070b12"><title>CardsInStock</title><style>{css}</style></head><body><main class="shell">
      <header class="mast"><div class="brand"><div class="logo">{logo}</div><h1>CardsInStock</h1></div><div class="statusbar"><b>{states['live']} live</b> · {len(visible_products)} liquid SKUs · {hidden_thin} thin hidden<br>updated {esc(generated[:16].replace('T',' '))} UTC</div></header>
      <div class="controls"><input id="search" type="search" placeholder="Search product, season or box type…"><select id="season"><option value="">All seasons</option>{season_options}</select><select id="mode"><option value="all">All tracked products</option><option value="live">Verified live stock</option><option value="priced">Any price / market data</option><option value="gaps">Coverage gaps</option></select></div>
      <div id="families">{''.join(family_html)}</div>
      <div class="footer">Verified retailer prices are separated from unverified leads and stale market snapshots. Shipping is included only when known.</div>
    </main><script>
const q=document.getElementById('search'),season=document.getElementById('season'),mode=document.getElementById('mode');
function apply(){{const needle=q.value.trim().toLowerCase(),s=season.value,m=mode.value;document.querySelectorAll('.product-card').forEach(card=>{{const state=card.dataset.state;let ok=(!needle||card.dataset.search.includes(needle))&&(!s||card.dataset.season===s);if(m==='live')ok=ok&&state==='live';else if(m==='priced')ok=ok&&['live','lead','market'].includes(state);else if(m==='gaps')ok=ok&&['unknown','soldout'].includes(state);card.classList.toggle('hidden',!ok)}});document.querySelectorAll('.family').forEach(f=>{{f.classList.toggle('hidden',![...f.querySelectorAll('.product-card')].some(c=>!c.classList.contains('hidden')))}})}}
[q,season,mode].forEach(el=>el.addEventListener(el===q?'input':'change',apply));
document.querySelectorAll('.expand-toggle').forEach(btn=>btn.addEventListener('click',()=>{{const card=btn.closest('.product-card');const expanded=card.classList.toggle('expanded');btn.setAttribute('aria-expanded',expanded?'true':'false')}}));
apply();
</script></body></html>'''

    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(body)
    print(f"Built compact liquid-market dashboard with {len(visible_products)} products; {hidden_thin} thin products hidden")


if __name__ == "__main__":
    main()
