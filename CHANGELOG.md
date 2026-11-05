# Changelog

## [Não lançado]
### Added
- Registros → aba "Pedidos": novo botão "Exportar contexto de produção..." (habilitado quando um trabalho de impressão está selecionado na lista). Gera um arquivo `.json` consumido pelo PX Tool Box (ver, no repositório PXToolBox, `docs/integrations/nexor-order-context.md`) — identificador real `rollId` + `job_hash` (confirmado único só dentro desta base de dados, nunca globalmente — ver docstring de `modules/registros/px_export.py`), etiqueta de pedido informada, tecido, tipo e referência do arquivo de origem. O Nexor não tem pedido comercial formal (sem número/cliente/status) — o texto do botão e das mensagens nunca chama isto de "pedido" como identificador, só como "pedido informado" quando o dado existe. Recusa exportar uma linha sem pedido informado (ex.: um avanço/espaço). Somente leitura: não altera nada no rolo/trabalho de impressão, não abre o PX/Corel automaticamente — o usuário escolhe o destino do arquivo e importa manualmente do outro lado.
- `core/config.py`: novo campo `installation_id` (`PXCoreConfig`) e `get_installation_id()` — id curto e opaco gerado uma única vez por instalação (persistido em `config.json`), incluído na exportação do contexto de produção acima (`source.installationId`, opcional) para desambiguar `rollId`/`job_hash` vindos de instalações diferentes. Nunca um identificador de pedido comercial, nunca enviado a lugar nenhum fora desse arquivo de exportação explícito.
- `core/printlogs_db.py`: `installation_id` sozinho não resolvia o escopo real de `(rollId, job_hash)` — conferido com testes reais (`tests/test_database_identity.py`): a mesma instalação pode apontar para bases `.db` diferentes (mesmo id, bases diferentes), e `base_dir` pode ser uma pasta de rede compartilhada entre várias instalações (id diferente, mesma base — ver o comentário real do `journal_mode` em `connect()`). Adicionado `get_database_id()` + nova tabela `db_identity` — um id gerado e gravado DENTRO do próprio arquivo `printlogs.db` (protegido contra corrida de criação simultânea), por isso sobrevive a cópia/restauração do arquivo e é igual entre instalações que acessem a mesma base compartilhada. Incluído na exportação como `source.databaseId` (opcional). `installation_id` permanece, documentado com sua garantia real (mais limitada).
- Registros → confirmação pós-exportação do contexto de produção: depois de gravar o arquivo com sucesso, uma janela mostra o caminho completo e duas ações auxiliares — "Mostrar arquivo na pasta" (`core/paths.reveal_file_in_explorer`, abre o Explorer com o arquivo já selecionado, via lista de argumentos — nunca concatenação de shell) e "Copiar caminho" (área de transferência). Uma falha em qualquer uma das duas nunca desfaz a confirmação de que o arquivo foi exportado — aparece como aviso à parte, na mesma janela. A janela também lembra: "No PX Tool Box DEV, use Produção > Carregar contexto de produção" — exportar aqui nunca significa que o PX recebeu o contexto. Nenhuma infraestrutura de "lembrar última pasta usada" foi criada: não existia nada equivalente no Nexor hoje, e o diretório de exportação é escolha da máquina/usuário a cada vez (nunca uma preferência portátil, nunca usado para localizar o PX automaticamente). Cancelamento ou falha de gravação continuam sem anunciar sucesso, como já era.

## [1.6.39] - 2026-11-05
### Added
- Registros → "Detalhes do rolo selecionado": nova aba "Lista do rolo", igual à de mesmo nome na Operação — todos os itens numa lista só, na mesma ordem do comprovante, incluindo ESPAÇO. Segue o combobox "Versão do rolo" (movido pra cima das abas, já que agora afeta tanto "Pedidos" quanto "Lista do rolo").
### Fixed
- Operação: os avanços (ESPAÇO) nunca eram salvos no banco ao fechar/atualizar um rolo — ficavam de fora da lista de orders gravada, mesmo o resto do código (resumo com "Espaços", "Agrupar espaços consecutivos" em Configurações) já esperando que eles estivessem lá. Corrigido: agora entram como orders normalmente (com tipo="", a marca de ESPAÇO). Como consequência direta, reabrir um rolo pelos Registros ("Editar rolo") preserva os avanços em vez de perdê-los pra sempre a cada edição, e eles também voltam a aparecer no resumo dos Registros.
- Registros → "Exportar contexto de produção...": um avanço/espaço tinha "pedido" preenchido (ex.: "ESPAÇO", não vazio) — o aviso de "sem pedido informado" não pegava esse caso. Agora também verifica o "tipo" (sempre vazio num avanço), então um ESPAÇO nunca gera um contexto de produção.

## [1.6.38] - 2026-11-05
### Fixed
- Registros → "Detalhes do rolo" → "Pedidos": ao editar um rolo (ex.: só trocar o nome) e escolher uma versão anterior no combobox ("Original"/"Edição N"), a lista aparecia fora de ordem — a cópia guardada dessa versão não era ordenada por EndTime como a versão atual sempre é, saindo na ordem em que os arquivos foram importados em vez da ordem cronológica. Corrigido na gravação (`update_roll_orders`) e também na leitura, pra já corrigir versões salvas antes deste reparo sem precisar editar o rolo de novo.

## [1.6.37] - 2026-11-05
### Changed
- Registros → "Detalhes do rolo selecionado" → aba "Pedidos": novo combobox "Versão", que mostra como padrão a versão ATUAL do rolo e deixa escolher qualquer versão anterior (Original, Edição 1, Edição 2...) de um rolo editado — antes só dava pra ver "o original" (sempre a primeira), numa janela separada. "Ver informações originais" saiu do menu de botão direito (que agora só tem "Editar rolo" e "Abrir comprovante"); pra ver uma versão anterior, selecione o rolo e troque o combobox. Numa versão que não é a atual, "Exportar contexto de produção..." fica desabilitado (só existe registro real pra exportar na versão atual).
- `core/printlogs_db.py`: a tabela `roll_original_orders` (guardava só UMA cópia, "a original") foi substituída por `roll_order_versions` (uma cópia por edição) — migrada automaticamente na primeira vez que o Nexor abrir o banco.

