"""O filtro: esta vaga interessa ao Bruno?

Um Gemini Flash lê o anúncio junto com o `config/profile.md` e devolve três
coisas: se é da área, qual a modalidade de trabalho e quais trechos do texto
parecem contato direto.

Duas decisões que valem para sempre:

- **Erro para o lado de notificar.** Sem chave, sem perfil ou com o modelo fora
  do ar, a vaga passa. Notificação a mais o Bruno ignora em dois segundos;
  vaga perdida ele nunca fica sabendo que existiu.
- **O modelo não decide contato, só sugere.** O que ele devolve em `contatos`
  passa pelo `contatos.de_sugestao`, que confere o trecho contra o texto
  original antes de virar link.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from config import GEMINI_API_KEY, GEMINI_MODEL, PROFILE_FILE

try:
    from google import genai
    from google.genai import types as genai_types
    GENAI_DISPONIVEL = True
except ImportError:  # pragma: no cover - ambiente sem a lib
    GENAI_DISPONIVEL = False

log = logging.getLogger("brunao-bot.classificador")

Categoria = Literal["relevante", "talvez", "irrelevante"]
Modalidade = Literal["remoto", "presencial", "hibrido", "indefinido"]

INSTRUCOES = """Você é o filtro de um grupo de Telegram que recebe vagas de
EDIÇÃO DE VÍDEO e de DIAGRAMAÇÃO garimpadas na plataforma "O Mercado de
Trabalho". As duas áreas valem: quem recebe as vagas faz as duas coisas.

Sua função é ler um anúncio e responder três coisas: se ele é de alguma das
duas áreas, qual a modalidade de trabalho e se há contato direto no texto.

## Como os anúncios são

Escritos às pressas, em português brasileiro, com erro de digitação, abreviação
e gíria. Trate como sinônimos as variações de grafia: "edição"/"edicao",
"vídeo"/"video"/"vídio", "reels"/"reel"/"reels", "vsl"/"VSL", "cortes"/"corte",
"premiere"/"premier"/"pr", "after effects"/"AE"/"after", "capcut"/"cap cut",
"davinci"/"da vinci resolve", "motion"/"motion graphics"/"mografo",
"diagramação"/"diagramacao"/"diagramaçao"/"diagramar", "editoração"/"editoracao",
"ebook"/"e-book"/"e book", "indesign"/"in design"/"ID", "apostila"/"apostilha".

Leve em conta o TÍTULO, a PROFISSÃO/ÁREA, as SKILLS e a DESCRIÇÃO juntos. Muitas
vezes a descrição é vaga ("preciso de alguém pro meu Instagram") mas a categoria
ou as skills entregam que o trabalho é da área.

## Modalidade

- "presencial": exige estar num lugar físico — comparecer ao escritório, gravar
  em estúdio/evento, morar ou residir em determinada cidade, "vaga para São
  Paulo capital", "trabalho no local", "atuação in loco".
- "hibrido": mistura dias presenciais com remoto.
- "remoto": diz explicitamente remoto, home office, à distância, freelancer
  online, "de onde você estiver".
- "indefinido": não fala nada sobre onde se trabalha. **A maioria cai aqui — e
  está tudo bem.** Não invente presencialidade que o texto não afirma. Só use
  "presencial" quando o texto EXIGE presença física de forma clara.

Note a diferença: o assunto do vídeo ser um evento presencial não torna a VAGA
presencial. Editar em casa imagens gravadas num casamento é trabalho remoto.

## Contatos

Copie em `contatos` os trechos LITERAIS do texto que sejam forma de contato ou
candidatura fora da plataforma: número de WhatsApp/telefone, e-mail, link de
formulário, @ de Instagram. Copie exatamente como está escrito, sem corrigir,
sem reformatar, sem completar dígito. Se não houver nada, devolva lista vazia.
Nunca escreva um número que não esteja no texto.

## Categoria

- "relevante": é claramente demanda de vídeo ou de diagramação, dentro do que o
  perfil aceita.
