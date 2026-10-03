import html
import json
import re
from pathlib import Path

from ebay_utils import search_url

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
DETAILS = ROOT / "config" / "product_details.json"
DETAILS_EXTRA = ROOT / "config" / "product_details_extra.json"
LATEST = ROOT / "data" / "latest.json"
MARKET = ROOT / "data" / "market_latest.json"
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
    text = str(name).replace("Topps ", "", 1).replace(" Club Competitions", "")
    return text


def format_label(value):
    return {
        "Blaster / Value": "VALUE",
        "Hobby Jumbo": "JUMBO",
        "Mega Tin": "MEGA TIN",
        "Full Box": "FULL BOX",
    }.get(value, str(value).upper())


def listing_url(row):
    return row.get("final_url") or row.get("url") or "#"


def retail_rank(row):
    delivered = row.get("delivered_price")
    price = row.get("price")
    return (0, delivered) if delivered is not None else (1, price if price is not None else 10**12)


def hard_bad_lead(row):
    title = str(row.get("title") or "").lower()
    # Keep validation failures visible as leads unless the page itself clearly says
    # it is a different sale unit. The lead never becomes a verified market price.
    if "case" in title or "break" in title:
        return True
    if any(x in title for x in ["starter pack", "sticker", "multipack", "multi pack", "bundle"]):
        return True
    if re.search(r"\bpack\b", title) and not re.search(r"\bbox\b|\btin\b", title):
        return True
    return False


def lead_rows(rows):
    out = []
    for row in rows:
        if row.get("status") in ("VERIFIED", "OUT_OF_STOCK"):
            continue
        if row.get("price") is None or hard_bad_lead(row):
            continue
        out.append(row)
    out.sort(key=lambda r: float(r.get("price") or 10**12))
    return out


def hit_summary(detail):
    bits = []
    packs = detail.get("packs_per_box")
    cards = detail.get("cards_per_pack")
    if packs and cards:
        bits.append(f"{packs}×{cards}")
    guarantees = detail.get("guarantees") or []
    for g in guarantees[:3]:
        bits.append(str(g))
    return " • ".join(bits) if bits else "Box configuration being sourced"


def sold_view(market):
    sold = market.get("sold_market") or {}
    c30 = sold.get("count_30d") or 0
    if c30 and sold.get("median_30d") is not None:
        return sold.get("median_30d"), "30d sold", f"{c30} sales", sold
    if sold.get("long_median") is not None:
        count = sold.get("long_count")
        days = sold.get("long_window_days") or 390
        return sold.get("long_median"), f"{days}d sold", f"{count} comps" if count is not None else "market comp", sold
    if sold.get("fmv") is not None:
        return sold.get("fmv"), "sold FMV", "aggregate", sold
    return None, "Sold market", "no data", sold


