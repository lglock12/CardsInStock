import html
import json
from pathlib import Path

ROOT = Path(__file__).parent
products = json.loads((ROOT / "config/products.json").read_text())
latest_path = ROOT / "data/latest.json"
latest = json.loads(latest_path.read_text()) if latest_path.exists() else {"generated_at": None, "observations": [], "lowest_verified": {}}
obs_by_product = {}
for obs in latest.get("observations", []):
    obs_by_product.setdefault(obs["product_id"], []).append(obs)

rows = []
for p in products:
    obs = obs_by_product.get(p["id"], [])
    verified = sorted((o for o in obs if o.get("status") == "VERIFIED"), key=lambda x: x.get("price") or 10**9)
    low = verified[0] if verified else None
    if low:
        price = f'${low["price"]:,.2f}'
        seller = html.escape(low["seller"])
        buy = f'<a class="buy" href="{html.escape(low.get("final_url") or low["url"])}" target="_blank" rel="noopener">BUY</a>'
    else:
        price, seller, buy = "—", "No verified stock", ""
    status_parts = []
    for o in sorted(obs, key=lambda x: (x.get("status") != "VERIFIED", x.get("price") or 10**9)):
        icon = {"VERIFIED":"🟢", "OUT_OF_STOCK":"🔴", "REJECTED":"🚫", "UNKNOWN":"⚪"}.get(o.get("status"), "⚪")
        amount = f'${o["price"]:,.2f}' if o.get("price") is not None else "—"
        status_parts.append(f'{icon} {html.escape(o["seller"])} {amount}')
    details = " · ".join(status_parts) if status_parts else "No retailer mappings yet"
    rows.append(f'''<tr data-season="{p['season']}" data-search="{html.escape((p['product']+' '+p['format']).lower())}">
<td><strong>{p['season']}</strong></td><td>{html.escape(p['product'])}<div class="format">{html.escape(p['format'])}</div></td>
<td class="price">{price}<div class="seller">{seller}</div></td><td>{buy}</td><td class="details">{details}</td></tr>''')

generated = latest.get("generated_at") or "Not collected yet"
page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CardsInStock</title><style>
:root{{--bg:#0b1020;--card:#121a2d;--line:#26324c;--text:#eef3ff;--muted:#9eabc5;--accent:#6ee7b7}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:1200px;margin:auto;padding:22px}}
h1{{margin:0;font-size:28px}}.sub{{color:var(--muted);margin:5px 0 18px}}.controls{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px}}input,select{{background:var(--card);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:10px 12px;font-size:15px}}
.table{{overflow:auto;border:1px solid var(--line);border-radius:12px}}table{{width:100%;border-collapse:collapse;min-width:850px;background:var(--card)}}th,td{{padding:13px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:#172139;font-size:12px;text-transform:uppercase;color:var(--muted)}}
.format,.seller,.details{{color:var(--muted);font-size:12px;margin-top:3px}}.price{{font-weight:800;white-space:nowrap}}.buy{{display:inline-block;background:var(--accent);color:#07130e;text-decoration:none;font-weight:900;padding:8px 12px;border-radius:8px}}.details{{max-width:430px}}
@media(max-width:650px){{main{{padding:14px}}h1{{font-size:24px}}}}
</style></head><body><main><h1>CardsInStock</h1><div class="sub">Accuracy-first soccer wax tracker · {len(products)} products · Last collection: {html.escape(str(generated))}</div>
<div class="controls"><input id="q" placeholder="Search product…"><select id="season"><option value="">All seasons</option><option>2023-24</option><option>2024-25</option><option>2025-26</option><option>2026-27</option></select></div>
<div class="table"><table><thead><tr><th>Season</th><th>Product / Format</th><th>Lowest verified</th><th></th><th>Retailer checks</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<script>const q=document.querySelector('#q'),s=document.querySelector('#season'),rows=[...document.querySelectorAll('tbody tr')];function f(){{let x=q.value.toLowerCase(),y=s.value;rows.forEach(r=>r.style.display=(!x||r.dataset.search.includes(x))&&(!y||r.dataset.season===y)?'':'none')}}q.oninput=f;s.onchange=f;</script>
</main></body></html>'''
(ROOT / "docs").mkdir(exist_ok=True)
(ROOT / "docs/index.html").write_text(page)
(ROOT / "docs/latest.json").write_text(json.dumps(latest, indent=2))
print(f"Built dashboard with {len(products)} products")
