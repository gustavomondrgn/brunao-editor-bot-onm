"""Bot de vagas de edição de vídeo do Bruno — "O Mercado de Trabalho" → Telegram.

A cada ciclo o bot faz três coisas:

1. Busca as vagas mais recentes da plataforma.
2. Filtra as novas: tem de ser demanda de vídeo, não pode ser presencial e
   precisa ter um contato fora da plataforma. O que passa vai para o grupo.
3. Revisita algumas das que já publicou. Vaga que saiu do ar tem a mensagem
   riscada no grupo, com "VAGA ENCERRADA" por cima.

Roda para sempre, sozinho, num container. Erro de rede, token vencido e API
fora do ar são esperados: o ciclo registra e tenta de novo no próximo.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Any

import requests

import classificador
import contatos as contatos_mod
import estado
import mensagem
import telegram
from classificador import Veredito
from config import (
    ACAO_VAGA_ENCERRADA,
    CHECK_INTERVAL,
    CONTATOS_ACEITOS,
    DATA_DIR,
    EXIGIR_CONTATO,
    GEMINI_MODEL,
    LOG_LEVEL,
    NOTIFICAR_TALVEZ,
    ONM_EMAIL,
    ONM_PASSWORD,
    PROFILE_FILE,
    RECHECK_DIAS,
    RECHECK_HORAS,
    RECHECK_POR_CICLO,
    TELEGRAM_CHAT_ID,
    TELEGRAM_RATE_LIMIT_SECONDS,
    TELEGRAM_TOKEN,
)
from contatos import Contato
from onm import AuthError, listar_vagas, login, verificar_vaga

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("brunao-bot")

# Ordem em que os contatos aparecem na mensagem: o que resolve com um toque no
# celular primeiro, o resto depois.
ORDEM_CONTATOS = {"whatsapp": 0, "link": 1, "telegram": 2, "telefone": 3,
                  "email": 4, "instagram": 5}


# ---------------------------------------------------------------------------
# Decisão sobre uma vaga
# ---------------------------------------------------------------------------

class Decisao:
    def __init__(self, publicar: bool, motivo: str, veredito: Veredito,
                 contatos: list[Contato]) -> None:
        self.publicar = publicar
        self.motivo = motivo
        self.veredito = veredito
        self.contatos = contatos


def avaliar(vaga: dict[str, Any]) -> Decisao:
    """Esta vaga vai para o grupo? E, se não vai, por quê?

    A ordem importa: o classificador roda primeiro porque a mesma chamada que
    diz se é vídeo já devolve os trechos de contato que ele enxergou — não
    adianta economizar aqui e perder a sugestão dele.
    """
    veredito = classificador.classificar(vaga)

    if veredito.modalidade == "presencial":
        return Decisao(False, "presencial", veredito, [])
    if veredito.categoria == "irrelevante":
        return Decisao(False, "fora do perfil", veredito, [])
    if veredito.categoria == "talvez" and not NOTIFICAR_TALVEZ:
        return Decisao(False, "talvez (notificação de talvez desligada)", veredito, [])

    achados = contatos_mod.extrair(vaga)

    # O que o classificador viu e a regex não: só entra se o trecho existir
    # letra a letra no anúncio.
    if veredito.contatos_sugeridos:
        bruto = f"{vaga.get('proposalExternalLink') or ''}\n{vaga.get('description') or ''}"
        conhecidos = {f"{c.tipo}:{c.valor}" for c in achados}
        for trecho in veredito.contatos_sugeridos:
            extra = contatos_mod.de_sugestao(trecho, bruto)
            if extra and f"{extra.tipo}:{extra.valor}" not in conhecidos:
                conhecidos.add(f"{extra.tipo}:{extra.valor}")
                achados.append(extra)

    achados.sort(key=lambda c: ORDEM_CONTATOS.get(c.tipo, 9))
    aceitos = [c for c in achados if c.tipo in CONTATOS_ACEITOS]

    if EXIGIR_CONTATO and not aceitos:
        return Decisao(False, "sem contato fora da plataforma", veredito, achados)

    return Decisao(True, veredito.motivo, veredito, achados)


# ---------------------------------------------------------------------------
# Ciclo
# ---------------------------------------------------------------------------

def publicar_novas(vagas: list[dict[str, Any]], novas: set[int],
                   vistas: set[int], publicadas: estado.Publicadas) -> None:
    """Manda para o grupo, da vaga mais antiga para a mais nova.

    A ordem cronológica é de propósito: a API devolve DESC, e despejar assim no
    Telegram deixaria o grupo lendo de trás para frente.
    """
    for vaga in reversed([v for v in vagas if int(v.get("id", -1)) in novas]):
        vaga_id = int(vaga["id"])
        decisao = avaliar(vaga)

        if not decisao.publicar:
            log.info("Vaga %s descartada (%s) — %s", vaga_id, decisao.motivo,
                     vaga.get("title"))
            estado.registrar_descarte(vaga, decisao.motivo, decisao.veredito.motivo)
            vistas.add(vaga_id)
            continue

        texto = mensagem.formatar(vaga, decisao.veredito, decisao.contatos)
        try:
            message_id = telegram.enviar(texto)
        except requests.RequestException as exc:
            if telegram.erro_passageiro(exc):
                # Não entra em `vistas`: volta para a fila no próximo ciclo.
                log.error("Falha passageira enviando a vaga %s: %s — tento de novo",
                          vaga_id, exc)
                continue
            log.error("Falha definitiva enviando a vaga %s: %s — desistindo dela",
                      vaga_id, exc)
            vistas.add(vaga_id)
            continue

        log.info("Publicada a vaga %s (%s · contatos: %s) — %s", vaga_id,
                 decisao.veredito.categoria, contatos_mod.resumo(decisao.contatos),
                 vaga.get("title"))
        publicadas.registrar(vaga_id, vaga.get("title") or "", message_id, texto)
        vistas.add(vaga_id)
        time.sleep(TELEGRAM_RATE_LIMIT_SECONDS)


def revisar(token: str, publicadas: estado.Publicadas) -> None:
    """Reexamina algumas vagas publicadas e trata as que saíram do ar.

    Roda a conta-gotas — algumas por ciclo, cada vaga no máximo uma vez a cada
    `RECHECK_HORAS` — para a verificação não virar um segundo scraping.
    """
    if ACAO_VAGA_ENCERRADA == "nada":
        return

    pendentes = publicadas.a_checar(RECHECK_HORAS, RECHECK_POR_CICLO)
    if not pendentes:
        return

    for item in pendentes:
        situacao = verificar_vaga(token, item["id"])
        if situacao == "desconhecida":
            continue  # nem conta como falta: não sabemos de nada

        if not publicadas.marcar_checada(item["id"], situacao == "fechada"):
            continue

        message_id = int(item["message_id"])
        if ACAO_VAGA_ENCERRADA == "apagar":
            ok, verbo = telegram.apagar(message_id), "apagada"
        else:
            ok = telegram.editar(message_id, mensagem.encerrada(
                item.get("html") or item.get("titulo") or ""))
            verbo = "riscada"
        log.info("Vaga %s encerrada na plataforma — mensagem %s (%s)",
                 item["id"], verbo, "ok" if ok else "falhou")


def ciclo(token: str, vistas: set[int], primeira: bool,
          publicadas: estado.Publicadas) -> tuple[str, set[int], bool]:
    """Um ciclo completo. Devolve (token, vistas, primeira) atualizados."""
    try:
        vagas = listar_vagas(token)
    except AuthError as exc:
        log.warning("%s — reautenticando", exc)
        token = login()
        vagas = listar_vagas(token)

    atuais = {int(v["id"]) for v in vagas if v.get("id") is not None}

    if primeira:
        # Na estreia, só memoriza. Sem isso o grupo nasceria com 20 mensagens
        # de vagas que o Bruno já perdeu.
        log.info("Primeira execução — guardando %d vaga(s) sem notificar", len(atuais))
        estado.salvar_vistas(atuais)
        return token, atuais, False

    novas = atuais - vistas
    if novas:
        log.info("%d vaga(s) nova(s)", len(novas))
        publicar_novas(vagas, novas, vistas, publicadas)
    else:
        log.info("Nenhuma vaga nova (%d checadas)", len(atuais))

    vistas |= atuais
    estado.salvar_vistas(vistas)

    revisar(token, publicadas)
    return token, vistas, False


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def validar_env() -> None:
    faltando = [nome for nome, valor in {
        "ONM_EMAIL": ONM_EMAIL,
        "ONM_PASSWORD": ONM_PASSWORD,
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }.items() if not valor]
    if faltando:
        log.error("Faltam variáveis obrigatórias: %s", ", ".join(faltando))
        sys.exit(1)


def anunciar_configuracao(publicadas: estado.Publicadas) -> None:
    log.info("Bot de vagas de edição de vídeo iniciando (intervalo=%ds, dados=%s)",
             CHECK_INTERVAL, DATA_DIR)
    if classificador.ativo():
        log.info("Filtro LIGADO (modelo=%s, perfil=%s)", GEMINI_MODEL, PROFILE_FILE)
    else:
        motivos = []
        if not classificador.GENAI_DISPONIVEL:
            motivos.append("google-genai não instalado")
        elif not classificador.cliente():
            motivos.append("GEMINI_API_KEY ausente ou inválida")
        if classificador.carregar_perfil() is None:
            motivos.append(f"{PROFILE_FILE} não encontrado")
        log.warning("Filtro DESLIGADO — notificando TUDO. Motivo(s): %s",
                    "; ".join(motivos))
    log.info("Contato direto: %s (aceitos: %s)",
             "obrigatório" if EXIGIR_CONTATO else "opcional",
             ", ".join(sorted(CONTATOS_ACEITOS)) or "nenhum")
    log.info("Vaga encerrada: ação=%s · rechecagem a cada %dh, %d por ciclo, "
             "acompanhando por %d dias · %s",
             ACAO_VAGA_ENCERRADA, RECHECK_HORAS, RECHECK_POR_CICLO, RECHECK_DIAS,
             publicadas.resumo())


def main() -> None:
    parser = argparse.ArgumentParser(description="Bot de vagas de edição de vídeo")
    parser.add_argument("--uma-vez", action="store_true",
                        help="roda um único ciclo e sai (útil para testar o deploy)")
    args = parser.parse_args()

    validar_env()
    publicadas = estado.Publicadas()
    anunciar_configuracao(publicadas)

    vistas = estado.carregar_vistas()
    primeira = estado.primeira_execucao()
    token: str | None = None

    while True:
        try:
            if token is None:
                token = login()
            token, vistas, primeira = ciclo(token, vistas, primeira, publicadas)
        except AuthError as exc:
            log.error("Erro de autenticação: %s — tento no próximo ciclo", exc)
            token = None
        except requests.RequestException as exc:
            log.error("Erro de rede: %s — tento no próximo ciclo", exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Erro inesperado: %s — tento no próximo ciclo", exc)

        if args.uma_vez:
            return
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
