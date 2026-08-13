"""Stores de watermark isolados do Airflow real — Sprint 8."""

import sys
from types import SimpleNamespace
from uuid import uuid4

from pipeline.watermark import (
    AirflowVariableStore,
    JsonFileStore,
    NamespaceWatermarkStore,
    WatermarkState,
)


def test_json_store_sanitiza_chave_e_preserva_run_id(tmp_path):
    store = JsonFileStore(tmp_path)
    state = WatermarkState(last_watermark="2026-08", run_id=uuid4())

    store.set("origem/sub\\chave", state)

    assert (tmp_path / "origem_sub_chave.json").exists()
    assert store.get("origem/sub\\chave") == state
    assert store.get("nunca-gravada") == WatermarkState()


def test_airflow_store_usa_json_e_import_lazy(monkeypatch):
    class Variable:
        values = {}
        calls = []

        @classmethod
        def get(cls, key, default_var, deserialize_json):
            cls.calls.append(("get", key, default_var, deserialize_json))
            return cls.values.get(key)

        @classmethod
        def set(cls, key, value, serialize_json):
            cls.calls.append(("set", key, value, serialize_json))
            cls.values[key] = value

    monkeypatch.setitem(sys.modules, "airflow", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "airflow.models", SimpleNamespace(Variable=Variable))
    store = AirflowVariableStore()

    assert store.get("ausente") == WatermarkState()
    state = WatermarkState(last_watermark="2026", run_id=uuid4())
    store.set("senado", state)

    assert store.get("senado") == state
    assert ("set", "senado", Variable.values["senado"], False) in Variable.calls


def test_namespace_isola_leitura_e_escrita(tmp_path):
    base = JsonFileStore(tmp_path)
    isolado = NamespaceWatermarkStore(base, "validacao")
    state = WatermarkState(last_watermark="2025")

    isolado.set("senado", state)

    assert isolado.get("senado") == state
    assert base.get("senado") == WatermarkState()