## [1.6.36] - 2026-11-05
### Added
- Configurações → "Identificador deste computador": novo campo "Nome do operador deste computador" — quem fecha/atualiza rolos nesse PC. Quando preenchido, aparece no comprovante (PDF e JPG, já que o JPG é renderizado a partir do PDF) como "Operador de fechamento: <nome>"; em branco, a linha simplesmente não aparece.
### Changed
- Nome do rolo: o identificador do computador (quando cadastrado) passou a entrar logo depois da máquina, em vez do fim do nome — ex.: `M3_N_05-11-2026_0083` em vez de `M3_05-11-2026_0083_N`.
### Fixed
- `core/station.py`: salvar o identificador do computador apagava o nome do operador salvo (e vice-versa) — `write_module_cfg` substitui o arquivo inteiro, não faz merge. Agora cada save lê o config atual antes de alterar só o campo correspondente.

## [1.6.35] - 2026-11-05
### Fixed
- Detecção do nome do pedido pelo arquivo: um número solto no fim do nome (sem parênteses) era tratado como "contador de peça" e removido — então "Haras DRB 4.jpeg" virava pedido "Haras DRB", enquanto "Haras DRB 4 (2).jpeg" (mesmo pedido, 2ª peça) virava "Haras DRB 4", já que aí só o "(2)" era removido. Agora só o que está entre parênteses no fim é ignorado; um número solto faz parte do nome do pedido — os dois arquivos acima já voltam a ser reconhecidos como o mesmo pedido "Haras DRB 4".

## [1.6.34] - 2026-11-05
### Added
- Configurações → Operação: novo campo "Pasta de logs (geral)", com botões "Procurar…" e "Abrir pasta". É o fallback usado pelo diálogo de "Importar logs" quando a máquina do lote ainda não é conhecida (primeira importação da sessão) ou quando a impressora já conhecida não tem uma pasta própria cadastrada — "Pasta dos logs desta impressora" (Gerenciar Impressoras) continua tendo prioridade quando preenchida.

## [1.6.33] - 2026-11-05
### Fixed
- Registros → "Editar rolo": a janela abria pequena demais na primeira vez, porque o tamanho era fixado antes do conteúdo (Operação/Planejador) ser montado e empacotado — o Tk recalculava pelo conteúdo ainda vazio. Agora o tamanho (1200x800, com `minsize` igual) é aplicado só depois do conteúdo já estar montado.

## [1.6.32] - 2026-11-05
### Added
- Configurações → Gerenciar Impressoras: novo campo "Pasta dos logs desta impressora". Quando cadastrado, a Operação abre o diálogo de "Importar logs"/"Importar pasta" já nessa pasta (em vez de onde o Windows abriu da última vez), bastando selecionar os arquivos. Na primeira importação do rolo (máquina ainda não detectada), só assume essa pasta automaticamente se houver uma única impressora cadastrada com pasta definida — com mais de uma, não arrisca palpite.
- Registros → lista de rolos: menu de botão direito com "Editar rolo", "Abrir comprovante" e "Ver informações originais (antes da edição)" — antes só dava pra editar/abrir pelo botão no topo, precisando selecionar a linha primeiro. Nova coluna "Editado" mostra quais rolos já foram alterados depois de fechados.
- Editar um rolo pelos Registros ("Editar rolo" → Operação/Planejador → "Atualizar Rolo") agora preserva o estado ORIGINAL do rolo (como ele estava no primeiro fechamento) — orders e PDF/comprovante originais continuam acessíveis mesmo depois da edição. "Abrir comprovante" num rolo editado pergunta se quer abrir o comprovante original, o atual, ou os dois; "Ver informações originais" mostra a lista de itens de como o rolo estava antes da edição.
### Fixed
- Operação: fechar o mesmo rolo uma segunda vez (depois de importar mais logs na mesma sessão, sem reabrir pelos Registros) criava um rolo NOVO no banco com conteúdo repetido, em vez de atualizar o rolo já salvo — e por isso acusava "possível duplicidade" contra ele mesmo. Agora, depois do primeiro "Fechar Rolo", o botão já vira "Atualizar Rolo" e passa a atualizar o mesmo rolo. O aviso de duplicidade entre rolos também para de considerar o próprio rolo em edição/atualização como "outro rolo".

## [1.6.31] - 2026-11-05
### Added
- Operação: a coluna "Tipo" (Pedido, Reposição, Fora do padrão…) passou a aparecer na tabela de itens do comprovante — tanto no PDF quanto no JPG (que é renderizado a partir do mesmo PDF).
### Changed
- Operação: o JPG de registro (espelhado, enviado pra impressora) agora é renderizado a partir de um PDF intermediário contínuo — uma única "página" alta, sem as quebras de página do comprovante em papel (cabeçalho e margens repetidos a cada página). O PDF salvo para o usuário abrir/imprimir continua paginado normalmente; só o JPG passou a ser contínuo.

## [1.6.30] - 2026-10-30
### Added
- Operação: impressoras que não imprimem um arquivo dedicado de espaço, mas deixam um avanço em branco automático entre arquivos, agora têm esse avanço (lido do próprio log do arquivo real, campo `VPositionMM`) listado como um item de ESPAÇO próprio, com a metragem em branco correta — antes esse avanço não entrava na listagem de forma alguma quando a máquina não tinha arquivo de espaço cadastrado. Funciona em paralelo ao cadastro de "Arquivo(s) de espaço…", que continua existindo para as máquinas que imprimem um arquivo dedicado.
### Changed
- Menu lateral: Operação passou a ser o primeiro item (o Nexor agora abre direto nela ao iniciar); Planejador passou para o segundo.

