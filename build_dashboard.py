import html
import json
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).parent
products = json.loads((ROOT / 'config/products.json').read_text())
details = json.loads((ROOT / 'config/product_details.json').read_text()) if (ROOT / 'config/product_details.json').exists() else {}
latest_path = ROOT / 'data/latest.json'
latest = json.loads(latest_path.read_text()) if latest_path.exists() else {'generated_at': None, 'observations': []}
images = latest.get('product_images', {})
obs_by_product = {}
for o in latest.get('observations', []):
    obs_by_product.setdefault(o['product_id'], []).append(o)


def money(v):
    return f'${v:,.2f}' if v is not None else '—'


def fmt_name(v):
    x = v.upper().replace(' / VALUE', '').replace('HOBBY JUMBO', 'JUMBO')
    return 'BLASTER' if x in ('VALUE', 'BLASTER') else x


def listing_url(o):
    return o.get('final_url') or o.get('url') or '#'


def ebay_search(p):
    q = f"{p['season']} {p['product']} {p['format']} sealed box"
    return 'https://www.ebay.com/sch/i.html?_nkw=' + quote_plus(q) + '&LH_BIN=1&LH_ItemCondition=1000'


def card(p):
    obs = obs_by_product.get(p['id'], [])
    verified = [o for o in obs if o.get('status') == 'VERIFIED']
    verified.sort(key=lambda o: (
        o.get('delivered_price') is None,
        o.get('delivered_price') if o.get('delivered_price') is not None else o.get('price', 10**9)
    ))
    low = verified[0] if verified else None
    d = details.get(p['id'], {})
    has_oos = any(o.get('status') == 'OUT_OF_STOCK' for o in obs)
    state = 'available' if low else ('soldout' if has_oos else 'unverified')

    img = images.get(p['id'])
    if img:
        visual = f'<img src="{html.escape(img)}" alt="{html.escape(p["product"] + " " + p["format"])}" loading="lazy">'
    else:
        visual = f'<div class="image-placeholder"><span>{fmt_name(p["format"])}</span><small>IMAGE PENDING</small></div>'

    packs = d.get('packs_per_box')
    cards = d.get('cards_per_pack')
    config = f'{packs} packs × {cards} cards' if packs and cards else 'Configuration pending'
    hits = ' · '.join('✓ ' + html.escape(x) for x in d.get('guarantees', [])) or 'Guarantees pending'

    checks = []
    for o in sorted(obs, key=lambda x: (x.get('status') != 'VERIFIED', x.get('price') or 10**9)):
        icon = {'VERIFIED': '🟢', 'OUT_OF_STOCK': '🔴', 'REJECTED': '🚫', 'UNKNOWN': '⚪'}.get(o.get('status'), '⚪')
        label = {'VERIFIED': 'in stock', 'OUT_OF_STOCK': 'sold out', 'REJECTED': 'rejected', 'UNKNOWN': 'not verified'}.get(o.get('status'), 'not verified')
        seller = html.escape(o['seller'])
        url = html.escape(listing_url(o))
        price = money(o.get('delivered_price') if o.get('delivered_price') is not None else o.get('price'))
        ship = ' delivered' if o.get('delivered_price') is not None else ''
        checks.append(
            f'<a class="check {o.get("status", "").lower()}" href="{url}" target="_blank" rel="noopener">'
            f'<span>{icon} {seller}</span><span>{price}{ship} · {label} ↗</span></a>'
        )

    if low:
        delivered = low.get('delivered_price')
        price = low.get('price')
        cpp = low.get('cost_per_pack')
        url = html.escape(listing_url(low))
        seller = html.escape(low['seller'])
        best = delivered if delivered is not None else price
        commerce = (
            f'<div class="best"><div><span class="eyebrow">BEST VERIFIED</span>'
            f'<div class="big">{money(best)}</div><div class="dim">{seller}</div></div>'
            f'<a class="buy" href="{url}" target="_blank" rel="noopener">BUY ↗</a></div>'
            f'<div class="metrics"><span><b>{money(price)}</b><small>ITEM</small></span>'
            f'<span><b>{"FREE" if low.get("shipping") == 0 else money(low.get("shipping")) if low.get("shipping") is not None else "TBD"}</b><small>SHIPPING</small></span>'
            f'<span><b>{money(cpp)}</b><small>$/PACK</small></span></div>'
        )
    else:
        commerce = '<div class="inactive-note">No live purchasable listing has been verified yet.</div>'

    checklist = f'<a class="textlink" href="{html.escape(d["checklist_url"])}" target="_blank" rel="noopener">Checklist ↗</a>' if d.get('checklist_url') else ''
    ebay = html.escape(ebay_search(p))

    return f'''<article class="format-card {state}" data-season="{p['season']}" data-search="{html.escape((p['product'] + ' ' + p['season'] + ' ' + p['format']).lower())}">
      <div class="product-visual">{visual}<div class="overlay"><span class="badge">{fmt_name(p['format'])}</span><span>{p['season']}</span></div></div>
      <div class="body">{commerce}
        <div class="spec"><b>{config}</b><span>{hits}</span></div>
        <details><summary>Compare retailers <span>{len(verified)} verified / {len(obs)} checked</span></summary><div class="checks">{''.join(checks) if checks else '<div class="dim">No retailer mappings yet</div>'}</div></details>
        <div class="links">{checklist}<a class="textlink ebay" href="{ebay}" target="_blank" rel="noopener">Search eBay BIN ↗</a></div>
      </div>
    </article>'''


