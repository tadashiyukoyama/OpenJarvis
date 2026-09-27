# Instalação reproduzível do OpenJarvis no Windows

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-09-13
Working tree base: `ec5e22e360943eb77560be3b9e5ea8ab7300b5eb`
Preparation branch: `codex/acelerachat-native-adapter`
Remote repository: `https://github.com/cesaryukoyama28-eng/openjarvis-codex` (private)

## 1. Objetivo e definição de reprodução

Este documento ensina um próximo Codex ou outro agente de IA a instalar, em um
computador Windows novo, a edição completa usada por César. O resultado esperado
é a mesma capacidade funcional, não uma cópia das contas ou conversas pessoais:

- interface Chat e Jarvis;
- voz em tempo real por Gemini Live;
- projetos e tarefas do Codex Desktop selecionáveis;
- delegação ao Codex com aprovação visual;
- e-mail de atendimento e WhatsApp administrados pelo AceleraChat;
- ferramentas nativas do Jarvis para leitura e mutação aprovada por contrato;
- memória e estado operacional no disco D:;
- acesso remoto de teste por Cloudflare Quick Tunnel;
- autenticação própria na frente do túnel;
- QR Code local para abrir a URL no tablet.

O repositório contém código, contratos, scripts, templates e documentação. Ele
deliberadamente não contém credenciais, tokens, QR Codes, bancos SQLite, e-mails,
conversas, segredos AceleraChat, logs, arquivos de processo ou histórico Codex.
Esses itens devem ser recriados ou reconectados em cada máquina.

## 2. Contrato obrigatório para o agente instalador

Antes de agir, o agente deve ler, nesta ordem:

1. `AGENTS.md`;
2. `.workspace/project.portable.json`;
3. este documento;
4. `docs/project/CURRENT-PROJECT-STATE.md`;
5. `docs/project/DOCUMENT-INDEX.md`;
6. `docs/project/ARCHITECTURE-MAP.md`;
7. `docs/project/JARVIS-AGENT-CONTRACT.md`;
8. `docs/project/operations/JARVIS-AGENT-RUNBOOK.md`;
9. Git, processos, portas e código real.

Regras sem exceção:

- não apagar nem substituir uma pasta existente;
- não inicializar Git sobre um `.git` não auditado;
- não copiar segredos da máquina antiga;
- não imprimir o conteúdo de `credenciais`;
- não instalar Ollama, modelos locais ou o grupo `desktop-native`;
- não tratar o Codex como API OpenAI ou como modelo comum;
- não iniciar dois backends, frontends ou app-servers nas mesmas portas;
- não enviar e-mail ou WhatsApp durante validações normais;
- não publicar no GitHub antes de o verificador de publicação passar;
- parar diante de arquivo, processo, banco ou divergência desconhecida.

Downloads, logins e pareamentos só podem começar com autorização do operador da
nova máquina. Nenhum script deste repositório instala silenciosamente software de
sistema.

## 3. Arquitetura que deve existir ao final

| Componente | Endereço/caminho | Responsabilidade |
|---|---|---|
| Frontend Vite | `http://127.0.0.1:5173` | Chat, Jarvis e Data Sources locais |
| Backend | `http://127.0.0.1:8127` | API, Agent Core, Sources e SPA compilada |
| Codex app-server | `ws://127.0.0.1:8131` | fronteira compartilhada do Codex Desktop |
| Gateway autenticado | `http://127.0.0.1:8140` | proteção do acesso remoto |
| Quick Tunnel | URL aleatória HTTPS | teste remoto no computador/tablet |
| Workspace | `F:\OpenJarvis` | código Git |
| Runtime | `F:\OpenJarvis\runtime` | estado, logs e processos |
| Estado ativo | `F:\OpenJarvis\runtime\state` | bancos e contexto local |
| Cache | `F:\OpenJarvis\cache` | cache uv/npm |
| Toolchains | `F:\OpenJarvis\toolchains` | Python gerenciado e ferramentas uv |
| Artefatos | `F:\OpenJarvis\artifacts` | evidências e saídas locais |
| Codex home | `F:\OpenJarvis\codex-home\.codex` | estado da instância Codex integrada |

