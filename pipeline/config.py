"""pipeline/config.py — Camada única de configuração do pipeline (ADR-008).

Unifica `config/*.yaml` (configuração estática e versionada) e `.env`
(segredos e variáveis de ambiente) em objetos `Settings` tipados via
Pydantic. Nenhum módulo deve ler arquivos de configuração diretamente —
sempre através deste loader.

Consequências do ADR-008:
- Toda configuração nova deve ser registrada primeiro em uma class
  `Settings` — sem isso, a config não é carregada (`extra="forbid"`).
- `pipeline_version` NÃO é lido daqui: é obtido de `pyproject.toml` em
  runtime (fonte única, RF-12 / versionamento.md §1).
- Segredos permanecem fora do repositório (`.env` no `.gitignore`).
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = REPO_ROOT / "config"
ENV_FILE = REPO_ROOT / ".env"
PYPROJECT_FILE = REPO_ROOT / "pyproject.toml"


class _StrictModel(BaseModel):
    """Base para configs versionadas: chave não registrada não é carregada."""

    model_config = ConfigDict(extra="forbid")


# ── config/sources.yaml ──────────────────────────────────────────


class EstrategiaWatermark(str, Enum):
    """Estratégia de watermark — versionamento.md §2."""

    INCREMENTAL = "incremental"
    ARQUIVO_ANUAL = "arquivo_anual"
    PARTICION_ANUAL = "particao_anual"


class WatermarkSettings(_StrictModel):
    """Watermark de um domínio de ingestão.

    `campo` é o campo na resposta da fonte usado para comparar com o
    último watermark; `parametro_filtro` é o query param usado para
    filtrar a requisição (nem sempre coincide com `campo`);
    `parametro_filtro_fim` é opcional para fontes que exigem um
    período fechado na requisição (ex: CGU cartões exige
    `mesExtratoInicio` E `mesExtratoFim` — no incremental ambos são
    setados com o mesmo mês). `parametro_filtro_ano` e
    `parametro_filtro_mes` refinam o filtro dentro de um período maior
    (ex: Câmara exige `idLegislatura`+`ano`+`mes` juntos).
    """

    estrategia: EstrategiaWatermark
    campo: str | None = None
    parametro_filtro: str | None = None
    parametro_filtro_fim: str | None = None
    parametro_filtro_ano: str | None = None
    parametro_filtro_mes: str | None = None
    formato_data: str | None = None


class EndpointSettings(_StrictModel):
    """Endpoint de API."""

    path: str
    parametros_fixos: dict[str, str] = Field(default_factory=dict)
    rate_limit: RateLimitEndpointSettings | None = None


class PaginacaoSettings(_StrictModel):
    """Nomes dos query params de paginação e tamanho de página."""

    parametro_pagina: str
    parametro_itens: str | None = None
    itens_por_pagina: int | None = Field(default=None, gt=0)


class RateLimitCamaraSettings(_StrictModel):
    """Rate limit da Câmara (~100 req/min, não documentado oficialmente)."""

    requisicoes_por_minuto: int = Field(default=100, gt=0)


class RateLimitEndpointSettings(_StrictModel):
    """Override de rate limit por endpoint (corretivo 6.5).

    Alguns endpoints de uma mesma fonte têm limite mais conservador que o
    da fonte — ex: `/cartoes` da CGU, tratado a 180 req/min (hipótese
    conservadora, docs/sprint6.5_limites_fontes.md §4) até confirmação
    oficial. Quando presente, sobrepõe `rate_limit` da fonte.
    """

    requisicoes_por_minuto: int = Field(gt=0)


class SiafiCamaraSettings(_StrictModel):
    """Código SIAFI da Câmara — pendência conhecida (BACKLOG.md)."""

    ug_siafi: str | None = None


class DeduplicacaoSettings(_StrictModel):
    """Deduplicação por chave natural na carga em Bronze (versionamento.md §2.2/§2.3).

    `campo` é o nome do campo do modelo Bronze (snake_case) usado como chave
    natural; `escopo` define o alcance de leitura da deduplicação:
    `ano_mes` (padrão) lê apenas a partição `fonte/ano=A/mes=M`;
    `ano` lê o ano inteiro (`fonte/ano=A/**`) para chaves únicas por ano
    (Senado CEAPS por COD_DOCUMENTO, emendas CGU por codigoEmenda).
    """

    campo: str
    escopo: str = "ano_mes"


class CargaHistoricaSettings(_StrictModel):
    """Início da janela histórica para a primeira carga (watermark vazio).

    Usado apenas quando não há watermark consolidado. Após a primeira carga,
    a extração é incremental/por período corrente.
    """

    data_inicio: str | None = None  # camara — ex: "2015-01-01" (filtro dataInicio)
    ano_inicio: int | None = None  # senado e emendas — ex: 2015
    mes_inicio: str | None = None  # cartoes — ex: "01/2013" (MM/AAAA)


class CamaraSettings(_StrictModel):
    """Fonte: API Câmara dos Deputados (dadosabertos.camara.leg.br)."""

    nome: str
    base_url: str
    formato: str = "json"
    encoding: str = "utf-8"
    paginacao: PaginacaoSettings
    rate_limit: RateLimitCamaraSettings
    endpoints: dict[str, EndpointSettings]
    watermark: dict[str, WatermarkSettings]
    deduplicacao: DeduplicacaoSettings
    carga_historica: CargaHistoricaSettings | None = None
    siafi: SiafiCamaraSettings = Field(default_factory=SiafiCamaraSettings)


class SiafiSenadoSettings(_StrictModel):
    """UG/Gestão SIAFI do Senado Federal (ADR-010)."""

    unidade_gestora: str
    gestao: str


class ExecucaoSenadoSettings(_StrictModel):
    """Frequência de execução da fonte Senado (sazonal, ADR-009)."""

    frequencia: str = "sazonal"


class ApiDadosAbertosSettings(_StrictModel):
    """API de Dados Abertos do Senado (legislativo) — Onda 2.

    Fonte distinta do CSV CEAPS: `legis.senado.leg.br/dadosabertos`.
    Fornece os dados mestres de senadores (`/senador/lista/atual.json`)
    para `dim_parlamentar` (ADR-020).
    """

    base_url: str
    formato: str = "json"
    encoding: str = "utf-8"
    endpoints: dict[str, EndpointSettings]


class SenadoSettings(_StrictModel):
    """Fonte: CSV anual CEAPS do Senado Federal (ADR-009)."""

    nome: str
    base_url: str
    padrao_arquivo: str
    formato: str = "csv"
    encoding: str = "ISO-8859-1"
    separador: str = ";"
    quote_char: str = '"'
    separador_decimal: str = ","
    formato_data: str = "%d/%m/%Y"
    api_dados: ApiDadosAbertosSettings
    deduplicacao: DeduplicacaoSettings
    carga_historica: CargaHistoricaSettings | None = None
    watermark: dict[str, WatermarkSettings]
    siafi: SiafiSenadoSettings
    execucao: ExecucaoSenadoSettings = Field(default_factory=ExecucaoSenadoSettings)


class AuthTransparenciaSettings(_StrictModel):
    """Autenticação da CGU — valor da chave em `.env` (env_var)."""

    header: str = "chave-api-dados"
    env_var: str = "CGU_API_KEY"


class RateLimitTransparenciaSettings(_StrictModel):
    """Rate limit documentado da CGU (ADR-009 / data_dictionary.md §3.3)."""

    requisicoes_por_minuto_diurno: int = Field(default=400, gt=0)
    requisicoes_por_minuto_noturno: int = Field(default=700, gt=0)
    janela_noturna_inicio: str = "00:00"
    janela_noturna_fim: str = "06:00"


class TransparenciaSettings(_StrictModel):
    """Fonte: Portal da Transparência (CGU)."""

    nome: str
    base_url: str
    auth: AuthTransparenciaSettings
    formato: str = "json"
    paginacao: PaginacaoSettings
    rate_limit: RateLimitTransparenciaSettings
    endpoints: dict[str, EndpointSettings]
    watermark: dict[str, WatermarkSettings]
    deduplicacao: dict[str, DeduplicacaoSettings]
    carga_historica: dict[str, CargaHistoricaSettings] | None = None
    separador_decimal: str = ","
    formato_data: str = "%d/%m/%Y"


class SourcesSettings(_StrictModel):
    """Configuração consolidada das três fontes de dados."""

    camara: CamaraSettings
    senado: SenadoSettings
    transparencia: TransparenciaSettings


# ── config/analytics.yaml ────────────────────────────────────────


class RedeSettings(_StrictModel):
    """Parâmetros do grafo parlamentar↔fornecedor (ADR-030.3).

    `limite_arestas_recorte` é o disjuntor de custo do recálculo total do
    grafo: acima de N arestas por período, o pipeline dispara alerta no
    DQ Report (sem bloquear) para reavaliar estratégia incremental via ADR
    de superseding. Fonte única ADR-008 — nunca hardcoded no código.
    """

    limite_arestas_recorte: int = Field(default=50000, gt=0)


#: Scores individuais do ADR-027 (grão período × parlamentar) — as 5
#: fórmulas do §9, na ordem do `risk_index`. Fonte única dos pesos
#: (`config/analytics.yaml → risk.pesos`, ADR-029) e do módulo de risk.
SCORES_RISCO = (
    "supplier_concentration_score",
    "political_exposure_score",
    "supplier_dependency_score",
    "expense_anomaly_score",
    "network_influence_score",
)


class RiskSettings(_StrictModel):
    """Pesos do `risk_index` e composição (ADR-029, Onda 4).

    `pesos` define a ponderação dos 5 scores do ADR-027 no `risk_index`:
    `risk_index_p = Σ_i w_i · score_i(p)`. Baseline vigente: 0.2 uniforme
    (ADR-003/ADR-029) — os pesos NÃO mudam por operação manual, apenas por
    ADR de amendment (pós-Sprint 6.5, com dado real). Validação Pydantic:
    exatamente as 5 chaves de `SCORES_RISCO`, todas > 0 e `sum == 1`
    (checklist de DQ — ADR-029).
    """

    pesos: dict[str, float] = Field(
        default_factory=lambda: {score: 0.2 for score in SCORES_RISCO}
    )

    @model_validator(mode="after")
    def _validar_pesos(self) -> "RiskSettings":
        if set(self.pesos) != set(SCORES_RISCO):
            raise ValueError(
                f"risk.pesos deve conter exatamente {set(SCORES_RISCO)} — recebido {set(self.pesos)}"
            )
        if any(v <= 0 for v in self.pesos.values()):
            raise ValueError("risk.pesos exige pesos > 0")
        total = sum(self.pesos.values())
        if not abs(total - 1.0) < 1e-9:
            raise ValueError(f"risk.pesos deve somar 1 — recebido {total}")
        return self


class AnalyticsSettings(_StrictModel):
    """Configuração da camada analítica/ML da Sprint 5.

    Topos consumidos por `analytics/parliamentarians/analytics.py` (Onda 1),
    `analytics/anomalies/anomalies.py` (Onda 2), `analytics/network/network.py` (Onda 3) e
    `analytics/parliamentarians/risk.py` (Onda 4 — `risk.pesos`, ADR-029).
    """

    rede: RedeSettings = Field(default_factory=RedeSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)


# ── config/api.yaml ──────────────────────────────────────────────


class ApiSettings(_StrictModel):
    """Configuração de runtime da API REST (Sprint 6, ADR-008).

    Identifica a API (`titulo`/`versao`/`descricao` também servidos em
    `/` e no OpenAPI) e define host/porta de execução. `caminho_db_env_var`
    nomeia a variável de ambiente que aponta para o DuckDB da camada Gold —
    a fronteira de leitura da API (ADR-026): ela NUNCA lê Bronze/Silver nem
    `ml_staging`. Paginação (`pagina_padrao`/`limite_padrao`/`limite_maximo`)
    é régua de recurso da API (RF-04) e vive aqui, não hardcoded.
    """

    titulo: str = "Observatório Parlamentar API"
    versao: str = "0.1.0"
    descricao: str = "API da Plataforma de Inteligência Parlamentar Brasileira"
    host: str = "0.0.0.0"
    porta: int = Field(default=8000, ge=1, le=65535)
    caminho_db_env_var: str = "DUCKDB_DATABASE_PATH"
    pagina_padrao: int = Field(default=1, ge=1)
    limite_padrao: int = Field(default=20, ge=1)
    limite_maximo: int = Field(default=100, ge=1)
    ano_minimo_consulta: int = Field(default=2015, ge=1900)


# ── config/dashboard.yaml ────────────────────────────────────────


class DashboardSettings(_StrictModel):
    """Configuração da camada de apresentação Streamlit (Sprint 7, ADR-008).

    Identifica o dashboard (`titulo`/`subtitulo`) e aponta para a base URL da
    API REST via variável de ambiente (`url_env_var`, default `API_URL` —
    injetada pelo docker-compose como `http://api:8000`). O dashboard NUNCA
    abre o DuckDB: consome a API como fronteira de leitura (RF-05, ADR-026).
    `exportacao_formatos` governa os botões de exportação (RF-08).
    """

    titulo: str = "Observatório Parlamentar"
    subtitulo: str = "Plataforma de Inteligência Parlamentar Brasileira"
    url_env_var: str = "API_URL"
    url_padrao: str = "http://localhost:8000"
    timeout_segundos: float = Field(default=30.0, gt=0)
    resposta_max_bytes: int = Field(default=10_485_760, gt=0)
    exportacao_formatos: list[str] = Field(
        default_factory=lambda: ["csv", "excel", "pdf"]
    )
    exportacao_max_linhas: int = Field(default=5_000, gt=0)


# ── config/pipeline.yaml ─────────────────────────────────────────


class AgendamentoSettings(_StrictModel):
    """Agendamento do pipeline (cron)."""

    cron: str = "@daily"


class CamadaBronzeSettings(_StrictModel):
    """Persistência da camada Bronze (Parquet + MinIO)."""

    tipo: str = "parquet"
    bucket_minio: str = "bronze"
    particionamento: list[str] = Field(default_factory=list)


class CamadaDuckdbSettings(_StrictModel):
    """Persistência das camadas Silver/Gold (DuckDB)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tipo: str = "duckdb"
    caminho_env_var: str = "DUCKDB_DATABASE_PATH"
    schema_duckdb: str = Field(..., alias="schema")


