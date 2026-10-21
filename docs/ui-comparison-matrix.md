# Matriz visual e funcional — Nexor

Comparação feita em 2026-10-05 a partir de `Referencia/Capturas/html/`,
`Referencia/Capturas/nexor/`, `nexor-prototipo-download.html` e os
inventários `manifesto.json`/`*-controles.json`.

| Módulo/estado | Referência | Programa/inventário | Diferenças corrigidas | Funcionalidade preservada | Situação |
|---|---|---|---|---|---|
| Planejador | `0001-dark-plan.png`, `0005`–`0020` | `dark-planejador-controles.json` e equivalentes por tema | Cabeçalho de página, cartões de configuração/exportação, abas Arquivos/Fila/Rolos/Pedidos, rolagem e espaçamento | Importação, arrastar/soltar, DPI/eixo, fila, espaços, tecidos, pedaços, listas, CSV, PDF/JPG e diálogos | Implementado; captura nova pendente |
| Operação | `0021`–`0032` | `dark-operacao-controles.json` e equivalentes | Cabeçalho, cartão de lote/exportação e agrupamentos mais próximos do protótipo | Parser de logs, máquina, ordem/blocos/pedidos, tecidos, espaços, exportações e atualização do histórico | Implementado; captura nova pendente |
| Registros | `0033`–`0044` | `dark-registros-controles.json` e equivalentes | Cabeçalho, filtros/lista/detalhes com margens e abas preservadas | Busca, limites, seleção, resumo/pedidos/eventos, copiar nome e edição por módulo/legado | Implementado; captura nova pendente |
| Configurações | `0045`–`0053` | `dark-configuracoes-controles.json` e equivalentes | Página com cabeçalho, cartões e grade de temas em 3 colunas | Diretório, impressoras, tecidos, aliases, pedaços e persistência dos oito temas | Implementado; captura nova pendente |
| Diálogos | `0048`–`0058` e variantes por tema | Inventários `*-dialogo-*` | Estilos centralizados, bordas e fontes XP/98, reaplicação em `Toplevel` mapeado | Formulários, validações, espaços, edição, expansão e exportação | Implementado por mecanismo central; captura nova pendente |

## Registro desta revisão (2026-10-06)

Antes desta revisão, a entrega anterior havia declarado shell, cartões e abas
implementados, mas a composição ainda era parcial: os cartões eram
`ttk.LabelFrame` legados, os módulos mantinham faixas horizontais e widgets
Tk clássicos não eram repintados quando a página era criada depois do tema.
O código copiado em `Referencia/Capturas/nexor/ambiente-isolado-*/projeto`
tem o mesmo SHA-256 de `Nexor.py` atual; portanto, as capturas realmente
correspondem ao código avaliado. O `config.json` do capturador tem
`theme: "auto"`, mas o Nexor usa `PXCoreConfig.theme_name` (padrão `dark`)
e os PNGs foram separados por tema. Não foi encontrada configuração oculta
que explique a diferença estrutural.

Imagens abertas e comparadas nesta revisão:

- `nexor/0001-dark-planejador.png` ↔ `html/0001-dark-plan.png`
- `nexor/0018-dark-planejador-dialogo-impressoras-0-gerenciar-impressoras.png` ↔ `html/0048-dark-dialogo-printers.png`
- `nexor/0077-light-planejador.png` ↔ `html/0059-light-plan.png`
- `nexor/0229-dracula-planejador.png`
- `nexor/0028-dark-operacao.png` ↔ `html/0021-dark-ops.png`
- `nexor/0049-dark-registros.png` ↔ `html/0033-dark-records.png`
- `nexor/0062-dark-configuracoes.png` ↔ `html/0045-dark-settings.png`
- `nexor/0021-dark-planejador-dialogo-tecidos-0-cadastro-de-tecidos-e-variacoes.png` ↔ `html/0050-dark-dialogo-fabrics.png`
- `nexor/0457-xp-planejador.png` ↔ `html/0349-xp-plan.png`
- `nexor/0407-solarized-planejador-dialogo-pedacos-de-tecido-0-pedacos-de-tecido-cortados.png` ↔ `html/0052-dark-dialogo-scraps.png` (comparação de estrutura de diálogo; tema intencionalmente diferente)

As alterações desta revisão cobrem o shell, as quatro páginas, tabelas,
abas, espaçamento, tokens, widgets Tk clássicos e diálogos modais. O overlay
web foi adaptado para Tkinter com `transient`, `grab_set`, foco inicial,
Escape e fechamento pelo protocolo da janela; não há overlay alfa nativo
portável no Tkinter sem alterar a janela principal.