def product_card(product, rows, detail, market, image):
    verified = sorted([r for r in rows if r.get("status") == "VERIFIED"], key=retail_rank)
    best_retail = verified[0] if verified else None
    leads = lead_rows(rows)
    best_lead = leads[0] if leads else None

    active = market.get("active_market") or {}
    ebay_best = market.get("best") if market.get("status") == "VERIFIED" else None
    ebay_fresh = bool(ebay_best) and bool(active) and not active.get("stale")
    ebay_stale = bool(ebay_best) and bool(active) and bool(active.get("stale"))
    sold_price, sold_label, sold_meta, sold = sold_view(market)

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

    # Product visual
    img = market.get("collectaio_image_url") or image
    if img:
        visual = f'<img src="{esc(img)}" alt="{esc(product["product"])}" loading="lazy">'
    else:
        initials = "".join(word[0] for word in short_product(product["product"]).split()[:3]).upper()
        visual = f'<div class="ph">{esc(initials or "BOX")}</div>'

    # Retail tile
    if best_retail:
        rp = best_retail.get("delivered_price") if best_retail.get("delivered_price") is not None else best_retail.get("price")
        ship_known = best_retail.get("shipping") is not None
        retail_sub = "delivered" if best_retail.get("delivered_price") is not None else "shipping TBD"
        retail_link = listing_url(best_retail)
        retail_html = f'''<a class="price-cell retail" href="{esc(retail_link)}" target="_blank" rel="noopener">
          <span class="price-label">RETAIL</span><b>{money(rp)}</b><small>{esc(best_retail.get('seller'))} · {retail_sub}</small></a>'''
        retail_compare = rp if ship_known and best_retail.get("delivered_price") is not None else None
    else:
        retail_html = '<div class="price-cell"><span class="price-label">RETAIL</span><b>—</b><small>no verified stock</small></div>'
        retail_compare = None

    # eBay tile
    if ebay_best:
        ep = ebay_best.get("delivered_price")
        age = active.get("freshness_days")
        badge = f"{age}d snapshot" if age is not None else "snapshot"
        status_word = "live snapshot" if ebay_fresh else "verify first"
        ebay_html = f'''<a class="price-cell ebay {'stale' if ebay_stale else ''}" href="{esc(ebay_best.get('url') or search_url(product))}" target="_blank" rel="noopener">
          <span class="price-label">EBAY BIN</span><b>{money(ep)}</b><small>{badge} · {status_word}</small></a>'''
        ebay_compare = ep if ebay_fresh else None
    else:
        ebay_html = f'''<a class="price-cell ebay" href="{esc(search_url(product))}" target="_blank" rel="noopener">
          <span class="price-label">EBAY BIN</span><b>—</b><small>search live ↗</small></a>'''
        ebay_compare = None

    # Sold tile
    sold_age = sold.get("freshness_days") if sold else None
    sold_stale = bool(sold.get("stale")) if sold else False
    sold_sub = sold_meta + (f" · {sold_age}d old" if sold_age is not None else "")
    sold_html = f'''<div class="price-cell sold {'stale' if sold_stale else ''}">
      <span class="price-label">{esc(sold_label.upper())}</span><b>{money(sold_price)}</b><small>{esc(sold_sub)}</small></div>'''

    # Highlight only apples-to-apples fresh delivered asks.
    live_values = [("retail", retail_compare), ("ebay", ebay_compare)]
    live_values = [(k, v) for k, v in live_values if v is not None]
    winner = min(live_values, key=lambda x: x[1])[0] if live_values else None
    if winner == "retail":
        retail_html = retail_html.replace('class="price-cell retail"', 'class="price-cell retail winner"', 1)
    elif winner == "ebay":
        ebay_html = ebay_html.replace('class="price-cell ebay ', 'class="price-cell ebay winner ', 1)

    # Potential lead: intentionally not promoted to market price until confirmed.
    lead_html = ""
    if best_lead:
        lead_price = best_lead.get("price")
        is_interesting = best_retail is None or best_retail.get("price") is None or lead_price < best_retail.get("price")
        if is_interesting:
            lead_html = f'''<a class="lead-chip" href="{esc(listing_url(best_lead))}" target="_blank" rel="noopener">
              <span>⚡ POSSIBLE DEAL</span><b>{money(lead_price)}</b><em>{esc(best_lead.get('seller'))} · unverified, check ↗</em></a>'''

    # Compact hit line and detailed drawer
    summary = hit_summary(detail)
    guarantees = detail.get("guarantees") or []
    chases = detail.get("possible_hits") or []
    hits_items = "".join(f"<li>{esc(x)}</li>" for x in guarantees)
    chase_items = "".join(f"<li>{esc(x)}</li>" for x in chases)
    official = detail.get("checklist_url") or detail.get("official_product_url") or detail.get("reference_url")
    details_link = f'<a href="{esc(official)}" target="_blank" rel="noopener">Official / checklist ↗</a>' if official else ''

    # Retailer/source drawer: keep every lead visible. Confirmed OOS is labeled, not erased.
    source_rows = []
    order = {"VERIFIED": 0, "UNKNOWN": 1, "REJECTED": 2, "OUT_OF_STOCK": 3}
    for row in sorted(rows, key=lambda r: (order.get(r.get("status"), 9), r.get("price") is None, r.get("price") or 10**12)):
        status = row.get("status") or "UNKNOWN"
        label = {"VERIFIED": "LIVE", "OUT_OF_STOCK": "OOS", "REJECTED": "LEAD", "UNKNOWN": "CHECK"}.get(status, "CHECK")
        cls = status.lower()
        p = row.get("delivered_price") if row.get("delivered_price") is not None else row.get("price")
        source_rows.append(f'''<a class="source-row {cls}" href="{esc(listing_url(row))}" target="_blank" rel="noopener">
          <span><i>{label}</i>{esc(row.get('seller'))}</span><b>{money(p)}</b></a>''')

    ebay_search = f'<a class="mini-link" href="{esc(search_url(product))}" target="_blank" rel="noopener">eBay search ↗</a>'
    collect_link = f'<a class="mini-link" href="{esc(market.get("collectaio_url"))}" target="_blank" rel="noopener">market source ↗</a>' if market.get("collectaio_url") else ''

    market_note = ""
    if sold_price is not None:
        range_text = ""
        if sold.get("min_30d") is not None and sold.get("max_30d") is not None:
            range_text = f"30d range {money(sold.get('min_30d'))}–{money(sold.get('max_30d'))}"
        long_text = ""
        if sold.get("long_median") is not None:
            long_text = f"{sold.get('long_window_days') or 390}d median {money(sold.get('long_median'))} · {sold.get('long_count') or 0} comps"
        market_note = " · ".join(x for x in [range_text, long_text] if x)

    state_label = {"live": "LIVE", "lead": "LEAD", "market": "MARKET", "soldout": "OOS", "unknown": "TRACKING"}[state]

    return f'''<article class="product-card state-{state}" data-state="{state}" data-season="{esc(product['season'])}" data-search="{esc((product['product']+' '+product['season']+' '+product['format']).lower())}">
      <div class="card-top">
        <div class="thumb">{visual}</div>
        <div class="identity"><div class="meta"><span>{esc(product['season'])}</span><span>{esc(format_label(product['format']))}</span><span class="state-pill {state}">{state_label}</span></div>
        <h3>{esc(short_product(product['product']))}</h3><div class="card-actions">{ebay_search}{collect_link}</div></div>
      </div>
      <div class="price-grid">{retail_html}{ebay_html}{sold_html}</div>
      {lead_html}
      <div class="hit-strip"><span>BOX</span>{esc(summary)}</div>
      <div class="drawers">
        <details><summary>Sources <span>{len(verified)} live · {len(leads)} leads · {len(rows)} checked</span></summary><div class="source-list">{''.join(source_rows) if source_rows else '<p class="empty">No mapped sources yet.</p>'}</div></details>
        <details><summary>Box hits <span>{len(guarantees)} guaranteed · {len(chases)} chase</span></summary><div class="hit-detail"><div><strong>Guaranteed / box</strong><ul>{hits_items or '<li>Not yet sourced</li>'}</ul></div><div><strong>Chase content</strong><ul>{chase_items or '<li>Not yet sourced</li>'}</ul></div>{details_link}</div></details>
        {f'<details><summary>Market detail <span>{sold_meta}</span></summary><div class="market-detail">{esc(market_note or "No additional sold-market detail yet.")}</div></details>' if sold_price is not None else ''}
      </div>
    </article>'''