class ArmazenamentoSettings(_StrictModel):
    """Diretórios e sistemas de persistência por camada."""

    bronze: CamadaBronzeSettings
    silver: CamadaDuckdbSettings
    gold: CamadaDuckdbSettings


class MinioSettings(_StrictModel):
    """Configuração do MinIO — valores sensíveis vêm de `.env` (env_var)."""

    endpoint_env_var: str = "MINIO_ENDPOINT"
    usuario_env_var: str = "MINIO_ROOT_USER"
    senha_env_var: str = "MINIO_ROOT_PASSWORD"
    secure: bool = False  # rede interna Docker (ADR-007)


class HttpSettings(_StrictModel):
    """Configuração HTTP para APIs externas."""

    request_timeout_seconds: float = Field(default=30.0, gt=0)


class VersionamentoSettings(_StrictModel):
    """Metadados de reprodutibilidade (RF-12) e tabela de controle."""

    metadados_obrigatorios: list[str] = Field(default_factory=list)
    tabela_controle: str = "pipeline_runs"


class RetryDefaultSettings(_StrictModel):
    """Política de retry padrão via tenacity (ADR-009)."""

    max_tentativas: int = Field(default=5, ge=1)
    espera_exponencial_min_segundos: float = Field(default=2.0, ge=0)
    espera_exponencial_max_segundos: float = Field(default=60.0, ge=0)


