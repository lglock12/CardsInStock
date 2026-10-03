import json
from pathlib import Path

import collector
from matching import product_match

ROOT = Path(__file__).parent
BASE_DETAILS = ROOT / "config" / "product_details.json"
EXTRA_DETAILS = ROOT / "config" / "product_details_extra.json"
MERGED_DETAILS = ROOT / "data" / ".product_details_merged.json"

# Reuse the mature retailer parsers/output pipeline while replacing only the
# matcher and feeding it the expanded, source-validated box configurations.
collector.product_match = product_match


def prepare_details():
    merged = {}
    if BASE_DETAILS.exists():
        merged.update(json.loads(BASE_DETAILS.read_text()))
    if EXTRA_DETAILS.exists():
        merged.update(json.loads(EXTRA_DETAILS.read_text()))
    MERGED_DETAILS.parent.mkdir(parents=True, exist_ok=True)
    MERGED_DETAILS.write_text(json.dumps(merged, indent=2) + "\n")
    collector.DETAILS = MERGED_DETAILS


if __name__ == "__main__":
    prepare_details()
    collector.main()
