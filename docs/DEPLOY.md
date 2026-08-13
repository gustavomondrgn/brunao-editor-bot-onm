# Deploy

O bot roda no Coolify da Hetzner (`87.99.142.152`), como recurso **Docker
Compose** apontando para este repositório.

| | |
| --- | --- |
| Painel | <https://coolify.kandle.studio> |
| Projeto | Kandle Studio → production |
| Aplicação | `brunao-editor-bot` · uuid `yk7r02pxnyoiq9g7nm4j3uxb` |
| Repositório | `gustavomondrgn/brunao-editor-bot-onm`, branch `main` |
| Compose | `/docker-compose.yml` na raiz |
| Container | `brunao-editor-bot` |
| Volume | `bot-data` → `/app/data` |
| Grupo | "Vagas Editor de Vídeo" · `-1003901848816` |
| Bot | [@onmVagasEdicaoBot](https://t.me/onmVagasEdicaoBot) |

Não há domínio nem porta: o bot só faz chamadas de saída.

## Publicar uma mudança

```bash
git push
```

Se o webhook do GitHub estiver ligado, o Coolify rebuilda sozinho. Para forçar
pela API:

```bash
curl -H "Authorization: Bearer $COOLIFY_TOKEN" \
  "https://coolify.kandle.studio/api/v1/deploy?uuid=yk7r02pxnyoiq9g7nm4j3uxb&force=false"
```

Ver os logs do container:

```bash
curl -H "Authorization: Bearer $COOLIFY_TOKEN" \
  "https://coolify.kandle.studio/api/v1/applications/yk7r02pxnyoiq9g7nm4j3uxb/logs?lines=100"
```

O token de API fica em `.coolify-config.json` (na raiz, fora do Git).

## Variáveis de ambiente

O Coolify lê o `docker-compose.yml` e cria sozinho todas as variáveis com o
valor padrão que está lá. Só as cinco secretas precisam ser preenchidas à mão —
e já estão: `ONM_EMAIL`, `ONM_PASSWORD`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`,
`GEMINI_API_KEY`.

Mudar qualquer outra (intervalo, regras do filtro, ação de vaga encerrada) é
editar no painel e redeployar — não precisa mexer no código.

> **Nunca cadastre `DATA_DIR` no painel.** Ele já está fixo no compose apontando
> para o volume. Sobrescrever faz o bot perder o `seen_ids.json` a cada redeploy
> e reenviar todas as vagas para o grupo.

## O que sobrevive a um redeploy

No volume `bot-data`, portanto **sim**:

- `seen_ids.json` — o que já foi analisado
- `publicadas.json` — o que está no grupo e ainda é acompanhado, com os
  `message_id` que permitem riscar a mensagem depois
- `skipped_jobs.jsonl` — o histórico de descartes

Dentro da imagem, portanto **não** (voltam ao que está no repositório):

- `bot/config/profile.md` e o resto do código

Apagar o volume é começar do zero: a primeira execução só memoriza as vagas
atuais, sem notificar, e o bot perde a capacidade de riscar as mensagens
antigas — elas ficam no grupo como estão.

## Recriar a aplicação do zero

```bash
# 1. criar
curl -X POST https://coolify.kandle.studio/api/v1/applications/public \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"project_uuid":"rx6m0gn1gwn42lhitqhs09em",
       "server_uuid":"vaur673aef258q0fqyhxqbg6",
       "environment_name":"production",
       "environment_uuid":"sk4kbikatpvfaev2qgl8n5ia",
       "git_repository":"https://github.com/gustavomondrgn/brunao-editor-bot-onm",
       "git_branch":"main","build_pack":"dockercompose",
       "docker_compose_location":"/docker-compose.yml",
       "name":"brunao-editor-bot","instant_deploy":false}'

# 2. preencher os segredos (PATCH, não POST — o Coolify já criou as chaves)
curl -X PATCH https://coolify.kandle.studio/api/v1/applications/<uuid>/envs \
  -H "Authorization: Bearer $COOLIFY_TOKEN" -H "Content-Type: application/json" \
  -d '{"key":"ONM_PASSWORD","value":"...","is_preview":false,"is_literal":true}'

# 3. deploy
curl -H "Authorization: Bearer $COOLIFY_TOKEN" \
  "https://coolify.kandle.studio/api/v1/deploy?uuid=<uuid>&force=false"
```

## Se o grupo parar de receber vaga

Pela ordem, olhando os logs:

1. **`Erro de autenticação`** — a senha do ONM mudou, ou a conta caiu.
2. **`Filtro DESLIGADO`** — a `GEMINI_API_KEY` sumiu ou venceu. O bot continua
   notificando, mas sem filtro nenhum.
3. **`Gemini indisponível ... esperando`** repetido — cota do free tier
   estourada. Passa sozinho; se virar rotina, troque de modelo ou de chave.
4. **`sendMessage 403`** — o bot foi removido do grupo.
5. **`O grupo virou supergrupo`** — o `chat_id` mudou. O bot adota o novo
   sozinho, mas o `TELEGRAM_CHAT_ID` do painel precisa ser atualizado, senão o
   próximo deploy volta a falhar.
6. **Nenhum erro e nada chegando** — provavelmente é o filtro fazendo o
   trabalho dele. Confira `data/skipped_jobs.jsonl` no volume, ou rode
   `python scripts/testar_filtro.py` local para ver o que está sendo cortado.
