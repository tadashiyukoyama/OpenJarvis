# OJ2 — Auditoria do runtime Codex e instalação sem Ollama

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Data da auditoria: 2026-07-17 (America/Sao_Paulo)
Revisão arquitetural humana: aprovada em 2026-07-17
Branch: `audit/openjarvis-codex-runtime`
Baseline local/origin: `e57ac00b1f98b6b9e9db60145b838a5507e2c5fb`
Baseline upstream observado: `3000116d181eb69737241c09eaa70d4c65eb80a0`
Escopo: investigação estática e documentação; nenhuma implementação funcional.

## 1. Resumo executivo

O checkout oficial está íntegro no root canônico em `D:\dev\workspaces\openjarvis`.
O branch de auditoria foi criado a partir de `e57ac00b1f98b6b9e9db60145b838a5507e2c5fb`;
`origin/main` e o `HEAD` upstream observado foram revalidados antes desta fase.

O runtime atual é model-first. `SystemBuilder.build()` resolve e verifica um
`InferenceEngine` antes de construir o `JarvisSystem`, e a resolução falha com a
orientação para iniciar Ollama quando nenhum engine saudável é descoberto
(`src/openjarvis/system/builder.py:320-372`). O SDK repete a mesma dependência
lazy em `Jarvis._ensure_engine()` (`src/openjarvis/sdk.py:196-241`).

O desktop também é model-first: o fluxo Tauri inicia Ollama, verifica modelo,
inicia `jarvis serve` e só então declara a instalação pronta
(`frontend/src-tauri/src/lib.rs:919-1129`); a UI ainda bloqueia o primeiro envio
quando não há modelo selecionado (`frontend/src/components/Chat/InputArea.tsx:168-173`).
O instalador Windows baixa e executa o instalador do Ollama e puxa
`qwen3.5:2b` (`deploy/windows/install.ps1:298-380`). O quickstart instala
dependências, Ollama, modelo, backend e frontend (`scripts/quickstart.sh:69-182`).

A integração correta para a decisão do projeto é um `CodexAgent` de primeira
classe no `AgentRegistry`, no mesmo nível de `claude_code`, `opencode`,
`simple`, `orchestrator` e `react`. A seleção pública permanece seleção de
agente: `[agent] default_agent = "codex"`. O agente conversa com um processo
local já instalado do `codex app-server`, autenticado por uma conta Codex/ChatGPT
selecionada pelo usuário. Um selector interno de composição pode decidir se o
descriptor exige `InferenceEngine`, mas não é uma experiência pública
runtime→agent.

A documentação oficial descreve JSON-RPC bidirecional, `stdio` como transporte
padrão, threads/turns, streaming por notificações e aprovações server→client.
O schema estável e o probe local da versão `0.144.3` confirmaram handshake,
`account/read(refreshToken=false)`, `model/list`, approvals, streaming e os
campos de workspace/sandbox sem prompt ou thread.

Veredito OJ2-V: **GO somente para a futura PR A — External Agent Contract**.
Continua **NO-GO** para `CodexAgent` funcional, UI, instalação sem Ollama e
mudança de default. O OJ3 e o OJ4 continuam não autorizados.

## 2. Baseline e limites observados

| Item | Evidência | Resultado |
|---|---|---|
| Root Git | `git rev-parse --show-toplevel` | `D:\dev\workspaces\openjarvis` |
| Branch de trabalho | `git switch -c audit/openjarvis-codex-runtime e57ac00...` | criada sem worktree |
| HEAD inicial | `git rev-parse HEAD` | `e57ac00b1f98b6b9e9db60145b838a5507e2c5fb` |
| origin/main | `git rev-parse origin/main` | `e57ac00b1f98b6b9e9db60145b838a5507e2c5fb` |
| upstream/main live | `git ls-remote upstream refs/heads/main` | `3000116d181eb69737241c09eaa70d4c65eb80a0` |
| Worktrees | `git worktree list --porcelain` | somente o root canônico |
| Estado inicial | `git status --short --branch` | limpo, alinhado a main |
| Estado do projeto | `.workspace/local/project.local.json` | dependências/modelos falsos; Codex NOT_IMPLEMENTED |