## [1.6.29] - 2026-10-28
### Added
- Operação → "Detalhes do bloco" e "Lista do rolo": novo item "Remover item(ns)…" no menu de botão direito (e tecla Delete), com confirmação — remove da tela um ou mais arquivos selecionados por engano (ex.: log importado errado). Só afeta o rolo aberto nesta sessão; nada é apagado do banco até fechar/atualizar o rolo de novo.

## [1.6.28] - 2026-10-28
### Added
- Operação: nova aba "Lista do rolo" — mostra todos os arquivos do rolo numa lista única, na mesma ordem em que saem no comprovante (em vez de agrupados por tecido ou por pedido). Duplo clique ou botão direito → "Editar item…" permite corrigir nome do arquivo, tecido, pedido e observação de um arquivo específico (sem afetar outros do mesmo grupo); com mais de um item selecionado, oferece "Observação (em N arquivos)…" como nas outras abas. Qualquer edição feita ali ou nas abas "Ordem do rolo"/"Detalhes do bloco"/"Pedidos no rolo" aparece automaticamente nas demais.

## [1.6.27] - 2026-10-27
### Changed
- Manual: conteúdo bem mais detalhado — passo a passo completo de todo botão/campo do Planejador (parâmetros avançados, editar item, tecidos, ordem dos tecidos, pedaços de tecido) e da Operação (detecção automática de máquina, duplicidade, log adicional, edição em lote), filtros e abas de Registros, e um tópico novo dedicado ao editor visual de "Tipos de impressão" (antes só tinha um resumo em Configurações).

## [1.6.26] - 2026-10-27
### Changed
- Operação → importar logs: quando o computador de origem bate, sem ambiguidade, com uma impressora cadastrada (campo "Computador desta impressora"), a máquina é usada direto — não abre mais o diálogo "Selecionar máquina" pra confirmar. O status mostra "(detectada automaticamente)" nesse caso. Sem detecção (computador não cadastrado, ou logs de mais de um computador no mesmo lote), o diálogo continua aparecendo normalmente.

## [1.6.25] - 2026-10-27
### Added
- Operação: novo botão "Abrir comprovante", ao lado de "Fechar Rolo"/"Atualizar Rolo" — abre direto o PDF que acabou de ser gerado, sem precisar ir em Registros de produção. Fica desativado até fechar ou atualizar o rolo nessa sessão, e volta a ficar desativado em "Mais ações → Limpar".
### Fixed
- Tela "Manual": corrigido `ModuleNotFoundError: No module named 'modules.manual'` no .exe empacotado — o módulo não estava na lista de hiddenimports do PyInstaller, então não ia parar dentro do build (só funcionava rodando via `python Nexor.py`).

## [1.6.24] - 2026-10-26
### Added
- Operação → "Detalhes do bloco": agora é possível selecionar vários arquivos de uma vez (Ctrl+clique ou Shift+clique) e abrir "Observação…" pelo botão direito pra gravar a mesma anotação em todos eles de uma vez, em vez de repetir arquivo por arquivo.

## [1.6.23] - 2026-10-26
### Added
- Gerenciamento → Impressoras: novo campo "Computador desta impressora" (nome do PC que gera os logs dela — botão "Detectar de um log…" preenche sozinho a partir de um arquivo .txt de exemplo). Com isso cadastrado, a Operação sugere automaticamente a máquina certa ao importar logs, em vez do operador ter que escolher na mão toda vez — detecta pelo campo "ComputerName" dentro do log.
- Configurações → Diretório de trabalho: novo campo "Identificador deste computador" (ex.: PC1, PC2), salvo localmente em cada PC. Quando preenchido, entra no fim do nome do rolo gerado automaticamente (ex.: M1_26-10-2026_0046_PC1) — reforço extra contra dois computadores fecharem rolos com o mesmo número ao usar o Nexor em rede com mais de um PC apontando pro mesmo banco de dados compartilhado.

## [1.6.22] - 2026-10-26
### Changed
- Operação → "Editar pedido"/"Editar tecido" (grupo com mais de um arquivo de origem): trocado o fluxo de "selecionar arquivo(s) → digitar nome → Aplicar → repetir → Fechar" por um formulário com um campo de nome por arquivo, todos visíveis de uma vez — corrige todos e clica em "Salvar" uma única vez, sem precisar repetir o ciclo pra cada arquivo.

## [1.6.21] - 2026-10-26
### Fixed
- Operação → "Editar pedido" e "Editar tecido": quando o grupo juntava mais de um arquivo de origem diferente (ex.: vários pedidos detectados como "DESCONHECIDO" que na verdade eram pedidos distintos), renomear salvava o mesmo nome novo pra TODOS os arquivos do grupo de uma vez. Agora, nesse caso, o diálogo lista os arquivos distintos do grupo e deixa selecionar um ou mais e aplicar um nome só a eles, documento por documento, até fechar — permitindo corrigir cada pedido/tecido individualmente.
- Operação, Planejador e outras telas roláveis: ao rolar a roda do mouse sobre um diálogo aberto (ex.: Editar pedido), a página por trás também rolava junto (sem o operador perceber, já que o diálogo cobre a tela), e ao fechar o diálogo sobrava um espaço em branco no topo da página. Corrigido ignorando o scroll da página enquanto um diálogo modal estiver aberto.

## [1.6.20] - 2026-10-23
### Added
- Nova seção "Manual", no menu lateral (abaixo de Gerenciamento) — explica passo a passo como usar o Planejador, a Operação e os Registros de produção, pra que serve cada opção de Configurações, os cadastros de Impressoras/Tecidos/Pedaços de tecido, e tira dúvidas comuns (o que é ESPAÇO, aviso de duplicidade, diferença entre "Fechar Rolo" e "Atualizar Rolo" etc.).

