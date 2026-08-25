"""api/schemas/_common.py — tipos compartilhados entre contratos de resposta.

`Moeda` corrige o comportamento padrão do Pydantic v2, que serializa `Decimal`
como *string* em JSON (`"150.30"`), não como número (`150.3`). O uso de
`Decimal` internamente (precisão) é preservado — o encoder JSON é o único
ponto afetado, via `PlainSerializer(when_used="json")`.

Bug de origem: `GET /parlamentares/{id}/gastos`, `GET /anomalias` e
`GET /fornecedores/{cnpj_cpf_valor}` emitiam `valor_liquido`/`valor_glosa`/
`valor_liquido_total`/`total_gasto` como string JSON. O dashboard (`ui.py:
formatar_moeda`) espera `float`, causando `ValueError: Unknown format code
'f' for object of type 'str'` em `02_parlamentar.py`, `05_fornecedor.py` e
`07_anomalias.py` (as páginas `03_partido.py`/`04_estado.py` não quebravam
por já aplicarem `float(...)` defensivamente antes de consumir o campo).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import PlainSerializer

Moeda = Annotated[
    Decimal,
    PlainSerializer(lambda v: float(v), return_type=float, when_used="json"),
]