Nenhuma alteração funcional foi autorizada ou feita. A análise não inicializou
Git, não apagou `.git`, `.codex` ou item desconhecido, não criou worktree e não
alterou GitHub antes da revalidação acima.

## 3. Ferramentas disponíveis

Inventário feito por resolução de comandos e leitura de versão/ajuda; isso não
executou OpenJarvis, instaladores, serviços, autenticação ou gerenciadores de
dependência.

| Ferramenta | Estado observado |
|---|---|
| Python | instalado, `3.13.13`, em `C:\Users\Cesar\AppData\Local\Programs\Python\Python313\python.exe` |
| uv | não encontrado |
| Node | instalado, `v24.16.0`, em `C:\Program Files\nodejs\node.exe` |
| npm | `11.13.0` via `npm.cmd`; o wrapper PowerShell foi bloqueado pela política local |
| Rust/rustc | não encontrado |
| Cargo | não encontrado |
| Codex CLI | `codex-cli 0.144.3`; wrappers `codex.cmd` e `codex.exe` encontrados |
| Codex app-server | subcomando disponível; `stdio://` é o default documentado na ajuda local |
| Git | instalado, `2.54.0` |
| GitHub CLI | localizado; não usado para ler credenciais |

O status da conta Codex não foi consultado. Não foram executados `codex login`,
`codex logout`, `codex doctor`, app-server, MCP server ou qualquer fluxo que
pudesse abrir ou alterar credenciais.

## 4. Instalação atual e colisão com o objetivo sem Ollama

### 4.1 O instalador Windows

`deploy/windows/install.ps1` não é adequado ao projeto como está. Ele:

1. instala `uv` se ausente (`:216-241`);
2. clona `open-jarvis/OpenJarvis` para `%LOCALAPPDATA%\OpenJarvis`
   (`:243-277`);
3. executa `uv sync --extra desktop --group desktop-native` (`:282-293`);
4. baixa `OllamaSetup.exe`, executa `/S` e inicia o daemon (`:298-364`);
5. executa `ollama pull qwen3.5:2b`, aproximadamente 1,5 GB segundo o próprio
   script (`:366-380`);
6. escreve/usa estado no caminho de instalação e inicia trabalho posterior.

Conclusão: **sim, o instalador Windows instala Ollama**, baixa um modelo e
executa tarefas de instalação; é incompatível com a fase OJ2 e com o modo
principal Codex.

### 4.2 Quickstart e segunda clonagem

`scripts/quickstart.sh` contém a segunda rota de instalação: recomenda clonar
novamente o repositório oficial (`:8-11`), instala `uv` (`:69-78`), exige Node
(`:80-92`), instala/inicia Ollama (`:94-136`), baixa `qwen3:0.6b`
(`:138-147`), executa `uv sync` e `maturin develop` (`:149-158`), instala
frontend com `npm install` (`:160-163`) e inicia backend/frontend
(`:165-182`). Isso confirma a **segunda clonagem identificada** além do
checkout canônico D:; também há clones equivalentes na documentação e no
Tauri (`frontend/src-tauri/src/lib.rs:1165-1200`).

Não há `SkipOllama` ou `Skip-Ollama` no instalador Windows. A rota shell possui
`--minimal` em `scripts/install/install.sh`, mas a implementação desse caminho
continua sendo uma política de instalação do produto e não é uma solução Codex
auditada.

### 4.3 Instalação oficial adequada ao projeto

Para o objetivo desta equipe, **nenhuma instalação oficial encontrada é
adequada sem uma futura revisão**. As rotas atuais assumem pelo menos uma
combinação de `uv sync`, Ollama/modelo, `npm install`, extensão Rust ou clone
automático. A instalação adequada deverá:

- reutilizar o checkout existente em D: e recusar uma segunda clonagem;
- validar ferramentas já presentes e parar com instruções claras quando faltar
  uma ferramenta, sem instalar silenciosamente;
- preparar somente o backend/desktop necessário para o modo Codex;
- não instalar Ollama nem baixar pesos;
- manter estado administrado pelo projeto sob um root D explícito;
- tratar login Codex como ação explícita do usuário, fora do instalador;
- ter um gate próprio de runtime, não uma sequência `engine/model/server`.

