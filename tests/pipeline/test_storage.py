"""Persistência Parquet isolada de rede — regressões da Sprint 8."""

import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import pipeline.storage as storage_module
from pipeline.storage import LocalParquetStorage, MinioParquetStorage


class FakeMinio:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.buckets: set[str] = set()

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.buckets.add(bucket)

    def list_objects(self, _bucket, prefix, recursive):
        assert recursive
        return [SimpleNamespace(object_name=name) for name in self.objects if name.startswith(prefix)]

    def get_object(self, _bucket, name):
        return io.BytesIO(self.objects[name])

    def put_object(self, _bucket, name, data, length):
        value = data.read()
        assert len(value) == length
        self.objects[name] = value


def _df(*ids: int) -> pd.DataFrame:
    return pd.DataFrame({"id": list(ids), "valor": [f"v-{item}" for item in ids]})


def _storage_backends(tmp_path):
    return [
        LocalParquetStorage(tmp_path / "local"),
        MinioParquetStorage(FakeMinio(), "bronze"),
    ]


def test_read_dir_vazio_e_write_file_em_ambos_backends(tmp_path):
    for storage in _storage_backends(tmp_path):
        assert storage.read_dir(Path("ausente"), columns=["id", "valor"]).empty
        storage.write_file(Path("controle/pipeline_runs"), _df(1), "run-1.parquet")
        pd.testing.assert_frame_equal(
            storage.read_dir(Path("controle")), _df(1), check_dtype=False
        )


def test_write_merged_deduplica_particao_e_chave_nula(tmp_path):
    for storage in _storage_backends(tmp_path):
        destino = Path("camara/ano=2026/mes=1")
        storage.write_merged(destino, _df(1, 1, 2), natural_key="id")
        storage.write_merged(destino, _df(2, 3), natural_key="id")
        storage.write_merged(destino, _df(1, 2, 3), natural_key="id")
        resultado = storage.read_dir(destino).sort_values("id").reset_index(drop=True)
        assert resultado["id"].tolist() == [1, 2, 3]
        storage.write_merged(destino, _df(3, 3), natural_key=None)
        assert len(storage.read_dir(destino)) == 5


def test_write_merged_com_escopo_anual_le_particoes_irmas(tmp_path):
    for storage in _storage_backends(tmp_path):
        janeiro = Path("senado/ano=2026/mes=1")
        fevereiro = Path("senado/ano=2026/mes=2")
        storage.write_merged(janeiro, _df(1), natural_key="id", merge_scope="ano")
        storage.write_merged(fevereiro, _df(1, 2), natural_key="id", merge_scope="ano")
        assert storage.read_dir(fevereiro)["id"].tolist() == [2]


def test_factories_escolhem_backend_e_normalizam_endpoint(monkeypatch, tmp_path):
    class Secret:
        def get_secret_value(self):
            return "senha"

    class MinioClient:
        def __init__(self, host, **kwargs):
            self.host = host
            self.kwargs = kwargs

        def bucket_exists(self, bucket):
            return False

        def make_bucket(self, bucket):
            self.buckets = getattr(self, "buckets", set())
            self.buckets.add(bucket)

    env = SimpleNamespace(
        minio_endpoint="https://minio.local:9000",
        minio_root_user="usuario",
        minio_root_password=Secret(),
    )
    cfg = SimpleNamespace(
        minio=SimpleNamespace(secure=False),
        armazenamento=SimpleNamespace(bronze=SimpleNamespace(bucket_minio="bronze")),
    )
    monkeypatch.setitem(sys.modules, "minio", SimpleNamespace(Minio=MinioClient))
    monkeypatch.setattr(storage_module, "get_env", lambda: env)
    monkeypatch.setattr(storage_module, "get_pipeline", lambda: cfg)
    remoto = storage_module.criar_storage_minio()
    assert remoto.client.host == "minio.local:9000"
    assert remoto.client.kwargs["secure"] is True
    assert remoto.bucket == "bronze"

    monkeypatch.setattr(storage_module, "criar_storage_minio", lambda: remoto)
    assert storage_module.criar_storage() is remoto
    env.minio_endpoint = ""
    local = storage_module.criar_storage()
    assert isinstance(local, LocalParquetStorage)
    assert storage_module.criar_storage_local(tmp_path).root == tmp_path
