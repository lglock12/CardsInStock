import discover_sources
from matching import product_match

# Reuse the existing retailer-catalog scanner but make discovery obey the same
# matcher as collection and market comparison. Premium lines such as Sapphire,
# Inception, Deco and Museum are now first-class catalog products, so URL words for
# those products must not be globally pruned before the matcher sees them.
discover_sources.product_match = product_match
discover_sources.BAD_URL_MARKERS[:] = [
    "women", "womens", "match-attax", "match_attax",
    "sticker", "starter-pack", "multipack", "multi-pack",
    "royalty", "simplicidad", "reverence", "definitive",
]

if __name__ == "__main__":
    discover_sources.main()