## [1.6.19] - 2026-10-23
### Changed
- Configurações → Operação: nova opção "Agrupar espaços consecutivos no Resumo", na seção "Arquivos de espaço". Desmarcada (padrão, comportamento da versão anterior): cada avanço (ESPAÇO) aparece numa linha no Resumo dos Registros. Marcada: avanços seguidos — sem nenhum tecido real entre eles na sequência do rolo — somam numa única linha; um avanço separado de outro por um tecido real continua em linha própria mesmo assim.

## [1.6.18] - 2026-10-23
### Changed
- Configurações: "Modo do PDF" e "JPG espelhado" eram configurados duas vezes (uma em Operação, outra em Planejador) e podiam ficar dessincronizados. Agora é uma única seção "Exportação", global para os dois módulos.
- Removida a opção "Usar pasta/arquivo da impressora para o JPG espelhado" — isso já é decidido automaticamente pelo cadastro de cada impressora (pasta/arquivo de saída do JPG, em Impressoras): se a impressora usada tiver isso configurado, o JPG espelhado vai direto pra lá; senão, usa a pasta padrão do módulo.
- Registros de produção: no Resumo, os avanços entre tecidos (ESPAÇO) de rolos da Operação não entram mais agrupados num total único — ficam listados item a item, porque os operadores da calandra conferem um por um e um total agrupado confundia a contagem. Tecidos continuam agrupados por metragem, normalmente.

## [1.6.17] - 2026-10-23
### Changed
- Operação e Planejador: removido o diálogo "Exportar rolo" — o botão de destaque na tela principal agora é "Fechar Rolo" (ou "Atualizar Rolo" ao editar um rolo já registrado) e já gera o PDF normal + JPG espelhado e grava no banco direto, sem precisar abrir nenhuma janela. As exportações parciais (só PDF ou só JPG) saíram de tela; "Fechar Rolo" sempre gera os dois.
- Os botões "Abrir pasta PDF (comprovantes)" e "Abrir pasta JPG" que ficavam no diálogo removido passaram para Configurações, na seção de exportação de cada módulo (Operação e Planejador).

### Added
- Registros de produção: novo botão "Abrir comprovante", ao lado de "Editar rolo" — abre direto o PDF do rolo selecionado na lista.

## [1.6.16] - 2026-10-22
### Fixed
- Operação: rótulos "Qtd Pedidos" (Resumo por tecido) e "Qtd Peças" (Pedidos no rolo) — no PDF e nas telas — estavam errados, já que a contagem é sempre de arquivos/jobs, não de pedidos nem de peças (ex.: 1 pedido com 3 arquivos aparecia como "3" em "Qtd Pedidos"). Renomeados para "Arquivos" em todos os lugares (PDF "Ordem do Rolo", lista de tecidos, lista de pedidos e título de detalhe do tecido).

## [1.6.15] - 2026-10-22
### Changed
- A opção "Orientação do JPG" (0°, 90°, 180°, 270°) virou um campo por impressora no cadastro de Impressoras, em vez de um único padrão global em Configurações — cada máquina pode precisar do JPG girado de um jeito diferente.

## [1.6.14] - 2026-10-21
### Added
- Nova opção "Orientação do JPG" (0°, 90°, 180°, 270°) para o JPG de registro da impressora — antes saía sempre na mesma orientação (0°), agora dá pra girar conforme o que a impressora espera receber. (Na v1.6.15 essa opção foi movida para o cadastro de Impressoras, por máquina.)

## [1.6.13] - 2026-10-21
### Added
- Configurações → Tipos de impressão: cada regra ganhou a opção "Nome do pedido" — "Detectar pelo nome do arquivo" (padrão, comportamento de sempre) ou "Nome fixo", com um nome configurável pra usar em todo arquivo daquele tipo (ex.: Reposição → sempre "Variados", em vez de ficar "DESCONHECIDO" quando o nome do arquivo não tem pedido de verdade). A lista de regras mostra o modo escolhido em cada uma.

## [1.6.12] - 2026-10-21
### Added
- Configurações → Tipos de impressão: cada regra (Pedido, Reposição, ...) ganhou a opção "Avisar duplicidade entre rolos" — controla se itens desse tipo entram na verificação de pedido+tecido já impresso em outro rolo. Vem desligada de fábrica para Reposição (o nome do arquivo quase sempre se repete entre reposições, o que gerava aviso o tempo todo sem necessidade) e ligada para Pedido; totalmente ajustável por tipo na lista de regras.

## [1.6.11] - 2026-10-20
### Changed
- Operação: "Editar tecido" e "Editar pedido" agora mostram, dentro do próprio diálogo, a lista dos arquivos de origem daquele grupo (com contagem quando repetido) — antes, ao corrigir um "DESCONHECIDO" causado por erro de digitação no nome do arquivo, não tinha como saber a qual arquivo aquele nome se referia só pelo diálogo de renomear.

## [1.6.10] - 2026-10-18
### Added
- Operação: ao importar logs de uma impressora com "Log adicional" habilitado, se a pasta configurada não tiver nenhuma linha no formato esperado (log diário no mesmo padrão da M1), o Nexor não fica mais mostrando "sem correspondência" silenciosamente pra tudo — avisa "formato do log adicional não reconhecido" na barra de status e na coluna de impressão, pra ficar claro que a pasta apontada provavelmente está errada.
- Registros: a lista de rolos exportados ganhou a coluna "Observações", com a contagem de itens anotados ("📝 3") — dá pra ver de cara quais rolos têm alguma observação registrada sem abrir cada um.

