import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
PRODUCTS = ROOT / "config" / "products.json"
SOURCES = ROOT / "config" / "sources.json"
RETAILERS = ROOT / "config" / "retailers.json"
DETAILS = ROOT / "config" / "product_details.json"
OUT = ROOT / "data" / "latest.json"
HISTORY = ROOT / "data" / "history.jsonl"
HEADERS = {"User-Agent":"Mozilla/5.0 (compatible; CardsInStock/0.4; +https://github.com/lglock12/CardsInStock)","Accept-Language":"en-US,en;q=0.9"}

def normalize(text):
    text=(text or "").lower().replace("/","-").replace("’","'")
    return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9' -]+"," ",text)).strip()

def term_matches(term,title):
    term=normalize(term); title=normalize(title)
    aliases={"2023-24":["2023-24","2023 24"],"2024-25":["2024-25","2024 25"],"2025-26":["2025-26","2025 26"],"2026-27":["2026-27","2026 27"],"uefa":["uefa","ucc","club competitions"],"premier league":["premier league","epl"],"value":["value","blaster"],"jumbo":["jumbo","hobby jumbo"]}
    # Topps and several retailers market the 2025-26 Premier League Chrome release
    # as simply "2026 Topps Chrome Premier League". Keep the generic season matcher
    # conservative; only accept bare 2026 when the title itself clearly says Premier League.
    if term == "2025-26" and ("premier league" in title or " epl " in f" {title} "):
        return any(normalize(x) in title for x in aliases[term]) or bool(re.search(r"(^| )2026( |$)", title))
    return any(normalize(x) in title for x in aliases.get(term,[term]))

def extract_jsonld(soup):
    out=[]
    for tag in soup.find_all("script",attrs={"type":"application/ld+json"}):
        try:
            p=json.loads(tag.string or tag.get_text()); out.extend(p if isinstance(p,list) else [p])
        except Exception: pass
    return out

def walk_json(obj):
    if isinstance(obj,dict):
        yield obj
        for v in obj.values(): yield from walk_json(v)
    elif isinstance(obj,list):
        for v in obj: yield from walk_json(v)

def product_match(product,title):
    if not all(term_matches(t,title) for t in product["required_terms"]): return False,"missing required product terms"
    t=normalize(title)
    if any(normalize(x) in t for x in product["reject_terms"]): return False,"matched rejected format term"
    return True,"canonical product and format matched"

def money(value):
    if value is None:return None
    m=re.search(r"([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)",str(value)); return float(m.group(1).replace(",","")) if m else None

def parse_page(url):
    r=requests.get(url,headers=HEADERS,timeout=25,allow_redirects=True); r.raise_for_status(); soup=BeautifulSoup(r.text,"html.parser")
    title=""; price=None; currency="USD"; availability="UNKNOWN"
    og=soup.find("meta",property="og:title")
    if og and og.get("content"): title=og["content"].strip()
    elif soup.find("h1"): title=soup.find("h1").get_text(" ",strip=True)
    elif soup.title:title=soup.title.get_text(" ",strip=True)
    for root in extract_jsonld(soup):
        for node in walk_json(root):
            if node.get("@type")=="Product" or "offers" in node:
                title=node.get("name") or title; offers=node.get("offers")
                if isinstance(offers,list):offers=offers[0] if offers else None
                if isinstance(offers,dict):
                    price=money(offers.get("price") or offers.get("lowPrice")) or price; currency=offers.get("priceCurrency") or currency; av=normalize(offers.get("availability",""))
                    if "instock" in av or "in stock" in av:availability="IN_STOCK"
                    elif any(x in av for x in ["outofstock","out of stock","soldout","sold out"]):availability="OUT_OF_STOCK"
    if price is None:
        for selector in ['meta[property="product:price:amount"]','meta[property="og:price:amount"]','meta[itemprop="price"]']:
            tag=soup.select_one(selector)
            if tag and tag.get("content"):
                price=money(tag.get("content"))
                if price is not None:break
    page_text=normalize(soup.get_text(" ",strip=True))
    if availability=="UNKNOWN":
        if any(x in page_text for x in ["currently out of stock","out of stock","sold out","currently unavailable","no longer available"]):availability="OUT_OF_STOCK"
        elif any(x in page_text for x in ["add to cart","add to bag","buy it now","only 1 left","in stock"]):availability="IN_STOCK"
    if price is None:
        h1=soup.find("h1"); scope=h1.parent.get_text(" ",strip=True) if h1 and h1.parent else page_text[:5000]; c=re.findall(r"\$\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{2})?)",scope)
        if c:price=money(c[0])
    return {"title":title,"price":price,"currency":currency,"availability":availability,"final_url":r.url,"http_status":r.status_code}

