import html,json
from pathlib import Path
ROOT=Path(__file__).parent
products=json.loads((ROOT/'config/products.json').read_text())
details=json.loads((ROOT/'config/product_details.json').read_text()) if (ROOT/'config/product_details.json').exists() else {}
latest_path=ROOT/'data/latest.json'; latest=json.loads(latest_path.read_text()) if latest_path.exists() else {'generated_at':None,'observations':[]}
obs_by_product={}
for o in latest.get('observations',[]): obs_by_product.setdefault(o['product_id'],[]).append(o)

def money(v): return f'${v:,.2f}' if v is not None else '—'
def fmt_name(v):
    x=v.upper().replace(' / VALUE','').replace('HOBBY JUMBO','JUMBO')
    return 'BLASTER' if x in ('VALUE','BLASTER') else x

def card(p):
    obs=obs_by_product.get(p['id'],[])
    verified=[o for o in obs if o.get('status')=='VERIFIED']
    verified.sort(key=lambda o:(o.get('delivered_price') is None,o.get('delivered_price') if o.get('delivered_price') is not None else o.get('price',10**9)))
    low=verified[0] if verified else None; d=details.get(p['id'],{})
    checks=[]
    for o in sorted(obs,key=lambda x:(x.get('status')!='VERIFIED',x.get('price') or 10**9)):
        icon={'VERIFIED':'🟢','OUT_OF_STOCK':'🔴','REJECTED':'🚫','UNKNOWN':'⚪'}.get(o.get('status'),'⚪')
        label={'VERIFIED':'verified','OUT_OF_STOCK':'sold out','REJECTED':'blocked/rejected','UNKNOWN':'not verified'}.get(o.get('status'),'not verified')
        checks.append(f'<div class="check"><span>{icon} {html.escape(o["seller"])}</span><span>{money(o.get("price"))} · {label}</span></div>')
    packs=d.get('packs_per_box'); cards=d.get('cards_per_pack')
    config=f'{packs} packs × {cards} cards' if packs and cards else 'Box configuration pending'
    if d.get('bonus_cards'): config+=f' + {d["bonus_cards"]} bonus'
    hits=' · '.join('✓ '+html.escape(x) for x in d.get('guarantees',[])) or 'Guarantees pending validation'
    checklist=f'<a class="textlink" href="{html.escape(d["checklist_url"])}" target="_blank" rel="noopener">Checklist ↗</a>' if d.get('checklist_url') else '<span class="dim">Checklist pending</span>'
    if low:
        delivered=low.get('delivered_price'); price=low.get('price'); cpp=low.get('cost_per_pack'); seller=html.escape(low['seller']); url=html.escape(low.get('final_url') or low['url'])
        priceblock=f'<div class="best"><div><span class="eyebrow">BEST VERIFIED</span><div class="big">{money(delivered if delivered is not None else price)}</div><div class="dim">{seller}{" · delivered" if delivered is not None else " · item price"}</div></div><a class="buy" href="{url}" target="_blank" rel="noopener">BUY ↗</a></div>'
        metrics=f'<div class="metrics"><span><b>{money(price)}</b><small>ITEM</small></span><span><b>{money(low.get("shipping")) if low.get("shipping") not in (0,None) else ("FREE" if low.get("shipping")==0 else "TBD")}</b><small>SHIPPING</small></span><span><b>{money(cpp)}</b><small>$/PACK</small></span></div>'
        state='available'
    else:
        has_oos=any(o.get('status')=='OUT_OF_STOCK' for o in obs); state='soldout' if has_oos else 'unverified'
        title='SOLD OUT' if has_oos else 'NO VERIFIED PRICE'; sub='Mapped retailers currently show sold out.' if has_oos else 'Retailers are mapped, but no live price was verified.'
        priceblock=f'<div class="empty {state}"><b>{title}</b><span>{sub}</span></div>'; metrics=''
    return f'''<article class="format-card {state}" data-season="{p['season']}" data-search="{html.escape((p['product']+' '+p['season']+' '+p['format']).lower())}"><div class="cardtop"><span class="badge">{fmt_name(p['format'])}</span><span class="season">{p['season']}</span></div>{priceblock}{metrics}<div class="spec"><b>{config}</b><span>{hits}</span></div><details><summary>Retailer checks <span>{len(verified)} verified / {len(obs)} checked</span></summary><div class="checks">{''.join(checks) if checks else '<div class="dim">No retailer mappings yet</div>'}</div></details><div class="foot">{checklist}</div></article>'''

groups={}
for p in products: groups.setdefault(p['product'],[]).append(p)
sections=[]
for name,ps in groups.items():
    ps.sort(key=lambda p:(p['season'],['Blaster / Value','Mega','Hobby','Hobby Jumbo','Delight'].index(p['format']) if p['format'] in ['Blaster / Value','Mega','Hobby','Hobby Jumbo','Delight'] else 99),reverse=True)
    seasons=sorted(set(p['season'] for p in ps),reverse=True)
    inner=[]
    for season in seasons:
        cards=''.join(card(p) for p in ps if p['season']==season)
        inner.append(f'<div class="season-group"><h3>{season}</h3><div class="cards">{cards}</div></div>')
    sections.append(f'<section class="family" data-family="{html.escape(name.lower())}"><div class="family-head"><h2>{html.escape(name)}</h2><span>{len(ps)} formats tracked</span></div>{"".join(inner)}</section>')

