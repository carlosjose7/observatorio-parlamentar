import time

from fastapi import FastAPI, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.metrics import http_latency_seconds, http_requests_total
from api.routers.agent import router as router_agent
from api.routers.agregacoes import router as router_agregacoes
from api.routers.anomalias import router as router_anomalias
from api.routers.contador import router as router_contador
from api.routers.fornecedores import router as router_fornecedores
from api.routers.parlamentares import router as router_parlamentares
from api.routers.pipeline import router as router_pipeline
from api.routers.qualidade import router as router_qualidade
from api.routers.rede import router as router_rede
from pipeline.config import get_api, get_env


def criar_app() -> FastAPI:
    """Constrói a aplicação FastAPI com a fronteira de documentação por env.

    `/docs`, `/redoc` e `/openapi.json` são condicionados a `API_DOCS_ENABLED`
    (default true): em produção, atrás do nginx, devem ser desabilitados para
    não autodocumentarem a superfície de ataque a desconhecidos.
    """
    config = get_api()
    habilitar_docs = get_env().api_docs_enabled
    return FastAPI(
        title=config.titulo,
        description=config.descricao,
        version=config.versao,
        docs_url="/docs" if habilitar_docs else None,
        redoc_url="/redoc" if habilitar_docs else None,
        openapi_url="/openapi.json" if habilitar_docs else None,
    )


app = criar_app()


@app.get("/")
def root():
    return {"message": get_api().titulo, "version": get_api().versao}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.middleware("http")
async def _observar_http(request: Request, call_next):
    """Observa toda requisição (menos o próprio scrape) para o Prometheus.

    `rota` usa o template da rota (`/agent/parlamentar/{id}`), nunca o
    path com ID — cardinalidade limitada (ADR-051 §5). `/metrics` é
    excluído para o scrape a cada 15s não poluir as séries.
    """
    if request.url.path == "/metrics":
        return await call_next(request)
    inicio = time.perf_counter()
    resposta = await call_next(request)
    rota = getattr(request.scope.get("route"), "path", None) or request.url.path
    http_requests_total.labels(rota=rota, status=str(resposta.status_code)).inc()
    http_latency_seconds.observe(time.perf_counter() - inicio)
    return resposta


@app.get("/metrics")
def metrics():
    """Séries da API no formato de exposição do Prometheus (scrape interno)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


app.include_router(router_parlamentares)
app.include_router(router_fornecedores)
app.include_router(router_agregacoes)
app.include_router(router_anomalias)
app.include_router(router_rede)
app.include_router(router_qualidade)
app.include_router(router_pipeline)
app.include_router(router_agent)
app.include_router(router_contador)