## Limitações das referências

- A referência HTML registrou 475 eventos OK e 17 falhas. As falhas de
  `fabric-order`/`scrap-selection` ocorreram por controles fora da área
  visível; a falha de JavaScript veio do payload de captura.
- O manifesto do programa registra 666 eventos OK e 3 pendentes: dois
  estados de arquivo de espaço sem `Toplevel` aberto e os estados não
  visitados automaticamente (menus contextuais, erros, duplo clique,
  vazio e ações de salvar/exportar/imprimir).
- Não foi possível gerar novas capturas: além de não haver Xvfb/Chromium,
  o Python local falha ao iniciar Tkinter com `Can't find a usable init.tcl`.
  Assim, a validação visual final pós-alterações permanece **pendente**;
  os prints anteriores comprovam apenas o diagnóstico pré-alteração.

## Verificações executadas

- `python -m unittest discover -s tests -v` — 3 testes OK.
- `python -m compileall -q Nexor.py core modules` — OK.

## Revisão visual `nexor_3` (2026-10-07)

Inventário: 1.217 PNGs em `Referencia/Capturas/nexor_3/` e 467 em
`Referencia/Capturas/html/`. Imagens efetivamente abertas: `nexor_3/0001-dark-planejador.png`,
`0004-dark-planejador-area-0-y-03.png`, `0014-dark-planejador-aba-0-1-fila-de-impressao-area-0-y-03.png`,
`0038-dark-operacao.png`, `0048-dark-operacao-area-2-y-08.png`, `0103-dark-registros.png`,
`0119-dark-configuracoes.png`, os diálogos `0025`, `0028`, `0034`, `0035`, `0096`, `0099` e `0115`,
e as oito telas de tema `0001`, `0137`, `0273`, `0409`, `0545`, `0681`, `0817` e `1086`.
As referências HTML abertas foram `0001-dark-plan.png`, `0059-light-plan.png`, `0117-mid-plan.png`,
`0175-dracula-plan.png`, `0233-nord-plan.png`, `0291-solarized-plan.png`, `0349-xp-plan.png`,
`0407-win98-plan.png`, `0021-dark-ops.png`, `0033-dark-records.png` e `0045-dark-settings.png`,
além dos diálogos `0048`, `0050` e `0052`.

Depois dessas capturas, corrigi o overflow horizontal das ações do Planejador e da Operação,
separei campos e exportações em linhas próprias, converti agrupamentos de registros/configurações
para cartões e alinhei a ordem da página de configurações ao protótipo. A matriz responsiva recebeu
teste automatizado.

As imagens acima comprovam o diagnóstico pré-alteração. Não foram geradas novas capturas depois
dos ajustes; portanto a fidelidade visual final, inclusive todos os estados de erro, menus,
duplo-clique e exportações, permanece pendente. Os 1.217 arquivos foram inventariados, não abertos
individualmente.

Verificações desta revisão: `python -m unittest discover -s tests -v` (5 OK),
`python -m compileall -q Nexor.py core modules` (OK), `git diff --check` e
`git diff --cached --check` (OK; staging preservado).
- Importação dos quatro pontos de entrada Python — OK.
- Smoke check de conversão/formatadores do Planejador e parser — OK.

## Revisão visual `nexor_4` (2026-10-09)

### Base comprovada

- `Referencia/Capturas/nexor_4/`: 1.081 PNGs, mas só 1.018 estados distintos. Há
  63 estados do tema escuro com dois arquivos, porque houve duas rodadas
  (12:40 e 12:43). Na segunda, o diálogo "Ordem dos tecidos" foi inserido como
  `0032` e deslocou a numeração. Quando há duplicata, vale o arquivo mais
  recente. O `manifesto.json` (última rodada, 1.030 eventos) tem 1.028 OK e 2
  pendentes: o `xp` "Arquivo(s) de espaço" não abriu `Toplevel`, e menus,
  erros, duplo clique e estados vazios não foram visitados.
- `Nexor.py`, `core/ui.py`, `core/theme.py`, `modules/planejador.py`,
  `modules/operacao/ui.py`, `modules/registros/ui.py` e `core/version.py` dos
  três `ambiente-isolado-*` têm o mesmo SHA-256 que o working tree antes desta
  revisão. Portanto, os prints mostram exatamente a entrega `nexor_3`.

Imagens efetivamente abertas (a comparação foi lado a lado com a referência):

