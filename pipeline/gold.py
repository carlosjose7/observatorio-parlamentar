"""Contratos da camada Gold (Star Schema / Fact Constellation).

Reflete PROJECT_CONTEXT.md §7, ADR-010 (dimensões institucionais),
ADR-011 (dim_fornecedor), ADR-012 (constelação de fatos) e ADR-021
(agregados analíticos puros). Ver docs/architecture/arch_er.md para o
diagrama entidade-relacionamento completo.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from pipeline.contracts import FonteOrigemUnidadeGestora, Poder, TipoDocumento


class DimOrgao(BaseModel):
    """Entidade institucional — Câmara, Senado, Ministérios etc. (ADR-010)."""

    id_orgao: int
    poder: Poder
    instituicao: str
    sigla: str
    ug_siafi: str | None = Field(default=None, description="Apenas quando o órgão possui UG direta")
    gestao: str | None = Field(default=None, description="Apenas em conjunto com ug_siafi")


class DimUnidadeGestora(BaseModel):
    """Unidade administrativa/orçamentária (ADR-010). Tabela vazia na v1.

    Chave natural é (fonte_origem, codigo) — nunca codigo isolado.
    """

    id_unidade_gestora: int
    codigo: str
    gestao: str | None = Field(
        default=None, description="Aplica-se apenas quando fonte_origem == SIAFI"
    )
    nome: str
    id_orgao: int
    fonte_origem: FonteOrigemUnidadeGestora


class DimFornecedor(BaseModel):
    """Dimensão de fornecedor — schema revisado pelo ADR-011.

    cnpj_cpf_valor contém CNPJ em texto claro, CPF com hash HMAC, ou
    None — tipo_documento é obrigatório para qualquer consumidor
    interpretar o valor corretamente.
    """

    id_fornecedor: int
    cnpj_cpf_valor: str | None
    tipo_documento: TipoDocumento | None
    nome_fornecedor: str
    id_municipio: int | None = None


class DimParlamentar(BaseModel):
    """Dimensão de parlamentar, SCD Type 2 (PROJECT_CONTEXT.md §7)."""

    id_parlamentar: int
    surrogate_key: int
    nome: str
    id_partido: str
    uf: str
    effective_date: date
    end_date: date | None
    is_current: bool


class DimPartido(BaseModel):
    """Dimensão de partido político."""

    sigla: str
    nome: str
    ideologia: str | None = None


class DimEstado(BaseModel):
    """Dimensão de unidade federativa."""

    uf: str
    nome: str
    regiao: str


class DimMunicipio(BaseModel):
    """Dimensão de município, com código IBGE."""

    cod_ibge: int
    nome: str
    uf: str


class DimCategoriaDespesa(BaseModel):
    """Dimensão de categoria/tipo de despesa CEAP."""

    cod_tipo: str
    descricao: str


class DimData(BaseModel):
    """Dimensão de calendário completo."""

    data_sk: int = Field(..., description="YYYYMMDD")
    data_completa: date
    ano: int
    mes: int
    dia: int
    is_dia_util: bool


class FactDespesa(BaseModel):
    """Fato de despesa — grão: uma despesa parlamentar.

    id_orgao é NOT NULL desde a v1 (sempre resolvido, inclusive para
    Câmara/Senado). id_unidade_gestora permanece NULL até
    dim_unidade_gestora ser ativada (ADR-010) — isso preserva a
    estabilidade do schema; quando ativada, basta enriquecer via
    backfill, sem evolução estrutural do schema.
    """

    id_despesa: int
    id_parlamentar: int
    id_fornecedor: int
    id_orgao: int = Field(..., description="NOT NULL — ADR-010")
    id_unidade_gestora: int | None = Field(
        default=None, description="Nullable — inativo na v1, ADR-010"
    )
    cod_tipo: str
    data_sk: int
    cod_documento: str = Field(..., description="VARCHAR — formato GUID confirmado")
    valor_liquido: Decimal
    valor_glosa: Decimal

    run_id: str
    pipeline_version: str
    execution_timestamp: str
    source_version: str


class FactEmenda(BaseModel):
    """Fato de emenda parlamentar — grão: uma emenda (ADR-012).

    id_parlamentar é NOT NULL — toda emenda tem autor identificável,
    faz parte da identidade do evento.
    """

    id_emenda: int
    id_parlamentar: int = Field(..., description="NOT NULL — toda emenda tem autor")
    id_orgao: int
    id_unidade_gestora: int | None = Field(default=None, description="Nullable — padrão ADR-010")
    data_sk: int
    codigo_emenda: str
    tipo_emenda: str
    funcao: str
    subfuncao: str
    localidade_do_gasto: str
    valor_empenhado: Decimal
    valor_liquidado: Decimal
    valor_pago: Decimal

    run_id: str
    pipeline_version: str
    execution_timestamp: str
    source_version: str


class FactCartaoCpgf(BaseModel):
    """Fato de transação de cartão CPGF — grão: uma transação (ADR-012).

    Não referencia dim_parlamentar. O portador pertence
    estruturalmente ao Poder Executivo — uma coincidência eventual de
    portador ser parlamentar não é relação de domínio e não justifica
    FK aqui. Correlação futura com parlamentares (caso um requisito
    funcional exija) deve ser modelada como tabela bridge dedicada
    (ex: bridge_cartao_parlamentar), preservando o grão desta fato.
    """

    id_transacao: int
    id_orgao: int
    id_unidade_gestora: int = Field(
        ..., description="NOT NULL — a fonte CGU sempre fornece unidadeGestora.codigo"
    )
    id_fornecedor: int | None = Field(
        default=None, description="Resolvido a partir do CNPJ do estabelecimento, quando presente"
    )
    data_sk: int
    portador_nome: str
    portador_cpf_mascarado: str = Field(..., description="Pré-mascarado pela fonte CGU, armazenado como está")
    valor_transacao: Decimal

    run_id: str
    pipeline_version: str
    execution_timestamp: str
    source_version: str


class SupplierConcentration(BaseModel):
    """Agregado analítico puro (ADR-021) — concentração de gasto do parlamentar.

    HHI = `SUM(participacao^2)` sobre as despesas do parlamentar por
    ano (PROJECT_CONTEXT §7 métrica `hhi`); `participacao` = total do fornecedor
    dividido pelo total do parlamentar no ano. Grão: (ano, id_parlamentar).
    """

    ano: int
    id_parlamentar: int
    num_fornecedores: int
    total_valor: Decimal
    hhi: float


class SupplierGrowth(BaseModel):
    """Agregado analítico puro (ADR-021) — crescimento de receita por fornecedor.

    Receita pública anual recebida por fornecedor, com variação YoY contra o
    ano anterior (null no primeiro período). Grão: (ano, id_fornecedor).
    """

    ano: int
    id_fornecedor: int
    valor_recebido: Decimal
    valor_ano_anterior: Decimal | None = Field(
        default=None, description="NULL no primeiro período do fornecedor (sem ano anterior)"
    )
    variacao_pct: float | None


class ExpenseOutliers(BaseModel):
    """Detecção de anomalias estatísticas (ADR-002/§10, Sprint 5/Onda 2).

    Uma despesa anômala — satisfaz **pelo menos dois** dos seis critérios do
    §10 (Z-score > 2.5, Isolation Forest score < -0.1, fornecedor < 3
    clientes, empresa < 12 meses, valores idênticos >= 3 no mês, dia sem
    sessão). Materializada a partir de `ml_staging.expense_outliers`
    (ADR-026, Opção A — Python single-writer no staging, dbt só materializa
    o Gold). Grão: (id_despesa). `criterio_*`/`num_criterios` documentam por
    que cada despesa foi sinalizada; `zscore`/`if_score` preservam os scores
    da inferência.
    """

    id_despesa: int
    id_parlamentar: int
    id_fornecedor: int | None = Field(
        default=None, description="Nullable — nem toda despesa resolve fornecedor"
    )
    data_sk: int
    valor_liquido: Decimal
    zscore: float | None = Field(
        default=None, description="Score Z do critério 1 (µ/σ do histórico do parlamentar)"
    )
    if_score: float | None = Field(
        default=None, description="Score do Isolation Forest na inferência (critério 2)"
    )
    criterio_zscore: bool
    criterio_if: bool
    criterio_fornecedor_poucos_clientes: bool
    criterio_empresa_nova: bool
    criterio_valores_identicos: bool
    criterio_dia_sem_sessao: bool
    num_criterios: int = Field(..., description=">= 2 por construção (ADR-002)")

    run_id: str
    pipeline_version: str
    execution_timestamp: str
    source_version: str