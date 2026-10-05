# Changelog

## [0.4.4] - 2026-10-05
### Added
- PXPrintCalc: botão "Selecionar pedaços a usar…" ao lado de "Priorizar pedaços de tecido cortados" — permite marcar quais pedaços cortados (não usados) entram no planejamento da fila atual. Útil quando há pedaços do mesmo tecido vindos de fabricantes/lotes diferentes que não podem ser misturados no mesmo rolo: basta desmarcar os que não devem ser usados nesta fila

## [0.4.3] - 2026-10-05
### Fixed
- PXSearchOrders: achada a causa real da tela em branco no "Editar rolo" para rolos do PXPrintLogs — `PXPrintLogsUI` retorna o próprio frame esperando que quem o criou faça o `pack()` (é assim que o JocastaHub monta as abas), mas o "Editar rolo" não fazia esse pack na janela nova. PXPrintCalc não tinha esse problema porque se empacota sozinho. Agora o "Editar rolo" empacota o frame retornado quando necessário, igual ao JocastaHub

## [0.4.2] - 2026-10-05
### Fixed
- PXSearchOrders: "Editar rolo" ainda podia abrir uma janela em branco quando a preparação dos dados do rolo falhava (ex.: data/hora de um pedido em formato inesperado) — a janela de edição já tinha sido criada e exibida antes do erro aparecer. Agora os dados são preparados antes de abrir a janela (se falhar, não abre janela nenhuma) e qualquer `EndTime` em formato inesperado usa um valor de fallback em vez de travar a edição. O erro, se ocorrer, agora mostra o detalhe completo (traceback) em vez de uma mensagem genérica

## [0.4.1] - 2026-10-05
### Fixed
- PXSearchOrders/PXPrintCalc: corrigida tela em branco ao usar "Editar rolo" — ao reabrir um rolo já registrado, o PXPrintCalc tentava reagrupar/reparticionar os itens por tecido (bin packing completo, igual a uma fila nova), o que podia falhar e deixar a janela de edição incompleta. Agora, ao editar, o rolo é tratado como um único rolo contínuo (igual ao PXPrintLogs) — os itens só são acrescentados ao final, sem reagrupar por tecido

### Added
- PXPrintLogs: botão "Arquivo(s) de espaço…" — permite cadastrar o(s) nome(s) de arquivo/job que a máquina imprime como espaço entre tecidos (quando não há gap automático); ao importar, logs que casarem com esse nome são identificados e marcados como ESPAÇO em vez de pedido real
- PXPrintLogs: itens marcados como ESPAÇO aparecem na lista de pedidos do tecido/bloco (como "— ESPAÇO —") mas não entram em "Pedidos no rolo", no PDF exportado nem no registro do PXSearchOrders

## [0.4.0] - 2026-10-05
### Added
- PXSearchOrders: botão "Editar rolo" — reabre o rolo selecionado no módulo de origem (PXPrintCalc ou PXPrintLogs), já carregado com os itens registrados, para acrescentar serviços impressos depois que o rolo foi fechado. Ao reexportar, o mesmo registro é **atualizado** (não cria um rolo novo e desconexo)
- PXPrintCalc: quando um rolo novo usa um pedaço de tecido cortado, o pedaço agora é marcado como "usado" automaticamente no momento em que o rolo é registrado (antes só era possível marcar manualmente em "Pedaços de tecido…")
- PXPrintCalc: ao atualizar (via "Editar rolo") um rolo que usava um pedaço cortado, se a metragem do rolo atualizado passar a exceder a metragem do pedaço (sinal de que não foi deixado o espaço/troca de rolo), o pedaço volta automaticamente para "não usado"

### Changed
- PXPrintCalc/PXPrintLogs: ao editar um rolo já registrado, se o conteúdo acrescentado não couber mais em um único rolo, a atualização é bloqueada com um aviso (em vez de dividir silenciosamente em múltiplos rolos)

## [0.3.16] - 2026-10-05
### Fixed
- PXPrintCalc: em telas pequenas, o painel "Pedidos sendo impressos" (e os demais painéis abaixo da fila) ficavam cortados/ocultos fora da janela; a tela agora tem rolagem vertical, igual ao PXPrintLogs

## [0.3.15] - 2026-10-05
### Changed
- PXPrintCalc: a lista "Pedidos" no PDF exportado agora mostra o último item da fila primeiro, igual ao PXPrintLogs ("último impresso primeiro")

## [0.3.14] - 2026-10-03
### Added
- PXPrintCalc: botão "⤢ Abrir em janela" na fila (sequência), no "Resumo por rolo" e em "Pedidos sendo impressos" — abre cada painel numa janela maior, com botão "Atualizar" para repuxar os dados atuais
- PXPrintCalc: na janela de "Pedidos sendo impressos", opção de ordenar por metragem (padrão) ou alfabeticamente (A-Z)