| `nexor_4` | Referência `html/` |
|---|---|
| `0001-dark-planejador.png` (também ampliado em 2×) | `0002-dark-plan-pagina-y0.png` |
| `0003-dark-planejador-area-0-y-02.png` | `0003-dark-plan-pagina-y600.png` |
| `0036-dark-operacao.png` | `0022-dark-ops-pagina-y0.png` |
| `0060-dark-registros.png` | `0034-dark-records-pagina-y0.png` |
| `0108-dark-configuracoes.png` | `0046-dark-settings-pagina-y0.png` |
| `0023-dark-planejador-dialogo-impressoras-0-gerenciar-impressoras.png` | `0048-dark-dialogo-printers.png` |
| `0026`, `0029` (tecidos), `0032` (ordem), `0033` (pedaços), `0035` (selecionar pedaços), `0112` (impressoras via Configurações) | — (mosaico) |
| `0751-xp-planejador.png` | `0349-xp-plan.png` |
| `0892-win98-planejador.png` | `0407-win98-plan.png` |

Também foi lido o CSS do protótipo `nexor-prototipo-download.html`: `.nx-side`,
`.nx-top`, `.nx-button`, `input`, `.nx-tabs`, `th`, `.nx-panel`, `.nx-dialog`,
`.nx-status`, `.nx-theme-choice` e as regras `xp`/`win98`. Os demais 1.000+
PNGs foram inventariados por nome e horário, sem abertura individual. Os temas
`light`, `mid`, `dracula`, `nord` e `solarized` de `nexor_4` **não** foram
abertos.

### O que os prints de `nexor_4` mostram (diagnóstico antes das correções)

| # | Problema visto em `nexor_4` | Evidência | Correção posterior aos prints |
|---|---|---|---|
| 1 | A barra de status ficava numa fresta à direita, e a página não usava cerca de 1/3 da largura | `0001`, `0036`, `0108` (área vazia à direita, "Pronto" no canto) | `Nexor.py`: status e separador são empacotados antes do conteúdo |
| 2 | Labels, checkbuttons e frames dentro de cartões usavam `--n-bg`, formando faixas de outra cor no cartão. Era gritante no Win98, onde o teal aparecia dentro do cinza | `0001` ampliado, `0892` | `core/theme.py`: a varredura sabe o contexto (cartão/aba/diálogo → `--n-panel`) e troca o estilo padrão por `Panel.*` |
| 3 | Botões sem borda: pareciam texto solto | `0001` ampliado, `0060` | `relief="solid"` com borda `--n-line` (o `flat` do clam suprime a borda) |
| 4 | Campos, combobox, tabelas e Listbox com contorno claro/branco | `0001`, `0023`, `0032` | `lightcolor`/`darkcolor`/`bordercolor` explícitos, inclusive nos `style.map` de foco do clam; Listbox/Text sem relevo |
| 5 | Abas em caixa com bordas claras, sem o sublinhado da aba ativa | `0003`, `0060` | Elemento de imagem `NxTab.underline` com 2 px em `--n-brand`; os mapas de relevo do clam foram sobrescritos. XP/98 mantêm abas em caixa |
| 6 | Separadores em relevo 3D: linha clara nos temas escuros | `0001` (linha sob "Arraste e solte") | `TSeparator` passou a ser uma linha chapada `--n-line` |
| 7 | Menu lateral sobre `--n-bg`, itens em `--n-text`, ativo sem `--n-brand`, recuos inconsistentes e separador extra | `0001`, `0036`, `0060` | Lateral em `--n-panel`, itens em `--n-muted`, ativo `--n-brand-soft`/`--n-brand`, sem separador entre as seções |
| 8 | Barra superior sem painel; trilha "Produção / X" toda em negrito; XP/98 sem faixa azul | `0001`, `0751`, `0892` | `Top.*`: trilha com "Produção /" em `--n-muted`; XP `#0052d6` e 98 `#000080` (cor sólida no lugar do gradiente) |
| 9 | Botão principal igual em todos os temas (XP não era verde) | `0751` | Token `primary_bg` (XP verde, 98 cinza com contorno) |
| 10 | Diálogos com `geometry()` fixa cortavam o rodapé: Impressoras sem Nova/Salvar/Remover/Fechar e Selecionar pedaços com Cancelar/Salvar cortados | `0023`, `0112`, `0035` | `theme.fit_to_content`: no primeiro mapeamento o diálogo só **cresce** até o tamanho pedido pelo conteúdo, limitado à tela |
| 11 | Diálogos com fundo `--n-bg` e título em caixa de outra cor | `0023`, `0026`, `0033` | `Toplevel` usa contexto `--n-panel`; `dialog_header` usa `PanelTitle` e separador |
| 12 | Grade de temas com blocos chapados, sem prévia, descrição ou "Tema atual"; ordem diferente da grade do protótipo | `0108` | Cartões com prévia desenhada, nome, descrição, ✓ e borda de destaque; ordem `theme_keys_for_picker()` |
| 13 | Abas de detalhes do Registros cortadas na vertical | `0060` | A ordem do pack reserva altura para os detalhes; as alturas das listas foram reduzidas |
| 14 | Win98: título e subtítulo da página ilegíveis sobre o teal | `0892` | `Head.TFrame`: caixa cinza em relevo com padding (`.nx-head`) |
| 15 | Faltavam o indicador de etapas do Planejador e o aviso informativo da Operação | `0001` × `0002`, `0036` × `0022` | `step_indicator` e `info_banner` em `core/ui.py` (estáticos, sem lógica nova) |

