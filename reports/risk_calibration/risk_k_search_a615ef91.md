# ADR-063 — k search (leave-one-out)

- run_id: `a615ef91-eadd-4ebc-8dd3-91068d5c5b23` | stage: k_search
- execution_timestamp: 2026-10-16T13:19:16.630056+00:00
- window_years: [2023, 2024, 2025] | n_min_pares (comparator): 8
- k_grid: [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0]

## Mean absolute LOO error (pooled over years)

| casa | n | casa_only | adr062_rule | k=0.5 | k=1 | k=2 | k=4 | k=8 | k=16 | k=32 | k=64 | k=128 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| camara | 1332 | 0.280 | 0.271 | 0.274 | 0.273 | 0.272 | 0.271 | 0.271 | 0.272 | 0.273 | 0.274 | 0.276 |
| senado | 264 | 0.568 | 0.568 | 0.561 | 0.554 | 0.547 | 0.545 | 0.549 | 0.555 | 0.560 | 0.563 | 0.565 |

## Selected k (argmin, ties to larger k)

- camara: **k = 8.000** (by year: 2023: 16.000, 2024: 4.000, 2025: 4.000)
- senado: **k = 4.000** (by year: 2023: 4.000, 2024: 2.000, 2025: 4.000)

Fill `pooling.k` in the YAML with these values and run `--stage full`.