groups = {}
for p in products:
    groups.setdefault(p['product'], []).append(p)

sections = []
for i, (name, ps) in enumerate(groups.items()):
    seasons = sorted(set(p['season'] for p in ps), reverse=True)
    inner = []
    for season in seasons:
        order = {'Blaster / Value': 0, 'Mega': 1, 'Tin': 1, 'Hobby': 2, 'Hobby Jumbo': 3, 'Delight': 4}
        subset = sorted([p for p in ps if p['season'] == season], key=lambda p: order.get(p['format'], 99))
        inner.append(f'<div class="season-group"><h3>{season}</h3><div class="cards">{"".join(card(p) for p in subset)}</div></div>')
    sections.append(f'<section class="family family-{i % 6}"><div class="family-head"><div><span class="kicker">PRODUCT LINE</span><h2>{html.escape(name)}</h2></div><span>{len(ps)} formats</span></div>{"".join(inner)}</section>')

covered_ids = {o['product_id'] for o in latest.get('observations', []) if o.get('status') == 'VERIFIED'}
covered = len(covered_ids)
gaps = len(products) - covered
generated = html.escape(str(latest.get('generated_at') or 'Not collected yet'))

page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CardsInStock</title><style>
:root{{--bg:#080c14;--panel:#111824;--line:#263247;--text:#f5f7fb;--muted:#94a1b5;--accent:#65e6b5}}*{{box-sizing:border-box}}body{{margin:0;background:#080c14;color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:1500px;margin:auto;padding:28px 24px 70px}}header{{display:flex;justify-content:space-between;align-items:end;gap:20px}}h1{{margin:0;font-size:36px;letter-spacing:-1.4px}}.subtitle,.dim,.updated{{color:var(--muted)}}.updated{{font-size:11px;text-align:right}}.coverage{{display:inline-block;margin-top:7px;padding:6px 9px;border:1px solid var(--line);border-radius:999px;font-size:10px;color:#c8d3e3}}.coverage b{{color:var(--accent)}}.controls{{position:sticky;top:0;z-index:10;display:flex;gap:9px;margin:22px 0;padding:12px 0;background:rgba(8,12,20,.94);backdrop-filter:blur(10px)}}input,select{{background:#111824;color:var(--text);border:1px solid var(--line);border-radius:10px;padding:11px 13px}}input{{flex:1}}.family{{margin:38px 0 54px;border-radius:20px;padding:22px;background:linear-gradient(135deg,rgba(255,255,255,.045),rgba(255,255,255,.012));border:1px solid var(--line);border-top:4px solid var(--family)}}.family-0{{--family:#59d5e0}}.family-1{{--family:#a78bfa}}.family-2{{--family:#f4b860}}.family-3{{--family:#65e6b5}}.family-4{{--family:#f47b8a}}.family-5{{--family:#68a4ff}}.family-head{{display:flex;justify-content:space-between;align-items:end;padding-bottom:14px;border-bottom:1px solid var(--line)}}.family-head h2{{font-size:25px;margin:2px 0 0}}.family-head>span{{font-size:11px;color:var(--muted)}}.kicker{{font-size:9px;letter-spacing:.16em;color:var(--family);font-weight:900}}h3{{font-size:12px;letter-spacing:.12em;color:#aab5c6;margin:20px 0 10px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:14px}}.format-card{{overflow:hidden;background:var(--panel);border:1px solid var(--line);border-radius:15px}}.format-card.soldout,.format-card.unverified{{display:none}}.product-visual{{height:155px;background:#e9edf3;position:relative;display:flex;align-items:center;justify-content:center;overflow:hidden}}.product-visual img{{width:100%;height:100%;object-fit:contain;padding:8px}}.image-placeholder{{color:#172033;text-align:center;font-weight:950;font-size:22px}}.image-placeholder small{{display:block;font-size:8px;letter-spacing:.15em;margin-top:4px;color:#68758b}}.overlay{{position:absolute;left:9px;right:9px;top:9px;display:flex;justify-content:space-between;align-items:center;color:#101827;font-size:10px;font-weight:900}}.badge{{background:#0d1524;color:white;border-radius:999px;padding:6px 9px;letter-spacing:.08em}}.body{{padding:14px}}.best{{display:flex;justify-content:space-between;align-items:center;gap:10px}}.eyebrow{{font-size:8px;color:var(--accent);font-weight:900;letter-spacing:.12em}}.big{{font-size:26px;font-weight:950}}.buy{{background:var(--accent);color:#06130e;text-decoration:none;font-weight:950;font-size:11px;padding:10px 13px;border-radius:9px}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);border-radius:9px;margin:12px 0;overflow:hidden}}.metrics span{{text-align:center;padding:7px;border-right:1px solid var(--line)}}.metrics span:last-child{{border:0}}.metrics b,.metrics small{{display:block}}.metrics b{{font-size:12px}}.metrics small{{font-size:7px;color:var(--muted)}}.spec{{display:flex;flex-direction:column;gap:3px;color:var(--muted);font-size:10px;margin:9px 0}}.spec b{{color:#cbd4e2}}details{{border-top:1px solid var(--line);padding-top:9px}}summary{{display:flex;justify-content:space-between;cursor:pointer;font-size:10px;font-weight:800}}summary span{{color:var(--muted);font-weight:400}}.checks{{padding-top:5px}}.check{{display:flex;justify-content:space-between;gap:8px;font-size:9px;color:var(--muted);padding:7px 2px;border-bottom:1px dashed #253044;text-decoration:none;border-radius:5px}}.check:hover{{background:#182235;color:#e7edf7}}.check.verified{{color:#c7eadc}}.links{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}.textlink{{display:inline-block;color:var(--accent);font-size:10px;text-decoration:none;font-weight:800;margin-top:8px}}.textlink.ebay{{color:#a9b8ff}}.inactive-note{{font-size:10px;color:var(--muted);padding:10px 0}}body.show-all .format-card.soldout,body.show-all .format-card.unverified{{display:block;opacity:.72}}@media(max-width:650px){{main{{padding:18px 12px 50px}}header{{display:block}}.updated{{text-align:left;margin-top:8px}}.controls{{flex-wrap:wrap}}input{{flex-basis:100%}}.family{{padding:14px;margin:26px 0}}.cards{{grid-template-columns:1fr 1fr;gap:9px}}.product-visual{{height:120px}}.body{{padding:11px}}.big{{font-size:21px}}}}@media(max-width:430px){{.cards{{grid-template-columns:1fr}}.product-visual{{height:160px}}}}
</style></head><body><main><header><div><h1>CardsInStock</h1><div class="subtitle">Verified soccer wax deals. Scroll first, search when you need it.</div><div class="coverage"><b>{covered}/{len(products)}</b> formats currently have verified inventory · {gaps} coverage gaps</div></div><div class="updated">Showing verified in-stock products by default<br>Last collection: {generated}</div></header><div class="controls"><input id="q" placeholder="Search products…"><select id="season"><option value="">All seasons</option><option>2026-27</option><option>2025-26</option><option>2024-25</option><option>2023-24</option></select><select id="availability"><option value="available">In stock only</option><option value="all">Show unavailable / unverified</option></select></div>{''.join(sections)}<script>const q=document.querySelector('#q'),s=document.querySelector('#season'),a=document.querySelector('#availability');function f(){{document.body.classList.toggle('show-all',a.value==='all');let x=q.value.toLowerCase(),y=s.value;document.querySelectorAll('.format-card').forEach(c=>{{let base=(!x||c.dataset.search.includes(x))&&(!y||c.dataset.season===y);c.classList.toggle('filtered-out',!base);c.style.display=!base?'none':''}});document.querySelectorAll('.season-group').forEach(g=>{{let visible=[...g.querySelectorAll('.format-card')].some(c=>c.style.display!== 'none'&&(a.value==='all'||c.classList.contains('available')));g.style.display=visible?'':'none'}});document.querySelectorAll('.family').forEach(g=>g.style.display=[...g.querySelectorAll('.season-group')].some(x=>x.style.display!=='none')?'':'none')}}q.oninput=f;s.onchange=f;a.onchange=f;f();</script></main></body></html>'''

(ROOT / 'docs').mkdir(exist_ok=True)
(ROOT / 'docs/index.html').write_text(page)
(ROOT / 'docs/latest.json').write_text(json.dumps(latest, indent=2))
print(f'Built visual dashboard with {len(products)} products across {len(groups)} product families; {covered} have verified inventory')
