import collector
from matching import product_match

# Reuse the mature retailer parsers/output pipeline while replacing only the matcher.
collector.product_match = product_match

if __name__ == "__main__":
    collector.main()
