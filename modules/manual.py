"""Manual do operador — tela de ajuda só de leitura.

Explica o passo a passo de cada módulo e o que cada opção de Configurações
faz. Não lê nem grava nenhum dado do app; o conteúdo é só texto fixo.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from core import theme
from core.ui import page_heading

_VISAO_GERAL = """
# Visão geral

O Nexor organiza a produção de impressão em tecido: planejar o que vai ser
impresso, conferir o que a máquina realmente imprimiu, e consultar tudo que
já foi fechado.

O menu à esquerda tem 3 telas principais:

- Planejador — monta o plano de impressão antes de mandar pra máquina (o
  que, quanto, em que ordem), com ou sem logs reais ainda.
- Operação — confere os logs reais da impressora depois que o rolo foi
  impresso, e fecha o rolo (PDF + JPG espelhado).
- Registros de produção — histórico de tudo que já foi fechado, pra
  buscar, conferir e reabrir um comprovante antigo.

Em "Gerenciamento" ficam os cadastros compartilhados pelos dois módulos:
Impressoras, Tecidos e Pedaços de tecido.

Em "Configurações" ficam os valores padrão (modo do PDF, tamanho do JPG,
DPI, gaps etc.), o editor de regras de "Tipos de impressão" e os cadastros
fixos (arquivos de espaço, operadores).

## Fluxo típico de um rolo

1. (Opcional) Planeje no Planejador antes de imprimir — ou pule direto pro
   passo 2 se já tem os logs reais da máquina.
2. Depois de imprimir, importe os logs reais na Operação.
3. Confira a "Ordem do rolo" e corrija tecido/pedido/tipo errado, se
   precisar.
4. Clique em "Fechar Rolo" — gera o PDF (comprovante), o JPG espelhado e
   grava tudo no banco de uma vez só.
5. Quando precisar, vá em Registros de produção pra buscar esse rolo, ver
   o resumo ou abrir o comprovante de novo.

## Usando em mais de um computador (rede)

Dá pra ter vários computadores usando o Nexor ao mesmo tempo, com o mesmo
histórico — basta apontar o "Diretório de trabalho" (Configurações) de
todos pra uma mesma pasta de rede compartilhada. Dois detalhes importantes
nesse cenário, os dois em Configurações → Diretório de trabalho:

- O número sequencial do rolo é gerado pelo banco de dados compartilhado,
  então dois computadores nunca tiram o mesmo número ao mesmo tempo.
- Dá pra cadastrar, em cada PC, um "Identificador deste computador" (ex.:
  PC1, PC2) — entra no fim do nome do rolo gerado automaticamente, como
  reforço extra contra coincidência de nomes. Fica salvo só naquele
  computador.

Veja o tópico "Configurações" pra mais detalhes.
"""

_PLANEJADOR = """
# Planejador

Serve pra montar o planejamento de impressão antes (ou sem) ter logs reais
da máquina — por exemplo, planejar o que vai ser impresso num rolo novo,
ou lançar um lote manualmente a partir de imagens.

## Passo a passo

1. No cartão "Planejamento", escolha a Impressora (define a velocidade
   usada no cálculo de tempo — o botão "⟳" ao lado relê o cadastro de
   Impressoras se você acabou de cadastrar uma nova) e o Tecido no topo da
   tela. "Definir tecido" aplica o tecido escolhido aos itens selecionados
   na fila (se nada estiver selecionado, pede pra selecionar primeiro).
2. Importe os itens: arraste imagens (jpg/png/bmp/tif) pra área indicada
   logo abaixo ("…ou arraste imagens aqui"), use o botão "＋ Importar
   imagens" no topo da página, ou carregue uma lista salva antes em "Mais
   ações → Importar lista…".
3. Dê um nome ao lote em "Nome do lote" (e "Atualizar nome" se mudar
   depois, ou se quiser gerar um nome novo).
4. Em "Parâmetros do planejamento":
   - Modo: "tecido" (padrão) agrupa e ordena os itens por tecido,
     respeitando a metragem de cada rolo; "original" mantém a ordem exata
     de importação, reordenável à mão (veja abaixo).
   - "Ordem automática (menores no fim)": no modo tecido, deixa os itens
     menores de cada tecido por último dentro do rolo.
   - "Configurações avançadas ▸" (recolhido por padrão): "Priorizar
     pedaços de tecido cortados (não usados)" usa sobras já cadastradas em
     Pedaços de tecido em vez de cortar sempre do rolo cheio; o botão
     "Selecionar pedaços a usar…" ao lado abre um diálogo pra marcar quais
     pedaços específicos entram nessa fila (útil quando há pedaços do
     mesmo tecido de lotes/fornecedores que não podem se misturar) e
     escolher se cada pedaço conta pelo tamanho exato cadastrado ou com
     uma sangria extra em cm.
