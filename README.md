# Bot de vagas do Bruno — edição de vídeo e diagramação

Monitora a plataforma **O Mercado de Trabalho** (do O Novo Mercado) e manda no
grupo do Telegram só as vagas de **edição de vídeo** e de **diagramação** que
dá para responder **fora da plataforma** — com WhatsApp, formulário, link ou
e-mail no próprio anúncio.

Quando uma vaga já publicada sai do ar, o bot volta na mensagem do grupo e a
risca, com **🔴 VAGA ENCERRADA** por cima.

```text
🏢 VAGA

📌 VAGA EDITOR - 3 REELS POR DIA

👤 Fulano de Tal
🏷 Editor de vídeo · Design e Multimídia
🔧 Reels, TikTok, CapCut
🌎 Remoto
💰 R$1.500 – R$2.500
📅 2026-08-13 14:02

Preciso de editor para 3 reels por dia, cortes dinâmicos...

📲 WhatsApp: (81) 98262-6569

🔗 Ver no ONM
```

## As três regras do filtro

1. **É da área?** Duas áreas contam. **Vídeo:** edição, motion, cortes, VSL,
   legendagem, pós-produção, vídeo com IA. **Diagramação:** ebook, livro,
   revista, apostila, catálogo, proposta, apresentação, trabalho acadêmico
   formatado, InDesign. A régua no design é peça avulsa de divulgação (post,
   flyer, logo) não, documento paginado sim. Quem decide é o Gemini lendo
   [bot/config/profile.md](bot/config/profile.md).
2. **Dá para trabalhar à distância?** Vaga que exige presença física —
   escritório, estúdio, cobrir evento, morar em determinada cidade — não entra.
   Anúncio que não fala de local nenhum entra: a maioria é assim, e presencial
   só se o texto exigir.
3. **Tem contato direto?** Precisa haver WhatsApp, telefone, link de
   candidatura ou e-mail no anúncio. Vaga que só aceita proposta pela
   plataforma fica de fora — é a regra que faz o grupo valer a pena.

Na dúvida, o bot notifica: vaga marcada como "talvez" chega com 🤔 e uma linha
explicando a dúvida. Sem `GEMINI_API_KEY` ou sem o `profile.md`, o filtro se
desliga e o bot notifica tudo — nunca fica em silêncio por falha de infra.

> **Ordem de grandeza:** a exigência de contato direto é cara. Numa amostra de
> 25 vagas do ONM, 5 passaram nas três regras — e o que mais corta não é a
> área, é o contato: várias vagas de vídeo legítimas caem porque o anúncio só
> aceita proposta pela plataforma. O grupo recebe pouca coisa por dia, e é
> assim de propósito. Para afrouxar, mexa em `EXIGIR_CONTATO` e
> `CONTATOS_ACEITOS`.

## Estrutura

```text
.
├── docker-compose.yml       # o que o Coolify sobe
├── bot/
│   ├── Dockerfile
│   ├── main.py              # loop, decisão sobre cada vaga, revisor
│   ├── config.py            # variáveis de ambiente e caminhos
│   ├── onm.py               # login, listagem e "esta vaga ainda existe?"
│   ├── classificador.py     # Gemini: é vídeo? é remoto? tem contato?
│   ├── contatos.py          # extração de WhatsApp, link, e-mail, @
│   ├── mensagem.py          # o HTML que aparece no grupo
│   ├── telegram.py          # enviar, reescrever, apagar
│   ├── estado.py            # seen_ids, publicadas, descartes
│   ├── config/profile.md    # ← o filtro mora aqui
│   └── tests/               # testes da extração de contato
├── scripts/testar_filtro.py # roda o filtro sem enviar nada
└── data/                    # estado local (no container é volume)
```

## Rodar local

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r bot/requirements.txt
cp .env.example .env            # e preencha
python bot/main.py
```

Na primeira execução o bot só memoriza as vagas existentes e não notifica nada
— senão o grupo nasceria com 20 mensagens de vagas velhas. A partir do segundo
ciclo, notifica o que for novo.

Para testar sem esperar e sem enviar nada:

```bash
python scripts/testar_filtro.py --limite 20          # o que entraria e o que não
python scripts/testar_filtro.py --previa             # + a mensagem pronta
python scripts/testar_filtro.py --enviar 1           # publica 1 no grupo, de verdade
python bot/main.py --uma-vez                         # um ciclo só
python bot/tests/test_contatos.py                    # testes da extração
```

## Ajustar o filtro

Tudo que decide o que entra está em [bot/config/profile.md](bot/config/profile.md),
em português corrido. Adicione um tipo de trabalho na lista de relevantes ou de
irrelevantes e pronto.

- **Local:** salve o arquivo. O bot relê sozinho na checagem seguinte.
- **Produção:** edite, commite e pushe — o Coolify rebuilda e sobe.

Depois de mexer, rode `python scripts/testar_filtro.py` para ver o efeito nas
vagas que estão no ar agora.

## Variáveis de ambiente

| Variável | Padrão | Para que serve |
| --- | --- | --- |
| `ONM_EMAIL` / `ONM_PASSWORD` | — | conta do Mercado de Trabalho usada pelo bot |
| `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` | — | bot e grupo de destino |
| `GEMINI_API_KEY` | — | sem ela o filtro desliga e o bot notifica tudo |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | modelo do classificador |
| `CHECK_INTERVAL` | `600` | segundos entre checagens |
| `PAGE_LIMIT` | `20` | quantas vagas buscar por ciclo |
| `EXIGIR_CONTATO` | `true` | exigir contato fora da plataforma |
| `CONTATOS_ACEITOS` | `whatsapp,telefone,link,email` | o que conta como contato |
| `NOTIFICAR_TALVEZ` | `true` | mandar também as vagas duvidosas, com 🤔 |
| `ACAO_VAGA_ENCERRADA` | `marcar` | `marcar` risca, `apagar` remove, `nada` desliga |
| `RECHECK_HORAS` | `6` | de quanto em quanto tempo cada vaga é rechecada |
| `RECHECK_POR_CICLO` | `12` | quantas rechecagens por ciclo |
| `RECHECK_DIAS` | `30` | por quanto tempo uma vaga é acompanhada |
| `DESCRIPTION_MAX_CHARS` | `700` | tamanho do escopo na mensagem |
| `LOG_LEVEL` | `INFO` | |

`DATA_DIR` já vem fixo no `docker-compose.yml` apontando para o volume.
**Não cadastre no painel do Coolify** — apontar para fora do volume faz o bot
esquecer tudo a cada redeploy e reenviar todas as vagas para o grupo.

## Deploy

Está no ar no Coolify. Como funciona, como refazer e o que sobrevive a um
redeploy: [docs/DEPLOY.md](docs/DEPLOY.md). Detalhes de arquitetura e das
decisões: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).

```bash
docker compose up -d --build   # se quiser subir na mão
```
