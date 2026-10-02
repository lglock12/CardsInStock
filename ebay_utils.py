from urllib.parse import quote_plus


def canonical_terms(product):
    """Build a tight, human-readable eBay query for one sealed product SKU."""
    terms = [product["season"], "Topps"]
    name = product["product"].lower()

    if "merlin" in name:
        terms.append("Merlin")
    elif "chrome" in name:
        terms.append("Chrome")
    elif "finest" in name:
        terms.append("Finest")

    if "uefa" in name:
        terms.append("UEFA")
    elif "premier league" in name:
        terms.append("Premier League")

    fmt = product["format"]
    if fmt == "Blaster / Value":
        terms.extend(["Blaster", "box"])
    elif fmt == "Hobby Jumbo":
        terms.extend(["Jumbo", "box"])
    elif fmt == "Delight":
        terms.extend(["Delight", "box"])
    elif fmt == "Tin":
        terms.append("Tin")
    else:
        terms.extend([fmt, "box"])
    return terms


def quoted_query(product, season_override=None):
    terms = canonical_terms(product)
    if season_override:
        terms[0] = season_override
    quoted = " ".join(f'"{term}"' for term in terms)

    # Flagship searches are intentionally broad enough to catch listings that omit
    # the word "Flagship", so remove adjacent Topps product families at search time.
    name = product["product"].lower()
    if "flagship" in name:
        quoted += " -chrome -merlin -finest -sapphire -deco -museum -inception -pristine"
    return quoted


def search_url(product, season_override=None):
    query = quoted_query(product, season_override)
    # BIN only, new items, and Price + Shipping lowest first.
    return (
        "https://www.ebay.com/sch/i.html?_nkw=" + quote_plus(query)
        + "&LH_BIN=1&LH_ItemCondition=1000&_sop=15"
    )


def fallback_seasons(product):
    """Aliases used only if the primary exact-season eBay search yields no valid BIN."""
    season = product["season"]
    out = []
    if season == "2023-24":
        out.append("2023/24")
    elif season == "2024-25":
        out.append("2024/25")
    elif season == "2025-26":
        out.append("2025/26")
        if "premier league" in product["product"].lower():
            out.append("2026")
    elif season == "2026-27":
        out.append("2026/27")
    return out