5. Clique em "▶ Gerar planejamento" — monta a fila considerando DPI, eixo,
   setup e gaps configurados (resumo logo abaixo dos parâmetros; mude os
   valores em Configurações → Planejador).
6. Confira o resultado nas quatro abas (cada uma com "⤢ Abrir em janela"
   pra ver numa janela maior):
   - Arquivos — lista os arquivos na ordem de importação, sem agrupar;
     "Ver arquivos importados" leva direto pra essa visão dentro da aba
     "Fila de impressão".
   - Fila de impressão — a sequência final que vai pro rolo. No modo
     "original", arraste pela alcinha à esquerda de cada linha (ou use
     "Mover para cima"/"Mover para baixo" no menu de botão direito) pra
     reordenar manualmente; no modo "tecido" a ordem é automática.
   - Resumo dos rolos — quantos rolos serão usados, por tecido, com
     blocos/itens/metragem/tempo de cada um — é a conferência antes de
     fechar.
   - Pedidos — o mesmo conteúdo agrupado por pedido, com tecido(s), total
     e número de peças.
7. Duplo clique num item da fila (ou botão direito → "Editar item…") abre
   um diálogo pra trocar o Tecido (combobox; "Novo tecido…" cadastra um
   tecido novo na hora sem sair do diálogo), um DPI específico só daquele
   item (deixe vazio pra usar o DPI global) e uma Observação livre — ao
   salvar, o comprimento e o tempo desse item são recalculados na hora.
   Botão direito também oferece "Definir tecido…" (pra vários itens
   selecionados de uma vez) e "Remover item(s)".
8. Clique em "Fechar Rolo" (ou "Atualizar Rolo", se estiver editando um
   rolo já salvo) — gera o PDF, o JPG espelhado e grava no banco.

## Menu "Mais ações"

- Exportar CSV — exporta a fila atual pra uma planilha.
- Recalcular (DPI/Vel/Setup) — refaz os cálculos de todos os itens com os
  valores atuais de Configurações (útil depois de mudar DPI/gaps lá).
- Salvar lista… / Importar lista… — guarda ou recarrega a lista de itens
  (com tecido, DPI por item, observações etc.), pra reaproveitar um
  planejamento parecido depois sem reimportar as imagens.
- Tecidos… — cadastro de tecidos: nome canônico, variações (apelidos
  separados por vírgula, que batem com o nome do arquivo) e metragem
  padrão do rolo. Selecionar um item da lista preenche o formulário pra
  editar; "Adicionar / Atualizar" salva.
- Ordem dos tecidos… — quando o lote tem mais de um tecido, define em que
  ordem eles entram na fila (cima imprime antes). "Subir"/"Descer"
  reordenam a lista; o checkbox "Usar ordem automática (menores no fim)"
  é o mesmo da tela principal.
- Pedaços de tecido… — cadastro de sobras/retalhos cortados: Nome,
  Tecido, Metragem, Tipo (livre) e Observação. "Marcar como usado" /
  "Desmarcar" controlam se um pedaço entra como disponível na próxima
  fila; "Remover tecidos usados" limpa de uma vez os já marcados como
  usados (não mexe em rolos já registrados). O resumo no rodapé soma a
  metragem disponível por tecido/tipo.
- Limpar — zera a tela e volta aos valores padrão de Configurações.

Os valores de DPI, eixo, setup, gaps e sangria vêm de Configurações →
Planejador; mude lá se quiser outro padrão (o resumo na tela sempre
mostra os valores em uso, com um lembrete de onde alterá-los).
"""

_OPERACAO = """
# Operação

Serve pra conferir o que a máquina realmente imprimiu, a partir dos logs
reais dela, e fechar o rolo — gerar o comprovante em PDF e o JPG
espelhado.

## Passo a passo

1. Importe os logs: arraste os arquivos .txt pra área indicada, use o
   botão "⇧ Importar logs" no topo da página, ou "Mais ações → Importar
   pasta…" pra pegar uma pasta inteira de uma vez.
2. Se o computador que gerou os logs estiver cadastrado numa impressora
   (Gerenciamento → Impressoras → campo "Computador desta impressora"), a
   máquina é identificada sozinha, sem perguntar nada (aparece "(detectada
   automaticamente)" no status). Isso só funciona quando todos os logs
   importados juntos vêm do mesmo computador; sem detecção (computador não
   cadastrado, ou logs misturados de mais de uma máquina), o programa
   pergunta de qual máquina são antes de importar.
