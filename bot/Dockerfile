# O contexto de build é a RAIZ do repositório (ver docker-compose.yml), não a
# pasta `bot/` — assim o Dockerfile e o compose ficam cada um no seu lugar sem
# precisar de caminho relativo esquisito.
FROM python:3.12-slim

WORKDIR /app

COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código do bot. Os módulos se importam pelo nome (`import config`), então todos
# moram lado a lado em /app.
COPY bot/*.py ./

# Perfil do filtro. `config.py` procura em `<pasta do main>/config/profile.md`.
COPY bot/config/ ./config/

# Estado que precisa sobreviver a redeploy: seen_ids, publicadas, descartes.
VOLUME ["/app/data"]
ENV DATA_DIR=/app/data

# -u para o log sair sem buffer e aparecer em tempo real no Coolify.
CMD ["python", "-u", "main.py"]
