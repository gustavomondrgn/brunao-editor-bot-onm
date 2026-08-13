# Arquitetura e decisões

## O problema

O Mercado de Trabalho não notifica ninguém. Para não perder vaga, a pessoa
precisa ficar com a aba aberta o dia inteiro. E, mesmo olhando, a maioria das
vagas só aceita proposta pela própria plataforma — que é uma fila onde o
freelancer é mais um número.

O que interessa ao Bruno é o subconjunto pequeno: vaga **de vídeo**, **remota**
e com **contato direto no anúncio**, onde dá para chamar no WhatsApp antes dos
outros trinta.

## O caminho de uma vaga

```text
     ONM API                          filtro                      Telegram
┌────────────────┐          ┌────────────────────────┐       ┌──────────────┐
│ POST /login    │──JWT───▶ │ 1. é vídeo? é remoto?  │       │  grupo       │
│ GET /projects  │──vagas──▶│    (Gemini + profile)  │──────▶│  "Vagas      │
└────────────────┘          │ 2. tem contato direto? │ passa │  Editor de   │
        ▲                   │    (regex + validação) │       │   Vídeo"     │
        │                   └────────────────────────┘       └──────────────┘
        │                              │ não passa                  ▲
        │ re-auth no 401               ▼                            │ risca
        │                     skipped_jobs.jsonl                    │
        │                                                    ┌──────────────┐
        └───── GET /projects/{id} ──── 404 duas vezes ───────│  revisor     │
                                                             └──────────────┘
```

A cada `CHECK_INTERVAL` segundos: busca a primeira página, separa o que ainda
não viu, decide vaga por vaga, publica o que passa e depois revisita algumas
das que já publicou.

## Decisões

**Sem banco de dados.** Três arquivos JSON no volume dão conta: o que já foi
visto, o que está publicado e o que foi descartado. Postgres aqui seria
infraestrutura para guardar algumas centenas de inteiros.

**Sem framework de agente.** É um `while True` com `requests`. A única chamada
de LLM é uma classificação por vaga, com schema fixo — não há nada para um
framework orquestrar.

**Uma chamada de Gemini por vaga, não duas.** A mesma resposta que diz se é
vídeo e se é remoto já devolve os trechos que parecem contato. Classificar
antes de extrair contato parece desperdício (a vaga pode ser descartada
depois), mas inverter custaria a sugestão do modelo justamente nos anúncios em
que a regex não achou nada.

**O modelo sugere contato; a regex decide.** Todo trecho que o classificador
devolve passa por `contatos.de_sugestao`, que confere se ele existe letra a
letra no anúncio. Um número inventado nunca vira link no grupo. O caminho
normal é o inverso: a regex acha, e o modelo é só rede de segurança.

**Na dúvida, notifica.** Sem chave, sem perfil, com o Gemini fora do ar ou com
resposta inválida, a vaga passa. O bot pode errar mandando demais; não pode
errar ficando mudo. Por isso também o retry no 429: o fallback é seguro, mas
"seguro" ali significa encher o grupo de vaga fora da área.

**Vaga encerrada é riscada, não apagada.** Quem já viu a vaga entende o que
aconteceu, e o histórico do grupo continua fazendo sentido. `apagar` está
disponível em `ACAO_VAGA_ENCERRADA`, mas não é o padrão.

**Dois 404 para dar a vaga como encerrada.** Só um 404 explícito conta; 401,
429, 5xx e timeout devolvem "desconhecida" e nem contam como falta. A diferença
entre *a vaga acabou* e *a plataforma engasgou* é a diferença entre riscar a
mensagem certa e riscar uma vaga boa do grupo.

**Rechecagem a conta-gotas.** Cada vaga é revista no máximo uma vez a cada
`RECHECK_HORAS`, no máximo `RECHECK_POR_CICLO` por ciclo, e sai do
acompanhamento depois de `RECHECK_DIAS`. Com 12 por ciclo de 10 minutos, dá
folga de sobra para revisar tudo dentro do intervalo sem virar um segundo
scraping.

## A API do ONM

Não é documentada. O que está mapeado:

| O quê | Endpoint |
| --- | --- |
| Login | `POST auth.onovomercado.com.br/api/auth/login` com `{email, password, client: "mdt"}` |
| Token | vem no **cookie** `onm-sso-jwt-token`, não no corpo |
| Listagem | `GET api.onovomercado.com.br/mercado-de-trabalho/v1/projects?page=1&limit=20&sortDir=DESC` |
| Detalhe | `GET .../v1/projects/{id}` — **404 quando a vaga sai do ar** |
| Link público | `omercadodetrabalho.com/vagas/{id}` (POSITION) ou `/projetos/{id}` (PROJECT) |

Campos que importam em cada vaga: `id`, `title`, `description`, `createdAt`,
`type` (`POSITION` | `PROJECT`), `status`, `budgetMin`/`budgetMax` (podem vir
`0.0` ou faltar), `profession.description`, `profession.occupationArea.title`,
`skills[].description`, `author.name`, `proposalExternalLink` (URL, e-mail ou
telefone digitado solto — vem preenchido em cerca de um terço dos anúncios) e
`receiveProposalsOnlyPlatform`.

O JWT dura cerca de 30 dias. No 401 o bot reautentica e repete a chamada.

## Limites conhecidos

- **Só a primeira página.** Se saírem mais de `PAGE_LIMIT` vagas dentro de um
  `CHECK_INTERVAL`, as mais antigas do lote escapam. Com 20 vagas e 10 minutos,
  não acontece: a plataforma publica ~40 por dia.
- **`seen_ids.json` cresce para sempre.** Alguns milhares de inteiros por ano.
  Quando incomodar, basta podar por data.
- **Cota do Gemini.** O free tier dá 15 chamadas por minuto. Um lote grande de
  vagas novas espera e repete; se estourar as tentativas, o filtro abre.
- **Se o grupo virar supergrupo, o `chat_id` muda.** O bot adota o id novo
  sozinho e avisa no log — mas é preciso atualizar `TELEGRAM_CHAT_ID` no
  Coolify, senão o próximo deploy volta a falhar.
