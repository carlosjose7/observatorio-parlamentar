from fastapi import FastAPI

app = FastAPI(
    title="Observatório Parlamentar API",
    description="API da Plataforma de Inteligência Parlamentar Brasileira",
    version="0.1.0",
)

@app.get("/")
def root():
    return {"message": "Observatório Parlamentar API", "version": "0.1.0"}

@app.get("/health")
def health():
    return {"status": "healthy"}
