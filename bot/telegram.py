"""Conversa com a Bot API do Telegram: enviar, reescrever e apagar mensagem.

O `enviar` devolve o `message_id`, e é isso que permite voltar na mensagem
semanas depois para riscá-la quando a vaga sai do ar.
"""

from __future__ import annotations

import logging

import requests

from config import REQUEST_TIMEOUT, TELEGRAM_CHAT_ID, TELEGRAM_TOKEN

log = logging.getLogger("brunao-bot.telegram")

BASE = "https://api.telegram.org/bot{}/{}"

# O Telegram corta em 4096; sobra folga para o aviso de vaga encerrada caber na
# frente do texto riscado sem estourar.
LIMITE_TEXTO = 3900

# O id do grupo pode mudar por baixo do bot: quando um grupo comum vira
# supergrupo — o Telegram faz isso sozinho ao ativar histórico para novos
# membros, tópicos ou link público — o id antigo morre e a API devolve o novo
# num 400. Guardar aqui deixa o bot seguir funcionando até o fim do dia; o
# aviso no log é para trocar o TELEGRAM_CHAT_ID de verdade, senão o próximo
# deploy volta a falhar.
_chat_id = TELEGRAM_CHAT_ID


def _url(metodo: str) -> str:
    return BASE.format(TELEGRAM_TOKEN, metodo)


def _migrou(resp: requests.Response) -> bool:
    """Detecta a migração para supergrupo e adota o id novo."""
    global _chat_id
    if resp.status_code != 400:
        return False
    try:
        novo = ((resp.json() or {}).get("parameters") or {}).get("migrate_to_chat_id")
    except ValueError:
        return False
    if not novo:
        return False
    log.warning("O grupo virou supergrupo: chat_id %s → %s. "
                "ATUALIZE TELEGRAM_CHAT_ID para %s.", _chat_id, novo, novo)
    _chat_id = str(novo)
    return True


def enviar(texto: str) -> int | None:
    """Manda a mensagem no grupo e devolve o `message_id`.

    Levanta `requests.RequestException` quando falha — quem chama decide se
    devolve a vaga para a fila ou desiste dela.
    """
    corpo = {
        "text": texto[:LIMITE_TEXTO],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(_url("sendMessage"), json={"chat_id": _chat_id, **corpo},
                         timeout=REQUEST_TIMEOUT)
    if _migrou(resp):
        resp = requests.post(_url("sendMessage"), json={"chat_id": _chat_id, **corpo},
                             timeout=REQUEST_TIMEOUT)
    if not resp.ok:
        log.error("sendMessage %s: %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
    try:
        return int(((resp.json() or {}).get("result") or {}).get("message_id"))
    except (ValueError, TypeError):
        log.warning("sendMessage devolveu 200 sem message_id")
        return None


def editar(message_id: int, texto: str) -> bool:
    """Reescreve uma mensagem já publicada. Não levanta exceção."""
    try:
        resp = requests.post(
            _url("editMessageText"),
            json={
                "chat_id": _chat_id,
                "message_id": message_id,
                "text": texto[:LIMITE_TEXTO],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        # "not modified" = já estava assim. Missão cumprida do mesmo jeito.
        if resp.ok or "not modified" in resp.text.lower():
            return True
        log.warning("editMessageText %s falhou: %s", message_id, resp.text[:200])
    except requests.RequestException as exc:
        log.warning("editMessageText %s falhou: %s", message_id, exc)
    return False


def apagar(message_id: int) -> bool:
    """Apaga a mensagem. Bot administrador não sofre o limite de 48h."""
    try:
        resp = requests.post(
            _url("deleteMessage"),
            json={"chat_id": TELEGRAM_CHAT_ID, "message_id": message_id},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok or "not found" in resp.text.lower():
            return True  # alguém já apagou antes: dá no mesmo
        log.warning("deleteMessage %s falhou: %s", message_id, resp.text[:200])
    except requests.RequestException as exc:
        log.warning("deleteMessage %s falhou: %s", message_id, exc)
    return False


def erro_passageiro(exc: requests.RequestException) -> bool:
    """Vale retentar no próximo ciclo?

    Rede, timeout, 429 e 5xx passam. Um 4xx qualquer é problema da mensagem em
    si — HTML inválido, chat errado, bot expulso do grupo — e retentar só
    repetiria o mesmo erro para sempre, travando as vagas da fila atrás dela.
    """
    resp = exc.response
    if resp is None:
        return True
    return resp.status_code == 429 or resp.status_code >= 500