3. Dê um nome ao rolo em "Nome do rolo" (ou "Atualizar nome" se já tiver
   um e quiser gerar outro).
4. Confira as quatro abas:
   - Ordem do rolo — os tecidos impressos, do último pro primeiro, com
     metragem e quantidade de arquivos; duplo clique ou botão direito
     num tecido abre "Editar tecido".
   - Detalhes do bloco — os arquivos/jobs de um tecido selecionado na aba
     anterior; duplo clique ou botão direito num arquivo edita a
     observação. Pra anotar vários arquivos de uma vez com o mesmo texto
     (ex.: "papel manchado nesse trecho"), selecione todos com
     Ctrl+clique ou Shift+clique antes de abrir pelo botão direito — o
     menu passa a mostrar "Observação (em N arquivos)…" e salva o mesmo
     texto em todos de uma vez. O mesmo menu (ou a tecla Delete) tem
     "Remover item(ns)…" — tira da tela um ou mais arquivos selecionados
     por engano (ex.: importou o log errado); pede confirmação antes,
     e só afeta o rolo aberto, nada apagado do banco.
   - Pedidos no rolo — o mesmo conteúdo agrupado por pedido/tipo, em vez
     de por tecido; duplo clique ou botão direito abre "Editar pedido" ou
     "Editar tipo".
   - Lista do rolo — todos os arquivos do rolo numa lista só, na MESMA
     ordem em que saem no comprovante (não agrupados por tecido ou
     pedido). Duplo clique ou botão direito → "Editar item…" abre um
     diálogo com nome do arquivo, tecido, pedido e observação daquele
     item específico — diferente das outras abas, aqui a correção vale só
     pra aquele arquivo, não pro grupo inteiro que compartilha o mesmo
     tecido/pedido. Com mais de um item selecionado (Ctrl/Shift+clique),
     o botão direito oferece "Observação (em N arquivos)…", igual à aba
     "Detalhes do bloco". Em qualquer seleção, o botão direito (ou a
     tecla Delete) também tem "Remover item(ns)…", pra tirar arquivos
     selecionados por engano. Qualquer alteração feita em qualquer uma
     das quatro abas (tecido, pedido, tipo, observação, ou remoção)
     aparece automaticamente nas outras três — é a mesma lista de
     arquivos vista de formas diferentes.
5. Se algo foi identificado errado, corrija manualmente:
   - Editar tecido / Editar pedido — quando o grupo reúne arquivos de
     origem diferentes (ex.: vários pedidos detectados juntos como
     "DESCONHECIDO" por engano), o diálogo lista um campo de nome por
     arquivo distinto, todos visíveis de uma vez; corrija cada um e
     clique em "Salvar" uma única vez.
   - Editar tipo — troca o tipo (Pedido, Reposição, ou um subtipo manual
     cadastrado em Configurações) de todos os arquivos daquele pedido.
   Uma correção manual fica marcada e não é mais sobrescrita
   automaticamente depois — nem se você mudar as regras em Configurações
   e salvar de novo.
6. Avanços entre tecidos (quando a máquina imprime algo só pra avançar o
   rolo, sem ser pedido de verdade) aparecem como ESPAÇO — os nomes de
   arquivo que viram ESPAÇO são configurados em Configurações → Operação.
7. Antes de fechar, o programa avisa se o mesmo pedido + tecido já foi
   impresso em outro rolo salvo (possível duplicidade); você decide se
   continua ou cancela pra conferir. Esse aviso também aparece (só como
   informação, sem bloquear) logo depois de importar os logs. Ele só vale
   pra tipos marcados com "Avisa duplicidade" em Configurações → Tipos de
   impressão.
8. Se a impressora tiver "Log adicional" configurado (Gerenciamento →
   Impressoras — usado em máquinas, como a M1, onde quem imprime de fato é
   outro programa que grava seu próprio log), cada item mostra na coluna
   "Impressão (log adicional)" se a impressão física foi confirmada
   cruzando os dois logs (✓), se deu erro (⚠) ou se o formato do log
   configurado não é o esperado (⚠ formato desconhecido).
9. Clique em "Fechar Rolo" (ou "Atualizar Rolo", se estiver editando um
   rolo já salvo) — gera o PDF, o JPG espelhado e grava no banco, tudo de
   uma vez. Depois disso o botão "Abrir comprovante", ao lado, fica
   habilitado e abre direto o PDF que acabou de ser gerado — ele some de
   novo (desabilita) se você usar "Limpar" ou começar outro rolo.

## Menu "Mais ações"