## [1.6.9] - 2026-10-18
### Changed
- Gerenciar Impressoras: nova opção "Log adicional" por máquina — quando marcada, informa a pasta de um log diário externo (como o da M1) e a Operação passa a cruzar os dois logs automaticamente para confirmar a impressão real, em qualquer impressora cadastrada assim (antes era fixo pra "M1"). A pasta que antes ficava em Configurações → Operação saiu de lá; quem já tinha configurado precisa reconfigurar em Gerenciar Impressoras → "Log adicional".

## [1.6.8] - 2026-10-18
### Added
- Operação e Planejador: o operador agora pode anotar observações livres em qualquer item (ex.: "o papel manchou aqui"). Em Operação, clique duas vezes (ou botão direito → "Observação…") num item em "Detalhes do bloco"; em Planejador, abra "Editar item…" (duplo clique ou botão direito) na fila de impressão. As observações aparecem numa coluna própria nas duas telas e ficam salvas junto do rolo no banco — continuam visíveis depois de reabrir o rolo para edição ou consultar em Registros.

## [1.6.7] - 2026-10-18
### Added
- Operação: verificação de impressão real da M1. A M1 só registra o processamento (RIP) no log .txt de cada arquivo — quem realmente comanda a impressora e sabe se deu erro é outro programa, que grava um log diário próprio. Configurações → Operação ganhou um campo pra apontar a pasta desse log diário; ao importar logs de M1, cada arquivo é cruzado com ele (pelo horário em que o processamento terminou — vários arquivos processados em sequência são enviados juntos num mesmo lote físico à impressora, então o resultado do lote vale para todos os arquivos dele) e aparece uma coluna "Impressão (M1)" em "Detalhes do bloco", além de um aviso na barra de status quando algum lote veio com erro.

## [1.6.6] - 2026-10-16
### Added
- Configurações → Tipos de impressão: o editor de padrão (Nova/Editar) agora tem dois modos. **Simples** (padrão ao criar um tipo novo): só pede Tipo, Correspondência e uma palavra-chave que deve aparecer no nome do arquivo — sem exemplos nem regex. **Avançado** (botão "Modo avançado ▸"): o fluxo completo de exemplos → estrutura sugerida → regex, como já era. Uma regra existente reabre no modo certo automaticamente (simples se for só uma palavra-chave, avançado se tiver mais partes ou regex manual); ao trocar de simples pra avançado, a palavra-chave já digitada vira o primeiro exemplo.

## [1.6.5] - 2026-10-16
### Changed
- Configurações: a opção "Usar pasta/arquivo da impressora para o JPG espelhado" saiu dos diálogos de exportação do Planejador e da Operação e virou um padrão salvo em Configurações (junto de "Modo do PDF" e "JPG espelhado"), igual já era feito com os outros padrões de exportação. Os diálogos de exportação agora só mostram o botão de exportar e um resumo somente leitura (incluindo se vai usar a pasta da impressora), com "altere em Configurações".
- Operação e Planejador: o botão "Mais ações ▾" saiu do rodapé da tela (abaixo das listas/tabelas, de difícil percepção) e foi para o cartão principal do topo ("Rolo" em Operação, "Planejamento" em Planejador), ao lado do botão de ação principal.

## [1.6.4] - 2026-10-16
### Changed
- Configurações: removidos os cartões "Impressoras" e "Tecidos e aproveitamento" — eram duplicata exata dos atalhos já sempre visíveis no menu lateral ("Gerenciamento"); ficou só um aviso apontando pra lá.
- Configurações: a grade de temas ("Aparência") agora vem recolhida por padrão, atrás de "Mudar tema ▸" — é uma escolha ocasional e estava empurrando o resto da página pra baixo. O nome do tema atual continua sempre visível.
- Configurações: removido o botão "Editar selecionada" de Tipos de impressão — duplo clique na regra já abria o editor (como nas demais listas do app); a dica "duplo clique para editar" foi pro rótulo da lista.

## [1.6.3] - 2026-10-16
### Fixed
- O botão "Mais ações ▾" (Operação e Planejador) não tinha estilo próprio definido no tema — ficava com a aparência padrão clara do Windows (destoando do resto da tela escura) e virava branco ao passar o mouse por cima. Agora usa o mesmo visual dos demais botões, em todos os temas.

## [1.6.2] - 2026-10-16
### Changed
- Planejador: removido o indicador de etapas "1 Arquivos · 2 Configuração · 3 Fila e rolos · 4 Exportação" no topo da tela — era somente decorativo (não navegava nem refletia o passo atual) e não orientava o fluxo de trabalho.
- Operação: mesma reorganização visual já feita no Planejador. O cartão "Nome do rolo e opções de exportação" (10 botões + checkbox) e o cartão separado de arrastar-e-soltar viraram um único cartão "Rolo", com nome do rolo, máquina, o aviso de arrastar-e-soltar e o resumo de modo do PDF/JPG — e um botão "▶ Exportar…" em destaque. A exportação (PDF Normal/JPG Espelhado/Ambos, "usar pasta da impressora", pasta de destino) virou um diálogo próprio, igual ao do Planejador. "Importar pasta", "Abrir pasta PDF/JPG" e "Limpar" foram para um menu "Mais ações ▾" no rodapé. "Editar tecido"/"Editar tipo"/"Editar pedido" saíram da barra de botões — continuam disponíveis por duplo clique (como já era) e agora também por clique direito nas listas "Ordem do rolo" e "Pedidos no rolo".
- Registros: removido o botão "Recarregar" duplicado no cartão de filtros — a ação já existe, sempre visível, no cabeçalho da página ("⟳ Recarregar").

## [1.6.1] - 2026-10-16
### Fixed
- Operação: o tecido identificado no nome do arquivo agora é comparado com o cadastro de "Tecidos e variações" (Configurações), então aliases do mesmo tecido (ex.: "Dryfit", "Dry Fit", "Drifit") são agrupados sob um único nome em vez de aparecerem como tecidos diferentes na fila/resumo. Vale tanto para a importação de novos logs quanto para logs já abertos (reclassificados ao salvar Configurações), respeitando renomeações manuais feitas em "Editar tecido".
- Menu lateral: os atalhos "Tecidos" e "Pedaços de tecido" abriam o respectivo cadastro, mas também trocavam a tela principal para o Planejador — mesmo estando em Operação ou Registros. Agora só o diálogo abre; a tela visível não muda.