Como `nexor_4` foi capturado do código já com as correções da revisão
`nexor_3`, esses prints confirmam que aquelas correções entraram: as ações do
Planejador e da Operação quebram linha sem overflow horizontal, e Registros e
Configurações usam cartões. Os 15 defeitos acima continuavam presentes depois
delas. As imagens de `nexor_3` não foram reabertas nesta revisão.

### Regressão evitada nesta revisão

Com as prévias, a grade de temas ficou mais alta e empurraria "Diretório de
trabalho", "Impressoras" e "Tecidos" para fora da janela, porque a página de
Configurações não rolava. A página agora usa `page_scroll_container`, que
ganhou rolagem pela roda do mouse.

### Verificação local depois das alterações (não substitui nova captura)

Para conferir as alterações, rodei o Nexor do working tree com um `APPDATA`
isolado, copiado do perfil de `nexor_4` (a configuração real do usuário não
foi tocada), em 1280×800 com DPI-aware. Foram gerados 96 PNGs: 8 temas × (4
páginas no topo + 4 roladas + Impressoras, Tecidos, Pedaços e Selecionar
pedaços). Ficaram no scratchpad da sessão, fora do repositório. Abri os de
`dark` (todas as páginas e os quatro diálogos), `light` (Planejador), `xp`
(Planejador), `win98` (Planejador, Configurações topo/rolada, Operação),
`mid` (Operação), `dracula` (Registros), `nord` (Planejador rolado) e
`solarized` (diálogo Tecidos). Neles, os itens 1–15 aparecem corrigidos. Esses
prints locais **não** passam pelo capturador oficial e não cobrem "Ordem dos
tecidos", que exige imagens importadas e abre `messagebox`. Por isso, as
alterações continuam **pendentes de nova rodada de capturas** (`nexor_5`).

### Pendências conhecidas (não corrigidas)

- Ícones de linha do menu lateral (SVG no protótipo) não foram implementados.
- Composição do Planejador: o protótipo põe "Configuração de impressão"
  primeiro, com rótulos acima dos campos em 4 colunas, "Ajustes" recolhível, a
  barra de ferramentas dentro do cartão das abas e as métricas
  Arquivos/Comprimento/Tempo. O Nexor mantém o cartão "Ações do planejamento" e
  a sequência de cartões atual.
- Composição da Operação: falta o cartão "Lote carregado" com métricas e ações
  e as opções de exportação recolhíveis. Os controles seguem no cartão denso
  atual.
- Registros: rótulos dos filtros acima dos campos, botão principal "Buscar",
  cabeçalho do rolo selecionado com "Copiar nome"/"Editar rolo" e Resumo em
  fonte proporcional (ainda é `Text` monoespaçado).
- Limitações do Tkinter/ttk sem substituto equivalente: cantos arredondados,
  título do cartão dentro de um cabeçalho separado (o `Labelframe` desenha o
  título sobre a borda), gradientes XP/98, etiquetas coloridas (tags) dentro da
  `Treeview`, overlay escurecido atrás dos modais e fonte Inter 14 px.
- Estados não visitados pelo capturador (menus, erros, duplo clique, vazio,
  salvar/exportar) e o `xp` "Arquivo(s) de espaço" continuam sem evidência.

### Verificações desta revisão

`python -m unittest discover -s tests` (7 OK, 2 novos contratos de tema),
`python -m compileall -q Nexor.py core modules` (OK), `git diff --check` (OK).
O staging foi preservado: o índice estava vazio antes e continua vazio; não
houve commit nem push.