- Importar pasta… — importa todos os logs de uma pasta de uma vez.
- Abrir pasta PDF (comprovantes) / Abrir pasta JPG (operação) — abre no
  explorador a pasta onde os arquivos gerados ficam salvos.
- Limpar — zera a tela (não apaga nada já salvo no banco) e desativa o
  botão "Abrir comprovante" de novo, até fechar outro rolo.

O Modo do PDF, o tamanho do JPG espelhado e a pasta de saída da
impressora são definidos em Configurações (seção Exportação e cadastro
de Impressoras) — aqui só aparece um resumo, logo abaixo do nome do
rolo.
"""

_REGISTROS = """
# Registros de produção

É o histórico de tudo que já foi fechado (pela Operação ou pelo
Planejador) — pra buscar um rolo antigo, conferir o resumo ou reabrir o
comprovante.

## Buscar um rolo

Filtros no topo, combináveis entre si:

- Máquina — combobox com as máquinas cadastradas.
- Rolo contém — texto livre, compara com o nome do rolo.
- Pedido contém — texto livre, compara com o nome do pedido.
- Tipo — combobox com os tipos já usados nos rolos salvos.
- Limite — quantos rolos no máximo a lista mostra (padrão 300).

Os campos de texto e o Limite buscam ao apertar Enter; o combobox de Tipo
busca assim que você escolhe um valor. "Limpar filtros" volta tudo ao
padrão e "⟳ Recarregar" (no topo da página) relê o banco do zero.

## Lista de rolos

Clique num rolo da lista pra carregar os detalhes dele logo abaixo, em
três abas:

- Resumo — nome, máquina, data, total impresso e o detalhamento por
  tecido (metragem e quantidade de arquivos). Avanços (ESPAÇO) de rolos
  da Operação aparecem à parte, sem entrar na soma dos tecidos — veja a
  opção "Agrupar espaços consecutivos" em Configurações pra juntar
  avanços seguidos numa linha só.
- Pedidos — cada arquivo/job gravado nesse rolo, com tecido, tipo,
  metragem e observação.
- Eventos — o histórico de exportações/atualizações desse rolo (quando
  foi criado, quando foi reexportado, e o que mudou em cada vez).

## Ações

- Editar rolo — reabre o rolo selecionado no módulo de origem (Operação
  ou Planejador), com os dados já carregados, pronto pra corrigir e
  fechar de novo (ele é ATUALIZADO, não duplicado — o botão de fechar
  aparece como "Atualizar Rolo" nesse caso).
- Abrir comprovante — abre direto o PDF já gerado desse rolo, sem
  precisar reabrir pra exportar de novo.
- ⟳ Recarregar — atualiza a lista com o que estiver salvo no banco agora.

## Exportar contexto de produção (PX Tool Box)

Na aba "Pedidos" do rolo selecionado, escolha um trabalho de impressão
(linha com pedido informado — avanços/espaços não têm o que exportar) e
clique em "Exportar contexto de produção...". Escolha onde salvar o
arquivo `.json` (nome sugerido já vem pronto); a confirmação de
sobrescrita, se o arquivo já existir, é a mesma caixa nativa do Windows.

Gravado com sucesso, aparece uma janela de confirmação com:

- o caminho completo do arquivo;
- "Mostrar arquivo na pasta" — abre o Explorer com o arquivo já
  selecionado;
- "Copiar caminho" — copia o caminho pra área de transferência.

Essas duas ações são só auxiliares: se uma delas falhar (ex.: Explorer
não disponível), a mensagem de erro aparece à parte, na própria janela —
nunca desfaz a confirmação de que o arquivo já foi exportado.

Essa exportação é só leitura: nunca altera o rolo, o trabalho de
impressão nem abre o PX Tool Box ou o CorelDRAW automaticamente. No PX
Tool Box DEV, o arquivo é lido manualmente em Produção > "Carregar
contexto de produção..." — exportar aqui não significa que o PX já
recebeu nada; são dois passos manuais separados, sempre.

Identificadores incluídos (`installationId`, `databaseId`) servem só
pra ajudar o PX a notar se dois contextos vêm da mesma base de dados —
nunca são um número de pedido comercial (o Nexor não tem essa entidade
hoje) nem uma identificação global garantida.
"""

_CONFIGURACOES = """
# Configurações

Reúne os valores padrão e os cadastros fixos usados pelos módulos. Cada
seção tem a própria validação; use "Salvar todas as configurações", no
final da página, pra salvar tudo de uma vez — se alguma seção tiver um
valor inválido, o programa avisa qual e as demais são salvas normalmente.

## Aparência

Tema visual do programa — é só preferência pessoal, não afeta os dados.
"Mudar tema ▸" abre uma grade com prévia de cada tema; clique num cartão
pra aplicar na hora, em todas as telas. Fica salvo neste computador.