## [1.6.0] - 2026-10-15
### Changed
- Planejador: reorganização visual completa da tela, para reduzir a poluição de botões/cartões. De ~23 controles soltos em 6 cartões para 2 cartões no topo ("Planejamento": impressora, tecido, "▶ Gerar planejamento"; "Parâmetros do planejamento": modo, ordem automática, resumo de DPI/gaps, com "Configurações avançadas ▸" escondendo os ajustes de pedaços de tecido cortados), as abas Arquivos/Fila/Rolos/Pedidos já existentes como área principal, e um menu "Mais ações ▾" (Exportar…, Exportar CSV, Recalcular, Salvar/Importar lista, Tecidos…, Ordem dos tecidos…, Pedaços de tecido…, Limpar) no rodapé para o que é usado com menos frequência.
- A exportação (nome do lote, modo PDF/JPG, "usar pasta da impressora", botões Exportar PDF/JPG/Ambos) virou um diálogo próprio ("Exportar…", em Mais ações) em vez de ficar sempre visível na tela.
- "Mover acima/abaixo" saiu da barra de botões — continua disponível pelo menu de contexto (botão direito) da fila, igual já funcionava.
- "Voltar visão base" foi incorporado ao botão da aba "Arquivos" ("Ver arquivos importados").

### Fixed
- Planejador: o aviso "Editando rolo já registrado" (ao reabrir um rolo salvo para edição) podia não aparecer porque a variável de texto não tinha nenhuma referência mantendo-a viva — corrigido escrevendo o texto direto no rótulo.

## [1.5.2] - 2026-10-15
### Changed
- Configurações: os botões "Salvar tipos de impressão", "Salvar padrões da Operação" e "Salvar padrões do Planejador" foram substituídos por um único botão "Salvar todas as configurações" no final da página. Cada seção continua validando os próprios campos (um erro numa seção não impede as demais de salvar).

## [1.5.1] - 2026-10-15
### Added
- Configurações → Operação: cadastro de Operadores (identificador + nome) — o identificador é a letra que aparece no nome do arquivo de reposição (ex.: "N" em "N1 - Dryfit").
- PDF e JPG (modo Completo): nova coluna "Operador" na listagem de pedidos no rolo, identificando quem imprimiu cada reposição a partir do identificador cadastrado.

## [1.5.0] - 2026-10-15
### Added
- Configurações → Tipos de impressão: editor visual de padrão. Em vez de digitar regex, o usuário dá um ou mais exemplos de nome de arquivo e o Nexor sugere a estrutura (texto fixo, texto variável, data, número, letras, letras+número, número+letras, tecido cadastrado, separador) — cada bloco é confirmado/ajustado antes de salvar. A regex continua existindo, mas vira um detalhe técnico gerado automaticamente, com edição manual disponível no modo "Avançado".
- Bloco "Tecido cadastrado": ao invés de aceitar qualquer texto, usa o cadastro de tecidos e aliases do Planejador para montar a regex — e é recalculado contra o cadastro atual a cada classificação, então não fica desatualizado se o cadastro mudar depois.
- Testador de nome de arquivo (Configurações): agora avisa quando mais de uma regra combina com o mesmo nome, e explica que a de cima na lista vence.
- Detecção de conflito: ao salvar um padrão, o Nexor avisa (sem bloquear) se algum dos exemplos informados também combina com outra regra já cadastrada.

### Fixed
- Classificação de tipo de impressão (Pedido/Reposição/Fora do padrão/...) agora ignora a extensão do arquivo (.jpg/.jpeg/.png/...) antes de comparar, em vez de deixá-la vazar para dentro da regra.

### Changed
- Regras antigas (Pedido, Reposição) continuam funcionando exatamente como antes — foram preservadas como "regex avançada" na migração para o novo modelo, sem tentar reinterpretar a estrutura delas.

## [1.4.2] - 2026-10-15
### Changed
- Operação e Planejador: removidos os controles de "Modo do PDF" e "JPG espelhado" (radiobuttons e campo personalizado) das telas — esses padrões já são definidos em Configurações. As telas agora mostram só um resumo somente leitura dos valores em uso, igual ao que já acontecia com DPI/eixo/gaps.

## [1.4.1] - 2026-10-15
### Fixed
- Identificação de tecido em Reposição: arquivos como "N1 - Dryfit (2).jpeg" ou "N1 - Dryfit.jpeg" identificavam o tecido como "DRYFIT (2).JPEG" em vez de "DRYFIT" — a extensão e o que estiver entre parênteses no final (observação ou contador de arquivo duplicado) agora são ignorados na identificação do tecido. O nome completo do arquivo, com a observação, continua aparecendo normalmente nos relatórios.

## [1.4.0] - 2026-10-09
### Fixed
- Tipos de impressão: arquivos de pedido com data só de dia e mês (ex.: "16-10 - Dryfit - Primos e Amigos 3") eram classificados como "Fora do padrão"; agora são "Pedido". A regra antiga salva é atualizada automaticamente.
- Reposição também aceita espaço entre inicial e número (ex.: "N 2 - Aeroready").
- Pedaços de tecido: marcar/desmarcar como usado apagava o Tipo e a Observação do pedaço.

### Added
- Configurações → Tipos de impressão: regras (Pedido, Reposição, ...) e subtipos manuais editáveis direto na página, com teste ao vivo de nome de arquivo.
- Configurações → Operação, Planejador e Registros: padrões de PDF/JPG, arquivos de espaço, DPI, eixo, setup, gaps, rolo padrão, sangria, modo da fila e reclassificação dos registros salvos como "Fora do padrão".
- Pedaços de tecido: botão "Remover tecidos usados".

