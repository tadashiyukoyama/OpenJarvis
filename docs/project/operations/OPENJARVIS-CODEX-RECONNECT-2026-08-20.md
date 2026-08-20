# Correção do catálogo Codex após reinício do app-server

Data: 20 de agosto de 2026

## Identidade

- Branch: `codex/edge-live-relay-release`.
- SHA-base e rollback de código: `07d8680bdd73dab7c4f4ea4882ecd029ec44bcd6`.
- SHA funcional: `9de7141c15f2abc7214a003244cd464c854b27f9`.
- Core VPS preservado: `2ed693755e1cf0a21a0cb7cb704fbdd3c4294415`.
- AceleraChat preservado: `a01903b9d38377ea97bb07405d8ac1fa62edebd4`.

## Sintoma e causa confirmada

A PWA exibia `Codex conversations unavailable`. O endpoint real
`GET /v1/codex/catalog` retornava HTTP 503 e o Core registrava
`A operação local não foi concluída`.

O Edge Worker havia iniciado antes da geração atual do Codex app-server. Depois
do reinício do app-server, o Worker continuou conectado à VPS, mas manteve o
cliente local encerrado. Não havia conexão do processo Python com
`127.0.0.1:8131`; jobs `codex.catalog` e `codex.history` terminavam em `UNKNOWN`.
Uma conexão diagnóstica independente executou `thread/list` normalmente, o que
isolou a falha no ciclo de vida do executor Edge, não nos dados das conversas.

## Correção

`CodexEdgeExecutor.start()` agora reutiliza o cliente somente quando ele está em
estado `READY`. Se a geração anterior encerrou, o executor fecha o runtime
antigo e cria uma nova conexão, repetindo o handshake oficial
`initialize`/`initialized` antes das próximas operações.

A correção não adiciona retry cego a `codex.delegate`. Assim, uma queda durante
um comando mutável continua falhando de forma explícita, sem risco de criar dois
turnos no Codex.

## Validação

- Testes Edge, WebSocket e conversa Codex: `99 passed + 4 subtests`.
- Testes de catálogo, despacho e proxy Edge: `25 passed`.
- Total dos gates focados: `124 passed + 4 subtests`.
- Ruff check e Ruff format: aprovados.
- `git diff --check`: aprovado.
- `executor.py`: 390 linhas.
- Worker reiniciado em uma única instância lógica, com o par launcher/child
  esperado do ambiente virtual.
- Conexão Worker -> VPS: estabelecida.
- Conexão Worker -> Codex app-server em `127.0.0.1:8131`: estabelecida.
- `GET /v1/codex/catalog`: HTTP 200, 17 projetos e 23 conversas.
- `GET /v1/codex/threads/{id}/history`: HTTP 200, 30 mensagens na página e
  cursor para a página seguinte.
- Nenhum turno, mensagem, e-mail ou WhatsApp real foi enviado.

A suíte global foi iniciada, mas interrompida para não manter uma carga longa e
desnecessária no computador. Os gates focados cobrem todos os módulos alterados
e o fluxo real de leitura que reproduzia o incidente.

## Operação e rollback

O Core da VPS não foi substituído. A ativação ocorreu somente reiniciando a
tarefa agendada `OpenJarvis Edge Worker`, que passou a carregar o SHA funcional.

Rollback de código:

1. restaurar `07d8680bdd73dab7c4f4ea4882ecd029ec44bcd6` no diretório local;
2. reiniciar somente a tarefa `OpenJarvis Edge Worker`;
3. validar que existe uma única instância lógica do Worker.

O rollback não exige migration, alteração de credencial, reinício do Codex
Desktop ou mudança na VPS.
