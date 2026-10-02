# CardsInStock

Accuracy-first soccer wax price tracker.

## v0.1 goal

Prove that a small scheduled collector can reliably identify the **exact sealed box format**, current price, current stock state, and direct product URL across several reputable sellers.

### Rules

- Season + product + box format must all match.
- Hobby, Hobby Jumbo, Delight, Mega, and Blaster/Value are distinct products.
- Loose packs, cases, breaks, bundles, and sold/out-of-stock listings never count as the lowest purchasable price.
- Failed or ambiguous checks become `UNKNOWN`; stale data must not win the lowest-price calculation.
- Every observation includes a timestamp and source URL.
- v0.1 prioritizes accuracy over retailer coverage.

## Initial validation products

1. 2024-25 Topps Merlin UEFA — Hobby
2. 2024-25 Topps Chrome UEFA Club Competitions — Hobby Jumbo
3. 2025-26 Topps Merlin Premier League — Hobby
4. 2025-26 Topps Chrome Premier League — Mega
5. 2026-27 Topps Premier League Flagship — Hobby

The full catalog will expand only after repeated spot-checks show that the collector is trustworthy.