def shipping_for(seller,price,retailers):
    rule=retailers.get(seller,{})
    threshold=rule.get("free_shipping_threshold")
    if price is not None and threshold is not None and price>=threshold:return 0.0,"KNOWN"
    return None,"TBD"

def main():
    products=json.loads(PRODUCTS.read_text()); sources=json.loads(SOURCES.read_text()); retailers=json.loads(RETAILERS.read_text()) if RETAILERS.exists() else {}; details=json.loads(DETAILS.read_text()) if DETAILS.exists() else {}
    product_by_id={p["id"]:p for p in products}; checked=datetime.now(timezone.utc).isoformat(); observations=[]
    for source in sources:
        product=product_by_id[source["product_id"]]; obs={"checked_at":checked,"product_id":product["id"],"seller":source["seller"],"url":source["url"],"status":"UNKNOWN","price":None,"shipping":None,"delivered_price":None,"cost_per_pack":None,"currency":"USD","reason":""}
        try:
            page=parse_page(source["url"]); matched,reason=product_match(product,page["title"]); obs.update({"title":page["title"],"price":page["price"],"currency":page["currency"],"availability":page["availability"],"final_url":page["final_url"],"http_status":page["http_status"]})
            shipping,ship_status=shipping_for(source["seller"],page["price"],retailers); obs["shipping"]=shipping; obs["shipping_status"]=ship_status
            if shipping is not None and page["price"] is not None:obs["delivered_price"]=round(page["price"]+shipping,2)
            packs=details.get(product["id"],{}).get("packs_per_box"); basis=obs["delivered_price"] if obs["delivered_price"] is not None else page["price"]
            if packs and basis is not None:obs["cost_per_pack"]=round(basis/packs,2); obs["cost_per_pack_basis"]="delivered" if obs["delivered_price"] is not None else "item_price_shipping_tbd"
            if not matched:obs["status"],obs["reason"]="REJECTED",reason
            elif page["availability"]=="OUT_OF_STOCK":obs["status"],obs["reason"]="OUT_OF_STOCK","exact product matched but not purchasable"
            elif page["availability"]=="IN_STOCK" and page["price"] is not None:obs["status"],obs["reason"]="VERIFIED",reason
            else:obs["reason"]="could not verify both current price and purchasable stock"
        except Exception as exc:obs["reason"]=f"collector error: {type(exc).__name__}: {exc}"
        observations.append(obs)
    verified=[x for x in observations if x["status"]=="VERIFIED"]; lowest={}
    for obs in verified:
        # Prefer known delivered totals. Unknown shipping never silently beats a known delivered total.
        rank=(0,obs["delivered_price"]) if obs["delivered_price"] is not None else (1,obs["price"])
        current=lowest.get(obs["product_id"])
        current_rank=((0,current["delivered_price"]) if current and current.get("delivered_price") is not None else (1,current["price"])) if current else None
        if current is None or rank<current_rank:lowest[obs["product_id"]]=obs
    result={"generated_at":checked,"catalog_count":len(products),"verified_count":len(verified),"observation_count":len(observations),"lowest_verified":lowest,"observations":observations}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(result,indent=2))
    with HISTORY.open("a",encoding="utf-8") as f:
        for obs in observations:f.write(json.dumps(obs)+"\n")
    print(json.dumps(result,indent=2))
if __name__=="__main__":main()
