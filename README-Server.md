# Chest Count - servidor local incremental

API Python sem dependências externas. SQLite serve apenas o desenvolvimento local; este servidor não deve ser exposto publicamente.

## Iniciar e parar

PowerShell:

```powershell
cd C:\ChestCount-Server
python server.py
```

Escuta em `127.0.0.1:8080`; saída com Ctrl+C no mesmo terminal. Não uses comandos que terminem todos os processos Python. Para identificar um servidor iniciado em segundo plano, verifica `Get-CimInstance Win32_Process` e a linha de comando com o caminho completo deste `server.py` antes de parar o respetivo PID.

```powershell
python server.py --host 127.0.0.1 --port 8081 --database C:\ChestCount-Server\data\other-test.db
Invoke-RestMethod http://127.0.0.1:8080/api/v1/health
python inspect_db.py
python inspect_db.py --world "IDENTIDADE_DO_MUNDO"
python inspect_db.py --world "IDENTIDADE_DO_MUNDO" --chest "UUID_DO_BAU"
python -m unittest -v test_server
```

`CHESTCOUNT_HOST` e `CHESTCOUNT_PORT` também definem os valores padrão. O caminho padrão da base é `data/chestcount.db`. Os testes usam exclusivamente bases temporárias e portas dinâmicas. Logs no terminal e `logs/server.log`, com rotação. Stack traces internos ficam apenas nos logs.

## Componentes

- `server.py`: argumentos/configuração, rotas, respostas, logging, limite HTTP e interface `LocalDevelopmentPolicy.authorize` para futura autenticação.
- `validation.py`: validação dos envelopes, operações, UUIDs canónicos, mundos, nomes, dimensões, posições e itens.
- `repository.py`: transações, SQLite, revisões, idempotência e consultas.
- `inspect_db.py`: consulta pela CLI.
- `openapi.json`: contrato OpenAPI 3.1 reutilizável; `test_server.py`: regressões automatizadas.

## Endpoints

| Método e rota | Resultado |
| --- | --- |
| `POST /api/v1/sync` | Resultados individuais das alterações |
| `GET /api/v1/health` | Serviço e protocolo |
| `GET /api/v1/worlds` | Mundos |
| `GET /api/v1/worlds/{worldId}/chests` | Baús consolidados, incluindo tombstones |
| `GET /api/v1/worlds/{worldId}/chests/{chestId}` | Baú, itens, revisão e eliminação |
| `GET /api/v1/worlds/{worldId}/export` | `formatVersion:1`, `world`, baús ativos e tombstones separados |
| `GET /api/v1/worlds/{worldId}/changes?since=0&limit=100` | Eventos ordenados, `nextCursor`, `hasMore` |
| `POST /api/sync` | Arquivo legado, sem alterar SQLite |

Codifica os identificadores nos segmentos URL. Nomes e coordenadas nunca substituem UUIDs. O corpo está limitado a 8 MiB e a 256 alterações; as respostas do mod usam lotes até 128. Não existe execução de comandos nem acesso ao sistema de ficheiros a partir dos identificadores. Todos os valores SQLite usam parâmetros.

## Contrato e concorrência

Envelope: `protocolVersion:1`, `clientId` UUID persistente, `worldId`, `bootstrap` e `changes`. Cada alteração contém `changeId` UUID, `chestId` UUID, `revision` local positiva, `baseServerRevision` (0 quando inexistente), `operation`, `dimension` e `data`. Para upsert, a dimensão também pode ser inferida de `data.identity.dimension`. O mod inclui sempre dimensão, datas, mundo e cliente. Se um cliente externo omitir datas no upsert, o servidor usa a hora de receção como metadado; não verifica inventários Minecraft.

Operações:

- `upsert`: snapshot completo de um baú, substitui o inventário inteiro numa transação.
- `rename`: `data.name`; conserva inventário e identidade.
- `delete`: `data:{}`; eliminação lógica permanente para este UUID.
- `structure_changed`: `data.structureChanged`; conserva inventário.

Um mundo desconhecido exige `bootstrap:true`. A revisão inicial de cada UUID ausente é 0; o primeiro upsert atribui 1. Bootstrap não permite sobrescrever UUIDs existentes. O mod envia bootstrap no primeiro lote confirmado de cada mundo/destino e persiste essa informação. Dados JSON legados não são migrados automaticamente: o primeiro envio do mod cria os registos SQLite a partir do seu estado local.