## Diretório de trabalho

Pasta onde ficam o banco de dados (Registros, numeração dos rolos) e os
arquivos gerados (PDF, JPG). "Procurar…" escolhe a pasta; depois de
"Salvar diretório base", reinicie o programa pra aplicar. "📁 Abrir pasta"
abre essa pasta no explorador.

Pra usar o Nexor em mais de um computador com o mesmo histórico, aponte
todos pra uma mesma pasta de rede compartilhada aqui. Nesse caso, dá
também pra cadastrar um "Identificador deste computador" (ex.: PC1, PC2)
logo abaixo — entra no fim do nome do rolo gerado automaticamente (ex.:
"M1_26-10-2026_0046_PC1"), como reforço extra contra dois computadores
fecharem rolos com o mesmo número ao mesmo tempo. O número sequencial em
si já vem do banco compartilhado e não se repete sozinho; o identificador
cobre só o caso raro de a pasta de rede cair bem na hora de um dos PCs
gerar o número. Fica salvo só no computador onde foi preenchido — deixe
em branco se usar um PC só.

## Tipos de impressão

Regras que identificam automaticamente se um arquivo é Pedido, Reposição
etc., pelo nome do arquivo. Tem um editor visual próprio, bem mais
detalhado — veja o tópico "Tipos de impressão" no menu ao lado.

## Exportação

Vale igual pra Operação e pro Planejador, não precisa configurar duas
vezes:

- Modo do PDF — Completo (todo o detalhamento) ou Resumido.
- JPG espelhado — largura de 17 cm, 21 cm ou Personalizado (digite o
  valor em cm ao lado).

O JPG espelhado vai direto pra pasta/arquivo configurado na impressora
usada (cadastro de Impressoras), quando houver; sem isso, usa a pasta
padrão do módulo.

## Operação

- Abrir pasta PDF / Abrir pasta JPG — atalho pras pastas onde a Operação
  salva os comprovantes e os JPGs.
- Arquivos de espaço — cadastro de nomes de arquivo/job que a máquina
  imprime como avanço entre tecidos (não são pedidos de verdade); ao
  importar, esses logs viram ESPAÇO. Cada entrada tem um "Arquivo/job"
  (o nome que aparece no log) e uma "Exibição" (como aparece nas
  listagens — padrão "ESPAÇO" se deixar em branco). Selecione um item da
  lista pra editar; "Adicionar / Atualizar" salva, "Remover" apaga.
- Agrupar espaços consecutivos no Resumo — desmarcado (padrão): cada
  avanço aparece numa linha no Resumo dos Registros, pra bater com a
  conferência manual na calandra. Marcado: avanços seguidos — sem
  nenhum tecido real entre eles — somam numa linha só.
- Operadores — liga a inicial que aparece no nome do arquivo de
  reposição (ex.: "N" em "N1 - Dryfit") ao nome completo do operador
  (campos Identificador — só letras — e Nome), que aparece no PDF e no
  JPG no modo Completo. "Adicionar / Atualizar" salva, "Remover" apaga.

## Planejador

Valores padrão usados ao abrir a tela e ao clicar em "Limpar" (a
impressora e a velocidade vêm do cadastro de Impressoras, não daqui):

- DPI global, Setup (min/job), Gap entre tecidos (m), Gap antes do fim do
  rolo (m), Gap entre arquivos (m), Rolo p/ tecido sem metragem (m) e
  Sangria dos pedaços (cm).
- Eixo do comprimento — altura, largura ou maior (lado usado pra calcular
  o comprimento impresso a partir do tamanho em pixels da imagem).
- Modo da fila — tecido (padrão) ou original; é o mesmo seletor que
  aparece na tela do Planejador.
- Ordem automática dos tecidos (menores no fim) — mesmo checkbox da tela
  principal.
- Abrir pasta PDF / Abrir pasta JPG — atalho pras pastas do Planejador.

## Registros

Botão "Reclassificar registros 'Fora do padrão'" — reaplica as regras de
Tipos de impressão aos pedidos já salvos nesse tipo (útil depois de criar
ou ajustar uma regra, pra ela valer também pro que já foi importado antes,
sem precisar reabrir rolo por rolo). Tipos escolhidos à mão (Teste,
Terceirizado etc. via "Editar tipo") não mudam.
"""

_TIPOS_IMPRESSAO = """
# Tipos de impressão (editor de regras)

