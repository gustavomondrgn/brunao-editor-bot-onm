"""Como a vaga aparece no grupo.

O formato herda o do bot do Kandle Studio — cabeçalho, título, autor, categoria,
skills, orçamento, data, escopo e link. A adição desta versão é o bloco de
contatos, que é justamente o motivo de a vaga ter passado no filtro.
"""

from __future__ import annotations

import html
import re
from typing import Any

from classificador import Veredito
from config import DESCRIPTION_MAX_CHARS
from contatos import Contato
from onm import url_publica

AVISO_ENCERRADA = "🔴 <b>VAGA ENCERRADA</b> — saiu do ar na plataforma"

_TAGS = re.compile(r"</?(?:b|i|s|u|code|pre)>")
_LINKS = re.compile(r'<a href="[^"]*">([^<]*)</a>')


def truncar(texto: str, limite: int = DESCRIPTION_MAX_CHARS) -> str:
    texto = (texto or "").strip()
    # Linha em branco tripla vira dupla: anúncio copiado do Word vem cheio delas
    # e o espaço morto empurra o link para fora da tela do celular.
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    if len(texto) <= limite:
        return texto
    corte = texto[:limite]
    espaco = corte.rfind(" ")
    if espaco > 0:
        corte = corte[:espaco]
    return corte.rstrip(" ,.;:-") + "..."


def _dinheiro(vaga: dict[str, Any]) -> str:
    minimo, maximo = vaga.get("budgetMin"), vaga.get("budgetMax")
    tem_min = minimo not in (None, 0, 0.0)
    tem_max = maximo not in (None, 0, 0.0)
    if tem_min and tem_max:
        return f"💰 R${minimo:,.0f} – R${maximo:,.0f}".replace(",", ".")
    if tem_max:
        return f"💰 até R${maximo:,.0f}".replace(",", ".")
    if tem_min:
        return f"💰 a partir de R${minimo:,.0f}".replace(",", ".")
    return ""


def formatar(vaga: dict[str, Any], veredito: Veredito,
             contatos: list[Contato]) -> str:
    """A mensagem completa da vaga, em HTML do Telegram."""
    tipo = vaga.get("type") or ""
    cabecalho = "🏢 VAGA" if tipo == "POSITION" else "🎬 PROJETO"
    if veredito.categoria == "talvez":
        cabecalho = f"🤔 {cabecalho} (talvez)"

    linhas = [
        cabecalho,
        "",
        f"📌 <b>{html.escape(vaga.get('title') or '(sem título)')}</b>",
        "",
        f"👤 {html.escape((vaga.get('author') or {}).get('name') or 'Desconhecido')}",
    ]

    profissao_obj = vaga.get("profession") or {}
    profissao = profissao_obj.get("description") or ""
    area = ((profissao_obj.get("occupationArea") or {}).get("title")) or ""
    partes = [html.escape(p) for p in (profissao, area) if p]
    if partes:
        linhas.append("🏷 " + " · ".join(partes))

    skills = [s.get("description") for s in (vaga.get("skills") or [])
              if s and s.get("description")]
    if skills:
        linhas.append("🔧 " + html.escape(", ".join(skills)))

    if veredito.modalidade == "remoto":
        linhas.append("🌎 Remoto")
    elif veredito.modalidade == "hibrido":
        linhas.append("🌎 Híbrido")

    for linha in (_dinheiro(vaga), f"📅 {html.escape(vaga.get('createdAt') or '')}"
                  if vaga.get("createdAt") else ""):
        if linha:
            linhas.append(linha)

    escopo = truncar(vaga.get("description") or "")
    if escopo:
        linhas += ["", f"<i>{html.escape(escopo)}</i>"]

    if contatos:
        linhas.append("")
        linhas += [c.linha_html() for c in contatos]

    if veredito.categoria == "talvez" and veredito.motivo:
        linhas += ["", f"<i>🤖 {html.escape(veredito.motivo)}</i>"]

    linhas += ["", f'🔗 <a href="{url_publica(vaga)}">Ver no ONM</a>']
    return "\n".join(linhas)


def encerrada(html_original: str) -> str:
    """A mesma mensagem, riscada, com o aviso de encerrada por cima.

    Riscar em vez de apagar mantém o histórico do grupo fazendo sentido: quem
    já tinha visto a vaga entende o que aconteceu, em vez de achar que a
    mensagem sumiu do nada.
    """
    return f"{AVISO_ENCERRADA}\n\n<s>{_sem_formatacao(html_original)}</s>"


def _sem_formatacao(texto: str) -> str:
    """Tira a formatação de dentro antes de riscar tudo.

    O `<s>` do Telegram não aceita `<b>` aninhado sem reclamar de HTML
    inválido, e os links viram texto puro — vaga morta não merece convite ao
    clique.
    """
    return _LINKS.sub(lambda m: m.group(1), _TAGS.sub("", texto))
