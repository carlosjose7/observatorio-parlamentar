"""pipeline/quality.py — gate de validação Pandera e Data Quality Report.

Implementa o ADR-013 (fronteira Pydantic vs. Pandera): enquanto o
Pydantic valida cada registro individual na extração (Sprint 1), este
módulo valida o DataFrame agregado no momento da carga Silver — regras
que operam sobre a coluna/lote inteiro (range de datas, unicidade da
chave de negócio pós-normalização, não-negatividade de valores).

Os schemas Pandera são declarados por tabela Silver. Registros que
falham o gate vão para quarentena (repartição `_quarantine/`) — nunca
são descartados silenciosamente nem derrubam a execução. O resultado é
persistido na tabela estruturada `data_quality_report` (ADR-015),
particionado por `run_id`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
import pandera.errors as pa_errors

try:  # pandera >= 0.20 — namespace de pandas dedicado (evita FutureWarning)
    import pandera.pandas as pa
except ImportError:  # pandera 0.18–0.19 — import top-level
    import pandera as pa  # type: ignore[no-redef]

import structlog

from pipeline.parlamento import _VALORES_NORMALIZADOS

logger = structlog.get_logger()

_DATA_INICIO_PLAUSIVEL = date(2015, 1, 1)


def _nao_anterior_a(ano: int):
    """Check: valores de data não anteriores ao início de `ano`."""
    inicio = datetime(ano, 1, 1)

    def _check(series: pd.Series) -> pd.Series:
        return series.map(
            lambda v: True if pd.isna(v) else pd.to_datetime(v) >= inicio
        )

    return pa.Check(_check, name=f"nao_anterior_{ano}")


def _nao_futura():
    """Check: valores de data não futuros em relação à execução."""
    agora = datetime.now()

    def _check(series: pd.Series) -> pd.Series:
        return series.map(
            lambda v: True if pd.isna(v) else pd.to_datetime(v) <= agora
        )

    return pa.Check(_check, name="nao_futura")


def _chave_negocio_unica_check(chaves: list[str]) -> pa.Check:
    """Build Pandera check: sem duplicata na chave de negócio (ADR-014).

    A chave é parametrizável por tabela — despesa usa
    (`fonte`, `cod_documento`); outras tabelas informam a própria chave.

    Args:
        chaves: Colunas que compõem a chave de negócio da tabela.

    Returns:
        `pa.Check` nivel de DataFrame.
    """

    def _check(df: pd.DataFrame) -> pd.Series:
        return (~df.duplicated(subset=chaves, keep=False)).reindex(df.index)

    return pa.Check(_check, name="chave_negocio_unica")


def _codigo_emenda_nao_si() -> pa.Check:
    """Check: `codigo_emenda` não usa o marcador de ausência `S/I`.

    A amostragem da API CGU (ADR-017) revelou registros com
    `codigoEmenda = "S/I"` (código "sem informação"), que não é uma
    chave válida nem um código real. Linhas com esse marcador são
    isoladas na quarentena em vez de serem validadas como código
    legítimo.
    """

    def _check(series: pd.Series) -> pd.Series:
        return series.map(lambda v: not (isinstance(v, str) and v.strip() == "S/I"))

    return pa.Check(_check, name="codigo_nao_si")


# ── Schemas Pandera por tabela Silver (ADR-013) ──────────────────


def schema_silver_despesa() -> pa.DataFrameSchema:
    """Schema Silver para `silver_despesa` (Câmara + Senado).

    Regras de lote: valores não negativos, datas plausíveis (não antes
    de 2015, não futuras) e unicidade da chave de negócio
    (`fonte` + `cod_documento`). Datas/valores inválidos na origem já
    viraram `None` — detectados aqui pelo intervalo ou pela chave.
    """
    return pa.DataFrameSchema(
        columns={
            "fonte": pa.Column(str, nullable=False),
            "cod_documento": pa.Column(str, nullable=False),
            "data_documento": pa.Column(
                "datetime64[ns]",
                nullable=True,
                checks=[
                    _nao_anterior_a(2015),
                    _nao_futura(),
                ],
            ),
            "valor_liquido": pa.Column("float64", nullable=False, checks=pa.Check.ge(0)),
            "valor_glosa": pa.Column("float64", nullable=True, checks=pa.Check.ge(0)),
            "tipo_documento": pa.Column(
                str,
                nullable=True,
                checks=pa.Check.isin(["CNPJ", "CPF", "INVALIDO", None]),
            ),
        },
        checks=[_chave_negocio_unica_check(["fonte", "cod_documento"])],
    )


def schema_silver_cartao() -> pa.DataFrameSchema:
    """Schema Silver para `silver_cartao` (CGU cartões CPGF, ADR-013).

    Regras de lote: datas plausíveis (não antes de 2015, não futuras) e
    valores não negativos. Reflete NOT NULLs do `fact_cartao_cpgf`
    (ADR-010/ADR-012): `unidade_gestora_codigo` é obrigatória — a fonte
    CGU sempre fornece `unidadeGestora` — e portanto NÃO é tratada como
    nullable, ao contrário de despesa/emenda que têm UG inativa na v1.

    Obs: a unicidade da chave de negócio não é fixada aqui — a chave de
    negócio é o `id` nativo da CGU, propagado até a Silver no
    `pipeline/transparencia/transform.py`; o fallback de unicidade é
    passado pela camada ao `avaliar_qualidade` via `chaves_negocio`.
    """
    return pa.DataFrameSchema(
        columns={
            "data_transacao": pa.Column(
                "datetime64[ns]",
                nullable=False,
                checks=[
                    _nao_anterior_a(2015),
                    _nao_futura(),
                ],
            ),
            "valor_transacao": pa.Column(
                "float64", nullable=False, checks=pa.Check.ge(0)
            ),
            "estabelecimento_cnpj_valor": pa.Column(str, nullable=True),
            "estabelecimento_tipo_documento": pa.Column(
                str,
                nullable=True,
                checks=pa.Check.isin(["CNPJ", "CPF", "INVALIDO", None]),
            ),
            "estabelecimento_nome": pa.Column(str, nullable=False),
            "portador_nome": pa.Column(str, nullable=False),
            "portador_cpf_mascarado": pa.Column(str, nullable=False),
            "unidade_gestora_codigo": pa.Column(str, nullable=False),
            "unidade_gestora_nome": pa.Column(str, nullable=False),
        },
    )


def schema_silver_emenda() -> pa.DataFrameSchema:
    """Schema Silver para `silver_emenda` (CGU emendas, ADR-013/ADR-017).

    Regras de lote: valores monetários não negativos, unicidade da
    chave de negócio composta (`ano`, `codigo_emenda`) e rejeição do
    marcador de ausência `S/I`. `nome_autor` é carregado normalizado
    (uppercase, sem acento) e `tipo_emenda` fielmente tipado — sem
    tentativa de resolução para `id_parlamentar`, deferida ao Gold
    (ADR-017, Sprint 4).
    """
    return pa.DataFrameSchema(
        columns={
            "ano": pa.Column("int64", nullable=False),
            "codigo_emenda": pa.Column(
                str, nullable=False, checks=_codigo_emenda_nao_si()
            ),
            "tipo_emenda": pa.Column(str, nullable=False),
            "nome_autor": pa.Column(str, nullable=False),
            "funcao": pa.Column(str, nullable=True),
            "subfuncao": pa.Column(str, nullable=True),
            "localidade_do_gasto": pa.Column(str, nullable=True),
            "valor_empenhado": pa.Column("float64", nullable=True, checks=pa.Check.ge(0)),
            "valor_liquidado": pa.Column("float64", nullable=True, checks=pa.Check.ge(0)),
            "valor_pago": pa.Column("float64", nullable=True, checks=pa.Check.ge(0)),
        },
        checks=[_chave_negocio_unica_check(["ano", "codigo_emenda"])],
    )


def schema_silver_parlamentar() -> pa.DataFrameSchema:
    """Schema Silver para `silver_parlamentar` (snapshot Onda 2, ADR-020/ADR-024).

    Dados mestres dos deputados: um registro por `(fonte, id_parlamentar,
    data_status)` — grão estritamente diário da observação de `ultimoStatus`.
    `data` não pode ser do futuro nem anterior a 2015 (janela plausível da
    fonte). `nome` e `id_parlamentar` são críticos (não nulos); partido/UF podem
    faltar no `ultimoStatus` para parlamentares sem mandato vigente, por isso
    `sigla_partido`/`sigla_uf` são nullables.

    ADR-024 (paridade semântica Câmara×Senado):
    - `id_legislatura` é derivada do calendário legislativo a partir de `data` e
      deve ser `> 0` — data fora do calendário cai na quarentena (e o bug do
      hard-coded `0` do Senado deixa de ser uma linha válida).
    - `id_legislatura_fonte` guarda o bruto da API (auditoria, nullable).
    - `situacao_normalizada` usa o enum comum de `pipeline/parlamento`; valores
      fora do de-para viram `nao_mapeado` (nunca NULL silencioso).

    A unicidade da chave de negócio composta mantém o SCD2: snapshots
    idênticos entre execuções colapsam; uma mudança de partido/UF/
    situação gera nova linha — insumo do `dim_parlamentar` Gold
    (ADR-020).
    """
    return pa.DataFrameSchema(
        columns={
            "fonte": pa.Column(str, nullable=False),
            "id_parlamentar": pa.Column("int64", nullable=False),
            "nome": pa.Column(str, nullable=False),
            "sigla_partido": pa.Column(str, nullable=True),
            "sigla_uf": pa.Column(str, nullable=True),
            "id_legislatura": pa.Column(
                "int64",
                nullable=False,
                checks=pa.Check.gt(0, name="legislatura_valida"),
            ),
            "id_legislatura_fonte": pa.Column("Int64", nullable=True),
            "situacao_bruta": pa.Column(str, nullable=True),
            "situacao_normalizada": pa.Column(
                str,
                nullable=False,
                checks=pa.Check.isin(list(_VALORES_NORMALIZADOS)),
            ),
            "data": pa.Column(
                "datetime64[ns]",
                nullable=False,
                checks=[
                    _nao_anterior_a(2015),
                    _nao_futura(),
                ],
            ),
        },
        checks=[
            _chave_negocio_unica_check(["fonte", "id_parlamentar", "data"])
        ],
    )


# ── Linha do Data Quality Report (ADR-015) ───────────────────────


@dataclass
class LinhaQualidadeReport:
    """Uma linha do `data_quality_report` por tabela/execução.

    Attributes:
        run_id: Identificador da execução do pipeline.
        tabela: Nome da tabela Silver validada.
        total_registros: Quantidade de registros avaliados.
        registros_validos: Que passaram no gate Pandera.
        registros_quarentena: Que falharam e foram isolados.
        regras_violadas: Nomes das regras/colunas Pandera com falha.
        percentual_nulos_criticos: Ratio de nulos em campos críticos.
        registros_deduplicados: Linhas removidas pela dedup independente
            (ADR-014) antes do gate.
        execution_timestamp: Momento da validação.
    """

    run_id: str
    tabela: str
    total_registros: int
    registros_validos: int
    registros_quarentena: int
    regras_violadas: list[str] = field(default_factory=list)
    percentual_nulos_criticos: float = 0.0
    registros_deduplicados: int = 0
    execution_timestamp: datetime | None = None


def percentual_nulos(df: pd.DataFrame, campos_criticos: list[str]) -> float:
    """Ratío de valores nulos por campo crítico (0.0 a 1.0)."""
    if df.empty or not campos_criticos:
        return 0.0
    existentes = [c for c in campos_criticos if c in df.columns]
    if not existentes:
        return 0.0
    nulos = df[existentes].isna().sum().sum()
    total = len(df) * len(existentes)
    return round(nulos / total, 4)


def avaliar_qualidade(
    df: pd.DataFrame,
    schema: pa.DataFrameSchema,
    run_id: str,
    tabela: str,
    campos_criticos: list[str] | None = None,
    chaves_negocio: list[str] | None = None,
) -> tuple[pd.DataFrame, LinhaQualidadeReport]:
    """Valida um DataFrame Silver contra o schema Pandera.

    Separa linhas válidas das que violam o schema (quarentena) e
    consolida uma linha do `data_quality_report`. A validação nunca
    lança exceção não capturada: falhas viram quarentena + registro no
    relatório (ADR-013, ADR-015).

    Args:
        df: DataFrame Silver a validar.
        schema: Schema Pandera da tabela.
        run_id: Identificador da execução.
        tabela: Nome da tabela Silver.
        campos_criticos: Campos usados para o percentual de nulos.
        chaves_negocio: Colunas da chave de negócio (ADR-014) para o
            fallback de unicidade pós-gate. Padrão
            `["fonte", "cod_documento"]` (compatível com `silver_despesa`);
            tabelas com chave própria informam a dela (ex: emendas).

    Returns:
        (linhas_válidas, linha_do_relatório).
    """
    chaves_negocio = chaves_negocio or ["fonte", "cod_documento"]
    if df.empty:
        linha = LinhaQualidadeReport(
            run_id=run_id,
            tabela=tabela,
            total_registros=0,
            registros_validos=0,
            registros_quarentena=0,
            percentual_nulos_criticos=0.0,
        )
        return df, linha

    df_validos = df
    indices_invalidos: list[int] = []
    falhas = None

    try:
        schema.validate(df, lazy=True)
    except pa_errors.SchemaErrors as exc:
        falhas = exc.failure_cases
        indices_invalidos = sorted(
            set(int(i) for i in falhas["index"].dropna().tolist())
        )
        df_validos = df.drop(index=indices_invalidos)

    regras_violadas: list[str] = []
    if falhas is not None:
        # Prioriza o nome do check (ex: "chave_negocio_unica", intervalos);
        # quando o check não nomeia, cai para o nome da coluna.
        checks = {str(c) for c in falhas["check"].dropna().tolist() if str(c) != "<NA>"}
        if checks:
            regras_violadas = sorted(checks)
        else:
            regras_violadas = sorted(
                {str(c) for c in falhas["column"].dropna().tolist() if str(c) != "<NA>"}
            )
    elif all(c in df_validos.columns for c in chaves_negocio) and df_validos.duplicated(
        subset=chaves_negocio, keep=False
    ).any():
        regras_violadas = ["chave_negocio_unica"]

    linha = LinhaQualidadeReport(
        run_id=run_id,
        tabela=tabela,
        total_registros=len(df),
        registros_validos=len(df_validos),
        registros_quarentena=len(indices_invalidos),
        regras_violadas=regras_violadas,
        percentual_nulos_criticos=percentual_nulos(df, campos_criticos or []),
    )
    logger.info(
        "gate_qualidade",
        tabela=tabela,
        total=linha.total_registros,
        validos=linha.registros_validos,
        quarentena=linha.registros_quarentena,
        regras=linha.regras_violadas,
    )
    return df_validos, linha