## 5. Armazenamento, caches e disco

### 5.1 Runtime atual

`src/openjarvis/core/paths.py:82-122` resolve o root na ordem
`OPENJARVIS_HOME` → `XDG_DATA_HOME/openjarvis` → `Path.home()/.openjarvis`.
O guard impede runtime dentro do source tree, mas o fallback Windows atual é
`C:\Users\Cesar\.openjarvis`, contrariando o requisito D-only se a variável
não for configurada.

O root OpenJarvis concentra configuração, bancos, caches, logs, credenciais e
skills; caches regeneráveis ficam em `<root>/cache`. O código configura bancos
como `memory.db`, `telemetry.db`, `traces.db`, `sessions.db`, `agents.db` e
`optimize.db` sob o mesmo root em `src/openjarvis/core/config.py`.

O Claude runner copia arquivos para `<root>/claude_code_runner` e, se não
existir `node_modules`, executa `npm install` no primeiro uso
(`src/openjarvis/agents/claude_code.py:93-133`). Portanto essa integração tem
gravação e instalação em runtime, algo que o futuro Codex adapter deve evitar.

### 5.2 Codex e possíveis gravações em C:

O ambiente desta sessão informa `CODEX_HOME=D:\dev\codex-home\.codex`, mas os
conteúdos de autenticação não foram lidos. A documentação oficial do
app-server também menciona o socket de controle sob `$CODEX_HOME` e devolve
`codexHome` no handshake. A decisão recomendada é preservar a instalação e a
autenticação Codex existentes sem copiar tokens para OpenJarvis.

Possíveis gravações fora do D observadas estaticamente ou pelo inventário:

- fallback OpenJarvis em `C:\Users\Cesar\.openjarvis`;
- `%LOCALAPPDATA%\OpenJarvis` da rota Windows;
- `%TEMP%`, hoje `C:\Users\Cesar\AppData\Local\Temp`, para temporários;
- cache de documentação usado nesta auditoria em
  `C:\Users\Cesar\AppData\Local\Temp\openai-docs-cache`;
- instalação global de Node/Codex em `%ProgramFiles%`/`%APPDATA%`;
- caches de npm e ferramentas gerenciadas, fora do root do projeto.

Isso é uma matriz de risco, não uma leitura de conteúdo privado. Nenhum token,
cookie, chave ou arquivo de autenticação foi aberto ou copiado.

### 5.3 Estimativa de espaço

Medição estática do checkout atual: aproximadamente **0,139 GB** em 2.260
arquivos na árvore de trabalho; o pack Git observado foi aproximadamente
**43 MB**. Não há `node_modules`, venv de projeto, modelos ou dependências
instaladas contabilizados nessa medição.

Estimativa provisória para um futuro modo Codex sem Ollama: **0,5–2 GB além do
checkout**, dependendo do pacote Python/backend e da forma de distribuir o
frontend; **0 GB de pesos locais**. Essa faixa é planejamento, não critério de
aceite: deverá ser medida em uma fase autorizada após decidir se o frontend
será pré-compilado e se a extensão Rust será necessária.

## 6. Fluxo de runtime atual

O fluxo verificável é:

1. `load_config()` detecta hardware e escolhe engine/modelo padrão; a função
   atual recomenda `llamacpp` sem GPU, `mlx` em Apple, `ollama` em GPU NVIDIA de
   consumidor e outros engines em casos específicos
   (`src/openjarvis/core/config.py:257-276` e `:303-346`).
2. `SystemBuilder.build()` resolve o engine, executa health check e resolve o
   modelo antes de montar o sistema (`src/openjarvis/system/builder.py:320-372`).
3. O `JarvisSystem` agrega engine, model, agents, tools, sessões, observability,
   security e scheduler (`src/openjarvis/system/core.py:52-88`).
4. `QueryOrchestrator.ask()` escolhe agente ou chama diretamente
   `s.engine.generate(...)`; todo agente é instanciado com `s.engine` e
   `s.model` (`src/openjarvis/system/orchestrator.py:64-93` e `:129-227`).
5. Chat HTTP usa SSE para streaming direto; o caminho de agente executa o
   agente síncrono numa thread e transforma eventos em SSE
   (`src/openjarvis/server/stream_bridge.py:60-197`).
