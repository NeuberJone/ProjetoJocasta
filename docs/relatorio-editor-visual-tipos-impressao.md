# Relatório — Editor visual de "Tipos de impressão"

Data: 2026-10-15
Versão do Nexor após a mudança: **1.5.0**

## 1. O que foi pedido

Substituir o cadastro manual de regex na tela **Configurações → Tipos de
impressão** por um fluxo visual: o usuário dá exemplos de nome de arquivo, o
Nexor sugere uma estrutura (blocos com significado conhecido), o usuário
confirma/ajusta cada bloco, e só então a regex é gerada — a regex deixa de
ser a forma principal de cadastro e vira um detalhe técnico, ainda editável
num modo avançado.

## 2. Arquitetura — onde cada coisa foi parar

Antes de implementar, localizei:

- **Tela atual**: `modules/configuracoes.py`, função `build_print_types_section`
  (cadastro de regras) — é onde a UI nova entra.
- **Serviço de classificação**: `core/print_types.py`, função
  `classify_document` (primeira regra que bate vence; usado por
  `modules/operacao/parser.py::tipo_from_document` e pela própria tela de
  Configurações).
- **Persistência**: `modules/operacao/config.py` (`load_cfg`/`save_cfg`) →
  `core/config.py` (`read_module_cfg`/`write_module_cfg`) grava JSON em
  `cfg["print_type_rules"]`. Formato antigo: lista de `{"name", "pattern"}`.
- **Testes existentes**: `tests/test_print_types.py` (regras de fábrica,
  `classify_document`, migração de padrão legado).
- **Tecidos e aliases**: definidos dentro de `modules/planejador.py`
  (`load_fabrics`, `fabric_aliases`, `FabricEntry`...), usados só ali.

### Problema de import circular e a extração para `core/fabrics.py`

`modules/planejador.py` importa de `modules/operacao/parser.py`
(`pedido_from_document`). Como o novo bloco "Tecido" do padrão de impressão
precisa consultar o cadastro de tecidos **dentro da classificação**
(`core/print_types.py`, usada por `modules/operacao/parser.py`), importar o
cadastro diretamente de `modules/planejador.py` criaria um ciclo
(`planejador → operacao.parser → print_types → planejador`).

Solução: o cadastro de tecidos (código, não dados) foi movido para
`core/fabrics.py` (camada sem dependência de nenhum módulo de UI).
`modules/planejador.py` agora importa de lá e **reexporta os mesmos nomes**
(`load_fabrics`, `FabricEntry`, `fabric_aliases`, `infer_fabric_from_filename`,
etc.) — nenhum código que já usava essas funções via `modules.planejador`
precisou mudar. O arquivo de dados (`%APPDATA%/Nexor/Planejador/fabrics.json`)
não mudou de lugar nem de formato.

### Módulos novos

| Arquivo | Responsabilidade |
|---|---|
| `core/fabrics.py` | Cadastro de tecidos/aliases (extraído de `modules/planejador.py`). Novo: `known_fabric_names_with_aliases()`, usado pelo compilador do bloco Tecido. |
| `core/print_pattern.py` | **Modelo** (`Component`, tipos de bloco) + **compilador** (`compile_component`/`build_pattern`: componentes → regex) + migração de regra antiga → nova (`migrate_rule_dict`) + `resolve_pattern` (regera a regex a partir dos componentes, sempre que a regra não é "regex personalizada"). |
| `core/print_pattern_analyzer.py` | **Analisador de exemplos**: dado 1+ exemplos, sugere a sequência de blocos, com um nível de confiança por bloco (nunca decide sozinho — só sugere). |
| `core/print_types.py` | **Serviço de classificação** (já existia): `classify_document` (ganhou extensão removida + modo de correspondência + bloco Tecido dinâmico), mais novo: `matching_rules`, `classify_with_detail` (testador), `detect_conflicts` (detector de conflito). |
| `modules/configuracoes.py` | **UI**: `open_pattern_editor` (o modal novo) + `build_print_types_section` atualizada para abrir o modal em vez do formulário de duas colunas. Não tem regra de negócio — só monta a tela e chama as funções de `core/`. |

## 3. O modelo de componente

Cada regra passou a ter este formato (persistido como dict JSON, compatível
com o arquivo de configuração já existente):

```json
{
  "id": "156a3ad5609d",
  "name": "Amostra",
  "pattern": "^\\s*Amostra\\s*-\\s*.+\\s*-\\s*(?:Dryfit|dryfit|...)",
  "match_mode": "start",
  "components": [
    {"kind": "texto_fixo", "value": "Amostra"},
    {"kind": "separador", "value": "-"},
    {"kind": "texto_variavel"},
    {"kind": "separador", "value": "-"},
    {"kind": "tecido"}
  ],
  "examples": ["Amostra - Pedido ABC - Poliamida"],
  "custom_regex": false,
  "active": true
}
```

