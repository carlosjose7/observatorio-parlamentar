FROM python:3.11-slim

WORKDIR /app

COPY . .
# Instala APÓS copiar o código para o editable install descobrir os pacotes
# (se instalado antes, o finder fica com MAPPING vazio e o import quebra no
# Streamlit, cujo sys.path aponta para o diretório das páginas).
RUN pip install --no-cache-dir -e ".[dashboard]" \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

EXPOSE 8501

USER appuser

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["streamlit", "run", "dashboard/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
