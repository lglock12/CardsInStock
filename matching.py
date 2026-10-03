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
    expected = normalize(
        " ".join([
            product.get("product", ""),
            product.get("format", ""),
            *product.get("required_terms", []),
        ])
    )

    for marker in DISTINCT_PRODUCT_MARKERS:
        m = normalize(marker)
        if m in t and m not in expected:
            return False, "matched a different/untracked product or sale format"

    if not all(term_matches(term, t) for term in product["required_terms"]):
        return False, "missing required product terms"
    if any(reject_term_matches(term, t) for term in product["reject_terms"]):
        return False, "matched rejected format term"
    return True, "canonical product and format matched"
