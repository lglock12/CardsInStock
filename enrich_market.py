import json
from pathlib import Path

ROOT = Path(__file__).parent
MARKET = ROOT / "data" / "market_latest.json"
EBAY = ROOT / "data" / "ebay_latest.json"


def money(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def as_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def newest_market_inputs(product):
    prices = product.get("daily_prices") or []
    for row in sorted(prices, key=lambda x: str(x.get("date") or ""), reverse=True):
        metadata = row.get("metadata") or {}
        inputs = metadata.get("inputs") or {}
        if inputs.get("ebay_sold") or inputs.get("ebay_active"):
            return row, metadata, inputs
    return None, {}, {}


def sold_snapshot(metadata, sold):
    if not isinstance(sold, dict):
        return None
    sm = sold.get("metadata") or {}
    velocity = sm.get("sold_velocity") or {}
    recent = sm.get("recent_price_summary") or {}
    long_summary = sm.get("long_window_price_summary") or {}
    freshness = metadata.get("source_freshness_days") or {}
    stale_sources = metadata.get("stale_sources") or []

    count_30 = as_int(velocity.get("sold_count_30d"))
    median_30 = money(velocity.get("sold_median_30d"))
    if count_30 is None:
        count_30 = as_int(sm.get("recent_listing_count"))
    if median_30 is None:
        median_30 = money(recent.get("median"))

    return {
        "basis": "ebay_sold_aggregate",
        "fmv": money(sold.get("price")),
        "snapshot_date": sold.get("snapshot_date"),
        "updated_at": sold.get("updated_at"),
        "stale": "ebay_sold" in stale_sources,
        "freshness_days": as_int(freshness.get("ebay_sold")),
        "confidence": metadata.get("confidence"),
        "calculation_method": sm.get("calculation_method"),
        "count_7d": as_int(velocity.get("sold_count_7d")),
        "median_7d": money(velocity.get("sold_median_7d")),
        "count_21d": as_int(velocity.get("sold_count_21d")),
        "median_21d": money(velocity.get("sold_median_21d")),
        "count_30d": count_30,
        "median_30d": median_30,
        "min_30d": money(velocity.get("sold_min_30d") if velocity.get("sold_min_30d") is not None else recent.get("min")),
        "max_30d": money(velocity.get("sold_max_30d") if velocity.get("sold_max_30d") is not None else recent.get("max")),
        "long_window_days": as_int(sm.get("long_window_days")),
        "long_count": as_int(sm.get("long_window_listing_count") if sm.get("long_window_listing_count") is not None else long_summary.get("count")),
        "long_median": money(sm.get("long_window_median") if sm.get("long_window_median") is not None else long_summary.get("median")),
        "daily_rollups_30d": (sm.get("daily_sold_rollups_30d") or [])[-31:],
    }


def active_snapshot(metadata, active):
    if not isinstance(active, dict):
        return None
    freshness = metadata.get("source_freshness_days") or {}
    stale_sources = metadata.get("stale_sources") or []
    return {
        "basis": active.get("basis") or "unsold_floor",
        "floor": money(active.get("price")),
        "snapshot_date": active.get("snapshot_date"),
        "updated_at": active.get("updated_at"),
        "listing_count": as_int(active.get("total_listings")),
        "stale": "ebay_active" in stale_sources,
        "freshness_days": as_int(freshness.get("ebay_active")),
    }


def main():
    if not MARKET.exists():
        print("No market_latest.json to enrich")
        return

    data = json.loads(MARKET.read_text())
    sold_count = 0
    active_count = 0
    stale_active = 0

    for product in (data.get("products") or {}).values():
        _, metadata, inputs = newest_market_inputs(product)
        sold = sold_snapshot(metadata, inputs.get("ebay_sold"))
        active = active_snapshot(metadata, inputs.get("ebay_active"))
        if sold:
            product["sold_market"] = sold
            sold_count += 1
        else:
            product.pop("sold_market", None)
        if active:
            product["active_market"] = active
            active_count += 1
            if active.get("stale"):
                stale_active += 1
        else:
            product.pop("active_market", None)

    text = json.dumps(data, indent=2) + "\n"
    MARKET.write_text(text)
    EBAY.write_text(text)
    print(
        f"Market enrichment complete: {sold_count} sold aggregates, "
        f"{active_count} active-market freshness records, {stale_active} stale active snapshots"
    )


if __name__ == "__main__":
    main()
