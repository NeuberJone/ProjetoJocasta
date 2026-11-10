# Roadmap de modernização do Nexor

Referência: 05/11/2026. As fases mantêm a sequência de consolidação, produção confiável, produtividade e expansão. A evolução preserva regras existentes, contratos de produção e histórico, com migração deliberada e retorno verificável.

## Fase 1 — Consolidação

Escopo: configuração, segurança local, banco, logs, testes, build e documentação.

A implementação atual reúne JSON validado e atômico, recuperação explícita, senha DEV com PBKDF2 e compatibilidade SHA-1, espera de bloqueio/diagnóstico/backup SQLite, logging técnico com rotação e tratamento de falhas. Dependências conhecidas estão fixadas; testes têm runner isolado e CI Windows/Linux. A documentação descreve arquitetura, caminhos, contratos e dívida técnica reais.

Critérios de aceitação, marcados somente quando houver evidência:

- [ ] Revisão e suíte completa sobre a integração final, com compilação dos fontes.
- [ ] CI remota e instalação limpa usando os manifestos.
- [x] Smoke Windows em perfil descartável: seis páginas, oito temas, navegação mínima e configuração inválida preservada (`scripts/smoke-ui-isolated.py`, janela transparente).
- [ ] Revisão visual e fluxos completos de importação/exportação/edição com dados sintéticos.
- [x] Build em saída isolada concluído; inspeção do executável confirmou Tcl/Tk e `CHANGELOG.md`. O executável congelado não foi iniciado para smoke.
- [ ] Ensaio operacional de backup/restauração e bloqueio em ambiente representativo descartável.
- [ ] Homologação do compartilhamento SMB e das impressoras utilizados na operação.

Versão permanece **1.6.39**. Nenhum instalador ou publicação é implícito nesta fase.

## Fase 2 — Produção confiável

- [ ] Especificar e validar leitura de logs do **Neo Estampa e PrintXP**, com exemplos sintéticos de cada formato e regras de normalização documentadas.
- [ ] Implementar importação incremental e idempotente, com estado de progresso e tratamento de arquivos incompletos/alterados.
- [ ] Reconciliar o que foi planejado, registrado nos logs e confirmado na operação, expondo divergências sem modificar a origem silenciosamente.
- [ ] Definir métricas verificáveis de metragem, duração, espaços e produção por máquina, com rastreabilidade até os registros de origem.
- [ ] Separar parser/domínio de UI e reduzir efeitos nos imports como base para testar formatos e reprocessamentos sem Tkinter.
- [ ] Formalizar diagnóstico, retenção de backups e ensaio de restauração; medir bloqueios e interrupções no ambiente de rede descartável.

**Critério de saída:** o mesmo conjunto de logs importado novamente não duplica a produção; diferenças entre fontes são explicáveis e as métricas podem ser recalculadas a partir da evidência preservada. Novos formatos não alteram a interpretação dos registros existentes.

## Fase 3 — Produtividade

- [ ] Criar painel operacional a partir das métricas e estados validados na fase anterior.
- [ ] Unificar busca de rolos, etiquetas de pedidos informados, arquivos e eventos, mantendo claro o significado de cada identificador.
- [ ] Registrar ocorrências operacionais com vínculo aos itens/rolos e histórico de alterações.
- [ ] Acompanhar retrabalho de forma explícita, distinguindo-o da impressão original nas consultas e métricas.
- [ ] Simplificar os fluxos da interface com base nas tarefas do operador, preservando funções, temas e compatibilidade dos relatórios.
- [ ] Extrair cálculo/organização de fila do Planejador e coordenação dos relatórios para serviços menores, com regressão dos resultados conhecidos.
- [ ] Cobrir navegação, diálogos e resultados parciais com smoke automatizado e revisão visual em perfis descartáveis.

**Critério de saída:** o operador consegue localizar contexto e resolver ocorrências com menos etapas; retrabalho permanece rastreável; os fluxos principais são verificáveis sem dados de clientes.

## Fase 4 — Expansão

- [ ] Especificar estoque e movimentos vinculados à produção, definindo unidades, ajustes e auditoria antes de implementar.
- [ ] Evoluir a integração com **PX Tool Box** mediante contrato versionado, exemplos e validação conjunta dos aplicativos.
- [ ] Avaliar nesting com critérios mensuráveis de aproveitamento e compatibilidade dos arquivos.
- [ ] Produzir previsões somente a partir de métricas históricas verificadas, expondo hipóteses e erro observado.
- [ ] Definir arquitetura multiestação após medir latência, concorrência e volume; comparar SQLite local por serviço com banco cliente/servidor.
- [ ] Projetar migração/retorno, preservação de IDs/linhagem, operação offline e restauração antes de distribuir a nova arquitetura.
- [ ] Formalizar builds repetíveis, verificação de dependências e política de distribuição/suporte para o escopo escolhido.

A integração existente com PX Tool Box é **exportar um contexto de produção em JSON e importar manualmente no outro aplicativo**. Ela não abre Corel/PX nem sincroniza processos automaticamente. Integração ampliada, estoque, nesting, previsões e arquitetura multiestação permanecem futuros; o roadmap não os marca como implementados.

**Critério de saída:** cada expansão tem requisitos, contrato, teste de valor e operação definidos; instalação/atualização e retorno sobre dados sintéticos preservam histórico, configurações e exportações. WAL não deve ser ativado como solução automática para SMB.

Consulte [arquitetura atual](../architecture/current-state.md) e [dívida técnica](../architecture/technical-debt.md) antes de marcar etapas concluídas.