Fica em Configurações → Tipos de impressão. Cada regra tenta reconhecer
um tipo de arquivo (Pedido, Reposição, Amostra...) pelo nome do arquivo;
a primeira regra da lista que combinar vence — por isso a ORDEM da lista
importa. Um arquivo que não bate com nenhuma regra fica como "Fora do
padrão" e pode receber um subtipo manual depois, na Operação → Editar
tipo.

O Nexor já vem com duas regras de fábrica: Pedido (dia-mês no início, ex.
"16-10 - Dryfit - Cliente") e Reposição (inicial do operador + número, ex.
"N2 - Aeroready").

## Criar ou editar uma regra

Clique em "Nova" (ou duplo clique numa regra existente, ou selecione e
clique em "Editar selecionada") — abre um editor visual em vez de pedir
regex direto:

1. Tipo — o nome que esse arquivo vai receber (ex.: "Amostra").
2. Correspondência — "começa com" (padrão), "exatamente igual" ou
   "contém", e se a regra deve avisar duplicidade (ver tópico Operação) e
   se o nome do pedido vem do próprio arquivo ou é sempre um texto fixo
   pra esse tipo.
3. Exemplos de nome de arquivo — adicione um ou mais exemplos reais. O
   primeiro exemplo já dispara a análise automática da estrutura;
   exemplos extras só atualizam a prévia/teste (não refazem a estrutura
   sozinhos, pra não descartar ajustes que você já tenha feito à mão).
4. Estrutura identificada — uma linha por "bloco" do nome do arquivo
   (texto fixo, texto variável, data, número, letras, letras+número,
   número+letras, tecido ou separador), com um combobox pra trocar o tipo
   do bloco se a sugestão não bater, e um campo de valor literal quando o
   bloco é "Texto fixo". Blocos com confiança baixa vêm com uma nota
   pedindo confirmação. O botão "Reanalisar exemplos" refaz a sugestão do
   zero a qualquer momento (pede confirmação se a regra já tinha uma
   regex personalizada).
5. Prévia da regra — mostra ✓/✗ de cada exemplo cadastrado contra a regra
   atual, a regex gerada, avisos de estrutura inconsistente entre
   exemplos e avisos de conflito com outras regras já cadastradas — tudo
   ao vivo, antes de salvar. O campo "Testar nome de arquivo" ao lado
   testa qualquer nome avulso.
6. "Avançado" (oculto por padrão) revela a regex gerada, editável à mão.
   Editar a regex manualmente marca a regra como "regex personalizada" —
   a partir daí, mudar a estrutura visual não regera a regex sozinha (fica
   um aviso visível, e "Reanalisar exemplos" pede confirmação antes de
   substituir).
7. "Salvar padrão" valida o Tipo e a regex, avisa se há conflito com
   outra regra (não bloqueia — você decide se continua) e grava a regra.

O bloco "Tecido" é dinâmico: ele reconhece qualquer tecido cadastrado em
Gerenciamento → Tecidos, mesmo os adicionados depois de a regra já estar
salva — não precisa editar a regra de novo ao cadastrar um tecido novo.

## Tela principal

- Lista de regras — colunas Tipo, Padrão (regex), Origem (Visual ou
  Regex avançada), Avisa duplicidade e Nome do pedido.
- "Nova" / "Remover" / "▲ Subir" / "▼ Descer" — editam a lista e a ordem
  de prioridade.
- "Restaurar padrão" — volta pras duas regras de fábrica (Pedido e
  Reposição), descartando as demais.
- "Testar nome de arquivo" — mostra na hora qual tipo um nome de arquivo
  recebe; se mais de uma regra combinar, avisa quais e explica que a de
  cima na lista vence.
- Subtipos manuais — lista de opções extras (ex.: Teste, Cliente
  Terceirizado) disponíveis em "Editar tipo", na Operação, pra classificar
  à mão o que ficou como "Fora do padrão". "Adicionar" inclui o texto
  digitado; "Remover" tira o selecionado da lista.
"""

_CADASTROS = """
# Impressoras, Tecidos e Pedaços de tecido

Ficam no menu lateral, em "Gerenciamento" — cadastros compartilhados
pela Operação e pelo Planejador.

## Impressoras

Lista com Novo (botão "Nova"), seleção pra editar, "Salvar" e "Remover".
Campos do formulário:

- Nome completo e Nome de exibição (o que aparece nas telas, ex. "M1").
- Velocidade (m/min) — usada no cálculo de tempo do Planejador.
- Observações — texto livre.
- Pasta do JPG espelhado (+ "Procurar…") e Nome do arquivo do JPG — se
  preenchidos, o JPG dessa impressora vai direto pra essa pasta/arquivo ao
  fechar o rolo, em vez da pasta padrão do módulo. Opcionais.
