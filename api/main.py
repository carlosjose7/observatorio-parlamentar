from fastapi import FastAPI

from pipeline.config import get_api

from api.routers.parlamentares import router as router_parlamentares

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