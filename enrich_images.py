import json
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).parent
LATEST=ROOT/'data/latest.json'
HEADERS={'User-Agent':'Mozilla/5.0 (compatible; CardsInStock/0.6; +https://github.com/lglock12/CardsInStock)','Accept-Language':'en-US,en;q=0.9'}

def image_from(url):
    try:
        r=requests.get(url,headers=HEADERS,timeout=12,allow_redirects=True)
        r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
        for selector,attr in [('meta[property="og:image"]','content'),('meta[name="twitter:image"]','content'),('meta[property="twitter:image"]','content')]:
            tag=soup.select_one(selector)
            if tag and tag.get(attr): return urljoin(r.url,tag.get(attr).strip())
    except Exception: pass
    return None

def main():
    if not LATEST.exists(): return
    data=json.loads(LATEST.read_text()); observations=data.get('observations',[]); by_product={}
    for o in observations:
        if o.get('status')=='VERIFIED': by_product.setdefault(o['product_id'],[]).append(o)
    images={}
    for pid,obs in by_product.items():
        for o in obs:
            img=image_from(o.get('final_url') or o.get('url'))
            if img:
                images[pid]=img; break
    data['product_images']=images
    LATEST.write_text(json.dumps(data,indent=2))
    print(f'Enriched {len(images)} product images')
if __name__=='__main__': main()
