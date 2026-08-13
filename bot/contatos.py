"""Extração de formas de contato direto de uma vaga.

Esta é a regra que define o grupo: **só entra vaga que dá para responder fora
da plataforma**. Mandar proposta pelo Mercado de Trabalho não conta — o Bruno
quer o WhatsApp, o formulário, o link de candidatura.

O contato pode vir de dois lugares:

1. `proposalExternalLink`, o campo que o próprio ONM oferece ao contratante.
   Vem preenchido em ~30% dos anúncios e aceita qualquer coisa: URL, e-mail ou
   um telefone digitado solto.
2. A descrição, onde a maioria realmente escreve ("chama no zap 81 9...",
   "currículos para fulano@empresa.com").

Nada aqui usa LLM: é tudo determinístico e verificável. O classificador pode
sugerir contatos que a regex não viu, mas cada sugestão é **conferida letra a
letra contra o texto original** antes de virar link no grupo — modelo nenhum
inventa telefone de contratante neste bot.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

# Os 67 DDDs que existem. Serve tanto para validar telefone quanto para
# descartar CPF, CEP e número de processo, que é o que mais aparece por engano.
DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34, 35,
    37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62, 63, 64,
    65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88,
    89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}

# Domínios que, mesmo escritos sem "https://", são link de contato — o pessoal
# escreve "chama no wa.me/5511..." e a intenção é óbvia.
DOMINIOS_SOLTOS = (
    r"wa\.me|api\.whatsapp\.com|chat\.whatsapp\.com|whatsapp\.com|t\.me|"
    r"telegram\.me|bit\.ly|encurtador\.com\.br|forms\.gle|docs\.google\.com|"
    r"linktr\.ee|linkr\.bio|beacons\.ai|typeform\.com|tally\.so|airtable\.com|"
    r"notion\.so|notion\.site|jotform\.com|instagram\.com|linkedin\.com|"
    r"calendly\.com|discord\.gg"
)

RE_URL = re.compile(
    r"(?i)\b(?:https?://|www\.)[^\s<>\"'`()\[\]{}]+"
    rf"|\b(?:{DOMINIOS_SOLTOS})/[^\s<>\"'`()\[\]{{}}]*",
)
RE_EMAIL = re.compile(r"(?i)\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b")
RE_ARROBA = re.compile(r"(?<![\w@.])@([a-zA-Z][a-zA-Z0-9._]{2,29})\b")

# Candidato a telefone: começa e termina em dígito, aceita +, espaço, ponto,
# hífen e parênteses no meio. A validação séria vem depois, em cima dos dígitos.
RE_TELEFONE = re.compile(r"(?<![\w])(\+?\d[\d\s(). -]{6,22}\d)(?![\w])")

# Documentos que a regex de telefone pegaria por engano.
RE_CPF = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
RE_CNPJ = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")

RE_DINHEIRO_ANTES = re.compile(r"(?i)(?:r\$|rs|us\$|\$)\s*$")
RE_DINHEIRO_DEPOIS = re.compile(r"(?i)^\s*(?:reais|mil|k\b|,\d{2}|\.\d{2}\b)")

PALAVRAS_ZAP = ("whats", "wpp", "zap", "watsap", "wats", "wathsapp", "whatts")

ROTULOS = {
    "whatsapp": ("📲", "WhatsApp"),
    "telefone": ("☎️", "Telefone"),
    "link": ("🔗", "Candidatura"),
    "email": ("✉️", "E-mail"),
    "instagram": ("📸", "Instagram"),
    "telegram": ("💬", "Telegram"),
}


@dataclass(frozen=True)
class Contato:
    tipo: str          # whatsapp | telefone | link | email | instagram | telegram
    valor: str         # forma normalizada, usada para deduplicar
    exibicao: str      # como aparece na mensagem
    url: str           # para onde o link aponta
    origem: str        # "campo" (proposalExternalLink) ou "descricao"

    def linha_html(self) -> str:
        emoji, rotulo = ROTULOS.get(self.tipo, ("🔗", "Contato"))
        return (f'{emoji} {rotulo}: <a href="{html.escape(self.url, quote=True)}">'
                f"{html.escape(self.exibicao)}</a>")


# ---------------------------------------------------------------------------
# Telefone
# ---------------------------------------------------------------------------

def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def _normalizar_telefone(bruto: str) -> tuple[str, str, str] | None:
    """Devolve (E.164 sem '+', exibição, tipo) ou None se não for telefone.

    O que separa telefone de CPF, CEP e valor de contrato é a contagem de
    dígitos somada a um DDD que exista de verdade.

    Sobre o tipo: celular vira `whatsapp` porque em anúncio de freela número de
    celular É WhatsApp — e o `wa.me` de um número sem conta apenas avisa isso,
    não quebra nada. Fixo continua `telefone`, com link de discagem.
    """
    internacional = bruto.strip().startswith("+")
    d = _digitos(bruto)

    if internacional and not d.startswith("55"):
        # Número de fora: não dá para validar DDD nem adivinhar se é celular,
        # então vale a faixa da ITU e a grafia original de quem escreveu.
        if 10 <= len(d) <= 15:
            return d, re.sub(r"\s+", " ", bruto.strip()), "whatsapp"
        return None

    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]  # tira o código do país e cai no caso nacional
    elif internacional:
        return None

    if len(d) == 11:
        ddd, numero = int(d[:2]), d[2:]
        if ddd in DDDS and numero[0] == "9":
            return "55" + d, f"({d[:2]}) {numero[:5]}-{numero[5:]}", "whatsapp"
    elif len(d) == 10:
        ddd, numero = int(d[:2]), d[2:]
        if ddd in DDDS and numero[0] in "2345":
            return "55" + d, f"({d[:2]}) {numero[:4]}-{numero[4:]}", "telefone"
    return None


def _parece_zap(texto: str, inicio: int, fim: int) -> bool:
    """Alguém escreveu 'whats' / 'zap' perto do número?"""
    janela = texto[max(0, inicio - 80):fim + 40].lower()
    return any(p in janela for p in PALAVRAS_ZAP)


def _telefones(texto: str) -> list[tuple[str, str, str]]:
    """(e164, exibição, tipo) de cada telefone plausível do texto."""
    limpo = RE_CNPJ.sub(" ", RE_CPF.sub(" ", texto))
    achados: list[tuple[str, str, str]] = []
    for m in RE_TELEFONE.finditer(limpo):
        bruto = m.group(1)
        if RE_DINHEIRO_ANTES.search(limpo[max(0, m.start() - 6):m.start()]):
            continue
        if RE_DINHEIRO_DEPOIS.match(limpo[m.end():m.end() + 8]):
            continue
        norm = _normalizar_telefone(bruto)
        if not norm:
            continue
        e164, exibicao, tipo = norm
        # Fixo com "chama no zap" ao lado também é WhatsApp — é o dono do
        # número dizendo isso, e ele sabe melhor que a heurística.
        if tipo == "telefone" and _parece_zap(limpo, m.start(), m.end()):
            tipo = "whatsapp"
        achados.append((e164, exibicao, tipo))
    return achados


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def _limpar_url(url: str) -> str:
    return url.rstrip(".,;:!?…)”\"'")


def _contato_de_url(url: str, origem: str) -> Contato | None:
    url = _limpar_url(url)
    if not url:
        return None
    completa = url if url.lower().startswith(("http://", "https://")) else "https://" + url
    baixa = completa.lower()

    # Link de WhatsApp carrega o número: vira contato de WhatsApp, não link solto.
    m = re.search(r"(?:wa\.me/|api\.whatsapp\.com/send/?\?phone=|whatsapp\.com/send/?\?phone=)"
                  r"\+?(\d{10,15})", baixa)
    if m:
        norm = _normalizar_telefone("+" + m.group(1))
        if norm:
            e164, exibicao, _ = norm
            return Contato("whatsapp", e164, exibicao, f"https://wa.me/{e164}", origem)
        return Contato("whatsapp", m.group(1), "abrir conversa",
                       f"https://wa.me/{m.group(1)}", origem)

    if "chat.whatsapp.com" in baixa:
        return Contato("link", completa, "grupo de WhatsApp", completa, origem)
    if re.search(r"(?:t\.me|telegram\.me)/", baixa):
        apelido = completa.rstrip("/").rsplit("/", 1)[-1]
        return Contato("telegram", completa, "@" + apelido.lstrip("@"), completa, origem)
    if "instagram.com" in baixa:
        apelido = re.sub(r"\?.*$", "", completa.rstrip("/")).rsplit("/", 1)[-1]
        return Contato("instagram", completa, "@" + apelido.lstrip("@"), completa, origem)

    # Link genérico: mostra sem o "https://" e sem query, que só ocupa espaço.
    visivel = re.sub(r"^https?://(?:www\.)?", "", completa)
    visivel = visivel.split("?")[0].rstrip("/")
    if len(visivel) > 48:
        visivel = visivel[:45] + "..."
    return Contato("link", completa, visivel or completa, completa, origem)


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def extrair(vaga: dict[str, Any]) -> list[Contato]:
    """Todos os contatos diretos da vaga, sem repetição, campo antes da descrição."""
    achados: list[Contato] = []
    vistos: set[str] = set()

    def guardar(c: Contato | None) -> None:
        if c is None:
            return
        chave = f"{c.tipo}:{c.valor}"
        if chave in vistos:
            return
        vistos.add(chave)
        achados.append(c)

    campo = (vaga.get("proposalExternalLink") or "").strip()
    if campo:
        guardar(_do_texto_curto(campo, origem="campo"))

    for c in _da_descricao(vaga.get("description") or ""):
        guardar(c)

    return achados


def _do_texto_curto(valor: str, origem: str) -> Contato | None:
    """O `proposalExternalLink` é um campo só, com uma coisa dentro."""
    if RE_EMAIL.fullmatch(valor):
        return Contato("email", valor.lower(), valor, f"mailto:{valor}", origem)
    achado = RE_URL.search(valor)
    if achado:
        return _contato_de_url(achado.group(0), origem)
    if RE_EMAIL.search(valor):
        e = RE_EMAIL.search(valor).group(0)  # type: ignore[union-attr]
        return Contato("email", e.lower(), e, f"mailto:{e}", origem)
    telefones = _telefones(valor)
    if telefones:
        e164, exibicao, tipo = telefones[0]
        url = f"https://wa.me/{e164}" if tipo == "whatsapp" else f"tel:+{e164}"
        return Contato(tipo, e164, exibicao, url, origem)
    return None


def _da_descricao(texto: str) -> list[Contato]:
    """Varre a descrição na ordem que evita contar a mesma coisa duas vezes.

    URL primeiro (e some do texto de trabalho), porque `wa.me/5511999999999`
    contém um telefone que não deve ser extraído de novo; e-mail depois, porque
    o domínio dele parece uma URL; telefone e arroba por último.
    """
    if not texto:
        return []

    achados: list[Contato] = []
    trabalho = texto

    for m in RE_URL.finditer(texto):
        c = _contato_de_url(m.group(0), "descricao")
        if c:
            achados.append(c)
        trabalho = trabalho.replace(m.group(0), " ")

    for m in RE_EMAIL.finditer(trabalho):
        e = m.group(0)
        achados.append(Contato("email", e.lower(), e, f"mailto:{e}", "descricao"))
    trabalho = RE_EMAIL.sub(" ", trabalho)

    for e164, exibicao, tipo in _telefones(trabalho):
        url = f"https://wa.me/{e164}" if tipo == "whatsapp" else f"tel:+{e164}"
        achados.append(Contato(tipo, e164, exibicao, url, "descricao"))

    for m in RE_ARROBA.finditer(trabalho):
        apelido = m.group(1)
        achados.append(Contato("instagram", apelido.lower(), "@" + apelido,
                               f"https://instagram.com/{apelido}", "descricao"))

    return achados


def de_sugestao(trecho: str, texto_original: str) -> Contato | None:
    """Transforma em contato um trecho sugerido pelo classificador.

    Só passa o que existir **literalmente** no texto da vaga. É o que garante
    que um modelo distraído não invente um telefone que ninguém escreveu.
    """
    trecho = (trecho or "").strip()
    if not trecho or len(trecho) > 200:
        return None
    if trecho not in texto_original:
        # Última chance: o modelo pode ter reescrito só os separadores.
        d = _digitos(trecho)
        if not (d and len(d) >= 10 and d in _digitos(texto_original)):
            return None
    return _do_texto_curto(trecho, origem="classificador")


def resumo(contatos: list[Contato]) -> str:
    """Uma linha para o log: 'whatsapp(campo), link(descricao)'."""
    return ", ".join(f"{c.tipo}({c.origem})" for c in contatos) or "nenhum"
