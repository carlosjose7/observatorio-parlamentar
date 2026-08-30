"""api/repo.py — camada de acesso read-only à camada Gold (DuckDB).

Fronteira de leitura da API (ADR-026): a API consulta APENAS o DuckDB da
camada Gold apontado por `caminho_db_env_var` da config (`config/api.yaml` →
`DUCKDB_DATABASE_PATH`), em modo `read_only`. Nunca lê Bronze/Silver nem
`ml_staging`.

As consultas espelham o schema REAL emitido pelos modelos dbt do Gold
(dim_parlamentar/dim_fornecedor/dim_categoria_despesa/dim_data/fact_despesa).
Qualquer erro de acesso ao arquivo do DuckDB sobe como `GoldIndisponivel`,
que o router converte em HTTP 503 — a API degrada com intenção de serviço,
não estoura stack de driver ao cliente.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

import duckdb
import structlog

from api.schemas.agent import (
    AgentAnomalias,
    AgentContext,
    AgentFornecedor,
    AgentParlamentar,
    AnomaliaPorAno,
    AnomaliaPorCriterio,
    AnomaliasParlamentar,
    AnomaliaTop,
    FornecedorTop,
    MetricasFornecedor,
    MetricasGlobais,
    MetricasParlamentar,
    ParlamentarTop,
    ResumoPipeline,
    ResumoQualidade,
    RiscoParlamentar,
)
from api.schemas.agregacoes import (
    AgregacaoItem,
    ListaAgregacao,
    ListaTopFornecedores,
    SerieTemporal,
    SerieTemporalItem,
    TopFornecedorItem,
)
from api.schemas.anomalias import AnomaliaItem, ListaAnomalias
from api.schemas.contador import ContadorVisitas
from api.schemas.fornecedores import (
    FornecedorContexto,
    FornecedorResumo,
    GastoFornecedorItem,
    GastosFornecedor,
    ListaFornecedores,
    ListaParlamentaresFornecedor,
    ParlamentarFornecedor,
    PerfilFornecedor,
)
from api.schemas.parlamentares import (
    ArestaRede,
    GastoItem,
    GastosParlamentar,
    ListaParlamentares,
    NoRede,
    ParlamentarContexto,
    ParlamentarResumo,
    PerfilParlamentar,
    RedeParlamentar,
)
from api.schemas.pipeline import ExecucaoPipeline, PipelineStatus
from api.schemas.qualidade import LinhaQualidade, RelatorioQualidade
from api.schemas.rede import (
    ArestaFornecedor,
    ComunidadeItem,
    ListaComunidades,
    RedeFornecedor,
)
from pipeline.config import REPO_ROOT, get_api, get_env
from pipeline.normalize import normalizar_nome_proprio

logger = structlog.get_logger()


class GoldIndisponivel(Exception):
    """DuckDB da camada Gold inacessível (arquivo ausente ou falha de leitura)."""


def _tratar_erro_gold(funcao):
    """Converte falhas de driver/esquema do DuckDB em `GoldIndisponivel` (HTTP 503).

    Um schema do Gold desatualizado (tabela ausente) ou um erro de
    concorrência de conexão não vazam como 500 ao cliente — degradam como
    "camada Gold indisponível", consistente com o ADR de fronteira de
    leitura: a API depende do Gold estar construído.
    """

    @functools.wraps(funcao)
    def _invocar(*args, **kwargs):
        try:
            return funcao(*args, **kwargs)
        except GoldIndisponivel:
            raise
        except (duckdb.Error, OSError) as exc:
            logger.error(
                "gold_indisponivel", funcao=funcao.__name__, erro=str(exc)
            )
            raise GoldIndisponivel(
                f"Falha ao consultar a camada Gold: {exc}"
            ) from exc

    return _invocar


# ---------------------------------------------------------------------------
# Contador de visitas — DuckDB dedicado (separado do Gold read-only, ADR-026)
# ---------------------------------------------------------------------------

_CAMINHO_VISITAS = REPO_ROOT / "data" / "analytics" / "visitas.duckdb"


def _conexao_visitas() -> duckdb.DuckDBPyConnection:
    """Abre (ou cria) o DuckDB dedicado ao contador de visitas."""
    _CAMINHO_VISITAS.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(_CAMINHO_VISITAS))
    con.execute(
        "CREATE TABLE IF NOT EXISTS visitas ("
        "  data DATE PRIMARY KEY,"
        "  total BIGINT NOT NULL DEFAULT 0"
        ")"
    )
    return con


@_tratar_erro_gold
def incrementar_visitas() -> ContadorVisitas:
    """Incrementa o contador do dia e retorna os totais.

    Usa UPSERT (INSERT OR REPLACE) para garantir idempotência.
    """
    from datetime import date

    hoje = date.today()
    with _conexao_visitas() as con:
        con.execute(
            "INSERT INTO visitas (data, total) VALUES (?, 1) "
            "ON CONFLICT (data) DO UPDATE SET total = visitas.total + 1",
            [hoje],
        )
        linha_hoje = con.execute(
            "SELECT total FROM visitas WHERE data = ?", [hoje]
        ).fetchone()
        total_geral = con.execute("SELECT COALESCE(SUM(total), 0) FROM visitas").fetchone()[0]

    return ContadorVisitas(
        total_hoje=linha_hoje[0] if linha_hoje else 0,
        total_geral=total_geral,
    )


def caminho_do_gold() -> Path:
    """Resolve o caminho absoluto do DuckDB Gold (env → config, ADR-008).

    O valor da env pode ser relativo (ex.: `data/silver/observatorio.duckdb`,
    default do `.env.example`); aqui é ancorado na raiz do repositório.
    """
    config = get_api()
    bruto = get_env().duckdb_database_path
    caminho = Path(bruto or config.caminho_db_env_var)
    if not caminho.is_absolute():
        caminho = REPO_ROOT / caminho
    return caminho


def _conexao() -> duckdb.DuckDBPyConnection:
    """Abre o DuckDB Gold em modo read-only (nunca cria/modifica)."""
    caminho = caminho_do_gold()
    if not caminho.exists():
        logger.error("gold_indisponivel", caminho=str(caminho), motivo="arquivo_ausente")
        raise GoldIndisponivel(f"DuckDB Gold ausente: {caminho}")
    try:
        return duckdb.connect(str(caminho), read_only=True)
    except duckdb.Error as exc:  # pragma: no cover — driver é confiável p/ arquivo existente
        logger.error("gold_indisponivel", caminho=str(caminho), erro=str(exc))
        raise GoldIndisponivel(f"Falha ao abrir DuckDB Gold: {caminho}") from exc


_NO_PARLAMENTARES = """
    select id_parlamentar, nome, sigla_partido, sigla_uf, situacao_normalizada, fonte,
           url_foto
    from dim_parlamentar
    where is_current