def main():
    products = load_json(PRODUCTS, [])
    base_details = load_json(DETAILS, {})
    base_details.update(load_json(DETAILS_EXTRA, {}))
    latest = load_json(LATEST, {"observations": []})
    market_data = load_json(MARKET, {"products": {}})
    markets = market_data.get("products") or {}
    images = latest.get("product_images") or {}

    by_product = {}
    for row in latest.get("observations") or []:
        by_product.setdefault(row.get("product_id"), []).append(row)

    groups = {}
    states = {"live": 0, "lead": 0, "market": 0, "soldout": 0, "unknown": 0}
    cards_by_id = {}
    for product in products:
        rows = by_product.get(product["id"], [])
        market = markets.get(product["id"], {})
        card = product_card(product, rows, base_details.get(product["id"], {}), market, images.get(product["id"]))
        cards_by_id[product["id"]] = card
        # Mirror product_card state cheaply for headline counts.
        verified = any(r.get("status") == "VERIFIED" for r in rows)
        leads = bool(lead_rows(rows))
        active = market.get("active_market") or {}
        fresh_ebay = bool(market.get("best")) and bool(active) and not active.get("stale")
        sold_price = sold_view(market)[0]
        statuses = [r.get("status") for r in rows]
        if verified or fresh_ebay: state = "live"
        elif leads: state = "lead"
        elif sold_price is not None: state = "market"
        elif statuses and all(s == "OUT_OF_STOCK" for s in statuses): state = "soldout"
        else: state = "unknown"
        states[state] += 1
        groups.setdefault(product["product"], []).append(product)

    format_order = {"Blaster / Value": 0, "Tin": 1, "Mega": 1, "Mega Tin": 1, "Full Box": 2, "Hobby": 3, "Hobby Jumbo": 4, "Delight": 5, "Sapphire": 6, "Box": 7}
    family_html = []
    for family, ps in groups.items():
        ps = sorted(ps, key=lambda p: (p["season"], -format_order.get(p["format"], 99)), reverse=True)
        family_html.append(f'''<section class="family"><div class="family-title"><div><span>PRODUCT LINE</span><h2>{esc(short_product(family))}</h2></div><small>{len(ps)} formats</small></div><div class="card-grid">{''.join(cards_by_id[p['id']] for p in ps)}</div></section>''')

    seasons = sorted({p["season"] for p in products}, reverse=True)
    season_options = ''.join(f'<option value="{esc(s)}">{esc(s)}</option>' for s in seasons)
    generated = str(latest.get("generated_at") or "not collected")

    css = r'''
:root{--bg:#070b12;--surface:#0d1421;--surface2:#101a2a;--line:#22304a;--text:#f6f8fc;--muted:#8c9ab0;--green:#54e0ad;--blue:#68a0ff;--amber:#f2bf63;--red:#ff7f86}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -10%,#13213a 0,#070b12 38rem);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}a{color:inherit}.shell{width:min(1680px,100%);margin:auto;padding:18px clamp(12px,2vw,28px) 70px}.mast{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:20px;padding:12px 0 18px}.brand{grid-column:2;display:flex;align-items:center;gap:10px}.logo{width:38px;height:38px}.brand h1{font-size:clamp(27px,3vw,40px);letter-spacing:-1.8px;margin:0;font-weight:950}.tag{font-size:11px;color:var(--muted);text-align:center;margin-top:4px}.statusbar{grid-column:3;justify-self:end;text-align:right;color:var(--muted);font-size:10px}.statusbar b{color:var(--green)}.controls{position:sticky;z-index:20;top:0;display:grid;grid-template-columns:minmax(180px,1fr) auto auto;gap:8px;padding:10px 0;background:linear-gradient(#070b12f5,#070b12e8 78%,transparent);backdrop-filter:blur(12px)}input,select{min-width:0;border:1px solid var(--line);background:#0b1320;color:var(--text);border-radius:11px;padding:10px 12px;font:inherit;font-size:12px}.family{margin:26px 0 38px}.family-title{display:flex;align-items:end;justify-content:space-between;border-bottom:1px solid #18253a;padding:0 2px 9px;margin-bottom:11px}.family-title span{font-size:8px;letter-spacing:.16em;font-weight:900;color:var(--green)}.family-title h2{margin:2px 0 0;font-size:17px;letter-spacing:-.3px}.family-title small{color:var(--muted);font-size:9px}.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,310px),1fr));gap:10px;align-items:start}.product-card{min-width:0;border:1px solid var(--line);border-radius:15px;background:linear-gradient(145deg,#0e1726,#0a111d);padding:11px;box-shadow:0 12px 30px rgba(0,0,0,.12)}.product-card:hover{border-color:#354766}.card-top{display:grid;grid-template-columns:78px minmax(0,1fr);gap:10px;align-items:center}.thumb{width:78px;height:68px;background:#f2f4f8;border-radius:10px;overflow:hidden;display:grid;place-items:center}.thumb img{width:100%;height:100%;object-fit:contain;padding:4px;image-orientation:from-image}.ph{font-weight:950;color:#31415b;letter-spacing:-1px}.identity{min-width:0}.identity h3{margin:4px 0 4px;font-size:14px;line-height:1.12;letter-spacing:-.2px;white-space:normal}.meta{display:flex;gap:5px;align-items:center;flex-wrap:wrap}.meta>span{font-size:7px;font-weight:850;letter-spacing:.08em;color:#a6b3c5;background:#131e2f;padding:4px 6px;border-radius:999px}.state-pill.live{color:#73e7ba}.state-pill.lead{color:#f4c76a}.state-pill.market{color:#80aaff}.state-pill.soldout{color:#f08b8f}.card-actions{display:flex;gap:9px;flex-wrap:wrap}.mini-link{font-size:8px;color:#8fb0f8;text-decoration:none}.price-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin-top:10px}.price-cell{min-width:0;text-decoration:none;border:1px solid #24324a;border-radius:10px;background:#0a111c;padding:8px 7px;display:flex;flex-direction:column;gap:1px;position:relative}.price-cell b{font-size:clamp(14px,1.6vw,18px);letter-spacing:-.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.price-cell small{font-size:7px;color:var(--muted);line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.price-label{font-size:7px;color:#7f90aa;font-weight:900;letter-spacing:.1em}.price-cell.winner{border-color:#397962;box-shadow:inset 0 0 0 1px #2a5c4b}.price-cell.winner:after{content:"BEST";position:absolute;right:5px;top:5px;font-size:6px;font-weight:950;color:var(--green)}.price-cell.ebay{border-color:#293a60}.price-cell.sold{border-color:#225044}.price-cell.stale{border-color:#68542e}.lead-chip{margin-top:7px;display:grid;grid-template-columns:auto auto minmax(0,1fr);gap:7px;align-items:center;padding:7px 8px;border:1px solid #725b2d;background:#1d180f;border-radius:9px;text-decoration:none}.lead-chip span{font-size:7px;font-weight:950;letter-spacing:.08em;color:var(--amber)}.lead-chip b{font-size:12px}.lead-chip em{font-style:normal;color:#b6a47e;font-size:7px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.hit-strip{margin-top:8px;padding:7px 0 2px;color:#bcc7d7;font-size:9px;line-height:1.35}.hit-strip>span{font-size:7px;color:var(--green);font-weight:950;letter-spacing:.1em;margin-right:6px}.drawers{margin-top:7px;border-top:1px solid #1c293e}.drawers details{border-bottom:1px solid #172338;padding:0}.drawers summary{list-style:none;cursor:pointer;padding:8px 1px;font-size:9px;font-weight:850;display:flex;justify-content:space-between;gap:8px}.drawers summary::-webkit-details-marker{display:none}.drawers summary span{color:var(--muted);font-weight:500;font-size:8px}.source-list{padding:0 0 5px}.source-row{display:flex;justify-content:space-between;gap:10px;align-items:center;text-decoration:none;padding:6px 4px;border-radius:6px;font-size:8px;color:#bac5d5}.source-row:hover{background:#141f31}.source-row span{min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.source-row i{font-style:normal;font-size:6px;font-weight:950;padding:3px 4px;border-radius:4px;margin-right:5px;background:#1b2738;color:#91a0b5}.source-row.verified i{color:#61deb0}.source-row.out_of_stock i{color:#eb8e92}.source-row.rejected i,.source-row.unknown i{color:#efc66f}.source-row b{font-size:8px}.hit-detail{padding:1px 3px 9px;color:#acb8ca;font-size:8px;line-height:1.35}.hit-detail strong{color:#dbe2ec}.hit-detail ul{margin:4px 0 8px;padding-left:16px}.hit-detail a{color:var(--green);text-decoration:none;font-weight:800}.market-detail{font-size:8px;color:#9aa9be;padding:0 3px 9px}.empty{font-size:8px;color:var(--muted)}.state-soldout,.state-unknown{display:none}body.show-all .state-soldout,body.show-all .state-unknown{display:block;opacity:.7}body.live-only .product-card:not(.state-live){display:none}body.searching .filtered{display:none}@media(max-width:780px){.mast{grid-template-columns:1fr}.brand{grid-column:1;justify-self:center}.statusbar{grid-column:1;justify-self:center;text-align:center}.controls{grid-template-columns:1fr 1fr}.controls input{grid-column:1/-1}.card-grid{grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr))}.family{margin-top:22px}}@media(max-width:560px){.shell{padding:10px 10px 50px}.card-grid{grid-template-columns:1fr}.product-card{padding:10px}.card-top{grid-template-columns:72px minmax(0,1fr)}.thumb{width:72px;height:62px}.price-cell{padding:7px 6px}.price-cell b{font-size:16px}.lead-chip{grid-template-columns:auto auto}.lead-chip em{grid-column:1/-1}.family-title h2{font-size:16px}}@media(min-width:700px) and (max-width:1050px){.card-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}'''

    js = r'''
const q=document.querySelector('#q'), season=document.querySelector('#season'), view=document.querySelector('#view');
function apply(){
  const text=q.value.trim().toLowerCase(), s=season.value, mode=view.value;
  document.body.classList.toggle('show-all',mode==='all');
  document.body.classList.toggle('live-only',mode==='live');
  document.body.classList.toggle('searching',Boolean(text||s));
  document.querySelectorAll('.product-card').forEach(card=>{
    const match=(!text||card.dataset.search.includes(text))&&(!s||card.dataset.season===s);
    card.classList.toggle('filtered',!match);
  });
  document.querySelectorAll('.family').forEach(f=>{
    const visible=[...f.querySelectorAll('.product-card')].some(c=>{
      if(c.classList.contains('filtered')) return false;
      if(mode==='live') return c.classList.contains('state-live');
      if(mode==='all') return true;
      return !c.classList.contains('state-soldout')&&!c.classList.contains('state-unknown');
    });
    f.style.display=visible?'':'none';
  });
}
[q,season,view].forEach(x=>x.addEventListener(x===q?'input':'change',apply)); apply();'''

    page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#070b12"><title>CardsInStock</title><style>{css}</style></head><body><main class="shell">
    <header class="mast"><div></div><div><div class="brand"><svg class="logo" viewBox="0 0 48 48" aria-hidden="true"><rect x="13" y="5" width="27" height="35" rx="7" fill="#54e0ad"/><rect x="6" y="10" width="27" height="33" rx="7" fill="#0d1421" stroke="#f6f8fc" stroke-width="2.3"/><path d="M12 26l5 5 10-13" fill="none" stroke="#54e0ad" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></svg><h1>CardsInStock</h1></div><div class="tag">Soccer wax price intelligence — retail, eBay asks and sold market</div></div><div class="statusbar"><b>{states['live']} live</b> · {states['lead']} lead-only · {len(products)} tracked<br>Retail refresh {esc(generated)}</div></header>
    <div class="controls"><input id="q" type="search" placeholder="Search product, season or format…"><select id="season"><option value="">All seasons</option>{season_options}</select><select id="view"><option value="deals">Deals + leads + market</option><option value="live">Verified live only</option><option value="all">All tracked</option></select></div>
    {''.join(family_html)}
    </main><script>{js}</script></body></html>'''

    INDEX.parent.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(page)
    (ROOT / "docs" / "latest.json").write_text(json.dumps(latest, indent=2))
    print(f"Built modern dashboard: {len(products)} products; {states['live']} live, {states['lead']} lead-only, {states['market']} market-only")


if __name__ == "__main__":
    main()
