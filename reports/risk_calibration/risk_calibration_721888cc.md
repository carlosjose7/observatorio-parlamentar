# ADR-062 — calibration report

- run_id: `721888cc-ffec-4494-8859-e011e42f1d19`
- execution_timestamp: 2026-10-16T13:19:48.155762+00:00
- window_years: [2023, 2024, 2025] | n_min_pares: 8 | meses_min: 3.0 | w_min_aviso: 0.05

## CRITIC weights

| score | pooled | 2023 | 2024 | 2025 | range |
|---|---|---|---|---|---|
| C | 0.173 | 0.186 | 0.164 | 0.176 | 0.021 |
| D | 0.172 | 0.174 | 0.170 | 0.180 | 0.010 |
| E | 0.164 | 0.186 | 0.128 | 0.149 | 0.059 |
| A | 0.121 | 0.111 | 0.132 | 0.119 | 0.021 |
| N | 0.229 | 0.233 | 0.229 | 0.244 | 0.016 |
| V | 0.141 | 0.110 | 0.177 | 0.131 | 0.067 |

Below w_min_aviso (pooled): none

## 2023

- universe 535 | scored 535 | null-supplier value share 0.000
- Spearman(C, D): 0.217
- Spearman(V, ·): C=-0.153, D=0.112, E=-0.025, A=0.123, N=0.283
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
- Spearman(V, ·): C=-0.113, D=0.171, E=-0.045, A=0.152, N=0.242
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
- Spearman(V, ·): C=-0.093, D=0.112, E=-0.046, A=0.116, N=0.210
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

## ADR-063 — partial pooling

- k: camara=8.000, senado=4.000 | LOO argmin: camara=8.000, senado=4.000 | k equals argmin: {'camara': True, 'senado': True}

### A1 — UF share of the residual z (R² on UF dummies)

| year | casa | ADR-062 rule | pooled | strict | pass |
|---|---|---|---|---|---|
| 2023 | camara | 0.064 | 0.086 | True | False |
| 2023 | senado | 0.243 | 0.069 | False | True |
| 2024 | camara | 0.050 | 0.052 | True | False |
| 2024 | senado | 0.504 | 0.277 | False | True |
| 2025 | camara | 0.055 | 0.053 | True | True |
| 2025 | senado | 0.387 | 0.265 | False | True |

### A1-LOO — same comparison on out-of-sample residuals (informative, not part of the verdict)

| year | casa | ADR-062 rule | pooled | casa_only | pass |
|---|---|---|---|---|---|
| 2023 | camara | 0.075 | 0.068 | 0.123 | True |
| 2023 | senado | 0.243 | 0.061 | 0.243 | True |
| 2024 | camara | 0.046 | 0.052 | 0.100 | False |
| 2024 | senado | 0.506 | 0.270 | 0.506 | True |
| 2025 | camara | 0.047 | 0.053 | 0.070 | False |
| 2025 | senado | 0.388 | 0.254 | 0.388 | True |

### A2 — leave-one-out error (pooled over years)

| casa | k | error k | casa_only | ADR-062 rule | pass |
|---|---|---|---|---|---|
| camara | 8.000 | 0.271 | 0.280 | 0.271 | False |
| senado | 4.000 | 0.545 | 0.568 | 0.568 | True |

**A1: FAIL · A2: FAIL → criteria NOT met (ADR-063, item 9: rule of ADR-062 stands)**

### CRITIC weights (pooled): ADR-062 V vs pooled V

| score | ADR-062 V | pooled V |
|---|---|---|
| C | 0.173 | 0.173 |
| D | 0.172 | 0.171 |
| E | 0.164 | 0.164 |
| A | 0.121 | 0.121 |
| N | 0.229 | 0.227 |
| V | 0.141 | 0.144 |

### Per year

- 2023: V pooled vs V — Spearman 0.923, Jaccard top 0.479, mean rank shift 31.705; lambda_u {'camara': {'groups': 27, 'groups_below_half': 8, 'quantiles': {'p5': 0.39780219780219783, 'p25': 0.4666666666666667, 'p50': 0.5294117647058824, 'p75': 0.7150000000000001, 'p95': 0.85}}, 'senado': {'groups': 27, 'groups_below_half': 10, 'quantiles': {'p5': 0.3619047619047619, 'p25': 0.42857142857142855, 'p50': 0.5, 'p75': 0.5, 'p95': 0.5388888888888889}}}
- 2024: V pooled vs V — Spearman 0.939, Jaccard top 0.413, mean rank shift 27.440; lambda_u {'camara': {'groups': 27, 'groups_below_half': 9, 'quantiles': {'p5': 0.38461538461538464, 'p25': 0.4666666666666667, 'p50': 0.5294117647058824, 'p75': 0.7066666666666667, 'p95': 0.8523844460748349}}, 'senado': {'groups': 27, 'groups_below_half': 21, 'quantiles': {'p5': 0.3619047619047619, 'p25': 0.42857142857142855, 'p50': 0.42857142857142855, 'p75': 0.42857142857142855, 'p95': 0.5}}}
- 2025: V pooled vs V — Spearman 0.900, Jaccard top 0.623, mean rank shift 34.156; lambda_u {'camara': {'groups': 27, 'groups_below_half': 2, 'quantiles': {'p5': 0.45, 'p25': 0.5, 'p50': 0.5294117647058824, 'p75': 0.7150000000000001, 'p95': 0.855448275862069}}, 'senado': {'groups': 27, 'groups_below_half': 25, 'quantiles': {'p5': 0.3333333333333333, 'p25': 0.42857142857142855, 'p50': 0.42857142857142855, 'p75': 0.42857142857142855, 'p95': 0.47857142857142854}}}
