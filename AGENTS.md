# OpenJarvis Project Instructions

## Scope
Estas instrucoes valem somente para este repositorio.

## Authority
- Cesar define negocio, prioridade, aprovacao e veto.
- O arquiteto define escopo tecnico, contratos e criterios de aceite.
- O Codex investiga e executa somente o escopo autorizado.
- Nao ampliar a tarefa sem autorizacao.

## Read order
1. AGENTS.md
2. .workspace/project.portable.json
3. .workspace/local/project.local.json, quando existir
4. docs/project/CURRENT-PROJECT-STATE.md
5. docs/project/DOCUMENT-INDEX.md
6. documento da tarefa
7. Git, PR, CI e codigo real
8. somente entao alterar arquivos

## Source of truth
- Codigo: origin/main com SHA exato.
- Upstream: upstream/main.
- Estado local: comandos Git no clone real.
- Worktrees: git worktree list --porcelain.
- Finalidade de worktrees: ledger local.
- Decisoes: docs/project/DECISIONS.md.
- Estado: docs/project/CURRENT-PROJECT-STATE.md.
- Credenciais: .private ou secrets da plataforma; nunca na documentacao.

## Working rules
- Investigar antes de alterar.
- Usar branch de tarefa; nao trabalhar diretamente em main.
- Worktree somente quando houver beneficio real.
- Executar testes relacionados a mudanca.
- Atualizar apenas a documentacao impactada.
- Nao criar documentos duplicados para o mesmo assunto.
- Nao apagar arquivo desconhecido.
- Nao usar git clean -fdx sem autorizacao.
- Nao fazer deploy, migration, merge ou alteracao de GitHub settings sem autorizacao.
- Nao abrir ou copiar credenciais sem tarefa especifica.
- Nao baixar modelos grandes sem estimativa de espaco e autorizacao.
- Em duvida destrutiva, parar e relatar; em duvida nao destrutiva, investigar e prosseguir.

## Codex integration
- Codex sera integrado como agente externo selecionavel.
- Nao trata-lo como modelo OpenAI comum por API.
- A integracao devera preservar autenticacao, sessao, streaming, aprovacoes e workspace.
- A implementacao somente comeca apos auditoria do codigo oficial.

## Completion report
Toda tarefa deve informar:
- branch e SHA;
- arquivos alterados;
- testes executados;
- documentacao atualizada;
- riscos e bloqueios;
- deploy, migration, credenciais e GitHub alterados: sim ou nao.
