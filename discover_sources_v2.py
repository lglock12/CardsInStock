import discover_sources
from matching import product_match

# Reuse the existing retailer-catalog scanner but make discovery obey the same
# exact-match rules as collection and market comparison.
discover_sources.product_match = product_match
for marker in ("royalty", "simplicidad"):
    if marker not in discover_sources.BAD_URL_MARKERS:
        discover_sources.BAD_URL_MARKERS.append(marker)

if __name__ == "__main__":
    discover_sources.main()
