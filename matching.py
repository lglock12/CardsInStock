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


SEASON_SLASH_RE = re.compile(
    r"\b(?:2023\s*/\s*24|2024\s*/\s*25|2025\s*/\s*26|2026\s*/\s*27|"
    r"23\s*/\s*24|24\s*/\s*25|25\s*/\s*26|26\s*/\s*27)\b"
)


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


def sealed_unit_signal(title):
    t = normalize(title)
    return bool(re.search(r"\bbox\b|\btin\b|\bdisplay\b|\bsealed\b", t)) or any(
        x in t for x in [
            "breaker delight", "breaker's delight", "breakers delight", "sapphire edition"
        ]
    )


def obvious_single_or_wrong_unit(title):
    """High-confidence evidence that a result is a card/lot/break, not sealed wax."""
    raw = html_lib.unescape(str(title or "")).lower().replace("’", "'")
    t = normalize(raw)

    if any(x in t for x in [
        "single card", "you pick", "pick your card", "choose your card", "card lot",
        "lot of cards", "team set", "complete set", "replacement card",
        "psa ", "bgs ", "sgc ", "cgc ", "graded", "gem mint",
    ]):
        return True

    # Do not confuse season notation (2024/25, 25/26, etc.) with a serial-numbered
    # card. Strip known soccer season tokens first, then detect /99, 22/99, 1/1, #/25.
    serial_text = SEASON_SLASH_RE.sub("", raw)
    if re.search(r"(?:#\s*)?\d{1,3}\s*/\s*\d{1,3}\b|#/\s*\d{1,3}\b", serial_text):
        return True

    # Any explicit break sale is not a sealed-box transaction. "Breaker's
    # Delight" is safe because it does not contain the standalone word "break".
    if re.search(r"\bbreak\b|\bbreak spot\b", t):
        return True

    # Reject multi-box/tin lots. We track the price of one sealed sale unit, not
    # cases, 2x/3x lots, or team spots from multi-box breaks. Explicit 1x is okay.
    if re.search(r"\b(?:[2-9]|[1-9]\d+)\s*x?\s*(?:sealed\s+|hobby\s+|mega\s+|value\s+)?(?:box(?:es)?|tins?)\b", t):
        return True
    if re.search(r"\b(?:[2-9]|[1-9]\d+)\s*x\b.*\b(?:box(?:es)?|tins?)\b", t):
        return True
    if re.search(r"\b(?:box(?:es)?|tins?)\s*x\s*(?:\(\s*)?(?:[2-9]|[1-9]\d+)(?:\s*\))?\b", t):
        return True
    if re.search(r"\b(?:box(?:es)?|tins?)\s*x\s*(?:\(\s*)?(?:[2-9]|[1-9]\d+)(?:\s*\))?\b", t):
        return True
    if re.search(r"\b(?:box|tin)\s+lot\b|\blot\s+(?:of\s+)?(?:[2-9]|[1-9]\d+)\b|\bcase\b", t):
        return True
    # Common eBay lot syntax: "LOT x (2) ... HOBBY BOX", "lot x2", "2-box lot".
    if re.search(r"\blot\s*x\s*(?:\(\s*)?(?:[2-9]|[1-9]\d+)(?:\s*\))?\b", t):
        return True
    if re.search(r"\b(?:[2-9]|[1-9]\d+)\s*[- ]?box(?:es)?\s+lot\b", t):
        return True

    # Card-level language is safe only when the title also clearly describes the
    # sealed container (e.g. "Hobby Box - 1 Autograph").
    card_level = bool(re.search(
        r"\b(?:autograph|auto|refractor|parallel|rookie|rc|variation|insert|patch|relic|single)\b",
        t,
    ))
    if card_level and not sealed_unit_signal(t):
        return True

    if pack_is_loose_product(t):
        return True
    return False


def product_match(product, title):
    t = normalize(title)
    expected = expected_text(product)

    if obvious_single_or_wrong_unit(title):
        return False, "matched a single card, break, or non-box sale unit"

    for marker in DISTINCT_PRODUCT_MARKERS:
        m = normalize(marker)
        if m in t and m not in expected:
            return False, "matched a different/untracked product or sale format"

    if not all(term_matches(term, t) for term in product["required_terms"]):
        return False, "missing required product terms"
    if any(reject_term_matches(term, t) for term in product["reject_terms"]):
        return False, "matched rejected format term"

    if not family_matches(product, title):
        return False, "matched a different product family"
    if not competition_matches(product, title):
        return False, "matched a different competition"
    if format_conflicts(product, title):
        return False, "matched a different box format"

    # Premium/retail formats whose name can also appear on individual cards must
    # explicitly look like sealed packaging before becoming VERIFIED.
    if product.get("format") in {"Sapphire", "Delight", "Box", "Full Box", "Tin", "Mega Tin"}:
        if not sealed_unit_signal(title):
            return False, "format matched but sealed box/tin packaging was not explicit"

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
    """Require the intended product line and block adjacent sealed product lines.

    Some brands legitimately include "Chrome" in their names (Merlin Chrome,
    Stadium Club Chrome), so generic Chrome must be the fallback family rather
    than winning merely because the word Chrome appears in the title.
    """
    family = expected_family(product)
    t = normalize(title)

    adjacent = {
        "stadium club": ["merlin", "finest", "inception", "museum", "deco"],
        "merlin": ["stadium club", "finest", "inception", "museum", "deco"],
        "finest": ["stadium club", "merlin", "inception", "museum", "deco", "chrome"],
        "inception": ["stadium club", "merlin", "finest", "museum", "deco", "chrome"],
        "museum": ["stadium club", "merlin", "finest", "inception", "deco", "chrome"],
        "deco": ["stadium club", "merlin", "finest", "inception", "museum", "chrome"],
        # Chrome is intentionally strict: titles such as "Chrome Merlin" are
        # Merlin products, not generic Topps Chrome.
        "chrome": ["stadium club", "merlin", "finest", "inception", "museum", "deco"],
    }

    if family == "flagship":
        return not any(x in t for x in [
            "stadium club", "chrome", "merlin", "finest", "sapphire",
            "pristine", "inception", "museum", "deco", "reverence", "definitive",
        ])

    if family not in t:
        return False
    return not any(marker in t for marker in adjacent.get(family, []))


def format_conflicts(product, title):
    t = normalize(title)
    fmt = product.get("format")
    if re.search(r"\bbreak\b|\bbreak spot\b", t):
        return True
    if re.search(r"\b(?:[2-9]|[1-9]\d+)\s*x?\s*(?:sealed\s+|hobby\s+|mega\s+|value\s+)?(?:box(?:es)?|tins?)\b", t):
        return True
    if re.search(r"\b(?:[2-9]|[1-9]\d+)\s*x\b.*\b(?:box(?:es)?|tins?)\b", t):
        return True
    if re.search(r"\b(?:box|tin)\s+lot\b|\blot\s+(?:of\s+)?(?:[2-9]|[1-9]\d+)\b", t):
        return True
    if re.search(r"\blot\s*x\s*(?:\(\s*)?(?:[2-9]|[1-9]\d+)(?:\s*\))?\b", t):
        return True
    if re.search(r"\b(?:[2-9]|[1-9]\d+)\s*[- ]?box(?:es)?\s+lot\b", t):
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


def is_plausible_sealed_listing(product, title):
    """True for exact or near-exact sealed product listings suitable for CHECK."""
    if not title or obvious_single_or_wrong_unit(title) or not sealed_unit_signal(title):
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
