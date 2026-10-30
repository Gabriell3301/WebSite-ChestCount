# Interface de inventários

## Abrir e utilizar

Inicia `python server.py` e abre `http://127.0.0.1:8080/`. Seleciona um mundo, um baú e um slot. O botão **Atualizar** consulta os dados atuais. O checkbox permite ativar ou desativar consultas automáticas a cada 10 segundos. Mundo, baú, slot e preferências são conservados no `localStorage` do navegador; inventários não são persistidos aí.

As teclas de seta permitem percorrer os slots quando um deles tem foco. Os números dos slots nos detalhes são os índices originais da API: 0–26 ou 0–53. Os itens permanecem na posição recebida; a quantidade é mostrada no canto inferior direito.

As listas de mundos não têm um nome de apresentação no contrato atual. O seletor mostra um rótulo derivado do identificador e mantém o ID completo visível por baixo. Mundos `integration-test:` existentes são identificados como testes, sem serem apagados; um mundo normal é preferido na primeira abertura.

## Dados utilizados

A página faz apenas GET para health, lista de mundos, lista de baús e detalhe do baú. Nunca acede diretamente ao SQLite. O refresh consulta health e mundos em paralelo e depois a lista do mundo; o detalhe é consultado ao selecionar um baú ou quando a revisão/tombstone desse baú muda. Uma revisão inalterada conserva o detalhe já recebido e os elementos dos slots, evitando recarregar imagens desnecessariamente.

Os pedidos são limitados por timeout, não se sobrepõem entre ciclos de atualização e param quando a aba está oculta. Mudar de seleção cancela a consulta anterior. Respostas antigas não substituem os dados da seleção nova. Se o servidor parar com a página já aberta, a interface mantém o último snapshot recebido, mostra indisponibilidade e volta a tentar no próximo ciclo ou refresh manual.

`identity.blocks` com um bloco válido identifica 27 slots; dois blocos horizontalmente adjacentes, à mesma altura, identificam 54. O tamanho nunca deriva do número de itens. Sem identidade suficiente, o grid não é inventado e aparece uma indicação de tamanho desconhecido. Slots inválidos ou repetidos são assinalados sem reorganizar o conteúdo.

`deleted:true` é um tombstone. O checkbox **Mostrar removidos** permite consultar esses registos como histórico. Um baú selecionado que seja removido mantém a seleção e recebe a indicação de conteúdo histórico. `structureChanged:true` avisa que a geometria e o inventário são os últimos conhecidos. `syncedAt:null` significa que ainda não existe inventário confirmado: slots vazios não são apresentados como prova de um baú vazio.

O contrato não fornece `updated_at` por baú nem nomes traduzidos de itens. A página mostra `syncedAt` como **última leitura do inventário**, `serverRevision` como revisão e `worlds.updated_at` como atualização do mundo, além da hora da última consulta do navegador. O título do item é derivado do seu ID; o identificador completo continua visível. Não são feitas consultas de tradução ou lookup de metadados.

## Ícones BlocksItems

Documentação consultada: https://blocksitems.com/api. A URL utilizada é:

```text
https://blocksitems.com/api/2026.1.2/icon/{full_id_codificado}.png?size=64&placeholder=404
```

Usa o `item_id` original com validação de namespace/caminho e `encodeURIComponent`, num host e versão fixos. O `<img>` incorpora diretamente o PNG remoto, com `image-rendering: pixelated` e sem referrer; não há proxy, descarregamento em massa ou dependência de CORS para apresentar imagens. O navegador utiliza a sua cache normal. Ícones que falhem usam `/placeholder.svg`, com uma única transição e sem loop de erros. IDs já falhados na sessão usam o fallback nas visualizações seguintes.

Um erro, mod desconhecido ou ícone não renderizado não impede consultar slots, quantidades e IDs. Não se assume cobertura de todas as imagens de mods. A API externa só recebe IDs de itens usados nas imagens, sem nomes dos mundos ou baús enviados pelo JavaScript.

## Ficheiros e segurança

- `web/index.html`: estrutura acessível da página.
- `web/style.css`: layout responsivo, slots e paleta cinzento/verde.
- `web/app.js`: consumo da REST API, seleção, polling, validação e fallback.
- `web/chest.svg` e `web/placeholder.svg`: vetores locais.
- `web_routes.py`: whitelist explícita dos seis caminhos estáticos.

Os ficheiros são servidos apenas com bind e cliente loopback. Não existe serviço genérico de diretórios, acesso a `.db`, scripts Python, `.git` ou manifests por HTTP. Os IDs são codificados nas URLs e todo o conteúdo dinâmico é colocado com `textContent`, não HTML. CSP permite scripts/estilos apenas locais e imagens locais ou de `https://blocksitems.com`; também existem `nosniff` e política de referrer.

A interface não tem edição, remoção, autenticação fictícia, Player Status ou envio de inventários. O protocolo incremental e o esquema SQLite foram preservados. O servidor continua a ser exclusivamente de desenvolvimento.