6. A UI seleciona modelo, envia histórico e consome chunks SSE; sem modelo
   selecionado o envio é recusado (`frontend/src/components/Chat/InputArea.tsx:168-241`;
   `frontend/src/lib/api.ts:156-198` e `:700-800`).
7. Persistência de sessões de canais usa SQLite no root OpenJarvis
   (`src/openjarvis/server/session_store.py:18-55`); isso não é ainda um
   armazenamento de thread Codex.

O ponto exato de bloqueio da implementação atual é a fronteira engine-first em
`SystemBuilder._resolve_engine()`/`Jarvis._ensure_engine()`, reforçada pelo
gate de modelo na UI. Um `CodexAgent` isolado poderia não usar um engine saudável,
mas o caminho integrado atual não consegue chegar à construção do agente sem
resolver um engine. A PR A deve inverter a composição: resolver primeiro o
descriptor do agente e somente depois resolver engine/model quando o descriptor
for engine-backed.

## 7. Auditoria do ClaudeCodeAgent

O Claude existente é um adapter Python→Node:

- registra `claude_code` e mantém `engine` apenas por conformidade de interface;
  a inferência é delegada ao SDK Claude (`src/openjarvis/agents/claude_code.py:1-8`;
  `:43-57`);
- leva `api_key`, `workspace`, `allowed_tools`, `system_prompt` e `session_id`
  no JSON enviado ao runner (`:60-87` e `:154-172`);
- o runner grava `ANTHROPIC_API_KEY` no ambiente do processo Node e chama
  `query()` do pacote Anthropic (`src/openjarvis/agents/claude_code_runner/src/index.ts:1-118`);
- o Python chama `subprocess.run()` e espera o processo terminar
  (`src/openjarvis/agents/claude_code.py:139-204`); não há transporte de eventos
  token-a-token entre o runner e o servidor;
- o streaming HTTP posterior pode tentar `engine.stream_full()` para reemitir
  o resultado final, ou fazer replay palavra a palavra
  (`src/openjarvis/server/stream_bridge.py:243-303`);
- o teste confirma que `_ensure_runner()` instala npm no primeiro uso quando
  `node_modules` falta (`tests/agents/test_claude_code.py`, testes de runner).

O que é reutilizável como referência: lifecycle de processo, delimitação de
payload, timeout, tratamento de erro, eventos de turno e contexto de workspace.
O que não deve ser copiado: API-key em payload próprio, `npm install` implícito,
modelo fictício para satisfazer `BaseAgent`, execução síncrona sem streaming
nativo, e pressuposto de que um agente externo pode ser encaixado após um engine
local já resolvido.

Resposta auditada: **ClaudeCodeAgent funciona sem engine saudável somente em
isolamento**, pois não usa o parâmetro engine; **não funciona sem engine saudável
no runtime integrado atual**, porque `SystemBuilder` falha antes de o agente ser
construído.

## 8. Auditoria oficial do Codex app-server

Fontes oficiais consultadas em modo somente leitura:

- [Codex App Server README oficial](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md)
- [Interface MCP/app-server oficial do Codex](https://github.com/openai/codex/blob/main/codex-rs/docs/codex_mcp_interface.md)
- [Documentação OpenAI de Codex app-server](https://developers.openai.com/codex/app-server/)

Fatos relevantes para o desenho:

- o processo suporta JSON-RPC 2.0 bidirecional, com JSONL newline-delimited
  em `stdio`; WebSocket é experimental/não suportado para produção e o socket
  Unix é destinado ao controle local;
- o cliente deve enviar exatamente um `initialize`, depois `initialized`, e
  identificar-se em `clientInfo`;
- `thread/start`, `thread/resume`, `thread/read` e `thread/list` formam a
  superfície de sessões; `turn/start`, `turn/interrupt` e `turn/steer` controlam
  execução;
- `turn/started`, `item/started`, deltas `item/*`, `item/agentMessage/delta` e
  `turn/completed` permitem renderização incremental; token usage chega por
  notificações próprias;
- `cwd`, `model`, `approvalPolicy` e `sandboxPolicy` podem ser configurados no
  thread/turn; isso corresponde ao workspace e ao controle de capacidades do
  projeto;
- aprovações de comando/patch são requisições JSON-RPC iniciadas pelo servidor;
  o cliente deve responder `allow`/`deny` ou o subconjunto de permissões aceito;
- há login gerenciado por API key, navegador ChatGPT e device code. A decisão
  OJ2 seleciona o fluxo de conta Codex/ChatGPT e exclui API key OpenAI como
  requisito do modo principal;
- `model/list` fornece catálogo do runtime/account; isso não equivale a
  download de pesos e não deve ser tratado como `GET /v1/models` do Ollama;
- o protocolo e vários campos permanecem experimentais; a integração deve
  fixar a versão do binário/protocolo efetivamente testado e tratar erros de
  capacidade experimental explicitamente.

### Respostas requeridas pela arquitetura

| Pergunta | Decisão OJ2 |
|---|---|
| Integração recomendada | adapter `CodexAppServerClient` + `CodexAgent`, sem `InferenceEngine` local como pré-requisito |
| Transporte | `stdio://`, processo local long-lived; não WebSocket nesta primeira versão |
| Lifecycle | iniciar sob demanda, handshake único, monitorar stderr/exit, interromper turno, shutdown sem deixar filho órfão |
| Threads | mapear conversa OpenJarvis → `threadId`; persistir somente ID e metadata não secreta; usar `thread/resume` |
| Streaming | assinar `item/*`/`turn/*`, acumular deltas, emitir evento interno e SSE/UI incremental |
| Approvals | traduzir requests server→client para UX explícita; default deny/stop se o cliente não responder |
| Sandbox | mapear workspace D autorizado para `cwd`/sandbox profile; não elevar permissões silenciosamente |
| Autenticação | conta já autenticada pelo Codex; UX futura com status/read e fluxo oficial de login, sem copiar tokens |
| API key necessária | **não** para o modo primário com conta Codex/ChatGPT; suporte API key é uma capacidade oficial, mas excluída do escopo |
| Modelo local necessário | **não**; o catálogo/modelo do Codex é remoto/account-backed e não usa pesos Ollama |

## 9. Gaps que impedem o OJ4

1. O contrato `BaseAgent(engine, model)` não representa um agente externo com
   thread/process/auth próprios.
2. `SystemBuilder` não possui ramo para runtime externo sem engine saudável.
3. A configuração atual é engine/model-centric e não tem bloco aprovado de
   `runtime.codex` ou identidade de provider.
4. O desktop não tem estado `codex_ready`, `account_required` ou
   `approval_pending`; os três flags atuais são Ollama/model/server.
5. A UI assume `selectedModel` antes de enviar; para Codex deve selecionar
   provider/runtime e obter modelos pelo app-server, não por Ollama.
6. O servidor SSE atual conhece `ChatCompletionChunk`, tools e telemetry, mas
   não o envelope JSON-RPC bidirecional nem requests de approval.
7. A persistência de canais/sessões não tem vínculo seguro e versionado com
   `threadId` do Codex.
8. O teste de integração precisa provar login já existente, conta ausente,
   thread resume, reconnect, interrupt, stream truncado, approval allow/deny,
   sandbox/cwd e encerramento de processo.
9. A versão instalada do Codex é observável, mas o estado/auth da conta não foi
   verificado por proibição explícita; não há prova de que o app-server possa
   ser usado nesta máquina sem uma ação de login do usuário.
10. O modelo de telemetry atual presume engine/model local e pode atribuir
    `ollama` em caminhos especializados; a semântica Codex precisa ser definida
    antes de publicar custo, tokens ou energia.

## 10. Arquitetura proposta (não implementada)

```text
Chat/API/UI
    │ agent=codex (seleção pública)
    ▼
AgentRegistry → AgentDescriptor
    │
    ├─ engine-backed → resolve InferenceEngine → resolve model → Agent
    │
    └─ external      → CodexAgent → CodexAppServerClient
                                      └→ codex app-server (stdio JSON-RPC)
```

O `AgentRegistry` deve resolver o agente antes de qualquer engine. Para agentes
engine-backed, o comportamento atual permanece: resolver engine, resolver model
e manter health/list_models. Para `CodexAgent`, a composição não deve chamar
`_resolve_engine()`, `_resolve_model()`, `engine.health()`, `engine.list_models()`
nem procurar Ollama ou fazer fallback para engine local. O adapter deve expor um
resultado normalizado para o OpenJarvis (`content`, `thread_id`, `usage`,
`items`, `approval state`, erro), mantendo o protocolo Codex bruto isolado.

### Arquivos backend futuros

- `src/openjarvis/agents/codex.py`: `CodexAgent`, sem login automático;
- `src/openjarvis/integrations/codex_app_server.py`: transport, JSON-RPC,
  handshake, request correlation, notifications e process lifecycle;
- `src/openjarvis/integrations/codex_models.py`: DTOs versionados e allowlist de
  eventos/approvals;
- `src/openjarvis/core/runtime.py` ou equivalente: composição interna baseada no
  `AgentDescriptor`, sem selector público runtime→agent;
- `src/openjarvis/server/codex_routes.py`: status/account/thread e approval
  somente após definir a superfície auth e a política de exposição local;
- store futuro em D para `conversation_id ↔ threadId`, sem tokens.

### Arquivos frontend futuros

- componente de seleção `Codex`/`OpenJarvis local`;
- estado de runtime com `codex_ready`, `account_required`, `connecting`,
  `approval_pending`, `turn_running`, `error`;
- renderer de `item/agentMessage/delta`, tool/command/fileChange e diff;
- modal/painel de approval com allow/deny e razão/cwd;
- UX de login oficial (browser ou device code) sem exibir ou persistir token;
- troca de `selectedModel` obrigatório por provider + modelo opcional quando o
  provider é Codex.

### Configuração futura

Não criar `config.toml` funcional nesta fase. O desenho futuro deve ter apenas
configuração declarativa e segura, por exemplo:

```toml
[agent]
default_agent = "codex"

[agent.codex]
enabled = true
execution_mode = "external"
requires_engine = false
requires_model = false
external_runtime = "codex_app_server"
transport = "stdio"
approval_policy = "user"
sandbox_profile = "workspace"
workspace_root = "D:/..."
```

O exemplo é contrato de desenho, não instrução executada. O path final, os
nomes exatos e a política de sandbox exigem revisão OJ4.

### Testes futuros

- parser JSON-RPC com respostas fora de ordem e notificações sem request id;
- handshake, capabilities estáveis/experimentais e incompatibilidade de versão;
- thread start/resume/list/read e mapeamento D de conversa;
- turn start/interrupt/steer e reconexão após queda do processo;
- streaming de deltas, usage, erro e finalização;
- approval de comando/patch, deny por timeout e subset de permissões;
- cwd/sandbox sem escape do workspace;
- ausência de Ollama, ausência de modelo local e conta não autenticada;
- ausência de segredos em logs, config e trace;
- regressão do runtime local existente.

## 11. Instalação futura sem Ollama (proposta, não executada)

Sequência conceitual para uma fase futura explicitamente autorizada:

1. Confirmar o checkout D existente, branch de instalação dedicado e hashes de
   backup; não clonar novamente.
2. Definir `OPENJARVIS_HOME` para um diretório administrado no D, fora do source
   tree, e validar que a resolução de `paths.py` não cai no C.
3. Validar `python`, `node` somente quando necessários ao artefato escolhido,
   `git` e `codex`; não instalar silenciosamente ferramenta ausente.
4. Instalar somente o conjunto Python/backend aprovado em D. A forma exata
   (`uv sync --extra server` ou pacote equivalente) deve ser autorizada em uma
   fase de instalação separada; **não foi executada no OJ2**.
5. Não instalar Ollama, não iniciar Ollama, não executar `ollama pull`, não
   baixar modelo/pesos e não executar `npm install` do runner Claude.
6. Reutilizar a autenticação do Codex por ação explícita do usuário, usando o
   fluxo oficial do Codex em uma fase autorizada; OpenJarvis não recebe token.
7. Iniciar o backend futuro com runtime Codex selecionado e `codex app-server`
   via `stdio`, depois validar apenas health/status e a conta sem enviar prompt
   de produção.

Comandos futuros meramente propostos, todos **não executados**:

```powershell
# root e estado exclusivamente no D; path final depende da decisão OJ3/OJ4
$env:OPENJARVIS_HOME = 'D:\OpenJarvis\runtime'

# somente validação de ferramentas já instaladas
python --version
node --version
codex --version

# login interativo futuro, somente com autorização explícita do proprietário
codex login

# processo Codex futuro, sob controle do backend; não executar nesta fase
codex app-server --listen stdio://

# dependências do backend futuro, após gate de instalação; não executar nesta fase
uv sync --extra server
```

O último bloco é uma especificação operacional preliminar. Ele não autoriza
instalação, login, execução de app-server, `uv sync` ou qualquer download agora.

## 12. Matriz de arquivos e sequência de PRs

| Arquivo/área | OJ2 | Próxima PR de implementação |
|---|---|---|
| `docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md` | CANONICAL após revisão humana | preservar evidências e riscos não provados |
| `docs/project/CODEX-AGENT-INTEGRATION.md` | contrato arquitetural canônico | PR A requer autorização própria |
| `docs/project/ARCHITECTURE-MAP.md` | registrar limites verificáveis | atualizar mapa após adapter testado |
| `docs/project/ROADMAP.md` | fechar OJ2 como auditado, manter OJ3/OJ4 bloqueados | autorizar uma única fase futura |
| `src/openjarvis/integrations/codex_app_server.py` | não tocar | PR de transporte/protocolo |
| `src/openjarvis/agents/codex.py` | não tocar | PR de `CodexAgent`/selector |
| server/frontend/Tauri | não tocar | PR de status, streaming e approvals |
| installer/config | não tocar | PR de instalação sem Ollama, separada |

Sequência recomendada, cada item com gate próprio:

1. revisão humana do relatório e validação do protocolo/binário;
2. adapter app-server somente com testes offline/fakes;
3. runtime selector e `CodexAgent` sem alterar a rota local por default;
4. sessão, streaming e approvals end-to-end em ambiente autorizado;
5. UX desktop sem gate `ollama_ready/model_ready` para Codex;
6. instalador D-only sem Ollama, sem clone secundário e sem download de modelo;
7. validação final, PR review, e somente então eventual mudança de default.

## 13. Riscos e questões sem prova

- compatibilidade além do contrato básico entre `codex-cli 0.144.3` instalado e
  o protocolo que será usado na implementação end-to-end;
- disponibilidade e permissões da conta foram observadas apenas de forma
  sanitizada (`chatgpt` autenticado); nenhum identificador pessoal foi registrado;
- formato e durabilidade do `threadId` quando o app-server reinicia;
- comportamento de approval quando a conexão stdio é interrompida;
- política final de sandbox no Windows e tradução de `workspace`/roots;
- necessidade real de Tauri/`uv`/Rust para o pacote distribuído;
- semântica de custo/usage/telemetry para um provider Codex;
- concorrência de múltiplas conversas em um único processo app-server;
- permissões da conta e limites de uso, não testados;
- não há prova de que qualquer comando de login deva ser automatizado pelo
  OpenJarvis; a hipótese segura é delegar ao Codex oficial e não tocar tokens.

## 14. Critérios de aceite OJ2/OJ2-V

- [x] auditoria executada no branch dedicado, sem worktree;
- [x] `origin/main` e upstream main recapturados por refs live de 40 caracteres;
- [x] instalador Windows, quickstart, armazenamento, runtime, frontend e
  Claude auditados por leitura estática;
- [x] Codex app-server consultado em fontes oficiais somente leitura;
- [x] proposta sem Ollama/modelos/API key como requisito primário;
- [x] nenhuma implementação funcional ou workflow alterado;
- [x] schema estável da versão instalada gerado sem `--experimental`;
- [x] handshake `stdio` e encerramento sem órfão comprovados por probe local;
- [x] `account/read` executado com `refreshToken=false`, sem dados pessoais;
- [x] `model/list` executado sem prompt, thread, turn ou download de modelo;
- [x] arquitetura pública congelada como seleção de agente, não runtime→agent;
- [x] este relatório passa a `CANONICAL` após a revisão humana;
- [x] revisão arquitetural humana aprovada em 2026-07-17;
- [x] autorização limitada: GO somente para PR A — External Agent Contract;
  nenhuma implementação de CodexAgent, UI, instalação ou mudança de default.

## 15. Veredito

**OJ2 APROVADA. GO somente para a PR A — External Agent Contract; NO-GO para
`CodexAgent` funcional, UI, instalação e mudança de default.**

O projeto tem prova local suficiente para iniciar somente a abstração de
contrato da PR A. Ainda não há autorização para subprocess Codex em produção,
UI, instalação, login, mudança de default ou qualquer fase posterior.

## 16. OJ2-V — prova local e contrato congelado

### Prova da versão instalada

- versão: `codex-cli 0.144.3`;
- schema: gerado pelo comando estável publicado no próprio help, sem
  `--experimental`, em `.workspace/local/audit/codex-app-server-0.144.3-schema`;
- arquivos do schema: 267, com manifesto SHA-256 em
  `.workspace/local/audit/codex-app-server-0.144.3-schema-manifest.json`;
- métodos mínimos: `initialize`, `initialized`, `account/read`, `model/list`,
  `thread/start`, `thread/resume`, `thread/read`, `thread/list`, `turn/start`
  e `turn/interrupt` classificados como `STABLE`;
- classificação explícita: `STABLE` contém todos os mínimos acima;
  `EXPERIMENTAL` não foi gerado porque o comando não recebeu
  `--experimental`; `ABSENT_IN_0.144.3` não contém nenhum dos mínimos exigidos;
  nenhum método ausente foi tratado como suportado;
- approvals de command/fileChange, streaming `item/agentMessage/delta` e
  `turn/*`, e campos `cwd`, `approvalPolicy` e `sandboxPolicy` classificados
  como `STABLE`; schema experimental não foi gerado;
- probe: `codex app-server --listen stdio://`, clientInfo
  `openjarvis_codex_audit`, handshake aprovado em 1.036,86 ms;
- `codexHome`: somente comparação sanitizada com `CODEX_HOME`, resultado
  `EXPECTED`; `platformFamily=windows`, `platformOs=windows`;
- `account/read`: aprovado com `refreshToken=false`, `authenticated=true`,
  `authMode=chatgpt`, `planType` presente, rate limits ausentes; e-mail,
  account ID, token e demais identificadores não foram registrados;
- `model/list`: aprovado, seis IDs públicos, sem seleção, download ou prompt;
- encerramento: PID do probe terminou com código 0, sem processo app-server
  órfão e sem alteração de outros processos Codex.

### Contrato público obrigatório

```text
[agent]
default_agent = "codex"

AgentDescriptor(
    name="codex",
    execution_mode="external",
    requires_engine=false,
    requires_model=false,
    external_runtime="codex_app_server",
)
```

`Codex` é um agente de primeira classe e permanece lado a lado com
`claude_code`, `opencode`, `simple`, `orchestrator` e `react`. O seletor visual
principal é “Agente”. `RuntimeSelector`, se implementado, é detalhe interno da
composição e recebe o descriptor; não é uma seleção pública separada.

`SystemBuilder` deverá resolver o descriptor do agente antes do engine. O ramo
engine-backed mantém engine/model/health/list_models. O ramo Codex não chama
`_resolve_engine()`, `_resolve_model()`, `engine.health()`,
`engine.list_models()`, Ollama ou fallback local. `ClaudeCodeAgent` permanece
intacto e não será apagado nem renomeado.

### PR A — External Agent Contract

A única PR futura que este resultado permite preparar é a PR A de contratos,
sem implementar o CodexAgent:

- metadata de agente e distinção engine-backed versus external;
- resolução do agent antes do engine;
- engine/model opcionais somente onde necessários;
- testes com agente externo fake;
- nenhum subprocess Codex real, interface, Ollama, modelo, autenticação ou
  app-server em produção;
- nenhum `NoOpEngine`, `DummyEngine`, `FakeEngine` produtivo ou modelo fictício.

Critérios da PR A: selecionar `fake_external` não chama `get_engine`,
`engine.health` ou `list_models`; agentes atuais continuam usando engine/model;
nenhuma alteração do comportamento default antes da escolha explícita; CI
completo aprovado. A PR A ainda requer autorização própria para execução.

**Próxima fase autorizada: NENHUMA.**