- Orientação do JPG espelhado — 0°/90°/180°/270°, pra impressoras que
  recebem o arquivo virado.
- Log adicional — checkbox + pasta (com "Procurar…"), pra máquinas (como
  a M1) onde quem imprime de fato é outro programa, que grava um log à
  parte; a Operação cruza os dois logs pra confirmar a impressão real
  item por item.
- Computador desta impressora — nome do PC que gera os logs dela (campo
  "ComputerName" dentro do log .txt). O botão "Detectar de um log…" abre
  um seletor de arquivo e preenche esse campo sozinho a partir de um log
  de exemplo, sem precisar digitar nada. Com isso cadastrado, a Operação
  identifica a máquina certa ao importar sem perguntar nada (ver tópico
  Operação). Opcional; deixe em branco se não souber ou se a impressora
  não tiver essa informação no log.

## Tecidos

Abre pelo atalho em Gerenciamento ou por "Mais ações → Tecidos…" dentro
do Planejador. Nome canônico, Variações (outros jeitos como o tecido
aparece no nome do arquivo, separadas por vírgula) e Metragem do rolo (m)
— usada quando um tecido não tem metragem informada em outro lugar. A
lista mostra "canonical -> aliases | metragem do rolo"; clique num item
pra carregar no formulário e "Adicionar / Atualizar" salva (cadastrar um
nome que já existe funde as variações, em vez de duplicar).

## Pedaços de tecido

Abre pelo atalho em Gerenciamento ou por "Mais ações → Pedaços de
tecido…" dentro do Planejador. Sobras/retalhos já cortados, disponíveis
pra reaproveitar num planejamento novo em vez de cortar do rolo cheio
(ver "Priorizar pedaços de tecido cortados", no Planejador). Campos: Nome,
Tecido (combobox com os tecidos cadastrados), Metragem (m), Tipo (livre,
ex. pra separar por fornecedor/lote) e Observação.

Botões: "Novo" limpa o formulário, "Salvar" grava (novo ou edição do
selecionado), "Remover" apaga o selecionado (com confirmação), "Remover
tecidos usados" apaga de uma vez todos os já marcados como usados (não
mexe em rolos já registrados), e "Marcar como usado" / "Desmarcar"
alternam se aquele pedaço está disponível pra entrar numa fila nova. O
resumo no rodapé da tela soma a metragem disponível por tecido/tipo.
"""

_DICAS = """
# Dicas e perguntas frequentes

## O que é ESPAÇO?

É um avanço que a máquina imprime entre um tecido e outro — não é pedido
de verdade. Os nomes de arquivo que viram ESPAÇO são configurados em
Configurações → Operação → Arquivos de espaço.

## Por que apareceu um aviso de "possível duplicidade"?

O mesmo pedido + mesmo tecido já foi impresso em outro rolo salvo no
banco. Aparece em dois momentos: como aviso informativo logo depois de
importar os logs, e como confirmação (sim/não) ao tentar fechar o rolo.
Você decide se continua (ex.: reimpressão proposital) ou cancela pra
conferir antes. Esse aviso só vale pra tipos marcados com "Avisa
duplicidade" no editor de Tipos de impressão (Configurações).

## Por que a Operação não perguntou de qual máquina são os logs?

Porque o computador que gerou aqueles logs está cadastrado numa
impressora (Gerenciamento → Impressoras → "Computador desta impressora")
e todos os logs importados juntos vêm desse mesmo computador — nesse caso
a máquina é identificada sozinha. Se os logs vierem de mais de um
computador no mesmo lote, ou o computador não estiver cadastrado em
nenhuma impressora, o programa volta a perguntar.

## O que significam os status do "Log adicional" na Operação?

Só aparece quando a impressora tem "Log adicional" configurado
(Gerenciamento → Impressoras). "✓ Impressão confirmada" quer dizer que o
item bateu com o log físico da máquina; "⚠ Erro na impressão" indica que
o log físico registrou uma falha nesse item; "⚠ Formato do log adicional
não reconhecido" quer dizer que a pasta configurada não parece ter o tipo
de log esperado — confira o caminho em Gerenciamento → Impressoras.

## "Fechar Rolo" ou "Atualizar Rolo" — qual a diferença?

É o mesmo botão: o texto muda sozinho. "Fechar Rolo" cria um registro
novo; "Atualizar Rolo" aparece quando você abriu o rolo pela tela
"Editar rolo" (em Registros) e vai sobrescrever esse mesmo registro, em
vez de duplicar. O botão "Abrir comprovante", ao lado, só fica habilitado
depois de clicar em um dos dois nessa sessão, e desliga de novo em
"Limpar".

