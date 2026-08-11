"""api/schemas/agent.py — contratos agent-ready (Sprint 6, Onda 4; RF-05/§11).

JSON **semântico** para consumo por LLMs (ADR-032): payloads aninhados com
métricas nomeadas conforme a Camada Semântica (§8) e scores de risco (§9/
ADR-027) — não espelham os endpoints de negócio. Leitura read-only do Gold
(ADR-026); nenhuma métrica analítica é recalculada por request (ADR-030).

`taxa_ausencia`/`indice_alinhamento` (§8) ficam FORA por decisão de escopo do
ADR-032: dependem de `fact_presenca`/`fact_votacao`, ainda inexistentes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Rigido(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ── /agent/parlamentar/{id} ─────────────────────────────────────


class MetricasParlamentar(_Rigido):
    """Métricas da Camada Semântica §8 no grão do parlamentar (Gold)."""

    total_gasto: float | None
    gasto_medio: float | None
    num_transacoes: int
    num_fornecedores: int | None
    valor_maximo: float | None
    valor_mediano: float | None
    percentil_95: float | None
    hhi_recente: float | None
    hhi_periodo: int | None


class RiscoParlamentar(_Rigido):
    """Scores e risk_index do período mais recente (`risk_scores`, ADR-027/029)."""

    periodo: int
    supplier_concentration_score: float
    political_exposure_score: float
    supplier_dependency_score: float
    expense_anomaly_score: float
    network_influence_score: float
    risk_index: float


class AnomaliasParlamentar(_Rigido):
    """Resumo de anomalias do parlamentar (`expense_outliers`, ADR-002)."""

    num_despesas_anomalas: int
    proporcao: float | None


class FornecedorTop(_Rigido):
    """Um fornecedor do top por valor gasto pelo parlamentar."""

    id_fornecedor: int
    nome_fornecedor: str
    total_gasto: float | None
    num_transacoes: int


class AgentParlamentar(_Rigido):
    """Contexto semântico agregado de um parlamentar (perfil + métricas + risco)."""

    id_parlamentar: int
    fonte: str
    nome: str
    sigla_partido: str | None
    sigla_uf: str | None
    situacao_normalizada: str | None
    periodo_vigente_desde: str | None
    metricas: MetricasParlamentar
    risco: RiscoParlamentar | None
    anomalias: AnomaliasParlamentar
    top_fornecedores: list[FornecedorTop]


# ── /agent/fornecedor/{cnpj_cpf_valor} ──────────────────────────


class MetricasFornecedor(_Rigido):
    """Agregados do fornecedor sobre `fact_despesa` (Gold)."""

    total_recebido: float | None
    gasto_medio: float | None
    valor_maximo: float | None
    num_transacoes: int
    num_parlamentares: int | None


class ParlamentarTop(_Rigido):
    """Um parlamentar do top por valor recebido pelo fornecedor."""

    id_parlamentar: int
    nome: str
    total_gasto: float | None
    num_transacoes: int


class AgentFornecedor(_Rigido):
    """Contexto semântico agregado de um fornecedor (CNPJ claro / CPF HMAC, ADR-011)."""

    id_fornecedor: int
    cnpj_cpf_valor: str | None
    tipo_documento: str | None
    nome_fornecedor: str
    metricas: MetricasFornecedor
    top_parlamentares: list[ParlamentarTop]


# ── /agent/anomalias ────────────────────────────────────────────


class AnomaliaPorAno(_Rigido):
    ano: int
    quantidade: int


class AnomaliaPorCriterio(_Rigido):
    criterio: str
    quantidade: int


class AnomaliaTop(_Rigido):
    id_despesa: int
    id_parlamentar: int
    nome_parlamentar: str | None
    valor_liquido: float | None
    zscore: float | None
    num_criterios: int


class AgentAnomalias(_Rigido):
    """Resumo agregado de anomalias (ADR-032) — não a lista crua paginada."""

    total: int
    por_ano: list[AnomaliaPorAno]
    por_criterio: list[AnomaliaPorCriterio]
    top_por_zscore: list[AnomaliaTop]


# ── /agent/context ──────────────────────────────────────────────


class MetricasGlobais(_Rigido):
    """Visão geral do Gold (totalizadores sobre `fact_despesa` + `expense_outliers`)."""

    total_gasto: float | None
    num_transacoes: int
    num_fornecedores: int | None
    num_parlamentares: int | None
    num_anomalias: int


class ResumoQualidade(_Rigido):
    """Resumo do relatório de qualidade da execução mais recente (ADR-031)."""

    run_id: str | None
    tabelas_reportadas: int | None
    total_registros: int | None
    total_quarentena: int | None


class ResumoPipeline(_Rigido):
    """Resumo da execução mais recente do pipeline (ADR-019)."""

    run_id: str | None
    status: str | None
    execution_timestamp: str | None
    versao_pipeline: str | None


class AgentContext(_Rigido):
    """Contexto semântico sistêmico (CU-07/ADR-032) — o "retrato" para o LLM."""

    metricas_globais: MetricasGlobais
    periodos_com_dados: list[int]
    qualidade: ResumoQualidade
    pipeline: ResumoPipeline