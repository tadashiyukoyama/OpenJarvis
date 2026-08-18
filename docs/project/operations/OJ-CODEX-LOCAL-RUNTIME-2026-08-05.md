# Relatório de execução local — Codex como IA do OpenJarvis

Status: HISTORICAL EVIDENCE — FROZEN
Frozen on: 2026-08-09 02:06:31 -03:00
Current operational authority:
`docs/project/operations/JARVIS-AGENT-RUNBOOK.md`
Current architecture and state:
`docs/project/JARVIS-AGENT-CONTRACT.md` and
`docs/project/CURRENT-PROJECT-STATE.md`

This dated report preserves the chronological evidence of the original local
Codex/Jarvis integration. It must not receive new operational instructions.

Data e hora da validação: 2026-08-05 17:08:39 -03:00
Responsável: Codex, sob autorização de César
Escopo: execução local do runtime Codex, exclusivamente em D:

## Resultado

APROVADO para execução local pela CLI e pela API HTTP.

Evidências reais:

- `jarvis ask --agent codex` retornou `CODEX_LOCAL_OK`.
- `jarvis serve --agent codex` iniciou em `http://127.0.0.1:8127`.
- `GET /health` retornou `{"status":"ok"}`.
- `GET /v1/info` identificou `agent=codex` e `engine=codex_app_server`.
- `GET /v1/models` expôs o modelo externo `codex`.
- `POST /v1/chat/completions` não-streaming retornou `CODEX_API_OK`.
- A mesma rota em SSE streaming retornou `CODEX_STREAM_OK` e `data: [DONE]`.
- O frontend React/Vite está ativo em `http://127.0.0.1:5173`.
- `npm run build` compilou a interface e gerou os assets estáticos.
- Testes do frontend: 6 passaram em 1 arquivo.

## Ambiente

- Branch: `codex/real-codex-runtime`
- HEAD: `927c2ef5fc077bc591e910a6307579fe43d4620a`
- Python: 3.13.13
- Ambiente virtual: `D:\dev\workspaces\openjarvis\.venv`
- Runtime OpenJarvis: `D:\dev\runtime\openjarvis`
- `CODEX_HOME`: `D:\dev\codex-home\.codex`
- Nenhum modelo foi baixado.
- Ollama não foi usado nem é necessário para este caminho.
- Dependências frontend: `npm ci` concluído em `D:\dev\workspaces\openjarvis\frontend`.

## Validação

- 83 testes do transporte, runtime e agente Codex: PASS.
- 172 testes de rotas, CLI, SDK, servidor e integração: PASS.
- `py_compile`, Ruff check, Ruff format check e `git diff --check`: PASS.
- A suíte ampla não-live não foi concluída porque um teste opcional exige `polars`, que não foi instalado.
- Há falhas preexistentes fora do caminho Codex relacionadas ao backend nativo `openjarvis_rust` ausente.
- O npm reportou 29 vulnerabilidades no conjunto de dependências (2 low, 15 moderate, 12 high); `npm audit fix` não foi executado.

## Alterações locais

Foram ajustados os pontos de entrada CLI/SDK, o servidor HTTP, a identidade de conversa, o parser do envelope emitido pelo Codex Desktop e os testes correspondentes. As alterações ainda não foram commitadas nem enviadas ao GitHub.

## Operação atual

