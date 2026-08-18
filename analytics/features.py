"""analytics/features.py — Contrato da Feature Store (ADR-028).

Implementa o ADR-028 (Sprint 5/Onda 1): o `feature_store/registry.yaml`
deixa de ser scaffold vazio e passa a ser a fonte única de metadados de
features, validável por Pydantic. Nenhuma feature é criada sem registro —
o contrato garante que uma feature só entra no pipeline se tiver nome,
descrição, fórmula, origem, tipo, categoria e consumidores.

O registro distingue `feature` (valor cujo grão persiste em
`ml_staging`/Gold) de `função derivada` (categoria `funcao` — fórmula
reutilizável, ex: normalização Min-Max, que produz features). Features de
categoria `agregado`, `ml` ou `composicao` exigem `tabela` de origem
não vazia (evita feature órfã — ADR-028.5).

Primeiro registro (ADR-027/028): as 5 fórmulas de score do §9, o
`risk_index` (composição) e as funções derivadas `minmax` e
`regra_anomalia`.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "feature_store" / "registry.yaml"

_NOME_FEATURE_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: Categorias de feature — contrato ADR-028.2. Apenas `funcao` não persiste.
_FUNCAO_DERIVADA_SEM_TABELA = "funcao"


class FeatureCategoria(str, Enum):
    """Categoria de uma feature registrada (ADR-028.2)."""

    AGREGADO = "agregado"
    ML = "ml"
    COMPOSICAO = "composicao"
    FUNCAO = "funcao"


class Feature(BaseModel):
    """Metadados de uma feature registrada na Feature Store (ADR-028).

    Attributes:
        nome: Identificador snake_case, único no registry.
        descricao: Descrição em português (preferencialmente com a
            fórmula em linguagem natural).
        formula: Referência a ADR/seção ou expressão computável.
        origem: Camada/tabela fonte da feature — convenção
            `bronze_*`, `silver_*`, `ml_staging.*`, `fact_*`,
            `calculado`.
        tipo: Tipo do valor (Python/duckdb), ex: `float`, `Decimal`,
            `bool`.
        categoria: Enum do ADR-028.2.
        tabela: Tabela donde o valor é lido/computado. Obrigatória para
            categorias != `funcao` (ADR-028.3).
        ultima_atualizacao: Data ISO do último cálculo (null até ser
            calculada).
        consumidores: Lista de tabelas/models/features que consomem a
            feature (ex: `risk_scores`, `risk_index`).
    """

    model_config = ConfigDict(extra="forbid")

    nome: str
    descricao: str
    formula: str
    origem: str
    tipo: str
    categoria: FeatureCategoria
    tabela: str | None = Field(default=None)
    ultima_atualizacao: str | None = Field(default=None)
    consumidores: list[str] = Field(default_factory=list)

    @field_validator("nome")
    @classmethod
    def _validar_nome(cls, v: str) -> str:
        """Torna `nome` rigoroso — snake_case, sem caracteres estranhos."""
        if not _NOME_FEATURE_RE.match(v):
            raise ValueError(
                f"nome inválido '{v}' — use snake_case (letras minúsculas, "
                "dígitos e underscore)"
            )
        return v

    @model_validator(mode="after")
    def _exigir_tabela_quando_persistente(self) -> Feature:
        """Feature persistente sem origem concreta é feature órfã (ADR-028.5)."""
        if self.categoria != FeatureCategoria.FUNCAO and not self.tabela:
            raise ValueError(
                f"feature '{self.nome}' (categoria {self.categoria.value}) exige "
                f"'tabela' de origem não vazia — ADR-028.3"
            )
        return self


class FeatureRegistry(BaseModel):
    """Contrato do `feature_store/registry.yaml` (ADR-028.1).

    O arquivo é a fonte única de metadados de features; a classe valida o
    YAML na carga e em testes. Nomes duplicados e features órfãs falham a
    validação.
    """

    model_config = ConfigDict(extra="forbid")

    features: list[Feature] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validar_unicidade_nomes(self) -> FeatureRegistry:
        """Nomes de feature são únicos no registry (ADR-028.3)."""
        nomes = [f.nome for f in self.features]
        duplicados = sorted({n for n in nomes if nomes.count(n) > 1})
        if duplicados:
            raise ValueError(
                f"nomes de feature duplicados: {duplicados} — cada feature "
                "deve ter nome único no registry"
            )
        return self

    def obter(self, nome: str) -> Feature | None:
        """Busca uma feature pelo nome.

        Args:
            nome: Nome da feature procurada.

        Returns:
            A feature correspondente, ou `None` se não existir.
        """
        for feature in self.features:
            if feature.nome == nome:
                return feature
        return None


def carregar_registry(path: Path | None = None) -> FeatureRegistry:
    """Carrega e valida o `feature_store/registry.yaml` (ADR-028.1).

    Args:
        path: Caminho do registry. Padrão é o do repositório
            (`feature_store/registry.yaml`).

    Returns:
        `FeatureRegistry` validado, ou registry vazio se o YAML não
        declarar `features`.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
        pydantic.ValidationError: Se o conteúdo não respeitar o contrato.
    """
    caminho = path or REGISTRY_PATH
    if not caminho.exists():
        raise FileNotFoundError(f"Feature registry ausente: {caminho}")
    with caminho.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return FeatureRegistry.model_validate(raw)
