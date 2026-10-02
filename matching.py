import html as html_lib
import re

# Distinct Topps soccer lines that must never be treated as the standard products
# CardsInStock tracks. These guards apply to retailer discovery and market sources.
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
]

SEALED_FORMAT_MARKERS = [
    "box", "blaster", "value", "mega", "jumbo", "hobby", "delight", "tin"
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
    """Reject loose/single packs without rejecting box titles that mention pack count.

    Example that must PASS: "7-Pack Blaster Box".
    Example that must FAIL: "Hobby Pack" / "Single Pack".
    """
    t = normalize(title)
    if "pack" not in t:
        return False

    # A title that explicitly says it is a sealed box/tin format can safely mention
    # how many packs it contains.
    if "box" in t or "tin" in t:
        return False

    loose_phrases = [
        "single pack", "1 pack", "one pack", "loose pack", "individual pack",
        "pack only", "hobby pack", "retail pack", "value pack", "jumbo pack",
    ]
    if any(phrase in t for phrase in loose_phrases):
        return True

    # If pack is present but no sealed-container word is present, be conservative.
    return not any(marker in t for marker in SEALED_FORMAT_MARKERS if marker != "hobby")


def reject_term_matches(term, title):
    term = normalize(term)
    t = normalize(title)
    if term == "pack":
        return pack_is_loose_product(t)
    return term in t


def product_match(product, title):
    t = normalize(title)
    if any(normalize(marker) in t for marker in UNTRACKED_PRODUCT_MARKERS):
        return False, "matched a different/untracked Topps soccer product line"
    if not all(term_matches(term, t) for term in product["required_terms"]):
        return False, "missing required product terms"
    if any(reject_term_matches(term, t) for term in product["reject_terms"]):
        return False, "matched rejected format term"
    return True, "canonical product and format matched"