O backend permanece ativo no PID 2000 em `127.0.0.1:8127` e o frontend Vite no PID 14296 em `127.0.0.1:5173`. O endpoint visual está disponível em [OpenJarvis local](http://127.0.0.1:5173); a API técnica está em [Swagger](http://127.0.0.1:8127/docs).

## Selecao de projeto e conversa (2026-08-05 17:08:39 -03:00)

- `GET /v1/codex/catalog` retornou 10 projetos/workspaces e as conversas
  existentes no catalogo live do Codex app-server.
- A interface em `http://127.0.0.1:5173` agora exibe dois seletores na barra
  lateral: projeto/workspace e conversa Codex.
- Uma conversa existente e identificada pelo `thread_id` imutavel e e retomada
  com `thread/resume`; o backend nao cria outra conversa nesse caso.
- `+ New conversation` cria um alvo local novo no projeto selecionado; a
  primeira mensagem cria a thread nesse workspace.
- O titulo, preview e nome do projeto ficam somente como metadados da UI. O
  `turn/start` recebe exclusivamente a mensagem digitada pelo usuario.
- Teste fake do agente confirmou que a selecao explicita chama `thread_resume`,
  nao chama `thread_start` e envia exatamente `ola` como input.

Verificacao adicional: `GET /health` retornou 200 e `GET /v1/codex/catalog`
retornou 200 apos o reinicio do servidor local.

## Historico da conversa selecionada (2026-08-05 17:28:48 -03:00)

- `GET /v1/codex/threads/{thread_id}/history` foi adicionado e validado
  contra uma thread real do Codex app-server.
- A resposta real trouxe 120 mensagens publicas para o alvo `openjarvis` usado
  no teste, incluindo as mensagens enviadas pelo OpenJarvis.
- O OpenJarvis carrega esse historico ao abrir uma conversa existente, tanto
  pela lista local quanto pelo seletor Codex.
- O normalizador inclui mensagens do usuario e respostas finais do assistente;
  exclui raciocinio, ferramentas e mensagens intermediarias de andamento.
- Nenhuma mensagem de teste foi enviada durante essa validacao; a leitura foi
  somente `thread/read`.

## Sincronizacao automatica suportada (2026-08-05 17:54:42 -03:00)

- `GET /v1/codex/threads/{thread_id}/events` publica snapshots SSE somente
  quando o historico publico sanitizado muda.
- Cada snapshot possui revisao SHA-256 deterministica, `thread_id` e mensagens
  publicas com IDs canonicos; raciocinio, ferramentas e payloads internos nao
  sao enviados ao frontend.
- O frontend reconcilia os snapshots sem duplicar mensagens e preserva
  telemetria local quando o conteudo publico coincide.
- Um snapshot mais antigo que seja apenas prefixo nao remove a resposta local
  recem-concluida. Durante um stream iniciado no OpenJarvis, a sincronizacao de
  historico pausa e reconecta ao final para obter um snapshot integral.
- Quedas do canal usam reconexao com backoff limitado entre 1 e 10 segundos.
- Validacao real: HTTP 200, `text/event-stream`, revisao de 64 caracteres e 130
  mensagens publicas para a conversa selecionada.
- Validacao automatizada relacionada: 145 testes Python passaram, incluindo 4
  subtestes; 12 testes frontend passaram; TypeScript e build Vite passaram.
- O backend foi reiniciado e permanece em `127.0.0.1:8127` no PID 2000; o
  frontend Vite foi reiniciado em `127.0.0.1:5173` no PID 14296.
- A configuracao local ignorada `frontend/.env.local` fixa
  `VITE_API_URL=http://127.0.0.1:8127`; o bundle servido em `5173` foi
  verificado com esse backend e CORS retornou a origem local correta.

Limite confirmado: Codex Desktop e OpenJarvis usam processos app-server
distintos por `stdio`. O historico persistido e compartilhado, mas os deltas de
token nao sao. Assim, mensagens e respostas finais concluidas no Desktop
aparecem automaticamente no OpenJarvis; o mesmo stream de tokens nao pode ser
espelhado entre as duas interfaces pelo contrato publico atual.

## Atualizacao do Codex Desktop apos resposta (2026-08-05 18:36:29 -03:00)

- O teste `CODEX_STREAM_OK` anterior comprovava persistencia: o Desktop leu os
  dois turnos quando a tarefa foi aberta. Ele nao comprovava assinatura ao vivo
  dos eventos produzidos pelo processo app-server do OpenJarvis.
- `POST /v1/codex/threads/{thread_id}/desktop-refresh` foi adicionado para
  reabrir a tarefa concluida pela rota oficial documentada
  `codex://threads/{thread_id}`.
- A rota aceita somente cliente loopback, exige o cabecalho
  `X-OpenJarvis-Local-Action: codex-desktop-refresh`, valida o historico da
  thread no Codex atual e restringe o identificador para impedir injecao de
  caminho ou URI.
- O frontend chama a rota somente depois do encerramento normal de uma resposta
  iniciada no OpenJarvis e somente quando uma thread Codex existente esta
  selecionada. A opcao fica habilitada por padrao e pode ser desligada no painel
  `Codex target`.
- Validacao real: o manifesto AppX instalado registra o protocolo `codex`; a
  chamada para a thread selecionada retornou HTTP 202 e o deep link canonico.
- Regressao relacionada: 152 testes Python e 4 subtestes passaram; 15 testes
  frontend passaram; `compileall`, Ruff, `git diff --check`, TypeScript e o
  build Vite passaram. Permaneceram apenas avisos preexistentes de deprecacao e
  tamanho de bundle.
- O verificador de saude do navegador passou a consultar primeiro
  `VITE_API_URL=http://127.0.0.1:8127`, eliminando o falso alerta provocado pelo
  proxy Vite ainda apontado para a porta 8000.

Hipotese de 18:36, posteriormente rejeitada pela captura: o deep link unico
deveria recarregar o Desktop ao final da resposta. Tokens intermediarios
continuam exclusivos da interface que iniciou o turno; nenhum protocolo
privado, banco interno ou automacao de teclado foi usado.

## Correcao da recarga da tarefa ja aberta (2026-08-05 19:10:56 -03:00)

O aceite anterior do refresh foi retirado. O HTTP 202 e o registro do protocolo
provaram apenas que o Windows aceitou o deep link; a captura fornecida por Cesar
mostrou que a tarefa que ja estava aberta no Codex Desktop continuava com a tela
antiga.

A auditoria do manipulador de rotas da versao instalada Codex Desktop
26.730.8199 confirmou que `codex://threads/{thread_id}` consulta a tarefa e
navega para sua rota. Quando essa rota ja esta selecionada, o renderer nao e
remontado. A correcao passa primeiro por `codex://settings`, aguarda 750 ms e
entao abre `codex://threads/{thread_id}`. Ambas as rotas sao documentadas; a
rota intermediaria nao cria tarefa e nao altera conversa.

Evidencias tecnicas atuais:

- backend reiniciado em `127.0.0.1:8127`, PID 3120;
- chamada real da rota corrigida retornou HTTP 202;
- 154 testes Python e 4 subtestes passaram;
- 15 testes frontend passaram;
- Ruff check, Ruff format, TypeScript e build Vite passaram;
- nenhum protocolo privado, automacao de teclado ou alteracao do Codex Desktop
  foi usado.

Status de aceite: PENDENTE. Por decisao de Cesar, somente uma mensagem nova
enviada no navegador interno e observada na mesma tarefa ja aberta do Codex
Desktop, junto com a resposta concluida, autoriza marcar esta correcao como
terminada.

## Camada Jarvis com Gemini Live e fallback seguro (2026-08-05 23:03:12 -03:00)

Foi implementada uma nova aba nativa `Jarvis`, disponível em
`http://127.0.0.1:5173/jarvis`, sobre a interface existente. O HUD responsivo
possui núcleo visual animado, estados de conexão/escuta/raciocínio/fala/execução,
transcrições, linha do tempo, interrupção de fala, reconexão e entrada textual
para testes sem microfone.

A arquitetura entregue separa responsabilidades:

- o navegador captura áudio PCM 16 kHz, reproduz áudio PCM 24 kHz e mantém a
  sessão WebSocket Gemini Live;
- o backend loopback lê as chaves somente de variáveis privadas e solicita um
  token efêmero, de uso único e curta duração; nenhuma chave é enviada ao
  frontend, gravada na documentação ou registrada em logs;
- a ferramenta `delegate_to_codex` envia apenas o comando natural para o projeto
  e a conversa Codex atualmente selecionados, reutilizando o `thread_id` e o
  streaming já existentes;
- ações com consequência externa exigem confirmação explícita na própria aba
  antes da delegação;
- o sincronizador da conversa Codex foi elevado ao layout global, permanecendo
  ativo também quando a aba Jarvis está selecionada.

Foram definidos dois slots privados:

- `GEMINI_LIVE_API_KEY_PRIMARY`;
- `GEMINI_LIVE_API_KEY_FALLBACK`.

O fallback existe somente para continuidade técnica legítima após falha de
autenticação/revogação, transporte ou erro 5xx do provedor. Respostas
`429`/`RESOURCE_EXHAUSTED` não acionam a segunda credencial: o comando é
preservado, a interface informa o bloqueio e aguarda a recuperação da cota. O
launcher aceita exclusivamente esses dois nomes e `GEMINI_LIVE_MODEL`, não
imprime valores e injeta as variáveis apenas no processo backend.

Validação executada:

- 172 testes Python e 4 subtestes: PASS;
- 18 testes frontend: PASS;
- Ruff check, `compileall`, TypeScript e build Vite de produção: PASS;
- launcher em `-ValidateOnly`: PASS;
- `git diff --check`: PASS;
- `GET /v1/jarvis/live/status`: PASS, sem exposição de segredo;
- renderização local da aba em dimensões desktop e tablet: PASS;
- teste unitário de chave primária, fallback por autenticação e proibição de
  fallback por cota: PASS.

Status de aceite da voz: PENDENTE. O arquivo privado ignorado
`D:\dev\workspaces\openjarvis\.private\env\gemini-live.env` foi criado com os
dois valores vazios. Sem credenciais reais não é possível aprovar honestamente
o ciclo microfone -> Gemini Live -> ferramenta -> conversa Codex. Nenhuma chave
foi lida, copiada ou registrada pelo executor.

Fechamento de 2026-08-05 23:08 -03:00: a repetição combinada de todas as suítes
selecionadas excedeu o limite de 120 segundos do harness e, por isso, não foi
contada como novo PASS. Em seguida, o escopo novo foi revalidado separadamente:
5 testes do broker Gemini Live e 18 testes frontend passaram; build Vite,
TypeScript, Ruff, `compileall`, launcher `-ValidateOnly` e `git diff --check`
passaram. O backend ativo retornou saúde `ok`, modelo
`gemini-3.1-flash-live-preview` e confirmou os dois slots como não configurados.
O HTML auxiliar usado somente para a captura visual foi removido e o Edge
headless isolado foi encerrado.

Arquivos principais desta camada: `src/openjarvis/server/gemini_live.py`,
`frontend/src/lib/gemini-live.ts`, `frontend/src/lib/jarvis-api.ts`,
`frontend/src/lib/codex-command.ts`, `frontend/src/pages/JarvisPage.tsx`,
`frontend/src/pages/JarvisPage.css`, `tests/server/test_gemini_live.py` e
`frontend/src/lib/gemini-live.test.ts`.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. As alterações continuam locais e
não commitadas. Nenhuma dependência foi instalada nesta camada; nenhum modelo
foi baixado; Ollama não foi usado. Deploy, migration, credenciais reais e
GitHub: não alterados.

## Ativação controlada das duas credenciais (2026-08-05 23:42:18 -03:00)

Cesar forneceu e autorizou duas credenciais de teste. Os valores foram gravados
somente no arquivo privado ignorado `.private/env/gemini-live.env`, não foram
copiados para código, Git ou documentação e não são reproduzidos neste relatório.
O backend foi reiniciado com `-SkipDesktop`; o Codex Desktop aberto não foi
encerrado nem alterado.

Evidência sanitizada:

- status do broker: chave principal configurada e fallback configurado;
- emissão real: HTTP 200, slot `primary`, fallback inativo e token efêmero
  presente;
- WebSocket Gemini Live real: `setupComplete` recebido;
- resposta: 14 blocos de áudio e 3 eventos de transcrição recebidos;
- encerramento normal: `turnComplete` recebido;
- nenhum token ou valor de chave foi impresso.

Status de aceite atualizado: PROTOCOLO LIVE APROVADO; ACEITE VISUAL/SONORO
PENDENTE. Ainda é necessário atualizar a aba `/jarvis`, permitir o microfone,
ouvir a resposta e comprovar uma delegação por voz à conversa Codex selecionada.
Credenciais locais: alteradas sob autorização. Deploy, migration e GitHub: não.

## Despachante único Chat/Jarvis (2026-08-05 23:51:46 -03:00)

O primeiro teste visual/sonoro confirmou que a voz funcionava, mas a delegação
foi recusada porque `streamState.isStreaming` permaneceu obsoleto e a
sincronização apareceu como `paused`. Esse booleano era apenas estado de
apresentação e não provava que a conversa Codex continuava executando.

A correção eliminou o remetente paralelo do Jarvis. A caixa de Chat e a
ferramenta de voz `delegate_to_codex` agora chamam a mesma função
`sendCodexConversationMessage`, que:

- grava a mensagem no mesmo histórico OpenJarvis;
- usa a mesma rota `/v1/chat/completions`;
- envia o mesmo projeto e `codex_thread_id` selecionados;
- mantém um único lock real de execução para o aplicativo;
- libera o lock e o estado visual em `finally`;
- recupera um `isStreaming` órfão quando não existe execução proprietária;
- pausa a reconciliação durante o turno e a retoma depois do encerramento.

Validação: 2 regressões novas comprovaram mensagem pura/mesma thread,
recuperação de estado obsoleto, bloqueio apenas durante execução real e liberação
após conclusão. A suíte frontend completa passou com 20 testes em 6 arquivos;
TypeScript, build Vite e `git diff --check` passaram. O frontend permaneceu ativo
no processo Vite esperado em `127.0.0.1:5173`. Aceite no navegador: PENDENTE de
uma nova fala após o término desta própria tarefa Codex.

Deploy, migration, credenciais e GitHub: não realizados.

## Fila de delegação e voz Orus (2026-08-06 00:14:40 -03:00)

O erro visual `CODEX_CONVERSATION_TURN_FAILED` foi correlacionado com o log
real do backend. A causa exata era `CodexConcurrentTurnError`: uma segunda
delegação tentava iniciar outro turno enquanto a mesma thread ainda estava
ativa no runtime compartilhado.

A correção mantém a proibição de turnos concorrentes, mas adiciona uma fila
limitada a 300 segundos no `CodexAgent`. O runtime disponibiliza uma espera
condicional por thread e acorda os solicitantes quando o turno chega a estado
terminal, falha ao iniciar ou o runtime é fechado. Uma disputa entre dois
solicitantes acordados retorna à fila, sem sobrescrever histórico e sem abrir
uma segunda conversa.

A voz de todas as novas sessões Gemini Live foi alterada de `Kore` para
`Orus`. A instrução de sistema informa que a voz é masculina e firme e proíbe
o Jarvis de prometer uma troca no meio da sessão, porque a configuração de voz
é negociada no `setup` do WebSocket. A interface também expõe
`Voz Jarvis — Orus · masculina`. Uma sessão que já estava aberta deve ser
encerrada e criada novamente para receber a mudança.

Validação desta correção:

- 58 testes Python e 4 subtestes direcionados: PASS;
- 21 testes frontend em 6 arquivos: PASS;
- TypeScript e build Vite de produção: PASS;
- Ruff check e formatação dos arquivos afetados: PASS;
- suíte expandida: 1399 PASS, 2 skipped e 15 falhas preexistentes ligadas ao
  backend Rust ausente e diferenças conhecidas do ambiente Windows;
- suíte Python integral não foi coletada porque `polars`, extra opcional de
  comparação, não está instalado; nenhuma dependência foi instalada;
- serviços reiniciados: backend `8127`, app-server `8131` e frontend `5173`;
- saúde do backend: `ok`; os dois slots Gemini permaneceram configurados;
- prova Gemini Live real com `Orus`: `setupComplete`, áudio, transcrição e
  `turnComplete` recebidos pelo slot principal, sem imprimir credenciais.

Aceite visual/sonoro final: PENDENTE. O canal automatizado de controle do
navegador interno não foi disponibilizado nesta sessão. Conforme o gate de
Cesar, a tarefa não deve ser declarada concluída até encerrar a sessão antiga,
atualizar `/jarvis`, ouvir `Orus` e delegar uma mensagem pela própria tela.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais, sem commit e
sem push. Deploy, migration e GitHub: não alterados. Credenciais: valores não
alterados nesta correção.

## Mensagem de voz normal e recuperação terminal (2026-08-06 00:31:31 -03:00)

O teste visual seguinte confirmou que a delegação chegava à thread selecionada
e era persistida como `userMessage`, mas revelou que o OpenJarvis podia perder
a notificação terminal do app-server. Nesse cenário, a resposta existia no
histórico do Codex, porém o stream HTTP não terminava, o Chat permanecia
processando e o dispatcher continuava ocupado. Enquanto aguardava, o Gemini
repetia a chamada da ferramenta e produzia mensagens falsas de concorrência.

A correção mantém uma única rota de envio para Chat e voz e acrescenta três
garantias:

- o ID da mensagem criada pelo frontend percorre
  `codex_client_user_message_id` até o parâmetro oficial
  `turn/start.clientUserMessageId`, preservando a identidade de uma mensagem
  normal do usuário no cliente Codex;
- `wait_turn` continua usando notificações como caminho principal, mas a cada
  500 ms pode reconciliar exclusivamente o par `thread_id`/`turn_id` por
  `thread/read`; somente um estado terminal exato libera o stream e a fila;
- chamadas Gemini idênticas enquanto a primeira está em voo compartilham a
  mesma promessa e o mesmo resultado; não criam um segundo turno e não usam
  outra ponte.

Validação executada:

- schema JSON local do Codex instalado revalidado: `TurnStartParams` contém
  `clientUserMessageId` opcional e `userMessage` contém `clientId` opcional;
- 100 testes Python direcionados e 4 subtestes: PASS;
- 21 testes backend adicionais de Gemini/WebSocket/sistema: PASS;
- suíte frontend completa, 23 testes em 7 arquivos: PASS;
- Ruff check e format check: PASS;
- TypeScript e build Vite de produção: PASS;
- `git diff --check`: PASS;
- backend, app-server e frontend ativos em `8127`, `8131` e `5173`;
- dois smokes SSE reais e consecutivos na mesma thread Codex de teste inativa:
  HTTP 200 em 4,41 s e 2,07 s, marcador esperado e `[DONE]` recebidos;
- histórico público após os smokes: as duas mensagens do usuário e as duas
  respostas finais presentes.

Aceite visual final: PENDENTE. A correção está instalada e os serviços estão
ativos, mas a tarefa não será declarada concluída antes de uma nova delegação
pela aba Jarvis aparecer no Chat, retornar resposta, sair de `executando` e ser
confirmada visualmente por César no Codex Desktop.

Branch e SHA: `codex/real-codex-runtime` em
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais, sem commit e
sem push. Dependências e modelos: não alterados. Deploy, migration, GitHub e
valores de credenciais: não alterados.

## Aceite visual da delegação por voz (2026-08-06 00:43:09 -03:00)

César confirmou explicitamente o gate visual e funcional ao falar com esta
conversa Codex através do OpenJarvis voz. A delegação por voz está operacional,
aceita e em uso real. A mensagem percorreu a interface Jarvis, chegou à
conversa Codex selecionada e permitiu continuidade normal da interação.

Os ajustes finos restantes passam a ser resolvidos diretamente durante a
interação entre César e Jarvis. Eles não são mais bloqueio para o aceite da
delegação por voz.

Status atualizado: ACEITE VISUAL E FUNCIONAL CONFIRMADO POR CÉSAR. Nenhuma
alteração de código ou serviço foi necessária para registrar este aceite.
Deploy, migration, GitHub e valores de credenciais: não alterados.

## Idempotência, autorização, memória e restauração (2026-08-06 02:00:09 -03:00)

O uso real posterior ao aceite básico revelou três defeitos de endurecimento:

- a mesma frase podia receber novos IDs Gemini e abrir turnos Codex distintos
  depois de a primeira delegação terminar;
- Jarvis enviou um comando de shell para consultar logs sem César pedir que a
  consulta fosse encaminhada ao Codex;
- uma sessão Gemini Live nova não recebia histórico recente nem sabia informar
  a última resposta conhecida do Codex.

A investigação confirmou serviços saudáveis e ausência de retry HTTP ou fila
travada no backend. A correção ficou na camada frontend Live:

- mensagens WebSocket recebidas são processadas em série;
- cada `functionCall.id` conserva promessa e resultado durante a sessão;
- conversa e comando normalizado conservam o resultado por cinco minutos;
- chamadas repetidas recebem o resultado armazenado sem novo turno;
- o envelope de retorno usa `response: { result: ... }`;
- o VAD usa sensibilidade baixa para reduzir reativação por eco;
- uma chamada gerada pelo modelo não vale como autorização;
- somente uma fala atual que envie, peça ou delegue explicitamente algo ao
  Codex pode chamar o dispatcher;
- o texto enviado é a fala original de César, nunca shell criado pelo Gemini;
- sem autorização, o envio é bloqueado e Jarvis deve pedir confirmação;
- sessões novas recebem até 16 mensagens públicas recentes, a última resposta
  conhecida do Codex e marcação de contexto somente para leitura;
- valores com formato de chave, token ou segredo são removidos antes de esse
  contexto ser enviado ao Gemini.

### Incidente de restauração

Às 01:07 a implementação havia passado em 34 testes, build e prova HTTP. Entre
01:33:49 e 01:34:23, sem turno Codex ativo, o Desktop realizou uma sequência de
retomadas da thread enquanto os arquivos eram restaurados um por um. O padrão é
compatível com uma ação de desfazer alterações no cartão do Codex. A restauração
apagou `jarvis-context.ts` e `jarvis-delegation.ts`, mas deixou uma versão antiga
de `JarvisPage.tsx` importando `jarvis-delegation.ts`. O Vite então registrou:

`Failed to resolve import "../lib/jarvis-delegation" from "src/pages/JarvisPage.tsx"`.

César autorizou explicitamente a restauração. Os módulos e as alterações foram
reaplicados sem modificar outros arquivos do workspace.

Validação pós-restauração:

- 16 testes direcionados de autorização, idempotência, contexto e envelope:
  PASS;
- suíte frontend completa: 34 testes em 8 arquivos, PASS;
- TypeScript e build Vite de produção: PASS;
- `git diff --check`: PASS;
- `/jarvis`, `JarvisPage.tsx`, `jarvis-delegation.ts` e `jarvis-context.ts`:
  HTTP 200 pelo Vite;
- backend `8127` e app-server `8131`: HTTP 200;
- gate de autorização e sanitização de credenciais presentes no código servido.

Gate visual/voz pós-restauração: PENDENTE de recarregar `/jarvis`, iniciar uma
sessão nova e confirmar continuidade de contexto e ausência de delegação
automática. Não usar a ação **Desfazer** do cartão desta resposta, pois ela
reverterá novamente os arquivos restaurados.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais, sem commit nem
push. Dependências, modelos, deploy, migration, GitHub e valores de credenciais:
não alterados.

## Ferramentas seguras do Jarvis para Data Sources (2026-08-07 19:23:00 -03:00)

O Jarvis Gemini agora possui uma camada de ferramentas autenticada no backend,
sem entregar tokens OAuth ou estado de autenticação WhatsApp ao navegador ou ao
modelo. Gmail foi conectado às operações limitadas de busca e leitura e às
operações externas separadas de envio, arquivamento e movimento para a lixeira.
O botão de autorização da interface é o gate para as mutações; "apagar" usa a
lixeira recuperável do Gmail e não exclusão permanente.

WhatsApp foi preparado pelo canal QR Baileys existente: estado, disponibilidade
do QR e envio de texto estão expostos por endpoints locais autenticados. O QR é
retornado somente à interface para exibição e não entra no contexto do Gemini.
Chamadas de voz não foram simuladas: o bridge atual não possui transporte de
mídia/WebRTC revisado, portanto a ferramenta devolve indisponibilidade explícita
até que um adaptador de áudio seja escolhido e validado.

Arquivos principais: `src/openjarvis/server/jarvis_sources_router.py`,
`src/openjarvis/connectors/gmail.py`, `frontend/src/lib/jarvis-sources-api.ts`,
`frontend/src/lib/gemini-live.ts` e `frontend/src/pages/JarvisPage.tsx`.

Validações: `26 passed` no novo conjunto de endpoints mais o conjunto Gmail;
`26 passed` nos testes frontend direcionados; TypeScript, compilação Python,
Ruff e `git diff --check` aprovados. Nenhuma conta real foi acessada, nenhuma
mensagem foi enviada e o bridge WhatsApp não foi iniciado durante a validação.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais, sem commit nem
push. Deploy, migration, GitHub e credenciais: não alterados.

## Sincronização visual remota do Codex Desktop (2026-08-06 05:35:19 -03:00)

A investigação confirmou que a delegação feita por voz no tablet já persistia
a mensagem e a resposta na conversa Codex correta. O defeito restante era
exclusivamente visual: o processo do Codex Desktop não recebia o evento emitido
pelo app-server separado usado pelo OpenJarvis.

A correção consolidada mantém um único dispatcher para Chat e voz. Depois de a
resposta final ser persistida, o frontend solicita a remontagem documentada do
Desktop. O backend:

- aceita somente `POST /v1/codex/threads/{thread_id}/desktop-refresh`;
- exige cliente loopback e a capacidade local
  `X-OpenJarvis-Local-Action: codex-desktop-refresh`;
- valida a sintaxe e a existência da conversa no runtime Codex atual;
- abre `codex://settings`, aguarda 750 ms e então abre exclusivamente a URI
  `codex://threads/{thread_id}` validada.

Para o tablet, o gateway temporário autenticado reconhece somente esse caminho
exato. Ele remove cabeçalhos de endereço encaminhados e qualquer capacidade
fornecida pelo navegador, inserindo a capacidade confiável apenas na conexão
loopback gateway → backend. Uma chamada pública de prova enviou deliberadamente
um valor de capacidade falso; o gateway o descartou e a conversa selecionada
retornou HTTP 202 com URI `codex://`.

Validações executadas nesta correção:

- 15 testes Python direcionados: PASS;
- quatro testes frontend do dispatcher: PASS;
- Ruff check/format e compilação Python do gateway: PASS;
- TypeScript sem erros e build Vite de produção: PASS;
- `git diff --check`: PASS;
- CORS local para o cabeçalho de capacidade: HTTP 200;
- página e bundle de produção pelo Quick Tunnel: HTTP 200;
- novo caminho presente no bundle público: PASS;
- rota sem capacidade: HTTP 403;
- rota local e rota autenticada pelo túnel: HTTP 202;
- backend `8127`, app-server compartilhado `8131`, frontend `5173`, gateway
  `8140` e Quick Tunnel: ativos após o reinício seletivo.

Gate de aceite visual: PENDENTE. O canal de automação visual do Windows não
está disponível nesta execução, e a frase de prova solicitada ainda não chegou
ao histórico. Conforme a regra de César, a correção não será declarada concluída
até uma nova delegação por voz no tablet aparecer automaticamente, junto com a
resposta final, na conversa já aberta do Codex Desktop.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais sem commit ou
push. Dependências, modelos, migration, GitHub e valores de credenciais: não
alterados. O Quick Tunnel temporário foi mantido ativo; não houve deploy de
produção.

## Confirmação natural, controle visual e acesso móvel (2026-08-06 04:17:04 -03:00)

O teste real pelo túnel confirmou que a voz Gemini funcionava no navegador do
PC, mas a frase natural `Eu confirmo` não consumia a delegação pendente. O
autorizador reconhecia `confirmo` e `sim, eu confirmo`, porém não a forma com o
pronome inicial. Como consequência, a chamada seguinte do Gemini guardava o
mesmo pedido novamente e solicitava uma segunda confirmação. A barra visual
também era criada apenas para risco `external`; pedidos de risco `workspace`
ficavam pendentes sem os botões de autorização.

A correção adiciona formas naturais estritamente ancoradas (`eu confirmo`,
`eu autorizo`, `pode prosseguir`, `pode continuar` e `pode executar`) e mantém o
bloqueio de qualquer confirmação sem pedido pendente. Toda delegação que exigir
confirmação agora cria a barra visual; o rótulo diferencia ação externa de
delegação comum ao Codex. O comando guardado continua sendo consumido uma única
vez e a confirmação nunca é encaminhada como comando.

O tablet e o celular alcançavam o HTML do túnel, mas não carregavam os recursos
seguintes com a autenticação HTTP nativa. O gateway temporário passou a fornecer
uma página de login HTML própria, compatível com navegador móvel, e cria uma
sessão `Secure`, `HttpOnly`, `SameSite=Lax` por quatro horas. A API continua
retornando HTTP 401 sem sessão e as credenciais não são entregues ao backend.

Validações executadas:

- autorização/delegação frontend: 16 testes, PASS;
- TypeScript e build Vite de produção: PASS;
- `git diff --check`: PASS;
- gateway temporário: `py_compile`, Ruff format e Ruff check, PASS;
- simulação pública com User-Agent Android: página de login exibida, login
  concluído em `/jarvis`, novo bundle carregado e catálogo HTTP 200;
- catálogo remoto após login: 11 projetos e 17 conversas;
- API remota sem sessão: HTTP 401;
- backend, gateway e Quick Tunnel permaneceram ativos.

Gate visual/voz: PENDENTE de César recarregar a página, confirmar que a barra
aparece e provar uma delegação dizendo `Eu confirmo`. O Quick Tunnel permanece
temporário e não constitui deploy de produção.

Follow-up (2026-08-06 04:25:13 -03:00): o novo log sanitizado provou que o
Chrome móvel de César enviou credenciais válidas e o gateway aceitou o login às
04:24:50, mas o navegador não avançou depois do redirecionamento HTTP 303. O
POST válido agora retorna primeiro uma página HTTP 200 com `Set-Cookie`, a
mensagem visível `ACESSO AUTORIZADO`, redirecionamento por HTML e um botão
`CONTINUAR` como fallback. Uma simulação pública Android confirmou: login
aceito, um cookie de sessão criado, `/jarvis` HTTP 200, bundle atual carregado e
catálogo HTTP 200. Um login inválido mostrou erro visível e não criou cookie.
O log registra apenas resultado, IP e User-Agent; usuário e senha não são
registrados.

Second follow-up (2026-08-06 04:32:14 -03:00): o Chrome móvel exibiu
`ACESSO AUTORIZADO`, mas não saiu dessa página nem pelo botão. O gateway agora
emite, somente depois de credenciais válidas, um código aleatório de continuação
com validade de cinco minutos e vinculado ao IP e User-Agent do dispositivo. O
botão abre uma rota GET intermediária que grava novamente o cookie em resposta
HTTP 200 e oferece três mecanismos de navegação: JavaScript, meta refresh e link
manual. O código nunca é registrado e não aceita outro dispositivo.

A prova pública descartou propositalmente todo cookie recebido no POST, abriu a
continuação em um cliente Android novo com a mesma identidade e confirmou:
continuação HTTP 200, página `SESSÃO ATIVA`, um cookie criado pelo GET,
`/jarvis` HTTP 200 e bundle atual carregado. O log sanitizado registrou somente
`accepted` e `continued`.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais sem commit ou
push. Dependências, modelos, migration, GitHub e credenciais: não alterados.

## Confirmação fiel, logs consultáveis e memória entre sessões (2026-08-06 02:42:05 -03:00)

O uso por voz confirmou dois defeitos posteriores ao endurecimento anterior:

- quando Jarvis perguntava se podia enviar um comando, uma resposta curta como
  `Sim`, `Sim, eu confirmo` ou `Sí` podia ser encaminhada ao Codex no lugar do
  pedido original;
- a linha operacional existia apenas no estado React da aba atual. Uma nova
  sessão Live não podia consultar de forma confiável seus próprios eventos nem
  as mensagens públicas enviadas e respondidas na conversa Codex selecionada.

A causa da primeira falha era dupla. O autorizador podia construir o pedido
pendente usando a fala de confirmação atual, e o cliente tratava transcrições
incrementais como se a API fornecesse um marcador `finished`. A referência da
Gemini Live fornece texto de transcrição, mas não esse marcador; além disso, a
ordem da transcrição em relação às demais mensagens do servidor não é garantida.

A correção implementada mantém o transporte único já usado pelo Chat e adiciona:

- intenção pendente determinística, com ID, comando exato, expiração e consumo
  único depois da confirmação;
- bloqueio explícito de confirmação sem pedido pendente; `sim`, `confirmo` e
  equivalentes nunca são convertidos em um comando novo;
- extração fiel do conteúdo entre aspas em pedidos como
  `Manda pro Codex assim: "Jarvis funcionou."`;
- montagem dos fragmentos de transcrição por janela de inatividade e espera de
  fragmentos tardios antes de processar uma chamada de ferramenta;
- instrução Live para propor primeiro a ferramenta, pedir confirmação somente
  quando o gate responder `confirmation_required` e repetir o mesmo comando;
- ferramentas somente leitura `read_jarvis_operational_log` e
  `read_codex_recent_history`, respondidas pela própria camada OpenJarvis sem
  criar outro turno Codex;
- ledger SQLite idempotente por `thread_id`, sanitizado no servidor e limitado
  a 500 eventos por conversa;
- carregamento de memória operacional e histórico Codex sanitizado no início
  de cada nova sessão de voz.

O arquivo administrado de memória operacional fica em
`D:\dev\runtime\openjarvis\jarvis\operational-events.sqlite3`. Chaves e valores
com formato de credencial são removidos antes da persistência e antes de o
contexto ser entregue ao Gemini.

Validações executadas:

- suíte frontend completa: 42 testes em 8 arquivos, PASS;
- testes Python ampliados de Gemini, catálogo Codex e agente: 46 PASS;
- Ruff check e format check nos arquivos Python afetados: PASS;
- TypeScript e build Vite de produção: PASS;
- launcher local em modo de validação e reinício do backend: PASS;
- backend `8127`: saúde `ok` após o reinício;
- persistência real: o evento de validação foi gravado idempotentemente,
  o backend foi reiniciado e a consulta encontrou exatamente uma cópia com o
  mesmo ID e conteúdo.

Gate visual/voz desta correção: PENDENTE. O canal de automação do navegador
interno não está disponível para esta execução. A tarefa somente poderá ser
declarada concluída depois de a aba `/jarvis` provar visualmente que o pedido
original, e não a confirmação, chega ao Codex; que Jarvis consegue relatar a
última mensagem e resposta; e que isso permanece após encerrar e abrir uma nova
sessão Live.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais, sem commit nem
push. Dependências, modelos, deploy, migration, GitHub e valores de credenciais:
não alterados.
## Correção da divergência Gmail/Data Source — 2026-08-07

Investigação end-to-end confirmou que o erro `Gmail não está conectado` era
produzido antes de qualquer chamada à API do Gmail: o endpoint do Jarvis
instanciava sempre `GmailConnector` (OAuth), enquanto o Data Source sincronizado
pela interface era `gmail_imap` (IMAP com app password). O índice histórico de
e-mails não alterava o estado de conexão do conector OAuth.

Correção aplicada:

- resolução do conector ativo no backend, preferindo OAuth conectado e usando
  `gmail_imap` quando ele é o Data Source conectado;
- busca com sintaxe segura `from:`, `subject:`, `is:unread` e texto livre,
  limitada a 25 resultados, sem expor credenciais;
- leitura por UID IMAP ou cabeçalho `Message-ID`, com conteúdo
  limitado e resposta sanitizada;
- `/v1/jarvis/sources/gmail/status` agora informa `connector_id`, modo e
  capacidades efetivas;
- ações de mutação com IMAP ativo retornam `501` orientando conectar OAuth,
  em vez de produzir `Gmail não está conectado` ou simular sucesso.

Validação local: 8 testes direcionados do conector IMAP e do roteador passaram;
`compileall` passou. Os testes unitários usam mocks; um smoke live limitado da
busca `from:Marta inova-ts.com.br` retornou HTTP 200 e zero resultados, sem
imprimir corpo de mensagem. Nenhum e-mail foi enviado, arquivado ou apagado.

Branch e SHA permanecem `codex/real-codex-runtime` e
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais não foram
commitadas nem enviadas. Deploy, migration, GitHub e credenciais: não
alterados.
## Correção do travamento de inicialização e resposta final do Codex — 2026-08-07

Dois defeitos adicionais foram identificados no uso real do Jarvis:

- `GeminiLiveSession.connect()` aguardava indefinidamente o evento
  `setupComplete`; agora há timeout de 15 segundos, encerramento limpo do
  WebSocket e estado de erro visível;
- o dispatcher compartilhado usava `Comando concluído pelo Codex.` quando o
  stream SSE compatível terminava sem delta de texto. Agora ele consulta o
  histórico público da conversa selecionada e recupera a última resposta real
  do assistente, preservando relatórios completos. Sem histórico disponível,
  a operação falha explicitamente.

Validação: 12 testes frontend direcionados, TypeScript, build Vite, Ruff e
launcher local aprovados. Backend e frontend reiniciados em `127.0.0.1`; o
backend respondeu HTTP 200. Nenhum deploy, migration, GitHub ou credencial foi
alterado.

## Sources WhatsApp Baileys e resposta canônica do Codex — 2026-08-07

Foi corrigida a divergência que deixava o WhatsApp visível somente como Meta
Cloud API. O card de WhatsApp agora contém a seção separada `Baileys · QR
Code`, com botão explícito de início, geração local do QR, instruções de
leitura e estados `desconectado`, `conectando`, `conectado` e `erro`. A opção
não substitui nem altera o fluxo Meta.

O bridge Baileys estava somente em TypeScript e não tinha `dist/bridge.js` no
checkout local. O lifecycle agora copia também a fonte/tsconfig para o runtime
isolado e, somente quando o usuário inicia a conexão, instala as dependências
do bridge e compila o artefato. A enumeração de desconexão foi alinhada à
versão atual do Baileys (`connectionClosed`), permitindo a compilação real.

Também foi corrigida a resposta do Codex no caminho Jarvis: o resultado agora
é gravado integralmente no log operacional, sem `slice(0, 240)`, e a resposta
canônica do histórico é recuperada por quatro tentativas curtas quando o SSE
entrega apenas uma confirmação de transporte. O status da ferramenta
`whatsapp_status` deixou de sobrescrever o estado real com `complete`.

Arquivos principais:

- `frontend/src/components/setup/WhatsAppBaileysPanel.tsx`;
- `frontend/src/pages/DataSourcesPage.tsx`;
- `frontend/src/lib/codex-command.ts` e `frontend/src/lib/jarvis-context.ts`;
- `frontend/src/pages/JarvisPage.tsx`;
- `src/openjarvis/channels/whatsapp_baileys.py` e `.../bridge.ts`;
- `src/openjarvis/server/jarvis_operational_log.py`.

Validação executada: 53 testes frontend em 8 arquivos (incluindo 11 casos
direcionados); `npx tsc --noEmit`;
compilação TypeScript do bridge Baileys; testes Python direcionados do canal e
roteador; Ruff; build Vite e `git diff --check`. A instalação do frontend
reportou 30 avisos de auditoria e a instalação do bridge 6; nenhum `npm audit
fix` foi executado. Não houve login/QR real, envio de mensagem WhatsApp,
deploy, migration, alteração de GitHub ou alteração de credenciais.

## Sources: card visível do WhatsApp Baileys — 2026-08-07

Investigação confirmou que o endpoint `/v1/connectors` retorna o conector
indexável `whatsapp`, mas não retorna `whatsapp_baileys`: Baileys é um canal
Jarvis separado, com endpoints próprios para status, inicialização e QR. A
implementação anterior só colocava o QR dentro do card Meta e, por isso, não
era uma segunda opção evidente na lista.

Correção aplicada: `SOURCE_CATALOG` agora possui o item `whatsapp_baileys` e
`DataSourcesPage` injeta um card local desse ID quando o backend não o lista.
O card permanece disponível mesmo com Meta conectado e usa o mesmo painel QR
com polling de status. O bundle estático foi regenerado; a verificação do
artefato confirmou o rótulo `WhatsApp Baileys`, QR e ausência do texto antigo
de confirmação genérica.

Evolution API permanece fora da interface porque não há conector, autenticação
ou contrato de backend implementado para ela. Não foi criada uma opção falsa.

Validação: TypeScript, build Vite, 53 testes frontend e HTTP 200 em `8127`
(`/health`) e `5173` (`/`). Nenhuma sessão WhatsApp foi iniciada e nenhum QR
real foi lido durante a validação.
## Correção do 500 ao gerar QR Baileys — 2026-08-07

O smoke real do botão revelou que o processo do backend não conseguia
resolver `npm` no `PATH` reduzido do serviço Windows. Essa exceção ocorria
durante a preparação do bridge e resultava em resposta HTTP 500 vazia. O
canal agora resolve `node`/`npm` pelos executáveis instalados ao lado do Node,
converte falhas de preparação em estado de erro controlado e consome o stderr
do bridge. O bridge também busca a revisão atual do WhatsApp Web e declara
explicitamente o navegador OpenJarvis.

Validação real após reiniciar somente o backend local: `POST
/v1/jarvis/sources/whatsapp/start` retornou HTTP 200 e, em dois segundos,
`GET /v1/jarvis/sources/whatsapp/qr` retornou `available: true` com payload de
237 caracteres. O QR não foi escaneado e nenhuma mensagem foi enviada.
# WhatsApp namespace implementation note (2026-08-07)

The WhatsApp work is organized by namespace and responsibility. The
`channels/whatsapp/` namespace exposes the persistent domain store, while the
Baileys adapter owns lifecycle and the bridge separates event normalization
from command execution in `events.ts` and `commands.ts`.

The local store indexes contacts, chats and messages idempotently. The API
provides bounded contact/chat search, history, summaries, older-history fetch,
name resolution and approved mark-read. Structured approved actions cover
replies, reactions, polls, HTTPS media, chat organization, groups, privacy,
profile status and status broadcast. Voice calls remain separate until a
reviewed media/WebRTC adapter exists.

Gemini Live now exposes the conversation tools to Jarvis: contact/chat search,
bounded message reading, conversation context for summaries and the structured
action contract. The existing Meta Cloud API is preserved as
`channels/whatsapp/cloud.py`; Baileys remains a separate channel and auth
boundary.

Validation: 36 focused Python tests and 792 broader channel/server tests (2
skips) passed; Ruff and the Baileys TypeScript build passed. No QR scan, live send, group/privacy/profile mutation or broadcast was
performed. Deploy, migration, GitHub and credentials were not changed.

## Frontend update safety during Jarvis use - 2026-08-07

The PWA update policy was changed from automatic activation to prompt mode.
Workbox also explicitly keeps `skipWaiting` and `clientsClaim` disabled. A new
frontend bundle therefore waits for a deliberate navigation or reload instead
of replacing the active page during login, typing, or voice use.

Process audit: one OpenJarvis server owns the `8127` listener. The paired
Python processes are the expected parent/child reload arrangement; no second
Manus/OpenJarvis listener was found. Existing browser tabs may need one
deliberate reload to adopt the corrected service worker.

## Jarvis tool routing and WhatsApp recipient safety - 2026-08-08

## Baseline da correcao Jarvis/Bridge/Codex - 2026-08-08

### Gate da Fase 0

- Branch: `codex/real-codex-runtime`.
- SHA observado antes das novas correcoes: `927c2ef5fc077bc591e910a6307579fe43d4620a`.
- Worktree: unico checkout em `D:/dev/workspaces/openjarvis`; alteracoes
  anteriores permanecem preservadas e nao foram limpas.
- Processos/portas observados: backend Python em `127.0.0.1:8127`, Codex
  app-server em `127.0.0.1:8131` e o processo `cloudflared` ja existente. Nao
  foi iniciado nem substituido processo externo nesta auditoria.
- Nenhum arquivo desconhecido foi sobrescrito. Os arquivos novos desta tarefa
  foram separados por responsabilidade e serao validados antes de qualquer
  reinicio local.

### Matriz factual

| Sintoma | Evidencia confrontada | Causa operacional | Correcao desta execucao |
|---|---|---|---|
| Fragmentos de voz viram pedidos | eventos parciais no SQLite e no bridge | autorizacao durante transcricao incompleta | `TurnAssembler` e geracao de sessao |
| callbacks apos Encerrar | eventos posteriores ao fechamento da sessao | callback nao invalidado antes do fechamento | invalidacao por `session_generation` |
| confirmacao enviada como comando | evento Codex sem aprovacao anterior | autorizacao dependia do prompt/modelo | maquina de aprovacao obrigatoria |
| Jarvis envia WhatsApp para Codex | pedido de Klaus roteado incorretamente | catalogo/politica nao era autoridade unica | catalogo de ferramentas e validacao de rota |
| travamento em Codex | `thread/resume` e Desktop refresh expirados | preflight/retry e busy sem estado publico | resume controlado, busy imediato e erros estaveis |
| placeholder no historico | `comando concluido pelo Codex` no frontend | resposta final nao era evento canonico | dispatcher unico e resposta do historico publico |
| Baileys aparece conectado | `401`, `conflict`, `Logged out` no bridge | status generico perdia a razao tecnica | snapshot explicito de QR/conflito/logout |

O banco operacional foi lido em modo de auditoria: integridade valida, sem IDs
duplicados e retencao limitada a 500 eventos por thread. Logs foram usados
somente como evidencia; nenhum segredo, conteudo privado ou token foi copiado
para esta documentacao.

Gate de saida da Fase 0: aprovado para alteracao controlada. Deploy, migration,
GitHub e credenciais: nao alterados.

Gemini Live now receives a destination policy that separates Codex execution
from Gmail and WhatsApp Data Source actions. A Codex function call is blocked
unless the user's recorded request explicitly routes to Codex.

WhatsApp sending by contact name performs a read-only lookup before the
confirmation gate. The action is stopped for no match, ambiguous matches,
empty content, or simultaneous JID and name. Only the uniquely resolved JID
and original message text are retained in the approved action.

Validation: 58 frontend tests, 11 source-router tests, TypeScript build and
`git diff --check` passed. No WhatsApp message was sent during validation.

## Investigação de delegação incorreta e timeout do Codex - 2026-08-08

O teste de delegação por voz confirmou três pontos independentes. Delegações
Codex de baixo risco eram liberadas pelo frontend sem aprovação; agora toda
delegação Codex exige aprovação explícita. Em pedidos sem payload entre aspas,
o autorizador também podia conservar a fala conversacional em vez do comando
estruturado produzido pela ferramenta; a aprovação agora retém o payload
estruturado e nunca usa `sim` ou `confirmo` como comando.

O envio de prova ao thread selecionado expirou em `thread/resume`
(`request 311 timed out`). O catálogo e o histórico do thread responderam
HTTP 200, então a falha está no preflight de retomada do app-server, não na
seleção visual do projeto. O comando de investigação foi enviado pela ponte
nativa do Codex sem executar ação externa; o aceite visual do retorno continua
pendente.

Validação desta correção: 19 testes do autorizador frontend aprovados. Deploy,
migration, GitHub e credenciais não foram alterados.

## Hardening end-to-end Jarvis, Bridge e Codex — 2026-08-08 02:44:14 -03:00

### Contrato operacional

1. O `TurnAssembler` consolida transcrições e libera somente um turno final.
2. Cada callback valida `session_generation`; eventos antigos são descartados
   antes de alterar UI, estado ou ferramenta.
3. O catálogo determina o namespace: Gmail, WhatsApp ou Codex. Codex exige que
   Cesar tenha indicado explicitamente esse destino.
4. Para qualquer mutação ou delegação Codex, a chamada Gemini original fica
   pendente no `JarvisApprovalCoordinator`.
5. A interface mostra destino, projeto, conversa, comando exato e risco. Somente
   `Autorizar e executar` ou `Negar` resolve a pendência.
6. Gemini não pede confirmação por voz e recebe na mesma chamada o resultado do
   botão. `Sim` e `confirmo` falados não autorizam nem viram comando.
7. O dispatcher usa `request_id` e idempotência por conversa; Codex ocupado é
   recusado imediatamente e não há fila ou retry oculto.
8. A resposta final vem do histórico público canônico do thread e é publicada
   no Jarvis e no Chat sob a mesma correlação.

### Códigos públicos do transporte Codex

- `CODEX_BUSY`
- `CODEX_THREAD_NOT_FOUND`
- `CODEX_THREAD_RESUME_TIMEOUT`
- `CODEX_DISPATCH_TIMEOUT`
- `CODEX_PROJECT_INVALID`
- `CODEX_SESSION_CLOSED`
- `CODEX_DUPLICATE_REQUEST`

O timeout de dispatch tenta interromper somente o `turn_id` exato que foi
iniciado. Falha opcional ao atualizar visualmente o Desktop não substitui nem
apaga uma resposta já concluída no histórico.

### Diagnóstico seguro

Para rastrear uma operação, correlacionar `session_id`, `turn_id`, `request_id`,
`function_call_id`, `conversation_id` e `codex_thread_id`. Os eventos registram
tipo, decisão, hash e tamanho; comandos, respostas privadas, tokens e conteúdo
de Data Sources não entram no log operacional. A resposta completa permanece
no Chat e no histórico canônico autorizado.

### Baileys

O snapshot público distingue `disconnected`, `connecting`, `qr_required`,
`connected`, `conflict`, `logged_out` e `failed`, registra a última transição e
expõe `send_available` somente quando o processo do bridge está vivo. 401,
conflito ou logout nunca são convertidos em conectado.

### Gates executados

- 71 testes frontend em 13 arquivos: aprovados.
- 230 testes Python e 4 subtestes: aprovados; 31 avisos de depreciação.
- `npm run build` no frontend: aprovado; somente avisos conhecidos de chunk.
- `npm run build` no bridge Baileys: aprovado.
- Ruff check e Ruff format check: aprovados.
- `git diff --check`: aprovado.
- frontend `5173`, backend `8127` e app-server `8131`: HTTP 200 após reinício
  somente dos serviços locais necessários.

Gate ainda aberto: validação visual no navegador interno do Codex. A interface
não será declarada concluída enquanto esse smoke não confirmar o painel de
aprovação e o resultado aceito/negado. O mecanismo de controle do navegador não
estava disponível nesta sessão reiniciada; nenhum teste headless foi usado como
substituto.

Branch: `codex/real-codex-runtime`. HEAD:
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Arquivos permanecem locais e sem
commit/push. Deploy, migration, credenciais e GitHub: não alterados. Nenhuma
mensagem WhatsApp, e-mail, QR ou mutação externa foi executada.

## Smoke e recuperação do QR Baileys — 2026-08-08 03:34:00 -03:00

### Diagnóstico

O endpoint já distinguia `logged_out`, mas o painel antigo aceitava somente os
quatro estados genéricos. Como consequência, `logged_out` era tratado como
estado não terminal e a interface permanecia em polling até o timeout. A sessão
legacy deslogada estava em C:, enquanto a fundação do projeto exige artefatos
gerenciados em D:. Além disso, a ação visual mantinha “Aguardando conexão”
mesmo depois de renderizar o QR.

### Contrato operacional corrigido

1. `OPENJARVIS_RUNTIME_ROOT` define
   `D:\dev\runtime\openjarvis\whatsapp_baileys_bridge`.
2. O bridge pré-compilado e os módulos já existentes no workspace são
   reutilizados; o clique de QR não executa `npm install`.
3. `POST /v1/jarvis/sources/whatsapp/reset` exige `{ "confirm": true }`, remove
   somente a autenticação contida no runtime gerenciado e recusa caminho
   externo.
4. `conflict`, `logged_out`, `failed` e `error` encerram o polling e exibem uma
   ação específica.
5. `qr_required` mantém a sessão ativa, renderiza o código e mostra “QR pronto
   — escaneie no WhatsApp”.
6. O bridge encerra o processo após logout definitivo, impedindo que um PID
   obsoleto pareça conectado.

### Evidência

- serviços ativos: frontend `5173`, backend `8127`, Codex app-server `8131` e
  gateway do túnel `8140`;
- clique real no painel gerou `qr_required` e renderizou o QR em cerca de
  4,2 segundos, com instruções visíveis e sem erro de console;
- processo Node usa o bridge em
  `D:\dev\workspaces\openjarvis\src\openjarvis\channels\whatsapp_baileys_bridge\dist\bridge.js`;
- autenticação nova usa
  `D:\dev\runtime\openjarvis\whatsapp_baileys_bridge\auth`;
- sessão legacy em C: preservada e não utilizada;
- 75 testes frontend, 44 testes Python direcionados, TypeScript, Vite, bridge
  Baileys, Ruff check e Ruff format check: aprovados.

O QR foi gerado somente para prova visual; não foi escaneado e nenhuma mensagem
foi enviada. O conteúdo do QR não foi incluído nesta documentação. O túnel não
foi reiniciado. Deploy, migration, credenciais e GitHub: não alterados.

## Renovação de QR sem erro residual — 2026-08-08 03:54:42 -03:00

### Regra de transição

- fechamentos transitórios (`408`, conexão fechada/perdida, restart solicitado
  ou serviço temporariamente indisponível) publicam `connecting`, invalidam a
  geração antiga do socket e reconectam sem evento de erro;
- `connecting` limpa QR e erro anteriores;
- o próximo evento `qr` publica `qr_required` com `last_error=null`;
- logout, conexão substituída e falha terminal publicam `logged_out`,
  `conflict` ou `failed`, removem o QR e encerram o bridge;
- callbacks de gerações antigas não podem alterar o estado atual.
- o QR é enviado somente no evento estruturado para a API protegida e nunca é
  desenhado no `stderr` ou copiado para o log operacional.

### Diagnóstico

Se a interface exibir QR e erro ao mesmo tempo, verificar
`GET /v1/jarvis/sources/whatsapp/status`. O contrato aprovado exige:

```json
{
  "status": "qr_required",
  "reason": "qr_required",
  "last_error": null,
  "qr_available": true,
  "send_available": false
}
```

Após reinício apenas dos serviços locais, esse contrato foi observado em seis
amostras durante 50 segundos. O bridge, frontend `5173`, backend `8127`, Codex
app-server `8131` e gateway `8140` permaneceram ativos; o túnel Cloudflare não
foi reiniciado.

Validação: 47 testes Python direcionados, 75 testes frontend, builds
TypeScript/Vite/bridge, Ruff e `git diff --check` aprovados. A suíte Python
global encontrou o extra opcional `polars` ausente e excedeu cinco minutos ao
ser repetida sem esse teste; dependências não foram instaladas. O QR não foi
escaneado e nenhuma mensagem foi enviada. Uma geração adicional confirmou que
o trecho novo do log não contém glifos do QR. Seis capturas antigas de smoke,
com QRs já expirados, não puderam ser apagadas porque a política do host recusou
a remoção exata; a sessão atual não foi capturada. Deploy, migration,
credenciais e GitHub: não alterados.

## Delegação explícita, timeout de status e bridge UTF-8 — 2026-08-08 04:47:20 -03:00

### Correlação do pedido Codex

O request observado como timeout foi `request 103`. Ele não chegou a
`turn/start`: expirou no busy preflight porque `thread/read` solicitava os 177
turnos da conversa. A auditoria direta do protocolo mediu aproximadamente
4,575 s com `includeTurns=true` e 0,023 s com `includeTurns=false`.

Procedimento de diagnóstico atualizado:

1. Correlacionar `session_id`, `turn_id`, `request_id`, `function_call_id`,
   `conversation_id` e `codex_thread_id`.
2. Confirmar `confirmation_required` e a decisão do botão para o mesmo
   `request_id`; fala de confirmação nunca é autoridade.
3. Consultar o status do thread sem histórico.
4. Se o status for `active`, retornar `CODEX_BUSY` sem fila ou retry.
5. Se a leitura de status expirar, retornar `CODEX_THREAD_STATUS_TIMEOUT` sem
   iniciar turno.
6. Tratar evento SSE `error` como falha. O prefixo legado
   `Error during generation:` também deve ser rejeitado, nunca exibido como
   resposta concluída.

O autorizador não usa mais distância máxima entre verbo e destino. Ele exige
uma ação explícita e o destino Codex na fala consolidada. Fragmentos
`finished=true` do Gemini permanecem parciais até o limite oficial do turno.

### Diagnóstico do WhatsApp depois do QR

O bridge produz JSON UTF-8. Em Windows, nunca iniciar o `Popen` em modo texto
sem `encoding="utf-8"`; o locale `cp1252` pode falhar assim que contatos ou
mensagens com caracteres não representáveis forem sincronizados. Uma falha de
normalização/store registra somente tipo e classe do erro, preserva o leitor e
não muda a conexão. Eventos `error` com `scope=operation|protocol` alimentam
`last_operation_error`; apenas `scope=connection` pode publicar estado
terminal.

Antes de reiniciar um bridge que aparenta estar conectado, verificar sem ler o
conteúdo secreto:

```powershell
Get-Item D:\dev\runtime\openjarvis\whatsapp_baileys_bridge\auth\creds.json |
  Select-Object Length, LastWriteTime
```

Tamanho zero significa que o processo pode estar conectado somente com estado
em memória. O bridge atual usa escrita atômica para `creds.json`, mantém
`creds.backup.json` validado e restaura o backup quando o primário está vazio
ou inválido. Se não houver snapshot válido e existirem artefatos residuais, o
bridge falha fechado como `AUTH_INCONSISTENT`; somente uma pasta realmente
vazia pode iniciar um novo pareamento. A geração antiga deve ser preservada em
quarentena por ação explícita antes de gerar outro QR.

### Gate desta execução

- 81 testes frontend: aprovados;
- 150 testes Python e 4 subtestes: aprovados;
- 3 testes Node de autenticação resiliente: aprovados;
- frontend e bridge builds: aprovados;
- Ruff, formatação e `git diff --check`: aprovados;
- backend novo em `8127`: HTTP 200;
- WhatsApp atual: `qr_required`, `qr_available=true`, `last_error=null`, bridge
  Node vivo;
- nenhuma mensagem externa ou turno Codex foi disparado.

Pendente: reler uma vez o QR, confirmar `connected` após reinício e executar o
smoke visual no navegador interno quando seu controlador estiver disponível.
Branch `codex/real-codex-runtime`, HEAD
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Deploy, migration, GitHub e
credenciais não foram alterados nesta execução.

## Frescor do QR e autenticação inconsistente — 2026-08-08 11:18:10 -03:00

### Contrato operacional

Cada evento QR possui dois metadados públicos não secretos:

- `qr_generation`: contador monotônico durante a vida do canal;
- `qr_issued_at`: instante UTC da emissão daquela geração.

`GET /v1/jarvis/sources/whatsapp/qr` entrega payload, geração e estado em uma
única seção crítica. Os endpoints GET de QR e status devem responder sempre:

```text
Cache-Control: no-store, private, max-age=0
Pragma: no-cache
Expires: 0
```

O cliente também usa `cache: no-store`. O monitor começa na montagem da página
e continua somente em `connecting` ou `qr_required`; ele para em conexão,
falha terminal ou desmontagem. Uma nova geração limpa a imagem anterior antes
da conversão para Data URL. Se a leitura da API falhar, a imagem atual é
removida e o botão volta a permitir uma tentativa explícita.

### Recuperação segura

Uma credencial primária inválida é restaurada apenas quando existe backup
válido. Sem primário ou backup válidos:

1. diretório vazio significa primeira autenticação e pode gerar QR;
2. qualquer artefato existente significa `AUTH_INCONSISTENT`;
3. nenhum arquivo é apagado ou reutilizado;
4. o botão explícito de recuperação move exatamente o diretório gerenciado
   `runtime/whatsapp_baileys_bridge/auth` para `auth-quarantine/auth-<UTC>`;
5. caminhos personalizados, externos ou o próprio runtime são recusados.

No smoke desta execução, 839 itens antigos foram preservados em
`auth-quarantine/auth-20260808T141449517653Z`. O conteúdo dos arquivos não foi
lido. A pasta limpa gerou QR e o endpoint avançou de geração 2 para 3 sem
cache. Nenhum QR bruto foi escrito em log; a comparação utilizou somente um
prefixo SHA-256 de 12 caracteres.

### Gate

- 810 testes Python aprovados, 2 ignorados e 1 aviso de depreciação;
- 87 testes frontend aprovados;
- 4 testes Node de persistência/recuperação aprovados;
- builds frontend e bridge aprovados;
- Ruff check e format check aprovados;
- `git diff --check` aprovado;
- backend reiniciado; frontend, app-server e túnel preservados;
- nenhuma mensagem WhatsApp foi enviada.

O controlador visual do Chrome não foi exposto a esta sessão do Codex. A
rotação real e o monitor foram validados separadamente, mas a observação da
troca da imagem no navegador sem recarga permanece como gate manual.

Branch `codex/real-codex-runtime`; HEAD
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Deploy, migration e GitHub: não
alterados. Estado de autenticação: alterado somente para preservar a geração
inválida em quarentena e iniciar uma pasta vazia; demais credenciais: não.

## Contatos, reação e roteamento executor/assunto — 2026-08-08 13:08:06 -03:00

### Contrato de identidade WhatsApp

O runtime não infere mais que todo destinatário é `@s.whatsapp.net`. A
identidade é classificada explicitamente como PN, LID, grupo ou status. Contatos
podem carregar aliases PN/LID e um telefone normalizado; chats são relacionados
por esses aliases. A busca por nome consulta o índice completo, aplica ranking
determinístico e limita somente o resultado final. Uma busca numérica nunca
considera JIDs de grupo.

O banco canônico do launcher é:

```text
D:\dev\runtime\openjarvis\whatsapp\whatsapp_baileys.db
```

A migração preservadora usa `scripts/workspace/migrate-whatsapp-store.py`,
recusa sobrescrita, executa backup online do SQLite, compara contagens, exige
`PRAGMA integrity_check=ok` e grava hashes no manifesto. O legado em C: não deve
ser apagado automaticamente. O manifesto deste gate está em
`D:\dev\runtime\openjarvis\whatsapp\migration-2026-08-08.json`.

### Contrato de reação

1. A leitura de histórico expõe uma `message_ref` opaca.
2. `POST /v1/jarvis/sources/whatsapp/reaction/preview` resolve a referência e
   devolve somente metadados limitados para a aprovação visual.
3. O botão de aprovação emite token de uso único para
   `whatsapp_react_message`.
4. `POST /v1/jarvis/sources/whatsapp/reaction` resolve novamente a chave no
   servidor e envia a chave completa ao bridge.
5. O bridge responde com o mesmo `command_id`; sucesso, falha e timeout são
   estados distintos.
6. Reações no endpoint genérico e chaves incompletas de grupo falham fechado.

O modelo nunca recebe autorização para inventar `remoteJid`, participante ou
`fromMe`, e o preview não executa mutação.

### Matriz de roteamento

| Pedido | Executor | Resultado |
| --- | --- | --- |
| Relate ao Codex que a busca WhatsApp falhou | Codex | proposta de delegação e aprovação visual |
| Investigue no Codex o erro de reação | Codex | proposta de delegação e aprovação visual |
| Reaja a esta mensagem no WhatsApp | WhatsApp | preview e aprovação visual |
| Envie mensagem para um contato | WhatsApp | resolução por nome e aprovação visual |
| Pedido de mutação ambíguo | nenhum | esclarecimento; nenhuma execução |

Essa decisão é aplicada no classificador e repetida pelo route guard na hora do
dispatch. Palavras como WhatsApp ou Gmail descrevendo o assunto não podem
sobrescrever um executor Codex explicitamente solicitado.

### Smoke seguro e diagnóstico

Após reiniciar somente o backend, `GET /health` retornou HTTP 200 e o bridge
evoluiu de `connecting` para `connected`, com `send_available=true` e sem erro.
A busca exata por `Klaus Consultor` encontrou um contato. Um chat pessoal LID
recente retornou cinco mensagens, todas com referências opacas; o preview de
reação foi resolvido, e a tentativa de usar a operação genérica `reaction` foi
recusada com HTTP 400. Nenhuma mensagem ou reação real foi enviada.

Para diagnóstico sem conteúdo privado, correlacionar `command_id`, estado do
bridge e `message_ref`; não registrar texto, JID completo, token de aprovação
ou chave Baileys. Confirmar atividade do banco em D: pelo arquivo WAL e conferir
que o banco legado em C: não teve seu horário alterado.

Gate: 84 testes Python, 93 frontend e 7 Node aprovados; TypeScript/Vite, bridge,
Ruff, formatação e `git diff --check` aprovados. A validação visual no navegador
interno permanece pendente por indisponibilidade do controlador nesta sessão.

Branch `codex/real-codex-runtime`; HEAD
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Deploy, migration de plataforma,
GitHub e credenciais: não alterados. Migração local do índice WhatsApp:
realizada com backup, hashes e manifesto; fonte preservada.

## Recuperação do timeout de inicialização — 2026-08-08 15:58:34 -03:00

### Causa e contrato corrigido

A tela Jarvis reunia token Gemini, histórico integral da thread Codex e eventos
operacionais em um único `Promise.all` de 30 segundos. A thread selecionada
produzia aproximadamente 316 KB e levava cerca de 5,5 segundos no app-server;
consumidores simultâneos repetiam a mesma leitura. Ao mesmo tempo, rotas
declaradas assíncronas executavam SQLite e rede de forma síncrona, impedindo o
backend de responder mesmo a `/health`.

O contrato operacional passou a ser:

1. o token Gemini é o único requisito para iniciar a voz;
2. histórico e eventos têm quatro segundos, cancelamento e fallback local;
3. leituras integrais simultâneas da mesma thread compartilham uma única tarefa
   e cache curto;
4. timeout ou desconexão de um consumidor não cancela a leitura compartilhada;
5. rotas de conectores/Gmail e persistência de logs não bloqueiam o loop
   principal;
6. polls de Data Sources têm deadline, exclusão de sobreposição e cancelamento
   no unmount;
7. o gateway aplica limites de conexão e timeouts de upstream, retornando 504
   ou 502 em vez de manter requisições órfãs.

### Diagnóstico rápido

- Jarvis parado em `Inicializando`: verificar primeiro
  `POST /v1/jarvis/live/token`; histórico não deve impedir a sessão.
- `/health` lento durante Sources: verificar chamadas bloqueantes e polls
  concorrentes; não aumentar o timeout como correção.
- WhatsApp sem QR: consultar o status. `connected` com
  `send_available=true` significa sessão pronta e QR desnecessário.
- Gerar QR para outra conta: executar somente o fluxo explícito de
  reset/repareamento, preservando a autenticação anterior; abrir a página não
  autoriza essa mutação.

### Gate executado

- César confirmou no navegador que o Jarvis voltou a funcionar;
- 119 testes Python, 4 subtestes, 97 testes frontend e 7 testes Node do bridge:
  aprovados;
- build de produção TypeScript/Vite, Ruff check/format e
  `git diff --check`: aprovados;
- seis leituras concorrentes da mesma thread: cerca de 5,4–5,6 segundos, sem
  multiplicar leituras do app-server;
- oito health checks durante a carga: cerca de 0,30–0,39 segundo;
- token Live: HTTP 200 em cerca de 0,94 segundo;
- backend `8127`, app-server `8131`, frontend `5173` e gateway `8140`: ativos;
- probes autenticados no gateway local e no túnel: HTTP 200;
- WhatsApp: `connected`, `send_available=true`, `last_error=null`, QR ausente
  por contrato.

Branch `codex/real-codex-runtime`; HEAD
`927c2ef5fc077bc591e910a6307579fe43d4620a`. Alterações locais sem commit ou
push. Deploy, migration, credenciais e GitHub: não alterados.