Cada operação aplicada incrementa a revisão do baú. A base deve coincidir com a revisão atual; uma base desatualizada produz `conflict`. Revisões locais são comparadas apenas dentro de `(clientId, worldId, chestId)`, nunca entre clientes diferentes. Tombstones recusam upserts posteriores: para uma estrutura substituída usa um UUID novo.

`processed_changes` guarda a resposta e o hash da alteração. O mesmo `changeId` e conteúdo devolve `duplicate` se já foi aplicado, conservando a revisão originalmente atribuída. Reutilizar um ID com conteúdo diferente é `rejected`. Conflitos repetidos continuam conflitos, não se tornam sucessos. O cliente remove apenas `applied`/`duplicate`. Validações individuais inválidas recebem `rejected`; erros no envelope recebem HTTP 400. Erros inesperados de persistência revertem o lote inteiro e recebem 500. O teste de rollback injeta um erro SQLite deliberado, por isso o seu stack trace no terminal é esperado.

O cursor é `server_changes.sequence`, uma sequência global SQLite crescente e independente das revisões individuais. Usa `nextCursor` na consulta seguinte; `limit` vai de 1 a 256. O mod ainda não consome estes eventos automaticamente.

## SQLite e recuperação

- `worlds`: identidade, criação e atualização.
- `chests`: chave composta `(world_id,id)`, nome, dimensão, identidade/documento JSON, revisão, tombstone e datas.
- `chest_items`: chave composta `(world_id,chest_id,slot)`, FK para o baú, item e quantidade.
- `processed_changes`: chave global `change_id`, cliente/mundo/baú/revisão, hash e resultado durável.
- `server_changes`: sequência global, mundo, baú, operação, revisão e snapshot do evento.

Índices para mundo/tombstone, revisão por cliente e cursor por mundo. Chaves estrangeiras ativadas em todas as ligações. `BEGIN IMMEDIATE` serializa escritores; WAL, transações e fecho explícito das ligações permitem reiniciar sem perder operações confirmadas. Não copies apenas o ficheiro `.db` enquanto existem escritas: usa a API de backup SQLite ou para este servidor antes de copiar os seus ficheiros.

Os JSONs `sync_*.json` anteriores permanecem intocados. A rota antiga guarda novos ficheiros `legacy_<uuid>.json` exclusivamente para compatibilidade de testes e não interfere no estado consolidado.

## Conflitos e limitações

Não existe resolução automática. Consulta o baú e a revisão no GET, exporta ambos os estados e decide qual o conteúdo correto. Um cliente administrativo futuro pode enviar uma alteração nova, com novo changeId e a base atual, depois dessa decisão explícita. O mod conserva conflitos/rejeições para diagnóstico e não tenta forçar a sua resolução. Não edites a base em execução nem apagues tombstones para contornar conflitos.

Sem contas, tokens, TLS embutido ou proteção suficiente para exposição pública. A interface de autorização é apenas um ponto de extensão; o modo atual é explicitamente local. Para Yii2/MySQL, mantém o contrato e substitui o repositório, com a mesma transação para baú/itens/recibo/evento, restrições únicas e controlo de concorrência. Não interpretes revisões locais como uma ordem global.

Os exemplos sintéticos e seguros do contrato estão em [docs/examples/](docs/examples/). Capturas locais de integrações antigas em `examples/` permanecem locais, fora do Git.

## Interface HTML integrada

Abre **http://127.0.0.1:8080/** para selecionar mundos/baús e consultar os inventários guardados, com ícones BlocksItems, quantidades por slot, detalhes, revisão e refresh automático opcional a cada 10 segundos. A interface é exclusivamente de leitura e não altera o protocolo incremental nem o SQLite. Continua a ser servida apenas em loopback.

Ver [README principal](README.md), [guia da interface](docs/WEB-UI.md) e [relatório de testes](docs/WEB-VALIDATION.md). `python -m unittest -v test_server test_web test_web_browser` executa a suite completa; o navegador é opcional e só utiliza ferramentas já instaladas.
