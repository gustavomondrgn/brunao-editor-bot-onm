"""Cliente da API do "O Mercado de Trabalho".

Três operações: autenticar, listar as vagas mais recentes e perguntar se uma
vaga específica ainda está no ar.

A API não é documentada. O login devolve o JWT num cookie (`onm-sso-jwt-token`)
em vez do corpo da resposta, e o token vence — daí o `AuthError`, que o loop
principal usa como sinal para reautenticar e tentar de novo.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import requests

from config import (
    JWT_COOKIE_NAME,
    LOGIN_URL,
    ONM_EMAIL,
    ONM_PASSWORD,
    PAGE_LIMIT,
    PROJECT_DETAIL_URL,
    PROJECTS_URL,
    REQUEST_TIMEOUT,
    SITE_URL,
)

log = logging.getLogger("brunao-bot.onm")

Estado = Literal["aberta", "fechada", "desconhecida"]

# Status que o próprio ONM devolve quando a vaga já não vale mais. A vaga viva
# vem como "APPROVED". Esta é uma lista de negação de propósito: qualquer
# status desconhecido conta como aberta, porque errar para o lado de deixar a
# mensagem no ar é barato e o contrário não é.
STATUS_ENCERRADOS = {"CLOSED", "FINISHED", "EXPIRED", "CANCELED", "CANCELLED",
                     "REMOVED", "DELETED", "DISAPPROVED", "REPROVED"}


class AuthError(Exception):
    """Token vencido ou credenciais inválidas."""


def login() -> str:
    """Autentica e devolve o JWT do cookie `onm-sso-jwt-token`."""
    log.info("Autenticando no ONM como %s", ONM_EMAIL)
    resp = requests.post(
        LOGIN_URL,
        json={"email": ONM_EMAIL, "password": ONM_PASSWORD, "client": "mdt"},
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code in (400, 401, 403):
        raise AuthError(f"Login recusado ({resp.status_code}): {resp.text[:200]}")
    resp.raise_for_status()
    token = resp.cookies.get(JWT_COOKIE_NAME)
    if not token:
        raise AuthError(f"Login OK mas o cookie {JWT_COOKIE_NAME} não veio na resposta")
    log.info("Autenticado (token len=%d)", len(token))
    return token


def listar_vagas(token: str, limit: int = PAGE_LIMIT) -> list[dict[str, Any]]:
    """As vagas mais recentes, da mais nova para a mais antiga."""
    resp = requests.get(
        PROJECTS_URL,
        params={"page": 1, "limit": limit, "sortDir": "DESC"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 401:
        raise AuthError("Token vencido (401)")
    resp.raise_for_status()
    return (resp.json() or {}).get("content") or []


def verificar_vaga(token: str, vaga_id: int | str) -> Estado:
    """A vaga ainda está aberta? Nunca levanta exceção.

    **Na dúvida, aberta.** Só um 404 explícito — ou um status terminal — conta
    como fechada. Timeout, 401, 429 e 5xx devolvem "desconhecida", porque a
    diferença entre *a vaga acabou* e *a plataforma engasgou* é a diferença
    entre riscar a mensagem certa e riscar uma vaga boa do grupo.
    """
    try:
        resp = requests.get(
            PROJECT_DETAIL_URL.format(vaga_id),
            headers={"Authorization": f"Bearer {token}"},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        log.debug("Falha checando vaga %s: %s", vaga_id, exc)
        return "desconhecida"

    if resp.status_code == 404:
        return "fechada"
    if resp.status_code == 401:
        return "desconhecida"  # nosso token venceu, não que a vaga acabou
    if not resp.ok:
        log.debug("Vaga %s devolveu %s — inconclusivo", vaga_id, resp.status_code)
        return "desconhecida"

    try:
        status = str((resp.json() or {}).get("status") or "").upper()
    except ValueError:
        return "aberta"
    return "fechada" if status in STATUS_ENCERRADOS else "aberta"


def url_publica(vaga: dict[str, Any]) -> str:
    """O endereço da vaga no site, que é o link que vai na mensagem."""
    caminho = "vagas" if vaga.get("type") == "POSITION" else "projetos"
    return f"{SITE_URL}/{caminho}/{vaga.get('id')}"
