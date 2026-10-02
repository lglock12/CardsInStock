import html as html_lib
import re

# Distinct product lines / sale formats that must never be treated as the single
# sealed Topps soccer products CardsInStock tracks. These guards apply to both
# retailer discovery and market sources.
UNTRACKED_PRODUCT_MARKERS = [
    "women", "womens", "women's",
    "match attax",
    "sapphire",
    "pristine",
    "inception",
    "deco",
    "museum collection",
    "museum",
    "knockout",
    "royalty",
    "simplicidad",
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
        "2023-24": ["2023-24", "2023 24", "2023-2024", "2023 2024"],
        "2024-25": ["2024-25", "2024 25", "2024-2025", "2024 2025"],
        "2025-26": ["2025-26", "2025 26", "2025-2026", "2025 2026"],
        "2026-27": ["2026-27", "2026 27", "2026-2027", "2026 2027"],
        "uefa": ["uefa", "ucc", "club competitions"],
        "premier league": ["premier league", "epl", "english premier league"],
        "value": ["value", "blaster"],
        "jumbo": ["jumbo", "hobby jumbo"],
    }
    if term == "2025-26" and ("premier league" in title or " epl " in f" {title} "):
        return any(normalize(x) in title for x in aliases[term]) or bool(
            re.search(r"(^| )2026( |$)", title)
        )
    return any(normalize(x) in title for x in aliases.get(term, [term]))


def pack_is_loose_product(title):
    """Reject loose packs while allowing pack-count wording on a sealed box/tin.

    PASS: "7-Pack Blaster Box", "20 Packs Hobby Box", "Mega Tin".
    FAIL: "Blaster Pack", "Hobby Pack", "Mega Pack", "Single Pack".

    Accuracy-first rule: when a product title mentions pack(s), it must also name
    an actual sealed container (box or tin). Bundle/multipack/sticker sale formats
    are rejected separately by UNTRACKED_PRODUCT_MARKERS.
    """
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
    if any(normalize(marker) in t for marker in UNTRACKED_PRODUCT_MARKERS):
        return False, "matched a different/untracked product or sale format"
    if not all(term_matches(term, t) for term in product["required_terms"]):
        return False, "missing required product terms"
    if any(reject_term_matches(term, t) for term in product["reject_terms"]):
        return False, "matched rejected format term"
    return True, "canonical product and format matched"