- "talvez": pode ser da área mas o texto deixa dúvida — descrição curta demais,
  vaga genérica de social media que provavelmente inclui edição, vaga genérica
  de designer que provavelmente inclui diagramação, "preciso de alguém pro meu
  Instagram" sem dizer se é vídeo ou arte estática.
- "irrelevante": só para o que é claramente de outra praia. Na dúvida use
  "talvez"; é melhor uma notificação a mais do que perder um job.

Cuidado com a fronteira do design: peça avulsa de divulgação (post, flyer,
banner, cartaz, logo) NÃO é da área; documento paginado (ebook, apostila,
revista, catálogo, proposta, apresentação, trabalho acadêmico formatado) É.

Devolva JSON com: categoria, modalidade, motivo (uma frase curta em português,
até 100 caracteres, explicando a decisão) e contatos.
"""

ESQUEMA = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string", "enum": ["relevante", "talvez", "irrelevante"]},
        "modalidade": {"type": "string",
                       "enum": ["remoto", "presencial", "hibrido", "indefinido"]},
        "motivo": {"type": "string"},
        "contatos": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["categoria", "modalidade", "motivo"],
}


@dataclass
class Veredito:
    categoria: Categoria
    modalidade: Modalidade
    motivo: str
    contatos_sugeridos: list[str] = field(default_factory=list)

    @property
    def passa(self) -> bool:
        """Presencial é descartado mesmo quando é vaga de vídeo de verdade."""
        return self.categoria != "irrelevante" and self.modalidade != "presencial"


_cliente: Any = None
_perfil: str | None = None
_perfil_mtime: float | None = None


def carregar_perfil() -> str | None:
    """Lê o `profile.md`, recarregando sozinho quando o arquivo muda.

    O cache é por mtime para que editar o filtro rodando local valha na próxima
    checagem, sem reiniciar nada.
    """
    global _perfil, _perfil_mtime
    if not PROFILE_FILE.exists():
        if _perfil is not None:
            log.warning("Perfil %s sumiu", PROFILE_FILE)
            _perfil = _perfil_mtime = None
        return None
    mtime = PROFILE_FILE.stat().st_mtime
    if _perfil is None or mtime != _perfil_mtime:
        try:
            _perfil = PROFILE_FILE.read_text(encoding="utf-8")
            _perfil_mtime = mtime
            log.info("Perfil carregado de %s (%d chars)", PROFILE_FILE, len(_perfil))
        except OSError as exc:
            log.error("Falha lendo o perfil %s: %s", PROFILE_FILE, exc)
            return None
    return _perfil


def cliente() -> Any | None:
    global _cliente
    if not GENAI_DISPONIVEL or not GEMINI_API_KEY:
        return None
    if _cliente is None:
        try:
            _cliente = genai.Client(api_key=GEMINI_API_KEY)
            log.info("Gemini pronto (modelo=%s)", GEMINI_MODEL)
        except Exception as exc:  # noqa: BLE001
            log.error("Falha iniciando o Gemini: %s", exc)
            return None
    return _cliente


def ativo() -> bool:
    return carregar_perfil() is not None and cliente() is not None


def vaga_em_texto(vaga: dict[str, Any]) -> str:
    """A vaga achatada num bloco de texto, do jeito que o modelo lê melhor."""
    tipo = "Vaga (CLT/PJ)" if vaga.get("type") == "POSITION" else "Projeto freelance"
    profissao_obj = vaga.get("profession") or {}
    profissao = (profissao_obj.get("description") or "").strip()
    area = ((profissao_obj.get("occupationArea") or {}).get("title") or "").strip()
    skills = ", ".join(
        s.get("description") for s in (vaga.get("skills") or [])
        if s and s.get("description")
    )

    partes = [f"Tipo: {tipo}", f"Título: {(vaga.get('title') or '').strip()}"]
    if profissao or area:
        partes.append(f"Categoria: {profissao}{' · ' + area if area else ''}")
    if skills:
        partes.append(f"Skills: {skills}")
    if (vaga.get("proposalExternalLink") or "").strip():
        partes.append(f"Contato informado no anúncio: {vaga['proposalExternalLink'].strip()}")
    partes.append(f"Descrição: {(vaga.get('description') or '').strip() or '(sem descrição)'}")
    return "\n".join(partes)


# Cota do free tier: 15 chamadas por minuto. Um lote de vagas novas passa disso
# fácil, e um 429 não tratado derruba o filtro para o fallback "notifica tudo" —
# que é seguro, mas enche o grupo de vaga que não é da área. Daí a espera.
TENTATIVAS = 3
ESPERA_MAXIMA = 65.0
RE_RETRY_DELAY = re.compile(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'")


def _esperar_e_repetir(exc: Exception, tentativa: int) -> float | None:
    """Quantos segundos esperar antes de tentar de novo, ou None para desistir.

    Só vale para o que passa: cota estourada (429) e modelo sobrecarregado
    (500/503). Chave inválida e prompt recusado não melhoram com espera.
    """
    texto = str(exc)
    passageiro = ("429" in texto or "RESOURCE_EXHAUSTED" in texto
                  or "503" in texto or "UNAVAILABLE" in texto
                  or "500" in texto or "INTERNAL" in texto)
    if not passageiro or tentativa >= TENTATIVAS:
        return None
    achado = RE_RETRY_DELAY.search(texto)
    # A própria API diz quanto falta para a janela virar; sem isso, backoff.
    sugerido = float(achado.group(1)) + 1 if achado else 5.0 * (2 ** (tentativa - 1))
    return min(sugerido, ESPERA_MAXIMA)


def classificar(vaga: dict[str, Any]) -> Veredito:
    """Classifica a vaga. Qualquer falha vira 'relevante' — o filtro abre."""
    perfil = carregar_perfil()
    cli = cliente()
    if perfil is None or cli is None:
        return Veredito("relevante", "indefinido",
                        "filtro desligado (sem profile.md ou GEMINI_API_KEY)")

    prompt = (f"{INSTRUCOES}\n\n=== PERFIL DE QUEM RECEBE AS VAGAS ===\n{perfil}\n\n"
              f"=== ANÚNCIO A CLASSIFICAR ===\n{vaga_em_texto(vaga)}")
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ESQUEMA,
        temperature=0.1,
    )

    dados: dict[str, Any] | None = None
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resp = cli.models.generate_content(
                model=GEMINI_MODEL, contents=prompt, config=config)
            dados = json.loads(resp.text)
            break
        except Exception as exc:  # noqa: BLE001
            espera = _esperar_e_repetir(exc, tentativa)
            if espera is None:
                log.error("Classificador falhou na vaga %s: %s — deixando passar",
                          vaga.get("id"), str(exc)[:300])
                return Veredito("relevante", "indefinido",
                                f"erro no filtro ({type(exc).__name__})")
            log.warning("Gemini indisponível na vaga %s (tentativa %d/%d) — "
                        "esperando %.0fs", vaga.get("id"), tentativa, TENTATIVAS, espera)
            time.sleep(espera)

    if dados is None:  # pragma: no cover - só se o loop acabar sem break
        return Veredito("relevante", "indefinido", "erro no filtro (sem resposta)")

    categoria = dados.get("categoria")
    if categoria not in ("relevante", "talvez", "irrelevante"):
        log.warning("Categoria inválida %r na vaga %s", categoria, vaga.get("id"))
        categoria = "talvez"
    modalidade = dados.get("modalidade")
    if modalidade not in ("remoto", "presencial", "hibrido", "indefinido"):
        modalidade = "indefinido"

    sugestoes = [s for s in (dados.get("contatos") or []) if isinstance(s, str)]
    return Veredito(categoria, modalidade,
                    (dados.get("motivo") or "").strip()[:200], sugestoes[:6])