## [0.3.13] - 2026-10-03
### Added
- PXPrintCalc: novo painel "Pedidos sendo impressos" — agrupa os arquivos da fila (ou da lista base) por pedido (extraído do nome do arquivo, igual ao PXPrintLogs), mostrando tecido(s), metragem total e quantidade de peças por pedido

## [0.3.12] - 2026-10-03
### Changed
- PXPrintCalc: o "Gap entre arquivos" deixou de aparecer como linha "— ESPAÇO —" na lista da fila — continua contando normalmente na metragem total e do rolo, só não exibe mais a linha extra (diferente dos gaps entre tecidos e de fim de rolo, que continuam visíveis)

## [0.3.11] - 2026-10-03
### Fixed
- PXPrintCalc: botões "Mover acima/abaixo" e o arrastar pela alça "⋮⋮" pareciam não fazer nada porque o modo padrão é "tecido", onde a fila é sempre reagrupada automaticamente por tecido (a ordem manual não tem efeito ali). Agora os controles ficam desabilitados nesse modo e avisam para trocar para "original" ao tentar usar

## [0.3.10] - 2026-10-03
### Added
- PXPrintCalc: ao exportar PDF Normal/JPG Espelhado/Ambos, cada rolo da fila agora é registrado no banco do PXSearchOrders (mesma base do PXPrintLogs) — pedido, tecido, metragem e posição no rolo ficam pesquisáveis por lá, igual a quando o rolo vem de um log de impressão

## [0.3.9] - 2026-10-03
### Added
- PXPrintCalc: área "Arraste e solte imagens aqui" — permite importar arquivos de imagem arrastando do Explorer, igual ao PXPrintLogs, sem precisar abrir o diálogo "Importar imagens"

## [0.3.8] - 2026-10-03
### Added
- PXPrintCalc: arrastar e soltar para reordenar a fila — alça "⋮⋮" na primeira coluna da tabela; arrastar fora da alça continua selecionando normalmente (não interfere na seleção usada por "Definir tecido" e nos botões de mover)

## [0.3.7] - 2026-10-03
### Added
- PXPrintCalc: botões "▲ Mover acima" / "▼ Mover abaixo" para reordenar manualmente os arquivos da fila (modo "original") — ao intercalar um arquivo de outro tecido no meio da sequência de um tecido, o planejador já insere automaticamente o espaço antes e depois dele (troca de tecido = novo rolo)

## [0.3.6] - 2026-10-03
### Added
- PXPrintCalc: novo campo "Gap entre arquivos (m)" — gap configurável inserido entre arquivos consecutivos de um mesmo bloco/rolo de tecido (conta na metragem do rolo e influencia o encaixe dos pedaços cortados), mas nunca é inserido antes do primeiro nem depois do último arquivo do bloco

## [0.3.5] - 2026-10-03
### Added
- PXPrintCalc: o PDF exportado (Normal/Ambos) agora mostra qual pedaço cortado foi usado em cada rolo na tabela "Resumo por rolo", igual ao painel visual da tela
- PXPrintLogs e PXPrintCalc: o JPG espelhado, quando o PDF gerado tem mais de uma página (ex.: modo Completo), agora concatena todas as páginas verticalmente num único JPG contínuo — antes só a primeira página era capturada, cortando o resumo que ficava nas páginas seguintes

## [0.3.4] - 2026-10-03
### Fixed
- PXPrintCalc: corrigido planejador de fila que gerava dois espaços seguidos na troca de tecido quando um pedaço cortado estava ativo (o espaço de "fim de rolo vazio" não deveria ter sido inserido)
- PXPrintCalc: número do rolo agora é único em toda a fila — antes reiniciava em 1 a cada tecido, fazendo o "Rolo 1" de tecidos diferentes se misturarem no resumo e no PDF
- PXPrintCalc: o planejador agora tenta de verdade encaixar pedaços cortados (bin packing) em vez de só testar o maior item da fila contra o pedaço — itens menores que coubessem no pedaço eram descartados silenciosamente e o pedaço acabava nunca sendo usado

### Added
- PXPrintCalc: novo painel "Resumo por rolo (conferência)" — mostra visualmente, por rolo, o tecido, qual pedaço cortado foi usado (se algum), blocos, itens, total e tempo, no mesmo espírito do resumo que o PXPrintLogs gera no PDF

## [0.3.3] - 2026-10-03
### Added
- Impressoras: cadastro ganhou "Pasta do JPG espelhado" e "Nome do arquivo do JPG" (ambos opcionais) — permite apontar o JPG invertido de cada impressora para uma pasta/arquivo fixo (ex.: hot folder do RIP), independente do módulo usado
- PXPrintLogs e PXPrintCalc: checkbox "Usar pasta/arquivo da impressora para o JPG espelhado" na exportação — quando marcado, usa a pasta/arquivo cadastrado na impressora selecionada; quando desmarcado, exporta como antes (pasta estruturada padrão do módulo)