### Changed
- Operação e Planejador não têm mais os botões "Definir como padrão", "Arquivo(s) de espaço…" e "Tipos de impressão…", nem os campos fixos; o Planejador mostra um resumo dos valores em uso. Ao salvar em Configurações, as telas abertas recarregam sem reiniciar.

## [1.3.3] - 2026-10-09
### Fixed
- Barra de status ocupando a largura toda (antes ficava numa fresta à direita e a página perdia ~1/3 da largura).
- Diálogos com tamanho fixo (Impressoras, Selecionar pedaços) não cortam mais os botões do rodapé em telas com escala do Windows.
- Registros: as abas de detalhes do rolo não ficam mais espremidas/cortadas.
- Configurações agora rola, então todos os cartões continuam alcançáveis.

### Changed
- Temas mais fiéis ao protótipo em todas as telas e nos 8 temas: cartões, abas e diálogos sem faixas de outra cor; botões e campos com borda fina; aba ativa sublinhada; separadores chapados; menu lateral e barra superior no painel (XP com faixa azul e botão verde, Win98 com cabeçalho cinza em relevo).
- Configurações → Aparência: cartões de tema com prévia, descrição e indicação do tema atual.
- Planejador ganhou o indicador de etapas, e a Operação, o aviso sobre a ordem do rolo.

## [1.3.2] - 2026-10-07
### Changed
- Operação: no PDF/JPG do modo Completo, "Pedidos no rolo" agora aparece antes do "Resumo (ordem do rolo)" — o resumo passa a ser o último bloco do relatório.

## [1.3.1] - 2026-10-07

- Ajustes visuais responsivos no Planejador, Operação, Registros e Configurações.
- Reorganização das ações e exportações para evitar cortes horizontais.

## [1.3.0] - 2026-10-06
### Added
- Operação: novo campo **Tipo** por pedido (Pedido / Reposição / Fora do padrão / subtipos manuais), classificado automaticamente pelo nome do arquivo.
- Operação → "Tipos de impressão…": tela para cadastrar as regras de detecção automática (nome + padrão/regex, com ordem de prioridade) e os subtipos manuais usados para marcar o que cai em "Fora do padrão" (Teste, Terceirizado, e outros que você adicionar).
- Operação → "Editar tipo": permite corrigir manualmente o tipo de um pedido específico, escolhendo entre os tipos cadastrados.
- O tipo agora é salvo junto com cada pedido exportado (banco de dados), e o Registros ganhou um filtro "Tipo" para pesquisar rolos já exportados por tipo de impressão.

## [1.2.1] - 2026-10-06
### Added
- Planejador → "Pedaços de tecido…": novos campos **Tipo** e **Observação** no cadastro de cada pedaço cortado.
- Planejador → "Pedaços de tecido…": resumo com a metragem total agrupada por tecido + tipo (ex.: "Dryfit tipo Novo", "Dryfit tipo Antigo").

## [1.2.0] - 2026-10-05
### Added
- Nexor: motor de temas central (`core/theme.py`) com os 8 temas do protótipo HTML — Escuro (padrão), Claro, Meio-termo, Dracula, Nord, Solarized, Windows XP e Windows 98 — com cores extraídas diretamente do `Referencia/nexor-prototipo-download.html`.
- Configurações → "Aparência": grade com os 8 temas (botão de cada um já mostra sua própria paleta), aplica na hora (sem reiniciar), marca o tema ativo com "✓", e persiste em `core/config.py` (`theme_name`), restaurando na próxima abertura.
- O tema se propaga pra toda a aplicação: janelas/diálogos já abertos são recoloridos na hora da troca, e qualquer diálogo novo (de qualquer módulo) já nasce com o tema atual aplicado automaticamente — sem precisar alterar o código de cada diálogo individualmente.
- XP e Windows 98 também mudam acabamento (relevo/borda mais grosso nos botões, fonte Tahoma), não só cores.

## [1.1.1] - 2026-10-05
### Fixed
- Planejador/Operação: corrigida a ordem do JPG combinado (pasta da impressora) — o espelhado agora fica à esquerda e o normal à direita, igual ao modelo de referência atualizado (antes estava invertido)

## [1.1.0] - 2026-10-05
### Added
- Nexor: menu lateral reorganizado em duas seções, como no protótipo de referência — "Produção têxtil" (Planejador, Operação, Registros) e "Gerenciamento" (Impressoras, Tecidos, Pedaços de tecido, Configurações), com atalhos que abrem os cadastros do Planejador direto pelo menu lateral, sem precisar navegar manualmente até lá primeiro.
- Nexor: "Configurações" virou uma página do menu lateral (igual Planejador/Operação/Registros) em vez de um popup — mesmo conteúdo de antes (diretório base do PXCore) mais atalhos para Impressoras/Tecidos/Pedaços cortados. O item de menu "Abrir Configurações" continua funcionando, agora navegando pra essa página.
- Nexor: cabeçalho com indicador da página atual ("Produção / {página}").

## [1.0.0] - 2026-10-05
### Changed — Rebrand para Nexor
- O programa foi renomeado de "Projeto Jocasta"/JocastaHub para **Nexor** (`Nexor.py`, `Nexor.spec`, título da janela, versão).
- O programa agora tem só os 3 módulos da família de impressão, renomeados: **PXPrintLogs → Operação**, **PXPrintCalc → Planejador**, **PXSearchOrders → Registros**. Todos os outros módulos (PXFlow, PXComposer, PXDupe, PXPrint, PXOrderList, PXBridge, PXList e variantes, PXSort e variantes, PXTotaList) foram removidos do programa — o código de todos eles continua preservado em `Legado/snapshot-pre-nexor-2026-10-05/` (cópia completa do projeto como estava antes desta mudança).
- A navegação por abas ("Fluxos de Trabalho") foi trocada por um **menu lateral fixo** com os 3 módulos (Planejador, Operação, Registros). O Modo Dev foi removido (só existia para liberar módulos que não existem mais).
- Configurações já cadastradas (tecidos, pedaços cortados, impressoras, arquivos de espaço, preferências de PDF/JPG) são migradas automaticamente na primeira vez que o Nexor roda — nada precisa ser recadastrado.
- Rolos já exportados antes dessa mudança continuam funcionando normalmente no "Editar rolo" do Registros (compatibilidade com o nome antigo do módulo mantida).

