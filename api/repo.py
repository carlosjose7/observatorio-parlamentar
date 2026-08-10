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

import duckdb
import structlog
from pathlib import Path

from pipeline.config import REPO_ROOT, get_api, get_env
from pipeline.normalize import normalizar_nome_proprio

from api.schemas.anomalias import AnomaliaItem, ListaAnomalias
from api.schemas.qualidade import LinhaQualidade, RelatorioQualidade
from api.schemas.rede import ComunidadeItem, ListaComunidades
from api.schemas.fornecedores import (
    FornecedorContexto,
    FornecedorResumo,
    ListaFornecedores,
    ListaParlamentaresFornecedor,
    ParlamentarFornecedor,
    PerfilFornecedor,
)
from api.schemas.pipeline import ExecucaoPipeline, PipelineStatus
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
    select id_parlamentar, nome, sigla_partido, sigla_uf, situacao_normalizada, fonte
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
        colunas = ["id_parlamentar", "nome", "sigla_partido", "sigla_uf", "situacao_normalizada", "fonte"]

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
                   sigla_partido, sigla_uf, situacao_normalizada, id_legislatura,
                   effective_date, end_date, is_current
            from dim_parlamentar
            where id_parlamentar = ? and is_current
            """,
            [id_parlamentar],
        ).fetchone()
    if linha is None:
        return None
    colunas = [
        "id_parlamentar", "surrogate_key", "fonte", "nome", "nome_normalizado",
        "sigla_partido", "sigla_uf", "situacao_normalizada", "id_legislatura",
        "effective_date", "end_date", "is_current",
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


# ── Onda 3: anomalias, comunidades, qualidade e pipeline ─────────


@_tratar_erro_gold
def listar_anomalias(
    *,
    threshold: float | None,
    pagina: int,
    limite: int,
) -> ListaAnomalias:
    """Lista despesas sinalizadas na Gold (Onda 3, ADR-002/§10).

    Lê `expense_outliers` materializada — nunca recalcula a regra. O filtro
    `threshold` é piso sobre `zscore` do conjunto JÁ sinalizado (decisão de
    Onda 3): reabrir o `-0.1` do Isolation Forest ou os `>= 2` critérios
    seria re-execução de inferência, proibida pela fronteira (ADR-026/ADR-030).
    """
    condicao = " where zscore >= ?" if threshold is not None else ""
    parametros: list[object] = [threshold] if threshold is not None else []
    offset = (pagina - 1) * limite

    with _conexao() as con:
        total = con.execute(
            f"select count(*) from expense_outliers{condicao}", parametros
        ).fetchone()[0]
        linhas = con.execute(
            "select id_despesa, id_parlamentar, id_fornecedor, data_sk, valor_liquido,"
            " zscore, if_score, criterio_zscore, criterio_if,"
            " criterio_fornecedor_poucos_clientes, criterio_empresa_nova,"
            " criterio_valores_identicos, criterio_dia_sem_sessao, num_criterios"
            f" from expense_outliers{condicao}"
            " order by zscore desc limit ? offset ?",
            [*parametros, limite, offset],
        ).fetchall()

    colunas = [
        "id_despesa", "id_parlamentar", "id_fornecedor", "data_sk", "valor_liquido",
        "zscore", "if_score", "criterio_zscore", "criterio_if",
        "criterio_fornecedor_poucos_clientes", "criterio_empresa_nova",
        "criterio_valores_identicos", "criterio_dia_sem_sessao", "num_criterios",
    ]
    itens = [AnomaliaItem.model_validate(dict(zip(colunas, linha))) for linha in linhas]
    return ListaAnomalias(
        pagina=pagina, limite=limite, total=total, threshold=threshold, itens=itens
    )


@_tratar_erro_gold
def listar_comunidades() -> ListaComunidades:
    """Comunidades do grafo materializado (`network_nodes`, ADR-030) + nomes.

    Agrupa os nós por `(comunidade_id, periodo)` obtidos da Gold e resolve o
    nome por join com as dimensões (parlamentar na versão vigente do SCD2,
    ADR-020; fornecedor direto). Leitura de resultado — o particionamento já
    foi calculado pela Sprint 5 (Onda 3), não recalculado aqui.
    """
    with _conexao() as con:
        linhas = con.execute(
            """
            select nn.comunidade_id, nn.periodo, nn.id_no, nn.tipo_no,
                   nn.pagerank, nn.degree_centrality,
                   coalesce(dp.nome, df.nome_fornecedor) as nome
            from network_nodes nn
            left join dim_parlamentar dp
                on nn.tipo_no = 'parlamentar' and dp.id_parlamentar = nn.id_no and dp.is_current
            left join dim_fornecedor df
                on nn.tipo_no = 'fornecedor' and df.id_fornecedor = nn.id_no
            order by nn.periodo desc, nn.comunidade_id, nn.tipo_no, nn.id_no
            """
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