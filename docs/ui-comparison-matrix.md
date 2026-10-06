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
- Importação dos quatro pontos de entrada Python — OK.
- Smoke check de conversão/formatadores do Planejador e parser — OK.
