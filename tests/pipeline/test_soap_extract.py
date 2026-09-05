# tests/pipeline/test_soap_extract.py
"""Testes unitários do parser SOAP/XML (ADR-043, Onda 4).

Cobre o parsing de XML de resposta do Deputados.asmx, a extração de
filiacoesPartidarias e o cache Parquet.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import httpx
import pandas as pd

from pipeline.camara.schemas import CamaraFiliacaoPartidaria
from pipeline.contracts import LoadMetadata


def _run_meta(**override) -> LoadMetadata:
    dados = {
        "run_id": uuid4(),
        "pipeline_version": "0.1.0",
        "execution_timestamp": datetime(2026, 9, 1, 12, 0, 0),
        "source_version": "2026-09-01",
    }
    dados.update(override)
    return LoadMetadata(**dados)


# ── XML fixtures ──────────────────────────────────────────────────

_XML_SEM_FILIACOES = b"""<?xml version="1.0" encoding="utf-8"?>
<Deputado>
  <ideCadastro>12345</ideCadastro>
  <nomeParlamentar>TESTE SILVA</nomeParlamentar>
  <siglaUf>SP</siglaUf>
  <filiacoesPartidarias />
</Deputado>"""

_XML_UMA_FILIACAO = b"""<?xml version="1.0" encoding="utf-8"?>
<Deputado>
  <ideCadastro>12345</ideCadastro>
  <nomeParlamentar>TESTE SILVA</nomeParlamentar>
  <siglaUf>SP</siglaUf>
  <filiacoesPartidarias>
    <filiacaoPartidaria>
      <siglaPartido>PT</siglaPartido>
      <dataFiliacaoPartidoPosterior>2015-03-10T00:00:00</dataFiliacaoPartidoPosterior>
    </filiacaoPartidaria>
  </filiacoesPartidarias>
</Deputado>"""

_XML_MULTIPLAS_FILIACOES = b"""<?xml version="1.0" encoding="utf-8"?>
<Deputado>
  <ideCadastro>12345</ideCadastro>
  <nomeParlamentar>TESTE SILVA</nomeParlamentar>
  <siglaUf>SP</siglaUf>
  <filiacoesPartidarias>
    <filiacaoPartidaria>
      <siglaPartido>PT</siglaPartido>
      <dataFiliacaoPartidoPosterior>2015-03-10T00:00:00</dataFiliacaoPartidoPosterior>
    </filiacaoPartidaria>
    <filiacaoPartidaria>
      <siglaPartido>PSB</siglaPartido>
      <dataFiliacaoPartidoPosterior>2019-04-22T00:00:00</dataFiliacaoPartidoPosterior>
    </filiacaoPartidaria>
    <filiacaoPartidaria>
      <siglaPartido>PSD</siglaPartido>
      <dataFiliacaoPartidoPosterior>2023-02-15T00:00:00</dataFiliacaoPartidoPosterior>
    </filiacaoPartidaria>
  </filiacoesPartidarias>
</Deputado>"""

_XML_COM_NAMESPACE = b"""<?xml version="1.0" encoding="utf-8"?>
<s:Deputado xmlns:s="http://www.camara.leg.br/SitCamaraWS/Deputados.asmx">
  <s:ideCadastro>12345</s:ideCadastro>
  <s:siglaUf>SP</s:siglaUf>
  <s:filiacoesPartidarias>
    <s:filiacaoPartidaria>
      <s:siglaPartido>PT</s:siglaPartido>
      <s:dataFiliacaoPartidoPosterior>2015-03-10T00:00:00</s:dataFiliacaoPartidoPosterior>
    </s:filiacaoPartidaria>
  </s:filiacoesPartidarias>