class LoggingSettings(_StrictModel):
    """Configuração de logging estruturado (structlog)."""

    nivel_env_var: str = "LOG_LEVEL"
    formato: str = "json"


class ValidacaoSettings(_StrictModel):
    """Modo de validação da carga inicial (nunca ativo em produção).

    Quando `habilitado`, a janela histórica inicial é truncada para
    `limite_periodos` períodos (anos ou meses) e o estado de watermark é
    gravado em namespace isolado — valida as cargas com poucos dados sem
    contaminar o store real. O modo é sinalizado em log.
    """

    habilitado: bool = False
    limite_periodos: int | None = Field(default=None, ge=1)


class DataQualitySettings(_StrictModel):
    """Gate de integridade referencial da camada Gold (ADR-022.3a).

    `fk_orfa_threshold_pct` é o percentual de FK órfã nos fatos que dispara
    o alerta do test genérico dbt `fk_orphan_pct`. É a FONTE ÚNICA do
    threshold (ADR-008): o dbt o recebe via `--vars` gerado por
    `get_dbt_vars()` (ver funções abaixo) — nunca declara o valor próprio em
    `dbt_project.yml`.
    """

    fk_orfa_threshold_pct: float = Field(default=5.0, gt=0)


class PipelineSettings(_StrictModel):
    """Configuração de runtime do pipeline."""

    agendamento: AgendamentoSettings = Field(default_factory=AgendamentoSettings)
    armazenamento: ArmazenamentoSettings
    minio: MinioSettings = Field(default_factory=MinioSettings)
    http: HttpSettings = Field(default_factory=HttpSettings)
    versionamento: VersionamentoSettings = Field(default_factory=VersionamentoSettings)
    retry_default: RetryDefaultSettings = Field(default_factory=RetryDefaultSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    validacao: ValidacaoSettings = Field(default_factory=ValidacaoSettings)
    data_quality: DataQualitySettings = Field(default_factory=DataQualitySettings)


# ── .env (segredos e variáveis de ambiente) ──────────────────────


class EnvSettings(BaseSettings):
    """Segredos e variáveis de ambiente locais — carregados de `.env`."""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    cpf_hmac_secret_key: SecretStr = Field(default=SecretStr(""))
    cgu_api_key: SecretStr = Field(default=SecretStr(""))
    minio_endpoint: str = ""
    minio_root_user: str = "observatorio_admin"
    minio_root_password: SecretStr = Field(default=SecretStr(""))
    airflow_fernet_key: str = ""
    duckdb_database_path: str = "data/silver/observatorio.duckdb"
    log_level: str = "INFO"


# ── Loaders ──────────────────────────────────────────────────────


def _load_yaml(filename: str) -> dict:
    """Carrega um YAML versionado de `config/` para validação Pydantic."""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Arquivo de configuração ausente: {path}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@lru_cache(maxsize=1)
def load_sources_settings() -> SourcesSettings:
    """Carrega `config/sources.yaml` (schema `sources:`)."""
    return SourcesSettings.model_validate(_load_yaml("sources.yaml")["sources"])


@lru_cache(maxsize=1)
def load_pipeline_settings() -> PipelineSettings:
    """Carrega `config/pipeline.yaml` (schema `pipeline:`)."""
    return PipelineSettings.model_validate(_load_yaml("pipeline.yaml")["pipeline"])


@lru_cache(maxsize=1)
def load_env_settings() -> EnvSettings:
    """Carrega `.env` + variáveis de ambiente do processo."""
    return EnvSettings()


@lru_cache(maxsize=1)
def load_analytics_settings() -> AnalyticsSettings:
    """Carrega `config/analytics.yaml` (schema `analytics:`)."""
    return AnalyticsSettings.model_validate(_load_yaml("analytics.yaml")["analytics"])


@lru_cache(maxsize=1)
def load_api_settings() -> ApiSettings:
    """Carrega `config/api.yaml` (schema `api:`)."""
    return ApiSettings.model_validate(_load_yaml("api.yaml")["api"])


@lru_cache(maxsize=1)
def load_dashboard_settings() -> DashboardSettings:
    """Carrega `config/dashboard.yaml` (schema `dashboard:`)."""
    return DashboardSettings.model_validate(
        _load_yaml("dashboard.yaml")["dashboard"]
    )


def get_sources() -> SourcesSettings:
    """Acesso conveniente a `SourcesSettings` (cacheado)."""
    return load_sources_settings()


def get_pipeline() -> PipelineSettings:
    """Acesso conveniente a `PipelineSettings` (cacheado)."""
    return load_pipeline_settings()


def get_analytics() -> AnalyticsSettings:
    """Acesso conveniente a `AnalyticsSettings` (cacheado)."""
    return load_analytics_settings()


def get_api() -> ApiSettings:
    """Acesso conveniente a `ApiSettings` (cacheado)."""
    return load_api_settings()


def get_dashboard() -> DashboardSettings:
    """Acesso conveniente a `DashboardSettings` (cacheado)."""
    return load_dashboard_settings()


def get_dbt_vars() -> dict[str, str]:
    """Vars a injetar no dbt Gold via `--vars`, derivadas de `config/`.

    Fonte única (ADR-008): cada valor supérfluo vive em `config/pipeline.yaml`
    (validado por Pydantic) e é reaproveitado aqui na forma entendida pelo dbt —
    o projeto dbt NÃO declara valores supérfluos próprios. Toda invocação do
    `dbt build`/`dbt test`/`dbt run` (DAG futura do Gold ou testes) deve passar
    `--vars (json.dumps(get_dbt_vars()))`; sem isso, o dbt NÃO resolve a variável
    exigida (falha em vez de aplicar um default divergente — PROJECT_CONTEXT §15).

    O valor é string (JSON `--vars`), preservando a leitura numérica no
    consumo via `var`.
    """
    pipeline = get_pipeline()
    return {
        "fk_orfas_threshold_pct": str(pipeline.data_quality.fk_orfa_threshold_pct),
    }


def get_env() -> EnvSettings:
    """Acesso conveniente a `EnvSettings` (cacheado)."""
    return load_env_settings()


def get_pipeline_version() -> str:
    """Versão semântica do pipeline, lida de `pyproject.toml` (RF-12).

    Fonte única — `pipeline_version` não é declarado em YAML nem `.env`
    (versionamento.md §1: gerado do `pyproject.toml` no build da imagem).
    """
    try:
        import tomllib

        with PYPROJECT_FILE.open("rb") as fh:
            data = tomllib.load(fh)
        return data["project"]["version"]
    except (OSError, KeyError):
        return "0.0.0-dev"
