from fastapi import FastAPI

from pipeline.config import get_api

from api.routers.parlamentares import router as router_parlamentares
from api.routers.fornecedores import router as router_fornecedores
from api.routers.anomalias import router as router_anomalias
from api.routers.rede import router as router_rede
from api.routers.qualidade import router as router_qualidade
from api.routers.pipeline import router as router_pipeline

config = get_api()

app = FastAPI(
    title=config.titulo,
    description=config.descricao,
    version=config.versao,
)


@app.get("/")
def root():
    return {"message": config.titulo, "version": config.versao}


@app.get("/health")
def health():
    return {"status": "healthy"}


app.include_router(router_parlamentares)
app.include_router(router_fornecedores)
app.include_router(router_anomalias)
app.include_router(router_rede)
app.include_router(router_qualidade)
app.include_router(router_pipeline)