Todo estado administrado pelo projeto fica abaixo de `F:\OpenJarvis`. Aplicativos externos instalados
pelo Windows, como Git, Node, `cloudflared` e Codex Desktop, continuam sob gestão
do sistema operacional.

## 4. Baseline verificado

A máquina de referência validada em 2026-08-09 usa:

| Item | Versão observada | Regra para nova máquina |
|---|---:|---|
| Windows | build `10.0.26200.0` | Windows 11 x64 atualizado |
| Windows PowerShell | `5.1.26100.8894` | PowerShell 5.1 ou superior |
| Git for Windows | `2.54.0` | versão suportada atual |
| Node.js | `24.16.0` | Node 20 ou superior |
| npm | `11.13.0` | fornecido com Node |
| Python | `3.13.13` | gerenciado pelo uv; projeto aceita `<3.14` |
| cloudflared | `2026.7.1` | release Windows suportada atual |
| Codex Windows package | `26.803.5235.0` | pacote oficial atual |

Os lockfiles rastreados são a autoridade para dependências Python e frontend.
O bridge Baileys direto permanece apenas como código legado inativo e não faz
parte do bootstrap. Reserve pelo menos 5 GiB livres no disco D:. A instalação observada usa
aproximadamente 1,8 GiB entre ambiente Python, módulos Node e estado ativo, sem
contar caches temporários e crescimento futuro.

## 5. Pré-requisitos de sistema

Instale somente de fontes oficiais. Uma rota válida para Git, Node, uv e Codex é:

```powershell
winget install --id Git.Git -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id astral-sh.uv -e
winget install --id 9PLM9XGG6VKS -s msstore
```

