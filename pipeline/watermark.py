"""pipeline/watermark.py — armazenamento do estado de watermark por fonte.

versionamento.md §5: o watermark é **sempre** lido de um armazenamento de
estado (ex: Airflow Variable / pipeline_runs), nunca inferido do conteúdo das
camadas. Esta camada abstrai o armazenamento para manter os extractors puros
(testáveis sem Airflow) e permitir execução local com `JsonFileStore`.

Implementações:
- `AirflowVariableStore`: produção — grava em Airflow Variable (JSON com
  `last_watermark` e `run_id`, conforme versionamento.md §2.1).
- `JsonFileStore`: desenvolvimento e testes — arquivos JSON sob
  `data/bronze/watermarks/`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[1]


class WatermarkState(BaseModel):
    """Estado persistido de watermark de uma fonte (versionamento.md §2.1).

    Attributes:
        last_watermark: Último valor consolidado (data, ano ou mês).
        run_id: Execução que consolidou o watermark atual.
    """

    last_watermark: str | None = None
    run_id: UUID | None = None


class WatermarkStore(Protocol):
    """Contrato de persistência do estado de watermark."""

    def get(self, key: str) -> WatermarkState:
        """Retorna o estado atual (vazio se nunca gravado)."""
        ...

    def set(self, key: str, state: WatermarkState) -> None:
        """Persiste o estado atual."""
        ...


class JsonFileStore:
    """Armazenamento local em JSON — desenvolvimento e testes.

    Um arquivo por chave de watermark, ex: `watermark_camara_despesas.json`.
    """

    def __init__(self, root: Path | None = None):
        self.root = root or (REPO_ROOT / "data" / "bronze" / "watermarks")

    def _caminho(self, key: str) -> Path:
        nome_seguro = key.replace("/", "_").replace("\\", "_")
        return self.root / f"{nome_seguro}.json"

    def get(self, key: str) -> WatermarkState:
        caminho = self._caminho(key)
        if not caminho.exists():
            return WatermarkState()
        return WatermarkState.model_validate_json(caminho.read_text(encoding="utf-8"))

    def set(self, key: str, state: WatermarkState) -> None:
        caminho = self._caminho(key)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(state.model_dump_json(indent=2), encoding="utf-8")


class NamespaceWatermarkStore:
    """Wrapper que isola o estado de watermark sob um namespace.

    Usado no modo de validação (Opção B): as chaves são prefixadas, então a
    carga de validação nunca lê nem contamina o watermark de produção. Ex:
    `watermark_senado` → `validacao:watermark_senado` (JsonFileStore grava em
    `validacao_watermark_senado.json`; AirflowVariableStore usa a chave
    prefixada como nome da Variable).
    """

    def __init__(self, base: WatermarkStore, namespace: str):
        self._base = base
        self._namespace = namespace

    def _chave(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    def get(self, key: str) -> WatermarkState:
        return self._base.get(self._chave(key))

    def set(self, key: str, state: WatermarkState) -> None:
        self._base.set(self._chave(key), state)


class AirflowVariableStore:
    """Armazena watermark em Airflow Variable — produção.

    Import do Airflow é lazy: o módulo continua importável (e testável)
    mesmo sem Airflow instalado. O JSON persistido segue o formato de
    versionamento.md §2.1 (`{"last_watermark": ..., "run_id": ...}`).
    """

    def get(self, key: str) -> WatermarkState:
        from airflow.models import Variable

        raw = Variable.get(key, default_var=None, deserialize_json=False)
        if not raw:
            return WatermarkState()
        return WatermarkState.model_validate_json(raw)

    def set(self, key: str, state: WatermarkState) -> None:
        from airflow.models import Variable

        Variable.set(key, state.model_dump_json(), serialize_json=False)