</s:Deputado>"""


class TestParseFiliacoes:
    """Testes do parser XML _parse_filiacoes."""

    def test_retorna_lista_vazia_quando_sem_filiacoes(self):
        from pipeline.camara.soap_extract import _parse_filiacoes

        resultado = _parse_filiacoes(_XML_SEM_FILIACOES, 12345, 57, "SP", _run_meta())
        assert resultado == []

    def test_extrai_uma_filiacao(self):
        from pipeline.camara.soap_extract import _parse_filiacoes

        resultado = _parse_filiacoes(_XML_UMA_FILIACAO, 12345, 57, "SP", _run_meta())
        assert len(resultado) == 1
        fil = resultado[0]
        assert fil.id_deputado == 12345
        assert fil.sigla_partido == "PT"
        assert fil.data_filiacao == "2015-03-10T00:00:00"
        assert fil.id_legislatura == 57
        assert fil.uf == "SP"
        assert fil.partido_uf_aproximado is False

    def test_extrai_multiplas_filiacoes(self):
        from pipeline.camara.soap_extract import _parse_filiacoes

        resultado = _parse_filiacoes(
            _XML_MULTIPLAS_FILIACOES, 12345, 55, "SP", _run_meta()
        )
        assert len(resultado) == 3
        assert [f.sigla_partido for f in resultado] == ["PT", "PSB", "PSD"]
        assert [f.id_legislatura for f in resultado] == [55, 55, 55]

    def test_funciona_com_namespace(self):
        from pipeline.camara.soap_extract import _parse_filiacoes

        resultado = _parse_filiacoes(_XML_COM_NAMESPACE, 12345, 57, "SP", _run_meta())
        assert len(resultado) == 1
        assert resultado[0].sigla_partido == "PT"

    def test_campos_opcionais_nao_quebram(self):
        from pipeline.camara.soap_extract import _parse_filiacoes

        xml = b"""<?xml version="1.0" encoding="utf-8"?>
        <Deputado>
          <filiacoesPartidarias>
            <filiacaoPartidaria>
              <siglaPartido>PT</siglaPartido>
            </filiacaoPartidaria>
          </filiacoesPartidarias>
        </Deputado>"""
        resultado = _parse_filiacoes(xml, 1, 57, None, _run_meta())
        # dataFiliacaoPartidoPosterior ausente → registro ignorado
        assert len(resultado) == 0


class TestExtrairFiliacoesDeputado:
    """Testes da extração completa de filiações (com HTTP mock)."""

    def _mock_client(self, responses: dict[str, bytes]) -> httpx.Client:
        """Cria um httpx.Client com mock transport que responde por legislatura."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            # Extrai numLegislatura dos query params
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(url)
            params = parse_qs(parsed.query)
            leg = params.get("numLegislatura", [None])[0]
            xml = responses.get(leg, b"<Deputado />")
            return httpx.Response(200, content=xml)

        transport = httpx.MockTransport(handler)
        return httpx.Client(transport=transport)

    def test_extrai_filiacoes_de_uma_legislatura(self):
        from pipeline.camara.soap_extract import extrair_filiacoes_deputado

        responses = {
            "57": _XML_UMA_FILIACAO,
            "54": _XML_SEM_FILIACOES,
            "55": _XML_SEM_FILIACOES,
            "56": _XML_SEM_FILIACOES,
        }
        client = self._mock_client(responses)
        resultado = extrair_filiacoes_deputado(
            client, 12345, _run_meta()
        )
        assert len(resultado) == 1
        assert resultado[0].sigla_partido == "PT"

    def test_dedup_entre_legislaturas(self):
        from pipeline.camara.soap_extract import extrair_filiacoes_deputado

        # Mesma filiação aparece nas legislaturas 56 e 57
        responses = {
            "57": _XML_UMA_FILIACAO,
            "56": _XML_UMA_FILIACAO,
            "55": _XML_SEM_FILIACOES,
            "54": _XML_SEM_FILIACOES,
        }
        client = self._mock_client(responses)
        resultado = extrair_filiacoes_deputado(
            client, 12345, _run_meta()
        )
        # Dedup por (id_deputado, sigla_partido, data_filiacao)
        assert len(resultado) == 1

    def test_erro_na_legislatura_nao_interrompe(self):
        from pipeline.camara.soap_extract import extrair_filiacoes_deputado

        def handler(request: httpx.Request) -> httpx.Response:
            from urllib.parse import parse_qs, urlparse

            parsed = urlparse(str(request.url))
            params = parse_qs(parsed.query)
            leg = params.get("numLegislatura", [None])[0]
            if leg == "55":
                return httpx.Response(500, content=b"error")
            return httpx.Response(200, content=_XML_UMA_FILIACAO)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        resultado = extrair_filiacoes_deputado(
            client, 12345, _run_meta()
        )
        # Legislatura 55 falhou, mas as outras funcionaram
        assert len(resultado) >= 1


class TestSalvarCacheFiliacoes:
    """Testes do cache Parquet de filiações."""

    def test_salva_parquet(self, tmp_path):
        from pipeline.camara.soap_extract import salvar_cache_filiacoes

        fil = CamaraFiliacaoPartidaria.model_validate(
            {
                "id_deputado": 12345,
                "siglaPartido": "PT",
                "dataFiliacaoPartidoPosterior": "2015-03-10T00:00:00",
                "numLegislatura": 57,
                "siglaUf": "SP",
                "partido_uf_aproximado": False,
                "metadata": _run_meta().model_dump(),
            }
        )
        resultado = salvar_cache_filiacoes([fil], tmp_path / "filiacoes", _run_meta())

        assert resultado.exists()
        df = pd.read_parquet(resultado)
        assert len(df) == 1
        assert df.iloc[0]["id_deputado"] == 12345
        assert df.iloc[0]["sigla_partido"] == "PT"

    def test_cache_vazio_nao_cria_arquivo(self, tmp_path):
        from pipeline.camara.soap_extract import salvar_cache_filiacoes

        salvar_cache_filiacoes([], tmp_path / "filiacoes", _run_meta())
        assert not any(tmp_path.glob("**/*.parquet"))
