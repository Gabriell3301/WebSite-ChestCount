# Relatório da interface HTML — 30/10/2026

## Implementado

Explorador web de mundos, baús e inventários integrado em `/`, consumindo exclusivamente os endpoints REST já existentes. Inventários simples e duplos, slots originais/vazios, quantidades, seleção, detalhes, revisão, datas disponíveis, refresh manual, polling configurável e preservação da seleção. Estados vazios/offline/históricos e fallback local de ícones.

## Ficheiros

Criados: `web/index.html`, `web/style.css`, `web/app.js`, `web/chest.svg`, `web/placeholder.svg`, `web_routes.py`, `test_web.py`, `test_web_browser.py`, README principal, esta documentação e exemplos sintéticos em `docs/examples/`.

Modificados: `server.py` para encaminhar exclusivamente os caminhos estáticos; `README-Server.md` com referência à nova interface. O mod Fabric, o contrato incremental, o esquema e as linhas de dados SQLite não foram modificados pela implementação da interface.

## Testes executados

```powershell
python -m unittest -v test_server test_web test_web_browser
```

**41 testes passaram, sem falhas ou skips:** 23 regressões existentes do servidor, 7 testes HTTP/SQLite/estáticos e 11 testes de navegador. Os testes utilizaram bases temporárias e portas dinâmicas, incluindo uma base totalmente vazia. O traceback do teste de rollback é injetado deliberadamente e confirma a reversão transacional.

No navegador Chrome instalado, via DevTools Protocol, foram verificados: 27/54 slots, posição real, quantidades, clique/contorno/detalhes, PNG real, layout de 375 px sem overflow horizontal, baú vazio, mundo vazio, tombstones, seleção após atualização e após remoção lógica, falhas de rede/recuperação, URLs seguras, fallback de um 404 real, XSS como texto, polling sem sobreposição e desativação, ausência de lookups repetidos.

As capturas versionadas [desktop](screenshots/desktop.png) e [mobile](screenshots/mobile.png) mostram exclusivamente fixtures isolados. As capturas da base real, logs, hashes e relatórios detalhados de dados locais permanecem em `validation-web/`, fora do Git.

## BlocksItems e integração real

Os ícones `minecraft:diamond`, `minecraft:iron_ingot`, `minecraft:oak_log` e `minecraft:netherite_sword` responderam HTTP 200, `Content-Type: image/png`, assinatura PNG válida e URLs sem redirect. `chestcount:missing_test_icon` respondeu 404; o navegador apresentou o placeholder local mantendo quantidade/ID. Foi verificado que os ícones não exigem lookup de metadados nem proxy.

Depois de identificar o PID e verificar executável, linha de comando e data de criação, foi reiniciado apenas o servidor Chest Count. A página real foi aberta em `http://127.0.0.1:8080/`, apresentou um inventário SQLite sincronizado pelo mod, carregou os PNGs dos IDs reais e não produziu exceções JavaScript. Todos os pedidos feitos pela interface à API local foram GET. `/api/v1/health` manteve `success:true`, `protocolVersion:1`, `service:chestcount`.

O conteúdo lógico do SQLite e os hashes de todos os JSONs existentes em `data/` foram comparados antes/depois da fase de validação real e eram iguais nesse instante. Sincronizações posteriores do mod continuam a atualizar normalmente a base; a interface não envia essas alterações.

## Limitações

Nomes traduzidos de itens e nomes amigáveis de mundos não são fornecidos pelo contrato atual; os IDs são preservados. Datas do baú distinguem leitura do inventário e consulta do navegador, sem inventar uma data de atualização do baú. Ícones de mods ou indisponíveis têm fallback. Sem identidade física segura, não é inventado o tamanho do grid. Não existe autenticação para utilização pública; a interface só é servida em loopback. Não houve alterações no mod nem novas dependências de runtime.
