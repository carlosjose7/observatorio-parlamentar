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
from pydantic import BaseModel, ConfigDict, Field, SecretStr
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
    setados com o mesmo mês).
    """

    estrategia: EstrategiaWatermark
    campo: str | None = None
    parametro_filtro: str | None = None
    parametro_filtro_fim: str | None = None
    formato_data: str | None = None


class EndpointSettings(_StrictModel):
    """Endpoint de API."""

    path: str
    parametros_fixos: dict[str, str] = Field(default_factory=dict)


class PaginacaoSettings(_StrictModel):
    """Nomes dos query params de paginação e tamanho de página."""

    parametro_pagina: str
    parametro_itens: str | None = None
    itens_por_pagina: int | None = Field(default=None, gt=0)


class RateLimitCamaraSettings(_StrictModel):
    """Rate limit da Câmara (~100 req/min, não documentado oficialmente)."""

    requisicoes_por_minuto: int = Field(default=100, gt=0)


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


def get_sources() -> SourcesSettings:
    """Acesso conveniente a `SourcesSettings` (cacheado)."""
    return load_sources_settings()


def get_pipeline() -> PipelineSettings:
    """Acesso conveniente a `PipelineSettings` (cacheado)."""
    return load_pipeline_settings()


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
