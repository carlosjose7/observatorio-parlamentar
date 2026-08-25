from fastapi import FastAPI

from api.routers.agent import router as router_agent
from api.routers.anomalias import router as router_anomalias
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


app.include_router(router_parlamentares)
app.include_router(router_fornecedores)
app.include_router(router_anomalias)
app.include_router(router_rede)
app.include_router(router_qualidade)
app.include_router(router_pipeline)
app.include_router(router_agent)
