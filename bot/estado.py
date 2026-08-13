"""O que o bot precisa lembrar entre um ciclo e outro.

Três arquivos, todos no volume (`DATA_DIR`), nenhum banco de dados:

- `seen_ids.json` — o que já foi analisado, para não notificar duas vezes.
- `publicadas.json` — o que foi para o grupo e ainda merece ser revisitado,
  com o `message_id` de cada mensagem.
- `skipped_jobs.jsonl` — o que foi descartado e por quê, para conferir se o
  filtro está apertado demais.

O bot é feito para morrer e voltar (redeploy, reboot da VPS) sem que ninguém
perceba, então toda escrita é atômica: grava no `.tmp` e renomeia por cima.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import DATA_DIR, PUBLICADAS_FILE, RECHECK_DIAS, SEEN_IDS_FILE, SKIPPED_LOG_FILE

log = logging.getLogger("brunao-bot.estado")

# Quantos 404 seguidos, em checagens diferentes, antes de dar a vaga como
# encerrada. Dois, porque uma instabilidade momentânea da plataforma não pode
# riscar vaga boa do grupo.
CONFIRMACOES = 2


def agora() -> datetime:
    return datetime.now(timezone.utc)


def _salvar_json(caminho: Path, dados: Any) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False)
        tmp.replace(caminho)
    except OSError as exc:
        log.error("Falha salvando %s: %s", caminho, exc)


# ---------------------------------------------------------------------------
# Vagas já analisadas
# ---------------------------------------------------------------------------

def carregar_vistas() -> set[int]:
    if not SEEN_IDS_FILE.exists():
        return set()
    try:
        with SEEN_IDS_FILE.open("r", encoding="utf-8") as f:
            return {int(x) for x in json.load(f)}
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        log.warning("Falha lendo %s: %s — começando vazio", SEEN_IDS_FILE, exc)
        return set()


def salvar_vistas(ids: set[int]) -> None:
    _salvar_json(SEEN_IDS_FILE, sorted(ids))


def primeira_execucao() -> bool:
    return not SEEN_IDS_FILE.exists()


# ---------------------------------------------------------------------------
# Descartes
# ---------------------------------------------------------------------------

def registrar_descarte(vaga: dict[str, Any], motivo: str, detalhe: str = "") -> None:
    """Anota a vaga descartada para revisão posterior do filtro."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    linha = {
        "descartada_em": agora().isoformat(),
        "id": vaga.get("id"),
        "titulo": vaga.get("title"),
        "tipo": vaga.get("type"),
        "motivo": motivo,
        "detalhe": detalhe,
    }
    try:
        with SKIPPED_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(linha, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.error("Falha registrando descarte da vaga %s: %s", vaga.get("id"), exc)


# ---------------------------------------------------------------------------
# Vagas publicadas, para revisitar
# ---------------------------------------------------------------------------

class Publicadas:
    """Registro do que está no grupo, para saber o que riscar quando encerrar.

    Guarda o mínimo para responder "esta vaga ainda está aberta?" e, se não
    estiver, alcançar a mensagem certa no Telegram: o id na plataforma, o
    `message_id` e o HTML original (para riscar no lugar de apagar).
    """

    def __init__(self, caminho: Path = PUBLICADAS_FILE,
                 dias_de_vida: int = RECHECK_DIAS) -> None:
        self.caminho = caminho
        self.dias_de_vida = dias_de_vida
        self._itens: dict[str, dict[str, Any]] = {}
        self._carregar()

    def _carregar(self) -> None:
        if not self.caminho.exists():
            return
        try:
            with self.caminho.open("r", encoding="utf-8") as f:
                self._itens = json.load(f) or {}
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            log.warning("Falha lendo %s: %s — começando vazio", self.caminho, exc)
            self._itens = {}
        if self._itens:
            log.info("Acompanhando %d vaga(s) publicada(s)", len(self._itens))

    def _salvar(self) -> None:
        _salvar_json(self.caminho, self._itens)

    def registrar(self, vaga_id: int, titulo: str, message_id: int | None,
                  html: str) -> None:
        if message_id is None:
            # Sem o id da mensagem não há o que riscar depois; acompanhar a vaga
            # não serviria para nada.
            return
        self._itens[str(vaga_id)] = {
            "titulo": titulo,
            "message_id": message_id,
            "html": html[:4000],
            "publicada_em": agora().isoformat(),
            "checada_em": None,
            "faltas": 0,
            "encerrada": False,
        }
        self._salvar()

    def marcar_checada(self, vaga_id: str, achou_404: bool) -> bool:
        """Anota o resultado. Devolve True no momento em que vira encerrada."""
        item = self._itens.get(str(vaga_id))
        if not item:
            return False
        item["checada_em"] = agora().isoformat()
        # Voltou a responder? Zera: pode ter sido instabilidade da plataforma.
        item["faltas"] = int(item.get("faltas") or 0) + 1 if achou_404 else 0
        virou = bool(item["faltas"] >= CONFIRMACOES and not item["encerrada"])
        if virou:
            item["encerrada"] = True
        self._salvar()
        return virou

    def a_checar(self, intervalo_horas: int, limite: int) -> list[dict[str, Any]]:
        """As próximas vagas a reexaminar, quem está há mais tempo sem checagem antes."""
        self._podar()
        corte = agora() - timedelta(hours=intervalo_horas)
        pendentes = []
        for vaga_id, item in self._itens.items():
            if item.get("encerrada"):
                continue
            quando = _quando(item.get("checada_em"))
            if quando and quando > corte:
                continue
            pendentes.append({"id": vaga_id, **item})
        pendentes.sort(key=lambda i: i.get("checada_em") or "")
        return pendentes[:limite]

    def _podar(self) -> None:
        """Vaga de mês passado não vale requisição."""
        limite = agora() - timedelta(days=self.dias_de_vida)
        antes = len(self._itens)
        self._itens = {
            k: v for k, v in self._itens.items()
            if (_quando(v.get("publicada_em")) or agora()) > limite
        }
        if len(self._itens) != antes:
            log.info("Registro podado: %d vaga(s) saíram do acompanhamento",
                     antes - len(self._itens))
            self._salvar()

    def resumo(self) -> str:
        encerradas = sum(1 for i in self._itens.values() if i.get("encerrada"))
        return f"{len(self._itens)} acompanhada(s), {encerradas} encerrada(s)"


def _quando(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except ValueError:
        return None