"""
_ORDENACAO_PARLAMENTARES = " order by nome_normalizado, id_parlamentar"


@_tratar_erro_gold
def listar_parlamentares(
    *,
    nome: str | None,
    uf: str | None,
    partido: str | None,
    pagina: int,
    limite: int,
) -> ListaParlamentares:
    """Lista parlamentares vigentes (SCD2 `is_current`), com filtros opcionais.

    `nome` busca sobre `nome_normalizado` (filtro parcial, case/accent
    insensitive); `uf`/`partido` são igualdades exatas sobre `sigla_uf`/
    `sigla_partido`. Paginação é a régua de recurso da config (limite já
    validado pela query do router).
    """
    condicoes: list[str] = []
    parametros: list[object] = []

    if nome:
        normalizado = normalizar_nome_proprio(nome)
        if normalizado:
            condicoes.append("nome_normalizado ilike ?")
            parametros.append(f"%{normalizado}%")
    if uf:
        condicoes.append("sigla_uf = ?")
        parametros.append(uf)
    if partido:
        condicoes.append("sigla_partido = ?")
        parametros.append(partido)

    where = " and ".join(condicoes)
    clausula_where = f" and {where}" if where else ""
    offset = (pagina - 1) * limite

    with _conexao() as con:
        total = con.execute(
            f"select count(*) from dim_parlamentar where is_current{clausula_where}",
            parametros,
        ).fetchone()[0]
        linhas = con.execute(
            f"{_NO_PARLAMENTARES}{clausula_where}{_ORDENACAO_PARLAMENTARES} "
            "limit ? offset ?",
            [*parametros, limite, offset],
        ).fetchall()
        colunas = ["id_parlamentar", "nome", "sigla_partido", "sigla_uf", "situacao_normalizada", "fonte", "url_foto"]

    itens = [ParlamentarResumo.model_validate(dict(zip(colunas, linha))) for linha in linhas]
    return ListaParlamentares(pagina=pagina, limite=limite, total=total, itens=itens)


@_tratar_erro_gold
def obter_contexto_parlamentar(id_parlamentar: int) -> ParlamentarContexto | None:
    """Retorna o contexto do parlamentar vigente (ou `None` se inexistente)."""
    with _conexao() as con:
        linha = con.execute(
            """
            select id_parlamentar, nome, sigla_partido, sigla_uf, situacao_normalizada
            from dim_parlamentar
            where id_parlamentar = ? and is_current
            """,
            [id_parlamentar],
        ).fetchone()
    if linha is None:
        return None
    colunas = ["id_parlamentar", "nome", "sigla_partido", "sigla_uf", "situacao_normalizada"]
    return ParlamentarContexto.model_validate(dict(zip(colunas, linha)))


@_tratar_erro_gold
def listar_gastos(
    *,
    id_parlamentar: int,
    ano: int | None,
    pagina: int,
    limite: int,
) -> GastosParlamentar | None:
    """Histórico de despesas de um parlamentar, com dimensões resolvidas.

    Retorna `None` quando o parlamentar não existe (router responde 404).
    junta `fact_despesa` → `dim_data` (data real), `dim_categoria_despesa`
    (descrição) e `dim_fornecedor` (nome/tipo de documento) — tudo de FK que
    o pipeline garante resolvida antes de promover o fato (ADR-012/ADR-022.3a).
    `ano` é filtro opcional sobre `dim_data.ano`.
    """
    contexto = obter_contexto_parlamentar(id_parlamentar)
    if contexto is None:
        return None

    condicoes = ["f.id_parlamentar = ?"]
    parametros: list[object] = [id_parlamentar]
    if ano is not None:
        condicoes.append("d.ano = ?")
        parametros.append(ano)
    offset = (pagina - 1) * limite

    with _conexao() as con:
        total = con.execute(
            f"""
            select count(*)
            from fact_despesa f
            join dim_data d on d.data_sk = f.data_sk
            where {' and '.join(condicoes)}
            """,
            parametros,
        ).fetchone()[0]
        linhas = con.execute(
            f"""
            select
                f.id_despesa,
                d.data,
                d.ano,
                d.mes,
                c.descricao as tipo_despesa,
                fo.nome_fornecedor,
                fo.tipo_documento,
                f.valor_liquido,
                f.valor_glosa
            from fact_despesa f
            join dim_data d on d.data_sk = f.data_sk
            join dim_categoria_despesa c on c.cod_tipo = f.cod_tipo
            join dim_fornecedor fo on fo.id_fornecedor = f.id_fornecedor
            where {' and '.join(condicoes)}
            order by d.data_sk desc, f.id_despesa
            limit ? offset ?
            """,
            [*parametros, limite, offset],
        ).fetchall()
        colunas = [
            "id_despesa",
            "data",
            "ano",
            "mes",
            "tipo_despesa",
            "nome_fornecedor",
            "tipo_documento",
            "valor_liquido",
            "valor_glosa",
        ]

    itens = [GastoItem.model_validate(dict(zip(colunas, linha))) for linha in linhas]
    return GastosParlamentar(
        parlamentar=contexto, pagina=pagina, limite=limite, total=total, itens=itens
    )


@_tratar_erro_gold
def obter_perfil_parlamentar(id_parlamentar: int) -> PerfilParlamentar | None:
    """Perfil completo do parlamentar na versão vigente (`is_current`, ADR-020)."""
    with _conexao() as con:
        linha = con.execute(
            """
            select id_parlamentar, surrogate_key, fonte, nome, nome_normalizado,
                   sigla_partido, sigla_uf, situacao_normalizada, url_foto,
                   id_legislatura, effective_date, end_date, is_current
            from dim_parlamentar
            where id_parlamentar = ? and is_current
            """,
            [id_parlamentar],
        ).fetchone()
    if linha is None:
        return None
    colunas = [
        "id_parlamentar", "surrogate_key", "fonte", "nome", "nome_normalizado",
        "sigla_partido", "sigla_uf", "situacao_normalizada", "url_foto",
        "id_legislatura", "effective_date", "end_date", "is_current",
    ]
    return PerfilParlamentar.model_validate(dict(zip(colunas, linha)))


@_tratar_erro_gold
def obter_rede_parlamentar(id_parlamentar: int) -> RedeParlamentar | None:
    """Rede do parlamentar a partir dos resultados MATERIALIZADOS da Sprint 5.

    NÃO recalcula grafo/PageRank/comunidades (regra da Onda 2): lê
    `network_nodes`/`network_edges` da Gold (ADR-030). Se a Gold não tiver
    essas tabelas ainda (staging vazio), o banco retorna vazio — 200 honesto.
    """
    contexto = obter_contexto_parlamentar(id_parlamentar)
    if contexto is None:
        return None

    with _conexao() as con:
        nos_tuplas = con.execute(
            """
            select periodo, pagerank, degree_centrality, comunidade_id
            from network_nodes
            where tipo_no = 'parlamentar' and id_no = ?
            order by periodo
            """,
            [id_parlamentar],
        ).fetchall()
        arestas_tuplas = con.execute(
            """
            select ne.id_fornecedor, df.nome_fornecedor, ne.periodo, ne.valor_total
            from network_edges ne
            join dim_fornecedor df on df.id_fornecedor = ne.id_fornecedor
            where ne.id_parlamentar = ?
            order by ne.periodo desc, ne.valor_total desc
            """,
            [id_parlamentar],
        ).fetchall()

    nos = [NoRede.model_validate(dict(zip(["periodo", "pagerank", "degree_centrality", "comunidade_id"], no))) for no in nos_tuplas]
    arestas = [
        ArestaRede.model_validate(
            dict(zip(["id_fornecedor", "nome_fornecedor", "periodo", "valor_total"], aresta))
        )
        for aresta in arestas_tuplas
    ]
    return RedeParlamentar(parlamentar=contexto, nos=nos, arestas=arestas)


@_tratar_erro_gold
def listar_fornecedores(
    *,
    nome: str | None,
    tipo_documento: str | None,
    pagina: int,
    limite: int,
) -> ListaFornecedores:
    """Lista fornecedores (`dim_fornecedor`), com filtros opcionais.

    `nome` é filtro parcial case-insensitive sobre `nome_fornecedor`;
    `tipo_documento` é igualdade sobre o valor do contrato (`CNPJ`/`CPF`).
    """
    condicoes: list[str] = []
    parametros: list[object] = []

    if nome:
        condicoes.append("nome_fornecedor ilike ?")
        parametros.append(f"%{nome}%")
    if tipo_documento:
        condicoes.append("tipo_documento = ?")
        parametros.append(tipo_documento)

    clausula_where = f" where {' and '.join(condicoes)}" if condicoes else ""
    offset = (pagina - 1) * limite

    with _conexao() as con:
        total = con.execute(
            f"select count(*) from dim_fornecedor{clausula_where}",
            parametros,
        ).fetchone()[0]
        linhas = con.execute(
            f"select id_fornecedor, cnpj_cpf_valor, tipo_documento, nome_fornecedor"
            f" from dim_fornecedor{clausula_where}"
            " order by nome_fornecedor, id_fornecedor limit ? offset ?",
            [*parametros, limite, offset],
        ).fetchall()

    colunas = ["id_fornecedor", "cnpj_cpf_valor", "tipo_documento", "nome_fornecedor"]
    itens = [FornecedorResumo.model_validate(dict(zip(colunas, linha))) for linha in linhas]
    return ListaFornecedores(pagina=pagina, limite=limite, total=total, itens=itens)


def _fornecedor_contexto(con, cnpj_cpf_valor: str) -> FornecedorContexto | None:
    """Contexto do fornecedor por `cnpj_cpf_valor` (None se inexistente)."""
    linha = con.execute(
        """
        select id_fornecedor, cnpj_cpf_valor, tipo_documento, nome_fornecedor
        from dim_fornecedor
        where cnpj_cpf_valor = ?
        """,
        [cnpj_cpf_valor],
    ).fetchone()
    if linha is None:
        return None
    colunas = ["id_fornecedor", "cnpj_cpf_valor", "tipo_documento", "nome_fornecedor"]
    return FornecedorContexto.model_validate(dict(zip(colunas, linha)))


@_tratar_erro_gold
def obter_perfil_fornecedor(cnpj_cpf_valor: str) -> PerfilFornecedor | None:
    """Perfil do fornecedor (dimensão + agregados de gasto promovido).

    CNPJ casa exatamente; CPF está pseudonimizado (ADR-011) e não casa pelo
    número cru — `None` nesse caso.
    """
    with _conexao() as con:
        linha = con.execute(
            """
            select df.id_fornecedor, df.cnpj_cpf_valor, df.tipo_documento,
                   df.nome_fornecedor, df.id_municipio,
                   count(fd.id_despesa) as num_despesas,
                   coalesce(sum(fd.valor_liquido), 0) as valor_liquido_total
            from dim_fornecedor df
            left join fact_despesa fd on fd.id_fornecedor = df.id_fornecedor
            where df.cnpj_cpf_valor = ?
            group by df.id_fornecedor, df.cnpj_cpf_valor, df.tipo_documento,
                     df.nome_fornecedor, df.id_municipio
            """,
            [cnpj_cpf_valor],
        ).fetchone()
    if linha is None:
        return None
    colunas = [
        "id_fornecedor", "cnpj_cpf_valor", "tipo_documento", "nome_fornecedor",
        "id_municipio", "num_despesas", "valor_liquido_total",
    ]
    return PerfilFornecedor.model_validate(dict(zip(colunas, linha)))


@_tratar_erro_gold
def listar_parlamentares_fornecedor(
    *,
    cnpj_cpf_valor: str,
    pagina: int,
    limite: int,
) -> ListaParlamentaresFornecedor | None:
    """Parlamentares (vigentes) que gastaram com um fornecedor + agregados.

    Agrega sobre `fact_despesa` ↔ `dim_parlamentar` (`is_current` — o
    parlamentar aparece com a identidade vigente, ADR-020) e `dim_fornecedor`.
    Retorna `None` (router responde 404) quando o fornecedor não existe.
    """
    with _conexao() as con:
        contexto = _fornecedor_contexto(con, cnpj_cpf_valor)
        if contexto is None:
            return None
        total = con.execute(
            """
            select count(distinct fd.id_parlamentar)
            from fact_despesa fd
            join dim_parlamentar dp on dp.id_parlamentar = fd.id_parlamentar and dp.is_current
            where fd.id_fornecedor = ?
            """,
            [contexto.id_fornecedor],
        ).fetchone()[0]
        offset = (pagina - 1) * limite
        linhas = con.execute(
            """
            select fd.id_parlamentar, dp.nome, dp.sigla_partido, dp.sigla_uf,
                   sum(fd.valor_liquido) as total_gasto, count(*) as num_despesas
            from fact_despesa fd
            join dim_parlamentar dp on dp.id_parlamentar = fd.id_parlamentar and dp.is_current
            where fd.id_fornecedor = ?
            group by fd.id_parlamentar, dp.nome, dp.sigla_partido, dp.sigla_uf
            order by total_gasto desc, fd.id_parlamentar
            limit ? offset ?
            """,
            [contexto.id_fornecedor, limite, offset],
        ).fetchall()

    colunas = ["id_parlamentar", "nome", "sigla_partido", "sigla_uf", "total_gasto", "num_despesas"]
    itens = [ParlamentarFornecedor.model_validate(dict(zip(colunas, linha))) for linha in linhas]
    return ListaParlamentaresFornecedor(
        fornecedor=contexto, pagina=pagina, limite=limite, total=total, itens=itens
    )


@_tratar_erro_gold
def listar_gastos_fornecedor(
    *,
    cnpj_cpf_valor: str,
    ano: int | None,
    pagina: int,
    limite: int,
) -> GastosFornecedor | None:
    """Despesas recebidas por um fornecedor, com o parlamentar pagador.

    Espelho de `listar_gastos`: junta `fact_despesa` → `dim_data` (data/ano/
    mês), `dim_categoria_despesa` (descrição) e `dim_parlamentar` vigente
    (`is_current`, ADR-020). `ano` é filtro opcional sobre `dim_data.ano`.
    Retorna `None` (router responde 404) quando o fornecedor não existe.
    """
    with _conexao() as con:
        contexto = _fornecedor_contexto(con, cnpj_cpf_valor)
        if contexto is None:
            return None

        condicoes = ["f.id_fornecedor = ?"]
        parametros: list[object] = [contexto.id_fornecedor]
        if ano is not None:
            condicoes.append("d.ano = ?")
            parametros.append(ano)
        offset = (pagina - 1) * limite

        total = con.execute(
            f"""
            select count(*)
            from fact_despesa f
            join dim_data d on d.data_sk = f.data_sk
            where {' and '.join(condicoes)}
            """,
            parametros,
        ).fetchone()[0]
        linhas = con.execute(
            f"""
            select
                f.id_despesa,
                d.data,
                d.ano,
                d.mes,
                c.descricao as tipo_despesa,
                p.id_parlamentar,
                p.nome as nome_parlamentar,
                p.sigla_partido,
                p.sigla_uf,
                f.valor_liquido,
                f.valor_glosa
            from fact_despesa f
            join dim_data d on d.data_sk = f.data_sk
            join dim_categoria_despesa c on c.cod_tipo = f.cod_tipo
            join dim_parlamentar p
              on p.id_parlamentar = f.id_parlamentar and p.is_current
            where {' and '.join(condicoes)}
            order by d.data_sk desc, f.id_despesa
            limit ? offset ?
            """,
            [*parametros, limite, offset],
        ).fetchall()
        colunas = [
            "id_despesa",
            "data",
            "ano",
            "mes",
            "tipo_despesa",
            "id_parlamentar",
            "nome_parlamentar",
            "sigla_partido",
            "sigla_uf",
            "valor_liquido",
            "valor_glosa",
        ]

    itens = [
        GastoFornecedorItem.model_validate(dict(zip(colunas, linha)))
        for linha in linhas
    ]
    return GastosFornecedor(
        fornecedor=contexto, pagina=pagina, limite=limite, total=total, itens=itens
    )


# ── Onda 3: anomalias, comunidades, qualidade e pipeline ─────────


@_tratar_erro_gold
def listar_anomalias(
    *,
    threshold: float | None,
    ano: int | None,
    pagina: int,
    limite: int,
) -> ListaAnomalias:
    """Lista despesas sinalizadas na Gold (Onda 3, ADR-002/§10).

    Lê `expense_outliers` materializada - nunca recalcula a regra. O filtro
    `threshold` é piso sobre `zscore` do conjunto JÁ sinalizado (decisão de
    Onda 3): reabrir o `-0.1` do Isolation Forest ou os `>= 2` critérios
    seria re-execução de inferência, proibida pela fronteira (ADR-026/ADR-030).
    `ano` filtra pelo ano da data do documento (`data_sk // 10000`).
    """
    clausulas: list[str] = []
    parametros: list[object] = []
    if threshold is not None:
        clausulas.append("zscore >= ?")
        parametros.append(threshold)
    if ano is not None:
        clausulas.append("data_sk // 10000 = ?")
        parametros.append(ano)
    condicao = (" where " + " and ".join(clausulas)) if clausulas else ""
    condicao_o = (
        " where "
        + " and ".join(
            c.replace("zscore", "o.zscore").replace("data_sk", "o.data_sk")
            for c in clausulas
        )
        if clausulas
        else ""
    )
    offset = (pagina - 1) * limite

    with _conexao() as con:
        total = con.execute(
            f"select count(*) from expense_outliers{condicao}", parametros
        ).fetchone()[0]
        linhas = con.execute(
            "select o.id_despesa, o.id_parlamentar, dp.nome as nome_parlamentar,"
            " dp.sigla_partido, dp.sigla_uf, o.id_fornecedor, o.data_sk,"
            " o.valor_liquido, o.zscore, o.if_score, o.criterio_zscore,"
            " o.criterio_if, o.criterio_fornecedor_poucos_clientes,"
            " o.criterio_empresa_nova, o.criterio_valores_identicos,"
            " o.criterio_dia_sem_sessao, o.num_criterios"
            " from expense_outliers o"
            " left join dim_parlamentar dp"
            " on dp.id_parlamentar = o.id_parlamentar and dp.is_current"
            f"{condicao_o}"
            " order by o.zscore desc limit ? offset ?",
            [*parametros, limite, offset],
        ).fetchall()

    colunas = [
        "id_despesa", "id_parlamentar", "nome", "sigla_partido", "sigla_uf",
        "id_fornecedor", "data_sk", "valor_liquido",
        "zscore", "if_score", "criterio_zscore", "criterio_if",
        "criterio_fornecedor_poucos_clientes", "criterio_empresa_nova",
        "criterio_valores_identicos", "criterio_dia_sem_sessao", "num_criterios",
    ]
    itens = [AnomaliaItem.model_validate(dict(zip(colunas, linha))) for linha in linhas]
    return ListaAnomalias(
        pagina=pagina,
        limite=limite,
        total=total,
        threshold=threshold,
        ano=ano,
        itens=itens,
    )


@_tratar_erro_gold
def obter_rede_fornecedor(id_fornecedor: int) -> RedeFornecedor | None:
    """Rede INVERSA: parlamentares que interagiram com um fornecedor.

    Mesma fronteira do `obter_rede_parlamentar`: lê as arestas já
    materializadas na Gold (`network_edges`, ADR-030) e resolve nomes pelas
    dimensões — não recalcula grafo. Fornecedor inexistente → `None`
    (router responde 404).
    """
    with _conexao() as con:
        fornecedor = con.execute(
            "select nome_fornecedor from dim_fornecedor where id_fornecedor = ?",
            [id_fornecedor],
        ).fetchone()
        if fornecedor is None:
            return None
        arestas_tuplas = con.execute(
            "select ne.id_parlamentar, dp.nome, dp.sigla_partido, dp.sigla_uf,"
            " ne.periodo, ne.valor_total"
            " from network_edges ne"
            " left join dim_parlamentar dp"
            " on dp.id_parlamentar = ne.id_parlamentar and dp.is_current"
            " where ne.id_fornecedor = ?"
            " order by ne.valor_total desc",
            [id_fornecedor],
        ).fetchall()

    arestas = [
        ArestaFornecedor.model_validate(
            dict(
                zip(
                    [
                        "id_parlamentar", "nome", "sigla_partido", "sigla_uf",
                        "periodo", "valor_total",
                    ],
                    aresta,
                )
            )
        )
        for aresta in arestas_tuplas
    ]
    total = sum(a.valor_total for a in arestas)
    num_parlamentares = len({a.id_parlamentar for a in arestas})
    return RedeFornecedor(
        id_fornecedor=id_fornecedor,
        nome_fornecedor=fornecedor[0],
        total_recebido=total,
        num_parlamentares=num_parlamentares,
        arestas=arestas,
    )


@_tratar_erro_gold
def listar_comunidades(limite_nos: int = 200) -> ListaComunidades:
    """Comunidades do grafo materializado (`network_nodes`, ADR-030) + nomes.

    Agrupa os nós por `(comunidade_id, periodo)` obtidos da Gold e resolve o
    nome por join com as dimensões (parlamentar na versão vigente do SCD2,
    ADR-020; fornecedor direto). Leitura de resultado — o particionamento já
    foi calculado pela Sprint 5 (Onda 3), não recalculado aqui.

    Gate 3 (auditoria Sprint 7): `limite_nos` limita os nós por comunidade
    (top por pagerank) para o payload nunca explodir com grafos reais —
    o teto é enforced no SQL, não apenas na exibição.
    """
    with _conexao() as con:
        linhas = con.execute(
            """
            select comunidade_id, periodo, id_no, tipo_no, pagerank,
                   degree_centrality, nome
            from (
                select nn.comunidade_id, nn.periodo, nn.id_no, nn.tipo_no,
                       nn.pagerank, nn.degree_centrality,
                       coalesce(dp.nome, df.nome_fornecedor) as nome,
                       row_number() over (
                           partition by nn.comunidade_id, nn.periodo
                           order by nn.pagerank desc, nn.id_no
                       ) as rn
                from network_nodes nn
                left join dim_parlamentar dp
                    on nn.tipo_no = 'parlamentar' and dp.id_parlamentar = nn.id_no
                       and dp.is_current
                left join dim_fornecedor df
                    on nn.tipo_no = 'fornecedor' and df.id_fornecedor = nn.id_no
            ) sub
            where sub.rn <= ?
            order by periodo desc, comunidade_id, tipo_no, id_no
            """,
            [limite_nos],
        ).fetchall()

    grupos: dict[tuple[int, int], dict] = {}
    for comunidade_id, periodo, id_no, tipo_no, pagerank, degree, nome in linhas:
        chave = (comunidade_id, periodo)
        grupo = grupos.setdefault(
            chave, {"comunidade_id": comunidade_id, "periodo": periodo, "nos": []}
        )
        grupo["nos"].append(
            {
                "id_no": id_no,
                "tipo_no": tipo_no,
                "nome": nome,
                "pagerank": pagerank,
                "degree_centrality": degree,
            }
        )

    itens = [
        ComunidadeItem.model_validate(
            {"comunidade_id": c, "periodo": p, "tamanho": len(g["nos"]), "nos": g["nos"]}
        )
        for (c, p), g in grupos.items()
    ]
    return ListaComunidades(total=len(itens), itens=itens)


@_tratar_erro_gold
def listar_relatorio_qualidade(
    *,
    tabela: str | None,
    pagina: int,
    limite: int,
) -> RelatorioQualidade:
    """Data Quality Report da Gold (ADR-031), da execução mais recente.

    `regras_violadas` é lista serializada como JSON string na Silver; na Gold
    vira coluna varchar e é desserializada aqui para o contrato `list[str]`.
    """
    condicao = " where tabela = ?" if tabela else ""
    parametros: list[object] = [tabela] if tabela else []
    offset = (pagina - 1) * limite

    with _conexao() as con:
        total = con.execute(
            f"select count(*) from data_quality_report{condicao}", parametros
        ).fetchone()[0]
        linhas = con.execute(
            "select run_id, tabela, total_registros, registros_validos,"
            " registros_quarentena, registros_deduplicados, regras_violadas,"
            " percentual_nulos_criticos, execution_timestamp"
            f" from data_quality_report{condicao}"
            " order by execution_timestamp desc limit ? offset ?",
            [*parametros, limite, offset],
        ).fetchall()

    colunas = [
        "run_id", "tabela", "total_registros", "registros_validos",
        "registros_quarentena", "registros_deduplicados", "regras_violadas",
        "percentual_nulos_criticos", "execution_timestamp",
    ]
    itens = []
    for linha in linhas:
        bruto = dict(zip(colunas, linha))
        bruto["regras_violadas"] = json.loads(bruto["regras_violadas"] or "[]")
        bruto["execution_timestamp"] = (
            bruto["execution_timestamp"].isoformat()
            if bruto["execution_timestamp"] is not None
            else None
        )
        itens.append(LinhaQualidade.model_validate(bruto))
    return RelatorioQualidade(pagina=pagina, limite=limite, total=total, itens=itens)


@_tratar_erro_gold
def listar_execucoes(*, limite: int) -> PipelineStatus:
    """Execuções do pipeline consolidadas na Gold (ADR-019), mais recentes primeiro."""
    with _conexao() as con:
        linhas = con.execute(
            "select run_id, pipeline_version, execution_timestamp, status,"
            " fontes_com_erro, watermark_camara, watermark_senado,"
            " watermark_cgu_emenda, watermark_cgu_cartao"
            " from pipeline_runs order by execution_timestamp desc limit ?",
            [limite],
        ).fetchall()

    colunas = [
        "run_id", "pipeline_version", "execution_timestamp", "status",
        "fontes_com_erro", "watermark_camara", "watermark_senado",
        "watermark_cgu_emenda", "watermark_cgu_cartao",
    ]
    itens = []
    for linha in linhas:
        bruto = dict(zip(colunas, linha))
        bruto["execution_timestamp"] = (
            bruto["execution_timestamp"].isoformat()
            if bruto["execution_timestamp"] is not None
            else None
        )
        itens.append(ExecucaoPipeline.model_validate(bruto))
    return PipelineStatus(total=len(itens), itens=itens)


# ── Onda 4: agent-ready (ADR-032) ───────────────────────────────


def _mes_de_data_sk(data_sk: int | None) -> str | None:
    """`20260701` → `'2026-07'` — rótulo de janela para os payloads agent."""
    if data_sk is None:
        return None
    texto = str(data_sk)
    return f"{texto[:4]}-{texto[4:6]}"


def _agregado_metricas(con, clausula: str, parametros: list[object]) -> tuple:
    """Agregados da §8 sobre `fact_despesa` para o grão de uma coluna.

    Métricas da Camada Semântica §8 computadas como agregação SQL sobre o
    Gold materializado (ADR-032) — mesmo padrão do `/fornecedores/{cnpj}`.
    Devolve (total_gasto, gasto_medio, num_transacoes, num_fornecedores,
    valor_maximo, valor_mediano, percentil_95).
    """
    return con.execute(
        "select sum(valor_liquido), avg(valor_liquido), count(*),"
        " count(distinct id_fornecedor), max(valor_liquido),"
        " percentile_cont(0.5) within group (order by valor_liquido),"
        " percentile_cont(0.95) within group (order by valor_liquido)"
        f" from fact_despesa where {clausula}",
        parametros,
    ).fetchone()


@_tratar_erro_gold
def obter_agente_parlamentar(id_parlamentar: int) -> AgentParlamentar | None:
    """Contexto semântico agregado de um parlamentar (ADR-032).

    Reúne perfil vigente (SCD2), métricas §8, `hhi` recente
    (`supplier_concentration`), scores do período mais recente
    (`risk_scores`), contagem de anomalias e top-5 fornecedores por valor.
    Parlamentar inexistente → `None` (router responde 404).
    """
    perfil = obter_perfil_parlamentar(id_parlamentar)
    if perfil is None:
        return None

    with _conexao() as con:
        total, medio, n_transacoes, n_fornecedores, maximo, mediano, p95 = (
            _agregado_metricas(con, "id_parlamentar = ?", [id_parlamentar])
        )
        janela = con.execute(
            "select min(data_sk), max(data_sk) from fact_despesa"
        ).fetchone()
        hhi_linha = con.execute(
            "select ano, hhi from supplier_concentration"
            " where id_parlamentar = ? order by ano desc limit 1",
            [id_parlamentar],
        ).fetchone()
        risco_linha = con.execute(
            "select periodo, supplier_concentration_score, political_exposure_score,"
            " supplier_dependency_score, expense_anomaly_score,"
            " network_influence_score, risk_index"
            " from risk_scores where id_parlamentar = ? order by periodo desc limit 1",
            [id_parlamentar],
        ).fetchone()
        num_anomalias = con.execute(
            "select count(*) from expense_outliers where id_parlamentar = ?",
            [id_parlamentar],
        ).fetchone()[0]
        top_linhas = con.execute(
            "select fd.id_fornecedor, df.nome_fornecedor,"
            " sum(fd.valor_liquido) as total_gasto, count(*) as num_transacoes"
            " from fact_despesa fd"
            " join dim_fornecedor df on df.id_fornecedor = fd.id_fornecedor"
            " where fd.id_parlamentar = ?"
            " group by fd.id_fornecedor, df.nome_fornecedor"
            " order by total_gasto desc limit 5",
            [id_parlamentar],
        ).fetchall()

    risco = (
        RiscoParlamentar.model_validate(
            dict(
                zip(
                    [
                        "periodo", "supplier_concentration_score",
                        "political_exposure_score", "supplier_dependency_score",
                        "expense_anomaly_score", "network_influence_score",
                        "risk_index",
                    ],
                    risco_linha,
                )
            )
        )
        if risco_linha is not None
        else None
    )
    metricas = MetricasParlamentar(
        total_gasto=float(total) if total is not None else None,
        gasto_medio=float(medio) if medio is not None else None,
        num_transacoes=n_transacoes or 0,
        num_fornecedores=n_fornecedores,
        valor_maximo=float(maximo) if maximo is not None else None,
        valor_mediano=float(mediano) if mediano is not None else None,
        percentil_95=float(p95) if p95 is not None else None,
        hhi_recente=float(hhi_linha[1]) if hhi_linha is not None else None,
        hhi_periodo=hhi_linha[0] if hhi_linha is not None else None,
    )
    return AgentParlamentar(
        id_parlamentar=perfil.id_parlamentar,
        fonte=perfil.fonte,
        nome=perfil.nome,
        sigla_partido=perfil.sigla_partido,
        sigla_uf=perfil.sigla_uf,
        situacao_normalizada=perfil.situacao_normalizada,
        url_foto=perfil.url_foto,
        periodo_vigente_desde=perfil.effective_date.isoformat(),
        janela_inicio=_mes_de_data_sk(janela[0]) if janela else None,
        janela_fim=_mes_de_data_sk(janela[1]) if janela else None,
        metricas=metricas,
        risco=risco,
        anomalias=AnomaliasParlamentar(
            num_despesas_anomalas=num_anomalias,
            proporcao=(num_anomalias / n_transacoes) if n_transacoes else None,
        ),
        top_fornecedores=[
            FornecedorTop.model_validate(
                {
                    "id_fornecedor": tf[0],
                    "nome_fornecedor": tf[1],
                    "total_gasto": float(tf[2]) if tf[2] is not None else None,
                    "num_transacoes": tf[3],
                }
            )
            for tf in top_linhas
        ],
    )


@_tratar_erro_gold
def obter_agente_fornecedor(cnpj_cpf_valor: str) -> AgentFornecedor | None:
    """Contexto semântico agregado de um fornecedor (ADR-032).

    CNPJ casa exatamente; CPF está pseudonimizado (ADR-011) e não casa pelo
    número cru — `None` nesse caso (router responde 404).
    """
    with _conexao() as con:
        contexto = _fornecedor_contexto(con, cnpj_cpf_valor)
        if contexto is None:
            return None
        total, medio, n_transacoes, n_parlamentares, maximo = con.execute(
            "select sum(valor_liquido), avg(valor_liquido), count(*),"
            " count(distinct id_parlamentar), max(valor_liquido)"
            " from fact_despesa where id_fornecedor = ?",
            [contexto.id_fornecedor],
        ).fetchone()
        top_linhas = con.execute(
            "select fd.id_parlamentar, dp.nome,"
            " sum(fd.valor_liquido) as total_gasto, count(*) as num_transacoes"
            " from fact_despesa fd"
            " join dim_parlamentar dp on dp.id_parlamentar = fd.id_parlamentar and dp.is_current"
            " where fd.id_fornecedor = ?"
            " group by fd.id_parlamentar, dp.nome"
            " order by total_gasto desc limit 5",
            [contexto.id_fornecedor],
        ).fetchall()

    return AgentFornecedor(
        id_fornecedor=contexto.id_fornecedor,
        cnpj_cpf_valor=contexto.cnpj_cpf_valor,
        tipo_documento=(
            contexto.tipo_documento.value
            if contexto.tipo_documento is not None
            else None
        ),
        nome_fornecedor=contexto.nome_fornecedor,
        metricas=MetricasFornecedor(
            total_recebido=float(total) if total is not None else None,
            gasto_medio=float(medio) if medio is not None else None,
            valor_maximo=float(maximo) if maximo is not None else None,
            num_transacoes=n_transacoes or 0,
            num_parlamentares=n_parlamentares,
        ),
        top_parlamentares=[
            ParlamentarTop.model_validate(
                {
                    "id_parlamentar": tp[0],
                    "nome": tp[1],
                    "total_gasto": float(tp[2]) if tp[2] is not None else None,
                    "num_transacoes": tp[3],
                }
            )
            for tp in top_linhas
        ],
    )


@_tratar_erro_gold
def obter_agente_anomalias() -> AgentAnomalias:
    """Resumo agregado de anomalias (ADR-032) — não a lista crua paginada.

    Total, contagem por ano (`data_sk` YYYYMMDD), contagem por critério
    disparado e top-10 por zscore com nome do parlamentar.
    """
    with _conexao() as con:
        total = con.execute("select count(*) from expense_outliers").fetchone()[0]
        por_ano = con.execute(
            "select data_sk // 10000 as ano, count(*) as quantidade"
            " from expense_outliers group by ano order by ano desc"
        ).fetchall()
        criterios = con.execute(
            "select"
            " count(*) filter (where criterio_zscore),"
            " count(*) filter (where criterio_if),"
            " count(*) filter (where criterio_fornecedor_poucos_clientes),"
            " count(*) filter (where criterio_empresa_nova),"
            " count(*) filter (where criterio_valores_identicos),"
            " count(*) filter (where criterio_dia_sem_sessao)"
            " from expense_outliers"
        ).fetchone()
        top = con.execute(
            "select e.id_despesa, e.id_parlamentar, dp.nome,"
            " e.valor_liquido, e.zscore, e.num_criterios"
            " from expense_outliers e"
            " left join dim_parlamentar dp"
            " on dp.id_parlamentar = e.id_parlamentar and dp.is_current"
            " order by e.zscore desc limit 10"
        ).fetchall()

    nomes_criterios = [
        ("zscore", criterios[0]),
        ("isolation_forest", criterios[1]),
        ("fornecedor_poucos_clientes", criterios[2]),
        ("empresa_nova", criterios[3]),
        ("valores_identicos", criterios[4]),
        ("dia_sem_sessao", criterios[5]),
    ]
    return AgentAnomalias(
        total=total,
        por_ano=[
            AnomaliaPorAno.model_validate({"ano": a, "quantidade": q}) for a, q in por_ano
        ],
        por_criterio=[
            AnomaliaPorCriterio(criterio=nome, quantidade=q)
            for nome, q in nomes_criterios
            if q
        ],
        top_por_zscore=[
            AnomaliaTop.model_validate(
                {
                    "id_despesa": t[0],
                    "id_parlamentar": t[1],
                    "nome_parlamentar": t[2],
                    "valor_liquido": float(t[3]) if t[3] is not None else None,
                    "zscore": float(t[4]) if t[4] is not None else None,
                    "num_criterios": t[5],
                }
            )
            for t in top
        ],
    )


@_tratar_erro_gold
def obter_agente_contexto() -> AgentContext:
    """Contexto semântico sistêmico (CU-07/ADR-032) — o "retrato" do Gold."""
    with _conexao() as con:
        globais = con.execute(
            "select sum(valor_liquido), count(*),"
            " count(distinct id_fornecedor), count(distinct id_parlamentar)"
            " from fact_despesa"
        ).fetchone()
        num_anomalias = con.execute("select count(*) from expense_outliers").fetchone()[0]
        periodos = con.execute(
            "select distinct data_sk // 10000 as ano from fact_despesa order by ano"
        ).fetchall()
        qual = con.execute(
            "select run_id, count(*) as tabelas_reportadas,"
            " sum(total_registros) as total_registros,"
            " sum(registros_quarentena) as total_quarentena"
            " from data_quality_report"
            " group by run_id order by max(execution_timestamp) desc limit 1"
        ).fetchone()
        pipe = con.execute(
            "select run_id, status, execution_timestamp, pipeline_version"
            " from pipeline_runs order by execution_timestamp desc limit 1"
        ).fetchone()

    return AgentContext(
        metricas_globais=MetricasGlobais(
            total_gasto=float(globais[0]) if globais[0] is not None else None,
            num_transacoes=globais[1] or 0,
            num_fornecedores=globais[2],
            num_parlamentares=globais[3],
            num_anomalias=num_anomalias,
        ),
        periodos_com_dados=[p[0] for p in periodos],
        qualidade=ResumoQualidade(
            run_id=qual[0] if qual else None,
            tabelas_reportadas=qual[1] if qual else None,
            total_registros=qual[2] if qual else None,
            total_quarentena=qual[3] if qual else None,
        ),
        pipeline=ResumoPipeline(
            run_id=pipe[0] if pipe else None,
            status=pipe[1] if pipe else None,
            execution_timestamp=(
                pipe[2].isoformat() if pipe and pipe[2] is not None else None
            ),
            versao_pipeline=pipe[3] if pipe else None,
        ),
    )


# ── Agregações para gráficos (gastos por UF/partido/parlamentar/tempo) ──
#
# Todas partem de `fact_despesa` juntando `dim_parlamentar` pela versão
# vigente do SCD2 (`is_current`) — mesma convenção dos endpoints agent.
# A API só agrega o Gold materializado (ADR-026): nenhum recálculo analítico.

_JOIN_VIGENTE = (
    "join dim_parlamentar p"
    " on p.surrogate_key = f.surrogate_key and p.is_current"
)


def _agregar_por_dimensao(con: duckdb.DuckDBPyConnection, coluna: str, limite: int) -> list[AgregacaoItem]:
    """GROUP BY genérico sobre uma coluna da dimensão parlamentar vigente."""
    linhas = con.execute(
        f"""
        select p.{coluna} as rotulo,
               sum(f.valor_liquido) as total,
               count(*) as num_despesas
        from fact_despesa f {_JOIN_VIGENTE}
        where p.{coluna} is not null
        group by 1
        order by total desc
        limit ?
        """,
        [limite],
    ).fetchall()
    return [
        AgregacaoItem(rotulo=r[0], total=r[1], num_despesas=r[2]) for r in linhas
    ]


@_tratar_erro_gold
def agregar_gastos_por_uf(*, limite: int) -> ListaAgregacao:
    """Gastos agregados por UF do parlamentar vigente, ordenados por total."""
    with _conexao() as con:
        itens = _agregar_por_dimensao(con, "sigla_uf", limite)
    return ListaAgregacao(limite=limite, itens=itens)


@_tratar_erro_gold
def agregar_gastos_por_partido(*, limite: int) -> ListaAgregacao:
    """Gastos agregados por partido do parlamentar vigente, ordenados por total."""
    with _conexao() as con:
        itens = _agregar_por_dimensao(con, "sigla_partido", limite)
    return ListaAgregacao(limite=limite, itens=itens)


@_tratar_erro_gold
def agregar_top_parlamentares(*, limite: int) -> ListaAgregacao:
    """Top parlamentares por gasto acumulado na versão vigente."""
    with _conexao() as con:
        itens = _agregar_por_dimensao(con, "nome", limite)
    return ListaAgregacao(limite=limite, itens=itens)


@_tratar_erro_gold
def agregar_top_fornecedores(*, limite: int) -> ListaTopFornecedores:
    """Top fornecedores por valor recebido, com contagem de parlamentares."""
    with _conexao() as con:
        linhas = con.execute(
            """
            select f.id_fornecedor,
                   fo.nome_fornecedor,
                   sum(f.valor_liquido) as total,
                   count(distinct f.id_parlamentar) as num_parlamentares
            from fact_despesa f
            join dim_fornecedor fo on fo.id_fornecedor = f.id_fornecedor
            group by 1, 2
            order by total desc
            limit ?
            """,
            [limite],
        ).fetchall()
    return ListaTopFornecedores(
        limite=limite,
        itens=[
            TopFornecedorItem(
                id_fornecedor=r[0],
                nome_fornecedor=r[1],
                total_recebido=r[2],
                num_parlamentares=r[3],
            )
            for r in linhas
        ],
    )


@_tratar_erro_gold
def agregar_despesas_no_tempo() -> SerieTemporal:
    """Série mensal (AAAAMM) de total e quantidade de despesas."""
    with _conexao() as con:
        linhas = con.execute(
            """
            select substr(cast(f.data_sk as varchar), 1, 6) as periodo,
                   sum(f.valor_liquido) as total,
                   count(*) as num_despesas
            from fact_despesa f
            group by 1
            order by 1
            """
        ).fetchall()
    return SerieTemporal(
        itens=[
            SerieTemporalItem(periodo=r[0], total=r[1], num_despesas=r[2])
            for r in linhas
        ]
    )