## Onde ficam os PDFs e JPGs gerados?

Nas pastas do Diretório de trabalho (Configurações), dentro da pasta do
módulo (Operação ou Planejador). Use "Abrir pasta PDF/JPG" no menu "Mais
ações" de cada módulo, ou em Configurações, pra abrir direto no
explorador — ou "Abrir comprovante" (em Registros, ou na própria
Operação depois de fechar o rolo) pra abrir o PDF de um rolo específico
sem precisar achar a pasta.

## Como corrijo um rolo já fechado?

Em Registros de produção, selecione o rolo e clique em "Editar rolo" —
ele reabre no módulo de origem com os dados carregados; corrija o que
precisar e clique em "Atualizar Rolo".

## Como evito que dois computadores gerem rolos com o mesmo nome?

O número sequencial do rolo já vem do banco de dados compartilhado e não
se repete sozinho entre computadores. Como reforço extra, cadastre um
"Identificador deste computador" diferente em cada PC, em Configurações →
Diretório de trabalho — veja o tópico "Visão geral" ou "Configurações"
pra mais detalhes.
"""

TOPICS: list[tuple[str, str]] = [
    ("Visão geral", _VISAO_GERAL),
    ("Planejador", _PLANEJADOR),
    ("Operação", _OPERACAO),
    ("Registros de produção", _REGISTROS),
    ("Configurações", _CONFIGURACOES),
    ("Tipos de impressão", _TIPOS_IMPRESSAO),
    ("Impressoras, Tecidos e Pedaços", _CADASTROS),
    ("Dicas e perguntas frequentes", _DICAS),
]


def _configure_tags(text: tk.Text) -> None:
    spec = theme.get_spec()
    text.tag_configure("h1", font=("", 15, "bold"), foreground=spec.brand, spacing1=4, spacing3=10)
    text.tag_configure("h2", font=("", 11, "bold"), spacing1=14, spacing3=6)
    text.tag_configure("p", spacing3=6)
    text.tag_configure("bullet", lmargin1=18, lmargin2=30, spacing3=4)
    text.tag_configure("bullet2", lmargin1=34, lmargin2=46, spacing3=4)


def _render(text: tk.Text, body: str) -> None:
    text.configure(state="normal")
    text.delete("1.0", "end")
    for raw_line in body.strip("\n").split("\n"):
        line = raw_line.rstrip()
        if line.startswith("# "):
            text.insert("end", line[2:] + "\n", ("h1",))
        elif line.startswith("## "):
            text.insert("end", line[3:] + "\n", ("h2",))
        elif line.startswith("  - ") or line.startswith("   - "):
            text.insert("end", "•  " + line.lstrip()[2:] + "\n", ("bullet2",))
        elif line.startswith("- "):
            text.insert("end", "•  " + line[2:] + "\n", ("bullet",))
        elif line.strip() == "":
            text.insert("end", "\n")
        else:
            text.insert("end", line + "\n", ("p",))
    text.configure(state="disabled")


def build_ui(parent: tk.Misc) -> ttk.Frame:
    frame = ttk.Frame(parent)

    page_heading(
        frame, "Manual do Nexor",
        "Como usar cada parte do programa, passo a passo — e pra que serve cada opção de Configurações.",
    ).pack(fill="x", padx=22, pady=(22, 10))

    body = ttk.Frame(frame)
    body.pack(fill="both", expand=True, padx=22, pady=(0, 18))

    nav = ttk.Frame(body, width=210)
    nav.pack(side="left", fill="y", padx=(0, 14))
    nav.pack_propagate(False)

    lb = tk.Listbox(
        nav, exportselection=False, activestyle="none",
        highlightthickness=0, borderwidth=0, relief="flat",
    )
    lb.pack(fill="both", expand=True)
    for title, _ in TOPICS:
        lb.insert("end", "  " + title)

    text_frame = ttk.Frame(body)
    text_frame.pack(side="left", fill="both", expand=True)

    txt = tk.Text(
        text_frame, wrap="word", padx=16, pady=14,
        relief="flat", borderwidth=0, highlightthickness=0,
    )
    sb = ttk.Scrollbar(text_frame, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb.set, state="disabled")
    txt.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    _configure_tags(txt)

    def _on_theme_changed(_key: str) -> None:
        _configure_tags(txt)

    theme.on_theme_changed(_on_theme_changed)

    def on_select(_evt=None) -> None:
        sel = lb.curselection()
        idx = sel[0] if sel else 0
        _render(txt, TOPICS[idx][1])
        txt.yview_moveto(0)

    lb.bind("<<ListboxSelect>>", on_select)
    lb.selection_set(0)
    on_select()

    return frame