generated=html.escape(str(latest.get('generated_at') or 'Not collected yet'))
page=f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CardsInStock</title><style>
:root{{--bg:#080d18;--panel:#101827;--panel2:#151f31;--line:#25334a;--text:#f2f6ff;--muted:#94a3ba;--accent:#62e6b3;--warn:#f5c451;--bad:#f07178}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(180deg,#0b1220 0,var(--bg) 420px);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}}main{{max-width:1440px;margin:auto;padding:30px 24px 70px}}header{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin-bottom:22px}}h1{{font-size:34px;letter-spacing:-1px;margin:0}}.subtitle{{color:var(--muted);margin-top:5px}}.updated{{font-size:12px;color:var(--muted);text-align:right}}.controls{{position:sticky;top:0;z-index:5;background:rgba(8,13,24,.94);backdrop-filter:blur(10px);display:flex;gap:10px;padding:12px 0 16px;margin-bottom:8px}}input,select{{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:11px 13px;font-size:14px}}input{{flex:1;min-width:180px}}.family{{margin-top:34px}}.family-head{{display:flex;align-items:baseline;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:9px}}h2{{font-size:22px;margin:0}}.family-head span,.dim{{color:var(--muted);font-size:12px}}.season-group h3{{font-size:13px;color:var(--muted);letter-spacing:.08em;margin:18px 0 9px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}}.format-card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px;min-width:0}}.format-card.available{{border-top:2px solid var(--accent)}}.format-card.soldout{{border-top:2px solid var(--bad)}}.format-card.unverified{{border-top:2px solid var(--warn)}}.cardtop,.best,.foot,summary,.check{{display:flex;justify-content:space-between;gap:10px;align-items:center}}.badge{{font-size:11px;font-weight:900;letter-spacing:.09em;background:#243149;border:1px solid #34445f;border-radius:999px;padding:5px 8px}}.season{{font-size:11px;color:var(--muted)}}.best{{margin:17px 0 13px}}.eyebrow{{font-size:9px;color:var(--accent);font-weight:900;letter-spacing:.1em}}.big{{font-size:27px;font-weight:900;line-height:1.1;margin-top:2px}}.buy{{background:var(--accent);color:#07150f;text-decoration:none;font-weight:900;font-size:12px;padding:10px 13px;border-radius:9px}}.metrics{{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--line);border-radius:9px;overflow:hidden;margin-bottom:12px}}.metrics span{{padding:8px;text-align:center;border-right:1px solid var(--line)}}.metrics span:last-child{{border:0}}.metrics b,.metrics small{{display:block}}.metrics b{{font-size:13px}}.metrics small{{font-size:8px;color:var(--muted);margin-top:2px}}.spec{{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--muted);padding:3px 0 11px}}.spec b{{color:#cbd5e5;font-weight:650}}details{{border-top:1px solid var(--line);padding-top:10px}}summary{{cursor:pointer;font-size:11px;font-weight:750}}summary span{{font-weight:400;color:var(--muted)}}.checks{{padding-top:9px}}.check{{font-size:10px;color:var(--muted);padding:5px 0;border-bottom:1px dashed #202c40}}.check:last-child{{border:0}}.foot{{margin-top:10px}}.textlink{{color:var(--accent);text-decoration:none;font-size:11px;font-weight:800}}.empty{{margin:17px 0 14px;border-radius:9px;padding:13px;display:flex;flex-direction:column;gap:3px}}.empty b{{font-size:12px}}.empty span{{font-size:10px;color:var(--muted)}}.empty.soldout{{background:rgba(240,113,120,.08);border:1px solid rgba(240,113,120,.25)}}.empty.unverified{{background:rgba(245,196,81,.07);border:1px solid rgba(245,196,81,.23)}}@media(max-width:650px){{main{{padding:20px 13px 50px}}header{{display:block}}.updated{{text-align:left;margin-top:9px}}.controls{{flex-wrap:wrap}}select{{flex:1}}.cards{{grid-template-columns:1fr}}}}
</style></head><body><main><header><div><h1>CardsInStock</h1><div class="subtitle">Soccer wax prices, organized the way collectors shop.</div></div><div class="updated">{len(products)} formats tracked<br>Last collection: {generated}</div></header><div class="controls"><input id="q" placeholder="Search Merlin, Chrome, Premier League…"><select id="season"><option value="">All seasons</option><option>2026-27</option><option>2025-26</option><option>2024-25</option><option>2023-24</option></select><select id="availability"><option value="">All availability</option><option value="available">Verified in stock</option><option value="soldout">Sold out</option><option value="unverified">Not verified</option></select></div>{''.join(sections)}<script>const q=document.querySelector('#q'),s=document.querySelector('#season'),a=document.querySelector('#availability');function filter(){{let x=q.value.toLowerCase(),y=s.value,z=a.value;document.querySelectorAll('.format-card').forEach(c=>{{let show=(!x||c.dataset.search.includes(x))&&(!y||c.dataset.season===y)&&(!z||c.classList.contains(z));c.style.display=show?'':'none'}});document.querySelectorAll('.season-group').forEach(g=>g.style.display=[...g.querySelectorAll('.format-card')].some(c=>c.style.display!=='none')?'':'none');document.querySelectorAll('.family').forEach(f=>f.style.display=[...f.querySelectorAll('.format-card')].some(c=>c.style.display!=='none')?'':'none')}}q.oninput=filter;s.onchange=filter;a.onchange=filter;</script></main></body></html>'''
(ROOT/'docs').mkdir(exist_ok=True);(ROOT/'docs/index.html').write_text(page);(ROOT/'docs/latest.json').write_text(json.dumps(latest,indent=2));print(f'Built dashboard with {len(products)} products across {len(groups)} product families')
