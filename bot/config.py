"""Configuração do bot: variáveis de ambiente, caminhos e constantes.

Tudo que muda de ambiente para ambiente mora aqui, para que o resto do código
não precise saber que `os.environ` existe. Os defaults são os de produção —
rodar sem `.env` nenhum não deveria explodir, só ficar sem credencial.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# O `.env` fica na raiz do repositório, um nível acima de `bot/`. Em produção
# não existe arquivo nenhum: o Coolify injeta as variáveis direto no ambiente,
# e o `load_dotenv` simplesmente não acha nada e segue em frente.
BOT_DIR = Path(__file__).resolve().parent
REPO_DIR = BOT_DIR.parent
load_dotenv(REPO_DIR / ".env")

# --- Credenciais -----------------------------------------------------------

ONM_EMAIL = os.getenv("ONM_EMAIL", "").strip()
ONM_PASSWORD = os.getenv("ONM_PASSWORD", "").strip()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# --- Ritmo -----------------------------------------------------------------

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "600"))
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "20"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# --- Caminhos --------------------------------------------------------------

# Local: `data/` na raiz do repositório. Em produção: o volume `/app/data`,
# fixado no docker-compose. Nunca cadastre DATA_DIR no painel do Coolify —
# apontar para fora do volume faz o bot esquecer tudo a cada redeploy e
# reenviar o mundo inteiro para o grupo.
DATA_DIR = Path(os.getenv("DATA_DIR", str(REPO_DIR / "data")))
PROFILE_FILE = Path(os.getenv("PROFILE_FILE", str(BOT_DIR / "config" / "profile.md")))

SEEN_IDS_FILE = DATA_DIR / "seen_ids.json"
PUBLICADAS_FILE = DATA_DIR / "publicadas.json"
SKIPPED_LOG_FILE = DATA_DIR / "skipped_jobs.jsonl"

# --- API do ONM ------------------------------------------------------------

LOGIN_URL = "https://auth.onovomercado.com.br/api/auth/login"
PROJECTS_URL = "https://api.onovomercado.com.br/mercado-de-trabalho/v1/projects"
PROJECT_DETAIL_URL = PROJECTS_URL + "/{}"
SITE_URL = "https://omercadodetrabalho.com"
JWT_COOKIE_NAME = "onm-sso-jwt-token"

REQUEST_TIMEOUT = 30

# --- Classificador ---------------------------------------------------------

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()

# Vaga "talvez" (o classificador ficou na dúvida) vai para o grupo com 🤔 na
# frente. Desligar isso deixa o filtro seco: só o que ele tem certeza.
NOTIFICAR_TALVEZ = os.getenv("NOTIFICAR_TALVEZ", "true").lower() not in ("0", "false", "no")

# --- Contato direto --------------------------------------------------------

# A regra do Bruno: só entra no grupo vaga que dá para responder FORA da
# plataforma. Proposta pelo Mercado de Trabalho não conta.
EXIGIR_CONTATO = os.getenv("EXIGIR_CONTATO", "true").lower() not in ("0", "false", "no")

# Quais tipos de contato valem como "dá para responder direto". `email` está
# incluído porque é o segundo formato mais comum no campo de contato do ONM e
# continua sendo contato fora da plataforma; tire-o daqui para deixar só
# WhatsApp e link. `instagram` fica de fora por padrão: perfil citado na
# descrição quase nunca é canal de candidatura, é só a marca do contratante.
CONTATOS_ACEITOS = {
    t.strip().lower()
    for t in os.getenv("CONTATOS_ACEITOS", "whatsapp,telefone,link,email").split(",")
    if t.strip()
}

# --- Vaga encerrada --------------------------------------------------------

# `marcar` reescreve a mensagem no grupo riscando o texto e trocando o título
# por "VAGA ENCERRADA"; `apagar` remove a mensagem; `nada` desliga o revisor.
ACAO_VAGA_ENCERRADA = os.getenv("ACAO_VAGA_ENCERRADA", "marcar").strip().lower()

RECHECK_HORAS = int(os.getenv("RECHECK_HORAS", "6"))      # cada vaga, no máximo
RECHECK_POR_CICLO = int(os.getenv("RECHECK_POR_CICLO", "12"))
RECHECK_DIAS = int(os.getenv("RECHECK_DIAS", "30"))       # depois disso, esquece

# --- Mensagem --------------------------------------------------------------

DESCRIPTION_MAX_CHARS = int(os.getenv("DESCRIPTION_MAX_CHARS", "700"))
TELEGRAM_RATE_LIMIT_SECONDS = 1.0