## [0.5.0] - 2026-10-05
### Added
- PXPrintCalc e PXPrintLogs: o nome do rolo/lote agora usa um número sequencial (`M1_05-10-2026_0001`) no lugar do horário — o número é único e nunca se repete, mesmo com vários computadores usando o mesmo banco compartilhado (ver abaixo), já que é gerado de forma atômica no banco de dados. Se não conseguir gerar (ex.: banco inacessível), mostra um erro claro em vez de usar um nome arriscado de duplicar
- JocastaHub: o "Diretório base do PXCore" em Configurações agora é editável (com botão "Procurar…" para escolher uma pasta de rede) — antes só mostrava o valor atual. É o que permite usar o mesmo banco/pastas de PDF-JPG em vários computadores

### Changed
- `core/printlogs_db.py`: trocado o modo de journal do SQLite de WAL para DELETE — WAL depende de memória compartilhada que não funciona de forma confiável em pastas de rede, e o banco agora pode ser apontado para uma pasta de rede compartilhada entre computadores

### Fixed
- `core/config.py`: uma falha ao criar as subpastas padrão (ex.: pasta de rede temporariamente fora do ar) fazia `load_config()` tratar como "config corrompido" e resetar silenciosamente o diretório base pro padrão, apagando a configuração do usuário. Agora essas falhas são ignoradas sem afetar o resto da configuração

## [0.4.14] - 2026-10-05
### Changed
- PXPrintCalc e PXPrintLogs: corrigido o layout do JPG combinado (quando "Usar pasta/arquivo da impressora" está marcado) — o normal (não espelhado) e o espelhado agora ficam lado a lado (normal à esquerda, espelhado à direita), igual ao modelo de referência, em vez de empilhados um embaixo do outro

## [0.4.13] - 2026-10-05
### Changed
- PXPrintCalc e PXPrintLogs: ao exportar o JPG espelhado com "Usar pasta/arquivo da impressora" marcado, o arquivo agora traz o JPG espelhado seguido do JPG normal (não espelhado) num único arquivo — já que é o único arquivo que a impressora recebe. Sem essa opção marcada, a exportação continua normal (só o espelhado, na pasta padrão)

## [0.4.12] - 2026-10-05
### Changed
- PXPrintCalc: se o registro no SearchOrders falhar ao exportar, a mensagem agora mostra o erro completo (traceback) em vez de só o nome do tipo de erro, e se a fila gerada não tiver nenhum item (só espaços) isso agora aparece como aviso em vez de ficar em silêncio

## [0.4.11] - 2026-10-05
### Fixed
- PXPrintCalc: corrigido o planejador do modo "tecido" (bin packing) — quando nenhum item cabia no limite configurado do rolo (ex.: um tecido com metragem de rolo pequena, tipo 1m, combinada com o "Gap antes fim rolo" padrão de 1m), os itens que não cabiam em nenhum rolo eram todos empilhados juntos no último rolo tentado, em vez de cada um ir para o seu próprio rolo. Agora cada item só entra num rolo já aberto se realmente couber nele; senão abre um rolo novo só para ele

## [0.4.10] - 2026-10-05
### Added
- PXPrintCalc: menu de contexto (botão direito) na lista da fila — "Editar item…", "Definir tecido…", "Mover para cima/baixo" (modo original), "Remover item(s)" e "Atualizar"

## [0.4.9] - 2026-10-05
### Added
- PXPrintCalc: em "Selecionar pedaços a usar…", nova opção de "Tamanho exato do pedaço" ou "Sangria" — com sangria ativa, cada pedaço cortado é considerado com alguns cm a mais do que a metragem cadastrada (padrão 5 cm, editável) ao planejar a fila, dando uma tolerância de corte

## [0.4.8] - 2026-10-05
### Fixed
- PXPrintCalc: trocar o "Modo" (original/tecido) agora recalcula a fila na hora — antes, ao voltar de "original" para "tecido", a tabela continuava mostrando o agrupamento e as alças de arraste do modo anterior até clicar manualmente em "Gerar Fila"

## [0.4.7] - 2026-10-05
### Fixed
- PXPrintLogs: no diálogo "Arquivo(s) de espaço…", depois de cadastrar um arquivo, clicar em "Adicionar / Atualizar" de novo sem antes limpar o formulário sobrescrevia o item recém-criado em vez de adicionar um novo. Agora o formulário limpa sozinho após um cadastro novo, e há também um botão "Novo" para começar um cadastro do zero a qualquer momento

## [0.4.6] - 2026-10-05
### Added
- PXPrintCalc: duplo clique numa linha "— ESPAÇO —" da fila agora abre um diálogo para alterar o tamanho daquele espaço específico (padrão continua sendo o valor configurado em "Espaço entre tecidos"/"fim de rolo"), com opção de "Restaurar padrão"

## [0.4.5] - 2026-10-05
### Added
- PXPrintLogs: cada arquivo de espaço cadastrado em "Arquivo(s) de espaço…" agora tem um "Nome de exibição" próprio, mostrado nas listagens (bloco/tecido e detalhe de pedidos) no lugar do nome do arquivo — útil quando há mais de um arquivo de espaço diferente (ex.: "Fim de rolo" vs "Troca de tecido")

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
