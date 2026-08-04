"""pipeline/storage.py — persistência da camada Bronze (Parquet).

Dois backends com a mesma interface (ADR-007): filesystem local
(`LocalParquetStorage`, usado em desenvolvimento e testes) e MinIO
(`MinioParquetStorage`, usado na rede interna Docker).

A escrita de fatos em Bronze é **merge com deduplicação por chave natural**
(versionamento.md §2.2/§2.3): lê o que já existe no escopo da partição,
descartar chaves já presentes (keep-first-seen — registros antigos não são
sobrescritos) e **grava somente as linhas novas** em arquivo adicional. Com
isso, reprocessamento/backfill nunca duplica, e linhas tardias (correções de
fonte) são incorporadas preservando a primeira versão observada.

`pipeline_runs` é a exceção: não é particionado e usa `write_file` (um
arquivo por run_id) — caminho que não envolve colunas de partição.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Protocol

import pandas as pd

from pipeline.config import get_env, get_pipeline


class Storage(Protocol):
    """Interface comum de persistência Parquet da camada Bronze."""

    def read_dir(self, rel_dir: Path, columns: list[str] | None = None) -> pd.DataFrame:
        """Lê todos os arquivos Parquet sob `rel_dir`; vazio se não existir."""
        ...

    def write_merged(
        self,
        write_dir: Path,
        new_df: pd.DataFrame,
        natural_key: str | None,
        merge_scope: str = "ano_mes",
    ) -> None:
        """Grava somente as linhas de `new_df` cuja chave natural é nova.

        `merge_scope` controla o escopo de leitura da deduplicação:
        `ano_mes` (padrão) lê apenas a partição `fonte/ano=A/mes=M`;
        `ano` lê o ano inteiro (`fonte/ano=A/**`), para chaves naturais que
        só são únicas dentro do ano (Senado CEAPS por COD_DOCUMENTO e
        emendas CGU por codigoEmenda).
        """
        ...

    def write_file(self, rel_dir: Path, df: pd.DataFrame, filename: str) -> None:
        """Grava um único arquivo em caminho não particionado (ex: controle)."""
        ...


class LocalParquetStorage:
    """Persistência local (desenvolvimento e testes)."""

    def __init__(self, root: Path):
        self.root = root

    def _caminho(self, rel_dir: Path) -> Path:
        return self.root.joinpath(rel_dir)

    def read_dir(self, rel_dir: Path, columns: list[str] | None = None) -> pd.DataFrame:
        caminho = self._caminho(rel_dir)
        arquivos = sorted(caminho.glob("**/*.parquet")) if caminho.exists() else []
        if not arquivos:
            return pd.DataFrame(columns=columns)
        return pd.concat([pd.read_parquet(f) for f in arquivos], ignore_index=True)

    def write_merged(
        self,
        write_dir: Path,
        new_df: pd.DataFrame,
        natural_key: str | None = None,
        merge_scope: str = "ano_mes",
    ) -> None:
        merge_dir = write_dir.parent if merge_scope == "ano" else write_dir
        existente = self.read_dir(merge_dir, columns=list(new_df.columns))

        novos = new_df
        if natural_key:
            if not existente.empty:
                chaves_existentes = set(existente[natural_key].dropna())
                novos = novos[~novos[natural_key].isin(chaves_existentes)]
            novos = novos.drop_duplicates(subset=[natural_key], keep="first")
        if novos.empty:
            return

        destino = self._caminho(write_dir)
        destino.mkdir(parents=True, exist_ok=True)
        novos.to_parquet(destino / f"run-{uuid.uuid4()}.parquet", index=False)

    def write_file(self, rel_dir: Path, df: pd.DataFrame, filename: str) -> None:
        destino = self._caminho(rel_dir)
        destino.mkdir(parents=True, exist_ok=True)
        df.to_parquet(destino / filename, index=False)


class MinioParquetStorage:
    """Persistência em MinIO (rede interna Docker, ADR-007)."""

    def __init__(self, client, bucket: str):
        self.client = client
        self.bucket = bucket

    def _prefixo(self, rel_dir: Path) -> str:
        return str(rel_dir).replace("\\", "/").lstrip("/") + "/"

    def _objetos(self, prefix: str) -> list[str]:
        return [
            obj.object_name
            for obj in self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
            if obj.object_name.endswith(".parquet")
        ]

    def read_dir(self, rel_dir: Path, columns: list[str] | None = None) -> pd.DataFrame:
        prefix = self._prefixo(rel_dir)
        nomes = self._objetos(prefix)
        if not nomes:
            return pd.DataFrame(columns=columns)
        quadros = []
        for nome in nomes:
            resp = self.client.get_object(self.bucket, nome)
            quadros.append(pd.read_parquet(io.BytesIO(resp.read())))
        return pd.concat(quadros, ignore_index=True)

    def write_merged(
        self,
        write_dir: Path,
        new_df: pd.DataFrame,
        natural_key: str | None = None,
        merge_scope: str = "ano_mes",
    ) -> None:
        merge_dir = write_dir.parent if merge_scope == "ano" else write_dir
        existente = self.read_dir(merge_dir, columns=list(new_df.columns))

        novos = new_df
        if natural_key:
            if not existente.empty:
                chaves_existentes = set(existente[natural_key].dropna())
                novos = novos[~novos[natural_key].isin(chaves_existentes)]
            novos = novos.drop_duplicates(subset=[natural_key], keep="first")
        if novos.empty:
            return

        prefix = self._prefixo(write_dir)
        buf = io.BytesIO()
        novos.to_parquet(buf, engine="pyarrow", index=False)
        dados = buf.getvalue()
        self.client.put_object(
            self.bucket,
            prefix + f"run-{uuid.uuid4()}.parquet",
            io.BytesIO(dados),
            length=len(dados),
        )

    def write_file(self, rel_dir: Path, df: pd.DataFrame, filename: str) -> None:
        prefix = self._prefixo(rel_dir)
        buf = io.BytesIO()
        df.to_parquet(buf, engine="pyarrow", index=False)
        dados = buf.getvalue()
        self.client.put_object(
            self.bucket, prefix + filename, io.BytesIO(dados), length=len(dados)
        )


def criar_storage_local(root: Path | None = None) -> LocalParquetStorage:
    """Storage local padrão em `data/bronze/` (desenvolvimento e testes)."""
    if root is None:
        root = Path("data") / "bronze"
    return LocalParquetStorage(root)


def criar_storage_minio() -> MinioParquetStorage:
    """Storage MinIO a partir de config/pipeline.yaml + `.env` (ADR-008)."""
    import minio  # import lazy: backend opcional

    env = get_env()
    cfg = get_pipeline()
    endpoint = env.minio_endpoint
    host = endpoint.split("://", 1)[-1] if "://" in endpoint else endpoint
    secure = cfg.minio.secure
    if endpoint.lower().startswith("https"):
        secure = True
    cliente = minio.Minio(
        host,
        access_key=env.minio_root_user,
        secret_key=env.minio_root_password.get_secret_value(),
        secure=secure,
    )
    return MinioParquetStorage(cliente, cfg.armazenamento.bronze.bucket_minio)


def criar_storage() -> Storage:
    """Escolhe o backend: MinIO se configurado no `.env`, senão local."""
    env = get_env()
    if env.minio_endpoint:
        return criar_storage_minio()
    return criar_storage_local()
