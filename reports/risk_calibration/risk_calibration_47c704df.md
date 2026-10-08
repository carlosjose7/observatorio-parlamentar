# ADR-062 — calibration report

- run_id: `47c704df-57f1-48d4-a45c-c67fe8d1bcf9`
- execution_timestamp: 2026-10-08T23:38:12.974337+00:00
- window_years: [2023, 2024, 2025] | n_min_pares: 8 | meses_min: 3.0 | w_min_aviso: 0.05

## CRITIC weights

| score | pooled | 2023 | 2024 | 2025 | range |
|---|---|---|---|---|---|
| C | 0.174 | 0.185 | 0.168 | 0.174 | 0.017 |
| D | 0.174 | 0.174 | 0.174 | 0.179 | 0.005 |
| E | 0.164 | 0.186 | 0.131 | 0.148 | 0.055 |
| A | 0.114 | 0.113 | 0.109 | 0.123 | 0.014 |
| N | 0.231 | 0.232 | 0.236 | 0.244 | 0.012 |
| V | 0.143 | 0.110 | 0.182 | 0.131 | 0.072 |

Below w_min_aviso (pooled): none

## 2023

- universe 535 | scored 535 | null-supplier value share 0.000
- Spearman(C, D): 0.217
- Spearman(V, ·): C=-0.153, D=0.112, E=-0.025, A=0.119, N=0.283
- D old vs new: Spearman 0.296, Jaccard top 0.241, mean rank shift 146.228, mean 0.541 -> 0.709
- R² ln(total): months 0.000 → +UF 0.065 → +house 0.137
- p90_p10: raw 4.264 | monthly 4.201 | residual 3.939
- p99_p1: raw 42.857 | monthly 44.482 | residual 42.104
- groups: 54 total, 35 below n_min {'camara': 8, 'senado': 27}; fallback share 0.279; flags {'ok': 533, 'janela_curta': 2}
- months in office: partial-year share 0.497, below meses_min 0.004, without interval 0

| n_min | Spearman vs base | Jaccard top vs base | fallback share |
|---|---|---|---|
| 5 | 0.964 | 0.862 | 0.164 |
| 8 | 1.000 | 1.000 | 0.279 |
| 10 | 0.936 | 0.742 | 0.389 |

## 2024

- universe 529 | scored 529 | null-supplier value share 0.000
- Spearman(C, D): 0.156
- Spearman(V, ·): C=-0.113, D=0.171, E=-0.045, A=0.149, N=0.242
- D old vs new: Spearman 0.303, Jaccard top 0.165, mean rank shift 139.403, mean 0.573 -> 0.720
- R² ln(total): months 0.039 → +UF 0.130 → +house 0.147
- p90_p10: raw 2.330 | monthly 2.195 | residual 2.085
- p99_p1: raw 13.412 | monthly 13.590 | residual 13.347
- groups: 54 total, 36 below n_min {'camara': 9, 'senado': 27}; fallback share 0.265; flags {'ok': 515, 'janela_curta': 14}
- months in office: partial-year share 0.043, below meses_min 0.026, without interval 0

| n_min | Spearman vs base | Jaccard top vs base | fallback share |
|---|---|---|---|
| 5 | 0.947 | 0.656 | 0.168 |
| 8 | 1.000 | 1.000 | 0.265 |
| 10 | 0.948 | 0.767 | 0.361 |

## 2025

- universe 553 | scored 553 | null-supplier value share 0.000
- Spearman(C, D): 0.191
- Spearman(V, ·): C=-0.093, D=0.112, E=-0.046, A=0.119, N=0.210
- D old vs new: Spearman 0.353, Jaccard top 0.287, mean rank shift 139.396, mean 0.582 -> 0.732
- R² ln(total): months 0.027 → +UF 0.095 → +house 0.095
- p90_p10: raw 2.069 | monthly 2.015 | residual 1.862
- p99_p1: raw 25.963 | monthly 22.005 | residual 20.046
- groups: 54 total, 29 below n_min {'camara': 2, 'senado': 27}; fallback share 0.166; flags {'ok': 548, 'janela_curta': 5}
- months in office: partial-year share 0.029, below meses_min 0.009, without interval 0

| n_min | Spearman vs base | Jaccard top vs base | fallback share |
|---|---|---|---|
| 5 | 0.998 | 0.931 | 0.145 |
| 8 | 1.000 | 1.000 | 0.166 |
| 10 | 0.903 | 0.556 | 0.344 |
