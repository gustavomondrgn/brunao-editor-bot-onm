"""Roda o filtro nas vagas atuais do ONM e mostra o veredito, sem enviar nada.

É a ferramenta para calibrar o `bot/config/profile.md`: mexe no perfil, roda
isto, vê o que passaria a entrar e a sair do grupo. Não toca no Telegram, não
grava `seen_ids.json`, não gasta nada além das chamadas ao Gemini.

    python scripts/testar_filtro.py                # as 20 últimas vagas
    python scripts/testar_filtro.py --limite 40    # mais fundo no histórico
    python scripts/testar_filtro.py --previa       # mostra a mensagem pronta
    python scripts/testar_filtro.py --enviar 1     # publica 1 no grupo (teste real)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bot"))

import contatos as contatos_mod  # noqa: E402
import mensagem  # noqa: E402
import telegram  # noqa: E402
from main import avaliar  # noqa: E402
from onm import listar_vagas, login  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limite", type=int, default=20, help="quantas vagas buscar")
    p.add_argument("--previa", action="store_true",
                   help="imprime a mensagem formatada das vagas aprovadas")
    p.add_argument("--enviar", type=int, default=0, metavar="N",
                   help="publica de verdade as N primeiras aprovadas no grupo")
    args = p.parse_args()

    vagas = listar_vagas(login(), limit=args.limite)
    print(f"\n{len(vagas)} vaga(s) buscada(s)\n" + "=" * 78)

    aprovadas = []
    for vaga in reversed(vagas):
        d = avaliar(vaga)
        marca = "✅ ENTRA" if d.publicar else "❌ FORA  "
        print(f"\n{marca} [{vaga.get('id')}] {(vaga.get('title') or '')[:62]}")
        print(f"          {d.veredito.categoria} · {d.veredito.modalidade} · "
              f"contatos: {contatos_mod.resumo(d.contatos)}")
        print(f"          {d.motivo if not d.publicar else d.veredito.motivo}")
        if d.publicar:
            aprovadas.append((vaga, d))
            if args.previa:
                texto = mensagem.formatar(vaga, d.veredito, d.contatos)
                print("          " + "-" * 60)
                for linha in texto.splitlines():
                    print("          | " + linha)

    print("\n" + "=" * 78)
    print(f"{len(aprovadas)} de {len(vagas)} entrariam no grupo "
          f"({len(vagas) - len(aprovadas)} descartadas)")

    for vaga, d in aprovadas[:args.enviar]:
        mid = telegram.enviar(mensagem.formatar(vaga, d.veredito, d.contatos))
        print(f"enviada a vaga {vaga.get('id')} → message_id {mid}")


if __name__ == "__main__":
    main()