Instale `cloudflared` pelo MSI Windows publicado na
[página oficial de downloads](https://developers.cloudflare.com/tunnel/downloads/).
O Windows não atualiza automaticamente esse binário; verifique a versão antes de
cada reinstalação relevante.

Abra um novo PowerShell e confirme, sem continuar se algo faltar:

```powershell
git --version
node --version
npm --version
uv --version
cloudflared --version
Get-AppxPackage -Name OpenAI.Codex | Select-Object Name,Version,InstallLocation
Get-PSDrive D | Select-Object Name,Free,Used
```

O comando oficial atual para instalar o aplicativo Codex/ChatGPT no Windows vem
da [documentação da OpenAI](https://learn.chatgpt.com/docs/windows/windows-app).
O `uv` pode instalar o Python 3.13 necessário em D: quando o bootstrap for
executado; sua instalação oficial e o ID WinGet estão documentados pela
[Astral](https://docs.astral.sh/uv/getting-started/installation/).

## 6. Obtenção segura do repositório

O repositório canônico desta edição é privado:

`https://github.com/cesaryukoyama28-eng/openjarvis-codex`

O agente instalador deve autenticar o Git com uma conta autorizada por César. Não
substitua silenciosamente essa origem pelo repositório upstream: ele não contém a
integração completa descrita neste runbook.

Use como destino exato:

```powershell
$Target = 'F:\OpenJarvis'
```

Se `$Target` já existir, não clone, não mova e não apague. Audite primeiro:

```powershell
Test-Path -LiteralPath $Target
Test-Path -LiteralPath (Join-Path $Target '.git')
git -C $Target status --short --branch
git -C $Target remote -v
git -C $Target worktree list --porcelain
```

Se a pasta não existir, clone a origem oficial:

```powershell
git clone https://github.com/cesaryukoyama28-eng/openjarvis-codex.git F:\OpenJarvis
Set-Location F:\OpenJarvis
git rev-parse --show-toplevel
git branch --show-current
git rev-parse HEAD
git status --short
```

O resultado deve apontar para um único Git root em F:. O repositório de
distribuição foi criado a partir de um snapshot rastreado e verificado, com um
commit-raiz e sem a linhagem do ambiente de desenvolvimento. A origem OpenJarvis,
a licença Apache 2.0 e o SHA-base continuam registrados. Essa é a interpretação
aprovada de “repositório limpo”.

## 7. Bootstrap local reproduzível

O script de bootstrap não clona, não instala aplicativos de sistema, não baixa
modelos e não toca em credenciais existentes. Ele se recusa a trabalhar fora de
F: ou sobre uma configuração local divergente.

Primeiro faça o preflight não mutável:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\install-local-stack.ps1 -ValidateOnly
```

Estados possíveis:

- `BLOCKED`: falta pré-requisito, como `uv`;
- `READY_FOR_INSTALL`: pré-requisitos existem, artefatos ainda não;
- `VALIDATED`: dependências e builds necessários já existem.

Depois, com downloads de dependências explicitamente autorizados:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\install-local-stack.ps1 -InstallDependencies
```

O script executa exatamente:

- `uv sync --frozen --python 3.13 --extra desktop --extra dev`;
- `npm ci` e build de produção no frontend;
- criação, sem sobrescrita, dos templates privados Gemini, gateway e
  AceleraChat.

Ele direciona caches uv/npm e Python gerenciado para F:. Não execute o instalador
Windows herdado em `deploy/windows/install.ps1`: ele representa a distribuição
upstream com Ollama/modelo local e não reproduz esta edição Codex + Gemini.

Repita `-ValidateOnly`; o estado agora deve ser `VALIDATED`.

## 8. Configuração privada

O bootstrap cria templates ignorados pelo Git em `credenciais\workspace\env`. Edite-os
localmente sem mostrar valores ao agente ou aos logs.

### Gemini Live

Arquivo: `credenciais\workspace\env\gemini-live.env`

```dotenv
GEMINI_LIVE_API_KEY_PRIMARY=<CHAVE_PRINCIPAL>
GEMINI_LIVE_API_KEY_FALLBACK=<CHAVE_DE_FALLBACK_OPCIONAL>
GEMINI_LIVE_MODEL=
```

Crie a chave no Google AI Studio e siga a orientação oficial de manter chaves em
variáveis/armazenamento privado:
[Gemini API keys](https://ai.google.dev/gemini-api/docs/api-key). A chave de
fallback existe para falha técnica ou autenticação; ela não deve ser usada para
contornar limites, cotas ou políticas do provedor.

### AceleraChat

Arquivo: `credenciais\workspace\env\acelerachat.env`

```dotenv
ACELERACHAT_BASE_URL=https://atendimento.meugerenciador.pro/api/v1/openjarvis
ACELERACHAT_BEARER_TOKEN=<TOKEN_PRIVADO>
ACELERACHAT_WEBHOOK_SECRET_CURRENT=<SEGREDO_HMAC_ATUAL>
ACELERACHAT_WEBHOOK_SECRET_PREVIOUS=
ACELERACHAT_EMAIL_INBOX_ID=<ID_DA_CAIXA_EMAIL>
ACELERACHAT_WHATSAPP_INBOX_ID=<ID_DA_CAIXA_WHATSAPP>
```

Obtenha os valores pelo canal privado definido pelo administrador do
AceleraChat; não peça que o usuário os cole na conversa. `BASE_URL` deve ser
HTTPS, sem usuário, senha, query ou fragmento. O segredo anterior é opcional e
só existe durante rotação controlada. Os IDs podem ficar vazios apenas quando a
credencial autoriza exatamente uma caixa correspondente.

No AceleraChat, configure o callback HTTPS:

```text
<URL_PUBLICA>/v1/jarvis/agent/providers/acelerachat/webhooks
```

O callback não usa login do navegador. Ele é autenticado por HMAC no backend;
não coloque segredo na URL.

### Gateway remoto

Arquivo: `credenciais\workspace\env\cloudflare-quick-tunnel.env`

```dotenv
OJ_GATEWAY_USER=<USUARIO_LOCAL>
OJ_GATEWAY_PASSWORD=<SENHA_UNICA_E_FORTE>
```

Não coloque usuário ou senha na URL, QR Code, documentação ou comando do túnel.
O gateway lê somente esse arquivo, mantém sessões do navegador em memória e não
encaminha a autenticação ao backend.

### Codex Desktop

Não copie cookies ou tokens de outra máquina. Abra a instância iniciada pelo
launcher e autentique-se normalmente quando solicitado. Essa instância usa
`F:\OpenJarvis\codex-home\.codex`, separado do perfil padrão. O Codex permanece um
agente externo selecionável e usa o app-server oficial, não uma chave OpenAI.

## 9. Primeira inicialização local

Feche normalmente qualquer Codex Desktop já aberto. Faça primeiro uma validação:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\start-codex-live.ps1 -ValidateOnly
```

Para iniciar a composição igual à máquina de referência:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\start-codex-live.ps1
```

O launcher inicia app-server, backend, frontend e Codex Desktop; reutiliza apenas
processos reconhecidos e recusa colisões desconhecidas. O perfil atual usa acesso
amplo para manter a capacidade de controlar o computador. Em outra máquina,
comece preferencialmente com:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\start-codex-live.ps1 `
  -ApprovalPolicy on-request -SandboxMode workspace-write
```

Só altere para `never` + `danger-full-access` após César aprovar o risco daquela
máquina. Essa escolha muda permissões, não a arquitetura da integração.

Valide os serviços:

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/health
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5173/jarvis
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/v1/codex/catalog
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8127/v1/jarvis/agent/catalog
Get-NetTCPConnection -State Listen |
  Where-Object LocalPort -In 5173,8127,8131 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

No Codex Desktop, abra o projeto `F:\OpenJarvis`. No OpenJarvis,
selecione o projeto e uma tarefa existente. Chat deve carregar o histórico e a
aba Jarvis deve mostrar a sincronização Codex conectada.

## 10. Reconexão dos Data Sources

E-mail e WhatsApp são conectados e administrados no AceleraChat, não na
interface OpenJarvis. A aba Data Sources deve exibir apenas o estado canônico
dos providers `acelerachat_email` e `acelerachat_whatsapp`; ela não deve oferecer
Gmail OAuth/IMAP, QR Baileys local ou WhatsApp Meta.

Depois de preencher o arquivo privado e reiniciar somente os serviços conhecidos,
consulte o catálogo sem imprimir credenciais:

```powershell
$catalog = Invoke-RestMethod http://127.0.0.1:8127/v1/jarvis/agent/catalog
$catalog.providers |
  Where-Object id -Like 'acelerachat_*' |
  Select-Object id,status,connected,reason
```

Critério de aceite somente leitura:

- exatamente uma caixa de e-mail e uma caixa WhatsApp são selecionadas;
- e-mail busca, lista não lidos e lê uma conversa;
- WhatsApp informa estado, busca contato/chat e lê histórico;
- ferramentas não suportadas não aparecem;
- IDs do provider aparecem para o modelo apenas como referências opacas;
- nenhuma mensagem ou resposta externa é enviada.

Uma mutação real exige aprovação visual e autorização separada com alvo. HTTP
`accepted` não prova entrega; aguarde o evento assinado ou reconciliação por
backfill. Nunca repita automaticamente uma operação `UNKNOWN`.

Dados diretos históricos podem permanecer no estado local, mas não são copiados
ou reativados como fallback. O AceleraChat é a única fonte ativa desses canais.

## 11. Gemini Live, aprovação e memória

Abra `http://127.0.0.1:5173/jarvis`, permita o microfone e inicie uma sessão.
Valide:

1. Jarvis responde por voz;
2. uma leitura AceleraChat e-mail/WhatsApp não pede confirmação;
3. uma mutação ou delegação Codex mostra destino, projeto/tarefa e payload exato;
4. dizer “confirmo” não autoriza;
5. o botão **Negar** devolve a decisão ao Jarvis sem executar;
6. um resultado Codex aparece completo no Jarvis, Chat e histórico;
7. uma nova sessão recupera contexto resumido, sem transcrição integral.

Não aprove uma ação externa durante o smoke padrão. Envio real exige alvo e
autorização separados.

## 12. Túnel Cloudflare autenticado

O Quick Tunnel serve apenas para testes. Ele gera uma URL diferente a cada nova
execução, não possui SLA, limita requisições simultâneas e não suporta SSE. O
OpenJarvis usa reconciliação/polling finito no acesso remoto para preservar a
experiência dentro dessas limitações. Para uso estável, planeje futuramente um
túnel nomeado com domínio e Cloudflare Access; não misture essa configuração com
este fluxo.

O frontend de produção precisa existir porque o gateway encaminha ao backend
8127, que serve a SPA compilada. Com o OpenJarvis local saudável:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\start-remote-access.ps1 -ValidateOnly

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\start-remote-access.ps1
```

O segundo comando retorna JSON com:

- URL pública terminada em `/jarvis`;
- PID do gateway;
- PID do `cloudflared`;
- caminho do QR Code local.

Os arquivos operacionais ficam em:

```text
F:\OpenJarvis\runtime\cloudflare\public-url.txt
F:\OpenJarvis\runtime\cloudflare\openjarvis-url-qr.png
F:\OpenJarvis\runtime\cloudflare\remote-access.processes.json
```

Abra a URL, faça login com a credencial privada e instale a PWA no tablet se
desejado. Conceda microfone ao site HTTPS/PWA nas configurações do navegador.

Para encerrar somente processos iniciados pelo script:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\stop-remote-access.ps1
```

O script compara PID e linha de comando antes de parar qualquer processo,
preserva logs e se recusa a tocar em proprietário desconhecido. Referência
oficial: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

## 13. Gate técnico

Execute após a instalação e antes de declarar equivalência:

```powershell
.venv\Scripts\python.exe -m pytest tests\server\test_remote_access_gateway.py -q
.venv\Scripts\python.exe -m pytest tests\server\jarvis_agent -q
.venv\Scripts\python.exe -m ruff check src\openjarvis\server\remote_access `
  src\openjarvis\server\jarvis_agent tests\server\test_remote_access_gateway.py

Set-Location frontend
npm test -- --run
npx tsc --noEmit
npm run build
Set-Location ..

git diff --check
```

Depois execute o smoke visual local e remoto. O agente deve registrar data/hora,
branch, SHA, resultados e qualquer diferença de versão. Warnings já documentados
não equivalem a falha; novos erros ou timeouts bloqueiam a aceitação.

## 14. Checklist de equivalência funcional

- [ ] Git root único e auditado em D:.
- [ ] Nenhum arquivo desconhecido foi sobrescrito.
- [ ] Bootstrap final retornou `VALIDATED`.
- [ ] Nenhum Ollama, modelo ou Rust nativo foi instalado.
- [ ] App-server 8131 é compartilhado com o Codex Desktop.
- [ ] Backend 8127 e frontend 5173 respondem.
- [ ] Projeto e tarefa Codex podem ser selecionados.
- [ ] Chat carrega e acompanha histórico canônico.
- [ ] Gemini Live fala, escuta e mantém uma sessão.
- [ ] Aprovação e negação visuais funcionam.
- [ ] Confirmação falada não executa.
- [ ] AceleraChat e-mail busca não lidos e lê conversa.
- [ ] AceleraChat WhatsApp informa estado e lê contatos/chats.
- [ ] Webhook AceleraChat passa HMAC e reconcilia eventos sem duplicar ação.
- [ ] Nenhuma capacidade indisponível é anunciada.
- [ ] Gateway 8140 exige autenticação.
- [ ] Quick Tunnel abre no computador e no tablet/PWA.
- [ ] Microfone funciona no HTTPS remoto.
- [ ] URL e QR não contêm credenciais.
- [ ] Todos os estados administrados pelo projeto estão no D:.
- [ ] Testes, builds, lint e `git diff --check` passaram.
- [ ] Nenhuma mutação externa ocorreu no gate.

## 15. Diagnóstico sem improvisação

| Sintoma | Verificação factual | Correção permitida |
|---|---|---|
| bootstrap `BLOCKED` | campo ausente no JSON, especialmente `uv` | instalar o pré-requisito oficial; não trocar o gerenciador |
| porta ocupada | PID e `Win32_Process.CommandLine` | parar somente proprietário conhecido; desconhecido bloqueia |
| Codex “connecting” | 8131, catálogo e processo Desktop compartilhado | fechar Desktop normal e usar o launcher; não abrir segundo app-server |
| Chat sem histórico | SSE/eventos e leitura canônica da tarefa | seguir o runbook; não esconder com reload contínuo |
| Jarvis não inicia | health, status Gemini e arquivo privado presente | corrigir configuração; não registrar a chave |
| AceleraChat indisponível | provider, `reason`, URL HTTPS e arquivo privado | corrigir deployment/configuração privada; não reativar conector direto |
| seleção de inbox exigida | caixas autorizadas e IDs privados | informar o ID correto; não escolher automaticamente |
| mensagem presa em `ACCEPTED` | webhook, sequência e eventos de reconciliação | corrigir callback/HMAC e executar backfill somente leitura; não reenviar |
| webhook 401 | timestamp e rotação HMAC no servidor | alinhar segredo por canal privado; não enfraquecer o gateway |
| túnel não inicia | backend, gateway, `cloudflared` e porta 8140 | corrigir o item específico; não iniciar segunda instância |
| existe `.cloudflared/config.yml` | caminho do usuário | preservar; usar procedimento de túnel nomeado separado |
| remoto não atualiza por SSE | limitação oficial Quick Tunnel | usar polling previsto ou túnel nomeado; não desativar segurança |

## 16. Estado pessoal, backup e restauração

O código reproduz capacidades. Ele não reproduz identidade ou dados pessoais.
Para outra máquina conhecer canais e histórico, configure o acesso privado ao
mesmo AceleraChat e autentique o Codex/Gemini localmente.

Uma transferência de estado, se César solicitar no futuro, deve ser um processo
separado:

1. parar serviços conhecidos;
2. inventariar bancos e auth no D:;
3. verificar SQLite e hashes SHA-256;
4. criar arquivo criptografado fora do Git;
5. transferir por canal privado;
6. restaurar em staging;
7. validar hashes antes da ativação;
8. manter rollback até aceite explícito.

Nunca use GitHub para `knowledge.db`, `jarvis-agent.sqlite3`, `CODEX_HOME`,
segredos AceleraChat/Gemini, logs ou backups.

## 17. Gate de publicação do repositório limpo

Antes de qualquer push, com o worktree rastreado já commitado:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\verify-clean-publication.ps1
```

O resultado obrigatório é `PASS`. O verificador bloqueia caminhos privados,
bancos, logs, chaves, QR Codes, arquivos grandes inesperados, padrões prováveis de
segredo e alterações rastreadas não commitadas. Arquivos não rastreados são apenas
inventariados e nunca entram no push.

O repositório privado de destino é
`https://github.com/cesaryukoyama28-eng/openjarvis-codex`. Sua publicação inicial usa
um commit-raiz com a mesma árvore verificada e sem pais. Para reconstruir esse
snapshot localmente durante manutenção autorizada:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\create-clean-snapshot.ps1

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File scripts\workspace\create-clean-snapshot.ps1 -Create
```

O primeiro comando é preview; o segundo cria somente a branch local
`codex/distribution-snapshot`. O script usa o tree Git aprovado, preserva modos de
arquivo e cria um commit sem pais. Assim, quando apenas essa branch for enviada
ao novo repositório, objetos e commits da linhagem de desenvolvimento não ficam
alcançáveis no destino.

Antes do push, confirme:

```powershell
git rev-list --parents -n 1 codex/distribution-snapshot
git diff HEAD codex/distribution-snapshot --
```

O primeiro resultado deve conter um único SHA e nenhum pai; o segundo deve estar
vazio. Preserve `LICENSE`, os créditos no `README` e o SHA-base registrado na
mensagem do snapshot. Não faça force-push nem envie outra branch/tag por
conveniência. Qualquer nova publicação, mudança de visibilidade, configuração do
GitHub ou alteração de história exige autorização específica de César e uma nova
verificação integral.

## 18. Relatório obrigatório do agente instalador

Ao terminar, o agente deve informar:

- branch e SHA exatos;
- URL do repositório usado;
- versões observadas;
- caminhos criados em D:;
- arquivos alterados;
- dependências instaladas;
- testes e smokes executados;
- Sources conectados e capacidades reais;
- riscos, warnings e bloqueios;
- deploy alterado: sim ou não;
- migration externa alterada: sim ou não;
- credenciais alteradas: sim ou não, sem valores;
- GitHub alterado: sim ou não;
- túnel alterado: sim ou não;
- mutação AceleraChat e-mail/WhatsApp ou Codex realizada: sim ou não.

Só declare “igual ao ambiente de referência” quando todos os itens do checklist
forem comprovados. Caso contrário, declare o estado parcial e pare no gate.
