import html as html_lib
import re

# Adjacent product lines / sale formats. They are rejected unless the catalog SKU
# explicitly expects that marker. This lets us track premium lines as first-class
# products without allowing them to contaminate standard Chrome/Flagship.
DISTINCT_PRODUCT_MARKERS = [
    "women", "womens", "women's",
    "match attax",
    "stadium club",
    "sapphire",
    "pristine",
    "inception",
    "deco",
    "museum collection",
    "museum",
    "knockout",
    "royalty",
    "simplicidad",
    "reverence",
    "definitive",
    "sticker",
    "starter pack",
    "multipack",
    "multi pack",
    "pack set",
    "bundle",
]


def normalize(text):
    text = html_lib.unescape(str(text or ""))
    text = text.lower().replace("/", "-").replace("’", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' -]+", " ", text)).strip()


def expected_text(product):
    return normalize(
        " ".join([
            product.get("product", ""),
            product.get("format", ""),
            *product.get("required_terms", []),
        ])
    )


def term_matches(term, title):
    term = normalize(term)
    title = normalize(title)
    aliases = {
        "2023-24": ["2023-24", "2023 24", "2023-2024", "2023 2024", "2023/24"],
        "2024-25": ["2024-25", "2024 25", "2024-2025", "2024 2025", "2024/25"],
        "2025-26": ["2025-26", "2025 26", "2025-2026", "2025 2026", "2025/26"],
        "2026-27": ["2026-27", "2026 27", "2026-2027", "2026 2027", "2026/27"],
        "uefa": ["uefa", "ucc", "club competitions"],
        "uefa euro": ["uefa euro", "euro 2024", "euro 24"],
        "premier league": ["premier league", "epl", "english premier league"],
        "value": ["value", "blaster"],
        "jumbo": ["jumbo", "hobby jumbo"],
        "delight": ["delight", "breaker delight", "breaker's delight", "breakers delight"],
        "museum": ["museum", "museum collection"],
        "stadium club": ["stadium club", "stadium club chrome"],
        "full box": ["full box", "full display", "display box"],
        "mega tin": ["mega tin"],
    }
    if term == "2025-26" and ("premier league" in title or " epl " in f" {title} "):
        return any(normalize(x) in title for x in aliases[term]) or bool(
            re.search(r"(^| )2026( |$)", title)
        )
    return any(normalize(x) in title for x in aliases.get(term, [term]))


def pack_is_loose_product(title):
    """Reject loose packs while allowing pack-count wording on a sealed box/tin."""
    t = normalize(title)
    if not re.search(r"\bpacks?\b|multipack|multi pack", t):
        return False
    return not bool(re.search(r"\bbox\b|\btin\b", t))


def reject_term_matches(term, title):
    term = normalize(term)
    t = normalize(title)
    if term == "pack":
        return pack_is_loose_product(t)
    return term in t


def product_match(product, title):
    t = normalize(title)
    expected = expected_text(product)

    for marker in DISTINCT_PRODUCT_MARKERS:
        m = normalize(marker)
        if m in t and m not in expected:
            return False, "matched a different/untracked product or sale format"

    if not all(term_matches(term, t) for term in product["required_terms"]):
        return False, "missing required product terms"
    if any(reject_term_matches(term, t) for term in product["reject_terms"]):
        return False, "matched rejected format term"
    return True, "canonical product and format matched"


def expected_family(product):
    name = normalize(product.get("product"))
    # Stadium Club must be checked before generic Chrome.
    for marker in ("stadium club", "merlin", "finest", "inception", "museum", "deco", "chrome"):
        if marker in name:
            return marker
    return "flagship"


def competition_matches(product, title):
    name = normalize(product.get("product"))
    t = normalize(title)
    if "premier league" in name:
        return any(x in t for x in ["premier league", "english premier league", " epl "])
    if "uefa euro" in name:
        return "euro" in t and "uefa" in t
    if "uefa" in name:
        return any(x in t for x in ["uefa", " ucc ", "club competitions", "champions league"])
    return True


def family_matches(product, title):
    family = expected_family(product)
    t = normalize(title)
    if family == "flagship":
        return not any(x in t for x in [
            "stadium club", "chrome", "merlin", "finest", "sapphire",
            "pristine", "inception", "museum", "deco", "reverence", "definitive",
        ])
    return family in t


def format_conflicts(product, title):
    t = normalize(title)
    fmt = product.get("format")
    # A sealed Breaker's Delight box is a product, not a group break.
    if re.search(r"\b(?:group|team|player|random)\s+break\b|\bbreak spot\b", t):
        return True
    if "case" in t:
        return True
    if any(x in t for x in ["sticker", "starter pack", "multipack", "multi pack", "bundle"]):
        return True
    if fmt == "Hobby":
        return any(x in t for x in ["blaster", "value box", "mega box", "mega tin", "jumbo", "sapphire", "delight"])
    if fmt == "Blaster / Value":
        return any(x in t for x in ["hobby", "jumbo", "mega box", "mega tin", "sapphire", "delight"])
    if fmt == "Hobby Jumbo":
        return any(x in t for x in ["blaster", "value box", "mega box", "mega tin", "sapphire", "delight"])
    if fmt == "Sapphire":
        return "sapphire" not in t
    if fmt == "Delight":
        return not any(x in t for x in ["delight", "breaker delight", "breaker's delight", "breakers delight"])
    if fmt == "Tin":
        return "tin" not in t
    if fmt == "Mega Tin":
        return not ("mega" in t and "tin" in t)
    if fmt == "Full Box":
        return not any(x in t for x in ["full box", "full display", "display box"])
    return False


def _single_card_or_nonsealed(title):
    """High-confidence signals that a catalog result is not sealed wax."""
    raw = html_lib.unescape(str(title or "")).lower().replace("’", "'")
    t = normalize(raw)

    if any(x in t for x in [
        "single card", "you pick", "pick your card", "choose your card", "card lot",
        "lot of cards", "team set", "complete set", "replacement card",
        "psa ", "bgs ", "sgc ", "cgc ", "graded", "gem mint",
    ]):
        return True

    # Serial-numbered singles such as /99, 22/99, 1/1 or #/25 are not boxes.
    if re.search(r"(?:#\s*)?\d{1,3}\s*/\s*\d{1,3}\b|#/\s*\d{1,3}\b", raw):
        return True

    sealed_signal = bool(re.search(r"\bbox\b|\btin\b|\bdisplay\b|\bsealed\b", t))
    special_sealed = any(x in t for x in [
        "breaker delight", "breaker's delight", "breakers delight", "sapphire edition"
    ])

    # A lead without a packaging signal is too risky when its wording looks like a
    # card-level listing (autograph, refractor, parallel, rookie, numbered card, etc.).
    card_level = bool(re.search(
        r"\b(?:autograph|auto|refractor|parallel|rookie|rc|variation|insert|patch|relic|card)\b",
        t,
    ))
    if not (sealed_signal or special_sealed) and card_level:
        return True

    # For a loose "pack" to be a box lead, a sealed container must also be named.
    if pack_is_loose_product(t):
        return True

    # Potential-deal leads need some sealed-product signal. This intentionally
    # sacrifices dubious singles rather than presenting a fake $20 "box" bargain.
    return not (sealed_signal or special_sealed)


def is_plausible_sealed_listing(product, title):
    """Return True for exact or near-exact sealed product listings.

    This is looser than product_match only around retailer naming conventions. It is
    deliberately strict about product family, competition, format and sale unit so
    single cards and adjacent releases can never become a "possible deal".
    """
    if not title or _single_card_or_nonsealed(title):
        return False

    t = normalize(title)
    expected = expected_text(product)
    for marker in DISTINCT_PRODUCT_MARKERS:
        m = normalize(marker)
        if m in t and m not in expected:
            return False

    if not term_matches(product.get("season"), t):
        return False
    if not family_matches(product, t) or not competition_matches(product, t):
        return False
    if format_conflicts(product, t):
        return False
    return True


def plausible_product_lead(product, title):
    """Near-match suitable for a clickable CHECK lead, never for verified pricing."""
    if product_match(product, title)[0]:
        return False
    return is_plausible_sealed_listing(product, title)