## [0.3.2] - 2026-10-03
### Added
- PXPrintCalc: botões "Salvar lista…" e "Importar lista…" — salva a fila de impressão (itens, tecidos, DPI por item e todas as configurações: impressora, velocidade, modo, gaps, metragem, ordem dos tecidos) em um arquivo JSON para continuar depois sem reimportar as imagens uma a uma

## [0.3.1] - 2026-10-03
### Added
- PXPrintCalc: exportação em paridade com o PXPrintLogs — botões "Exportar PDF Normal", "Exportar JPG Espelhado" e "Exportar Ambos", com modo Completo/Resumido, largura do JPG (17cm/21cm/personalizado) e pastas estruturadas (pdf/print) com nomes versionados, iguais às do PXPrintLogs
- PXPrintCalc: seletor de impressora (com botão de atualizar) que preenche a velocidade (m/min) automaticamente a partir do cadastro de impressoras, influenciando o cálculo do tempo de impressão

### Fixed
- PXPrintLogs: nome do pedido agora trata parênteses no fim do nome do arquivo (ex.: "(Argentina)", "(Brasil)") como controle de separação, não como parte do nome — "Salum 12 (Argentina)" e "Salum 12 (Brasil)" agora são reconhecidos como o mesmo pedido "Salum 12"

## [0.3.0] - 2026-10-03
### Added
- PXPrintCalc: botão "Novo tecido…" direto no diálogo "Editar item", sem precisar abrir o cadastro de tecidos separado
- PXPrintCalc: metragem do rolo agora é por tecido (ex.: Elastano = 60m), cadastrada junto com os aliases em "Tecidos…"; substitui o antigo par fixo Dryfit/Outros
- PXPrintCalc: cadastro de "Pedaços de tecido" cortados (nome, tecido, metragem) com opção "Marcar como usado" / "Desmarcar"
- PXPrintCalc: checkbox "Priorizar pedaços de tecido cortados (não usados)" — quando ativo, o planejador de fila preenche primeiro os pedaços já cortados (do maior para o menor) antes de usar rolos cheios
- JocastaHub: tela "Gerenciar Impressoras" em Configurações (nome, nome de exibição, velocidade, observações) — cadastra, edita e remove impressoras
- PXPrintLogs: a lista de máquinas ao importar logs agora vem do cadastro de impressoras (antes era fixo M1/M2)

### Fixed
- PXPrintLogs: em telas pequenas, o painel "Pedidos no rolo" ficava cortado/oculto fora da janela; a tela agora tem rolagem vertical

## [0.2.7] - 2026-10-03
### Fixed
- PXPrintCalc: corrigido `FileNotFoundError` ao abrir a tela no executável — o cadastro de tecidos usava `__file__` para achar o caminho gravável, que não existe de verdade dentro do build congelado (PyInstaller); agora usa `%APPDATA%\ProjetoJocasta\PXPrintCalc\fabrics.json`, com migração automática dos tecidos já cadastrados

## [0.2.6] - 2026-10-03
### Fixed
- PXPrintCalc: implementado o relatório consolidado (JPG espelhado) — a geração da imagem estava com o corpo comentado e quebrava com erro ao exportar; agora usa fonte monoespaçada (Courier/Consolas) para manter as colunas alinhadas

## [0.2.5] - 2026-10-03
### Added
- PXPrintLogs: aviso de duplicidade entre rolos — se o mesmo pedido com o mesmo tecido já foi exportado em outro rolo, o programa avisa ao importar e pede confirmação antes de exportar
- PXPrintLogs: pedido agora é persistido no banco (coluna `pedido` na tabela `orders`), com migração automática de bancos existentes

## [0.2.4] - 2026-10-03
### Added
- PXPrintLogs: edição do nome do tecido direto na tela (duplo clique ou botão "Editar tecido") após importar os logs
- PXPrintLogs: extração e exibição do nome do pedido a partir do nome do arquivo, com lista "Pedidos no rolo" editável (duplo clique) para corrigir erros de digitação
- PXPrintLogs: PDF completo agora inclui, após o total geral do rolo, uma tabela com a lista de pedidos (nome, total em metros, quantidade de peças)

## [0.2.3] - 2026-02-27
### Fixed
- PXPrintLogs: corrigido alinhamento das colunas no resumo do PDF (Total, Qtd Pedidos, Último fim)
- Exportação: estrutura padronizada de pastas (pdf/print/temp) e nomes ISO com versionamento automático (_v2, _v3)

## [0.2.2] - (data)
- ...