Tipos de bloco implementados (todos compilam para regex em
`core/print_pattern.py::compile_component`):

| Bloco | Regex gerada |
|---|---|
| Texto fixo | o texto, escapado literalmente |
| Texto variável | `.+` |
| Data | `\d{1,2}[-/.]\d{1,2}` |
| Número | `\d+` |
| Letras | `[A-Za-z]+` |
| Letras + número | `[A-Za-z]+\s*\d+` (sem limitar a 1 letra — "N1", "NJ2", "AB15" batem) |
| Número + letras | `\d+\s*[A-Za-z]+` |
| Tecido | alternância `(?:Dryfit\|dryfit\|Aeroready\|...)` montada a partir do cadastro atual de tecidos+aliases |
| Separador | `-`, `/`, `_` ou espaço, com espaçamento flexível em volta (`A-B`, `A - B`, `A  -  B` todos batem) |
| Opcional | existe no modelo/compilador (`(?:...)?`), **mas não tem seletor na UI ainda** — ver limitações |

Três modos de correspondência por regra (`match_mode`): `start` ("começa
com", o comportamento histórico), `exact` ("exatamente igual") e `contains`
("contém") — usados por `classify_document` pra escolher entre `re.match`
(com ou sem `$` no fim) e `re.search`.

### Bloco "Tecido" é dinâmico, não congelado

`resolve_pattern()` **regera a regex a cada classificação** a partir do
cadastro de tecidos atual, sempre que a regra tem `components` e
`custom_regex` é falso. Se você cadastrar um tecido novo hoje, toda regra
estruturada que usa o bloco Tecido passa a reconhecê-lo na próxima
classificação, sem precisar editar a regra. (Testado em
`tests/test_print_pattern.py::ResolvePatternTests`.)

### Extensão do arquivo

`core/print_pattern.py::strip_extension()` remove a extensão (`.jpg`,
`.jpeg`, `.png`, `.tif`, ...) **antes** de qualquer análise ou classificação.
É usada tanto pelo analisador de exemplos quanto por
`classify_document`/`matching_rules`/`detect_conflicts`. A classificação é
sempre sobre o nome lógico do arquivo.

## 4. O analisador de exemplos (`core/print_pattern_analyzer.py`)

Fluxo: quebra cada exemplo em blocos de conteúdo/separador (`scan_example`),
alinha os exemplos que têm a mesma estrutura (exemplos com estrutura
diferente **não** são misturados silenciosamente — entram como aviso e
ficam de fora da sugestão, mas continuam disponíveis para testar a regra),
e sugere o tipo de cada bloco de conteúdo por posição, com uma ordem de
prioridade conservadora:

1. **2+ exemplos, idênticos nessa posição** → texto fixo (confiança alta).
2. **Todos batem no cadastro de tecidos** → tecido (alta).
3. **Todos seguem um padrão estrutural** (data/letras+número/número+letras/número) → esse tipo (alta).
4. **2+ exemplos, nada bateu** → texto variável (média) — evidência real de variação.
5. **Só 1 exemplo nessa posição**: tecido cadastrado → tecido (alta); padrão estrutural → esse tipo (média); palavra única (sem espaço) → texto fixo (baixa); frase com espaço → texto variável (baixa).

Confiança **baixa** sempre vem com a nota exigida no pedido: *"Não foi
possível identificar esta parte com segurança. Escolha o tipo do bloco."* —
e a UI pede confirmação de **todo** bloco antes de salvar, não só os de
baixa confiança.

Validei isso com os 5 exemplos de referência do pedido — a sugestão bateu
exatamente com a estrutura descrita em cada um (ver seção 7).

## 5. UI — o editor visual (`modules/configuracoes.py::open_pattern_editor`)

Um modal (`Toplevel`, no mesmo padrão dos outros diálogos do Nexor — ex.:
`open_fabrics_dialog` do Planejador) com:

- **Tipo** e **Correspondência** (começa com/exatamente igual/contém) no topo.
- **Exemplos de nome de arquivo**: lista + adicionar/remover. O primeiro
  exemplo já dispara a análise automaticamente; exemplos adicionados depois
  só atualizam a prévia/teste (a estrutura não é refeita sozinha, pra não
  descartar ajustes manuais que você já tenha feito).
- **Estrutura identificada**: uma linha por bloco, com um combobox pro tipo
  do bloco (pré-selecionado pela sugestão) e, para texto fixo, um campo com
  o valor literal. Mostra a confiança/nota quando relevante. Botão
  **"Reanalisar exemplos"** disponível a qualquer momento — se a regra já
  tiver uma regex personalizada, confirma antes de substituir.
- **Prévia da regra**: ✓/✗ de cada exemplo contra a regex atual, a regex em
  si, avisos de estrutura inconsistente, e avisos de conflito com outras
  regras já cadastradas — tudo ao vivo, antes de salvar. Mais um campo
  "Testar nome de arquivo" avulso.
- **Avançado** (oculto por padrão): revela a regex gerada num campo
  editável. Editar manualmente marca a regra como "regex personalizada"
  (`custom_regex: true`) — a partir daí, mudanças na estrutura visual **não**
  regeram a regex sozinhas (fica um aviso visível, e "Reanalisar exemplos"
  pede confirmação antes de substituir).
- **Salvar padrão**: valida tipo e regex, roda a detecção de conflito contra
  as demais regras (não bloqueia — avisa e pede confirmação) e devolve o
  dict final pra tela chamadora.

A tela principal (`build_print_types_section`) ganhou:
- Botões **"Nova"** e **"Editar selecionada"** (+ duplo clique na lista)
  abrindo o modal, no lugar do formulário de Tipo/Padrão.
- Coluna **Origem** na lista (Visual / Regex avançada).
- **Testar nome de arquivo** melhorado: agora mostra quando mais de uma
  regra combina e explica que a de cima na lista vence (via
  `classify_with_detail`).
- **▲ Subir / ▼ Descer / Remover / Restaurar padrão**: inalterados.

## 6. Compatibilidade com regras existentes

`core/print_pattern.py::migrate_rule_dict` converte o formato antigo
(`{"name", "pattern"}`) pro novo, **sem inventar interpretação**: regra
migrada vira `components: null` + `custom_regex: true` — ou seja, continua
sendo a mesma regex, rodando exatamente como antes, só que agora reconhecida
pela UI como "Regex avançada" (editável no modo avançado, com um aviso
explicando que pode ser reconstruída visualmente se o usuário quiser, mas
isso é opt-in, nunca automático).

As duas regras de fábrica (Pedido, Reposição) passam por esse caminho. O
upgrade de padrão legado que já existia (regra de Pedido com ano
obrigatório → regra sem ano) continua funcionando, só que agora dentro de
`normalize_rules`, que faz a troca do padrão **antes** de migrar o resto da
regra.

O `id` de uma regra migrada é determinístico (hash de `name:pattern`) — não
muda a cada carregamento, então a identidade da regra fica estável mesmo
sem nunca ter sido salva no formato novo.

## 7. Testes

### Suíte completa

```
python -m pytest tests/ -q
75 passed, 1 warning, 5 subtests passed
```

Nenhum teste existente foi removido. Um teste precisou ser **adaptado** —
`test_saved_legacy_default_patterns_are_upgraded` comparava o resultado de
`normalize_rules` com `DEFAULT_RULES` por igualdade exata de dict; como o
formato de retorno agora é mais rico (id, components, custom_regex...), o
teste passou a comparar nome/padrão explicitamente e checar que a regra
migrada ficou marcada como personalizada — o comportamento (upgrade do
padrão antigo) continua coberto.

### Testes novos

- `tests/test_print_pattern.py` (21 testes): extensão de arquivo, compilação
  de cada tipo de bloco (incl. tecido com/sem cadastro disponível), modos de
  correspondência, migração de regra legada (com e sem id), geração de id,
  `resolve_pattern` recompilando contra um cadastro de tecidos diferente.
- `tests/test_print_pattern_analyzer.py` (12 testes): os 5 exemplos de
  referência do pedido, separador `/`, espaçamento extra, extensão removida
  antes da análise, estrutura inconsistente entre exemplos (aviso, não
  mistura silenciosa), exemplos vazios, bloco "Tecido" não forçado para uma
  palavra que só parece um tecido.
- `tests/test_print_types_rules.py` (23 testes, 5 subtestes): ponta a ponta
  — os 7 casos obrigatórios do pedido (`Pedido`×2, `Reposição`×2, `Teste`,
  `Cliente Terceirizado`, `Amostra`), extensão de arquivo, espaços extras,
  aliases de tecido, tecido não cadastrado, prioridade (primeira regra que
  bate vence), conflito entre regra específica e genérica (com e sem
  reordenação), regex personalizada não é sobrescrita, migração de regra
  antiga, regra com regex quebrada é pulada (não derruba a classificação),
  regra inativa é ignorada, nome que não bate com nada cai em "Fora do
  padrão".

### Validação manual

Rodei os 5 exemplos principais do pedido **contra o cadastro real de
tecidos** desta máquina (não um cadastro de teste), construindo as regras do
jeito que o editor visual constrói (exemplo → `analyze_examples` →
`build_pattern`):

```
OK  '26-10 - Dryfit - Nome do Pedido'  -> Pedido
OK  '2/9 - Aeroready - Cliente'        -> Pedido
OK  'N1 - Dryfit'                      -> Reposição
OK  'NJ15 - Tactel'                    -> Reposição
OK  'Teste de cor'                     -> Teste
OK  'Amostra - Pedido ABC - Poliamida' -> Amostra
OK  'Cliente João - Dryfit'            -> Cliente Terceirizado
```

Também dirigi o modal programaticamente (sem interface gráfica visível,
localizando os widgets e chamando os mesmos comandos que os botões chamam)
para os seguintes fluxos, todos com o resultado esperado:
- Criar uma regra nova a partir de um exemplo (Amostra).
- Editar uma regra já estruturada (campos vêm pré-preenchidos corretamente).
- Abrir uma regra legada/personalizada (aviso correto, regex preservada ao
  salvar sem tocar em nada).
- Prévia ao vivo mostrando conflito com outra regra cadastrada, antes de
  salvar.

**O que eu não validei**: a interação visual de verdade (clicar com mouse,
ver o layout, redimensionar a janela, usar em telas pequenas/temas
diferentes). Validei a lógica e o fluxo de dados via automação de widgets,
não a experiência visual em si — recomendo abrir a tela uma vez e testar à
mão antes de considerar isso "pronto para uso" do ponto de vista de UX.

## 8. Limitações conhecidas

- **Bloco "Opcional" não tem seletor na UI.** O modelo e o compilador
  suportam (`core/print_pattern.py`, kind `opcional`, com `inner`), mas o
  editor visual não oferece essa opção na lista de tipos de bloco (exigiria
  uma segunda seleção aninhada — fora do escopo desta entrega). Quem
  precisar disso hoje só consegue pelo modo avançado (regex manual).
- **"Letras" sozinho quase nunca é sugerido automaticamente.** O analisador
  prefere "texto variável" pra uma palavra alfabética isolada, pra não
  forçar toda palavra a virar `[A-Za-z]+` por engano — "Letras" continua
  disponível manualmente no combobox, só não é uma sugestão automática.
- **Leitura do cadastro de tecidos por classificação.** Toda vez que uma
  regra com bloco Tecido é usada pra classificar, `core/fabrics.py` relê o
  arquivo `fabrics.json` do disco (não há cache entre chamadas). Isso é
  intencional (pra nunca ficar com a lista "congelada"), mas numa importação
  de pasta com muitos arquivos de uma vez isso é uma releitura por arquivo —
  não cheguei a medir o impacto real; se for perceptível, dá pra cachear por
  lote de importação depois.
- **Reanalisar exemplos substitui a estrutura inteira.** Não há merge
  bloco-a-bloco entre o que o usuário já ajustou manualmente e a nova
  sugestão — "Reanalisar" é tudo ou nada (com confirmação antes, se havia
  regex personalizada).
- **Separador entre blocos é sempre um único caractere + espaço flexível em
  volta.** Não cobre separadores compostos (ex.: " -- ", "::") nem a
  possibilidade de o MESMO exemplo usar separadores diferentes em posições
  diferentes com significados diferentes além do que já é capturado por
  posição.
- **Detecção de conflito é por exemplo, não exaustiva.** `detect_conflicts`
  testa os exemplos cadastrados na regra contra as demais — não gera casos
  de teste novos nem analisa as regex simbolicamente. Duas regras podem se
  sobrepor em strings que nenhum exemplo cobre, sem aviso.

## 9. Arquivos alterados/criados

**Novos:**
- `core/fabrics.py`
- `core/print_pattern.py`
- `core/print_pattern_analyzer.py`
- `tests/test_print_pattern.py`
- `tests/test_print_pattern_analyzer.py`
- `tests/test_print_types_rules.py`
- `docs/relatorio-editor-visual-tipos-impressao.md` (este arquivo)

**Reescritos/editados:**
- `core/print_types.py` (classificação estendida: extensão, modo de
  correspondência, tecido dinâmico, testador, detector de conflito)
- `modules/planejador.py` (cadastro de tecidos movido para `core/fabrics.py`,
  reexportado; `import os` removido por ter ficado sem uso)
- `modules/configuracoes.py` (editor visual novo + tela de tipos de
  impressão atualizada)
- `tests/test_print_types.py` (teste de migração adaptado ao novo formato)
- `core/version.py` (1.5.0), `CHANGELOG.md`

Este relatório não inclui os arquivos já modificados por sessões anteriores
não relacionadas a esta tarefa (ex.: `core/theme.py`, `core/ui.py`,
`modules/registros/ui.py`, `modules/operacao/exporters.py`, etc. — ver
`git status` para o estado completo da árvore de trabalho).

## 10. Nada foi commitado

Conforme pedido, nenhuma alteração foi commitada, enviada (push) ou
publicada como release. O executável `dist/Nexor-1.5.0.exe` foi gerado
localmente (rotina já estabelecida neste projeto após qualquer mudança de
código), mas isso não envolve git nem publicação.
