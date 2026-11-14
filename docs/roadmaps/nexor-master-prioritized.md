# Nexor (ProjetoJocasta) — Roadmap mestre priorizado

**Atualizado:** 2026-11-13 · **Código-fonte correto:** `NeuberJone/ProjetoJocasta` · **Entrada:** `Nexor.py` · **Versão do código:** `core/version.py = 1.6.41`.

> Este é o **Nexor Python/Tkinter existente**, não a reconstrução C#/WPF do repositório separado `NeuberJone/Nexor`. O roadmap criado naquele outro repositório **não descreve este código**. Preservar [roadmap de modernização](nexor-modernization-roadmap.md), [estado atual](../architecture/current-state.md), [dívida técnica](../architecture/technical-debt.md) e [CHANGELOG](../../CHANGELOG.md).
>
> **Legenda:** [x] implementação documentada no repositório; [~] implementação existente com validação/limites pendentes; [ ] ainda planejado. Não foram executados testes nem homologação em impressoras nesta revisão.

## Priorização

| Ordem | Prioridade | Trabalho | Critério de saída |
|---|---|---|---|
| 0 | P0 | Auditoria da versão 1.6.41, segurança de dados e testes | Build/CI/smoke executável e restauração testada |
| 1 | P0 | Confiabilidade de Operação, Planejador, Registros e relatórios atuais | Fluxos reais sem regressão, IDs e histórico preservados |
| 2 | P0 | Rede SMB, concorrência SQLite e backup | Política de acesso e recuperação homologadas |
| 3 | P1 | Neo Estampa + JetPrime/PrintXP incremental | Importações repetidas sem duplicar e com origem auditável |
| 4 | P1 | Conciliação, reposições, métricas de produção | Indicadores reproduzíveis e divergências explicadas |
| 5 | P1 | Modularização incremental do Python | Testes sem Tk, compatibilidade de UI/arquivos preservada |
| 6 | P2 | UX, pesquisa unificada e ocorrências | Menos passos, sem perder funções e temas |
| 7 | P2 | Planejamento e materiais/retalhos | Movimentos e disponibilidade rastreáveis |
| 8 | P2 | Integração ampliada com PXToolBox | Contratos versionados e teste conjunto |
| 9 | P3 | Analytics, previsões e multiestação | Métricas confiáveis e arquitetura medida |
| 10 | P3 | Instalador/ecossistema e sincronização opcional | Aplicativo continua independente e local-first |

## 0 — P0: estabelecer baseline real

- [x] Python 3.13 / Tkinter; `Nexor.py`, `core/`, `modules/`, SQLite `printlogs.db` e `Nexor.spec` documentados.
- [x] Runner isolado de testes, workflow CI Windows/Linux, logging, validação e gravação atômica JSON, PBKDF2 e APIs de backup/diagnóstico SQLite documentados.
- [x] Smoke isolado da UI (seis páginas, oito temas) e inspeção de build isolado documentados.
- [~] Divergência documental: `core/version.py` indica **1.6.41**, README e documentação de consolidação ainda mencionam **1.6.39**; alinhar após conferir artefatos.
- [ ] Executar suíte completa, `compileall`, CI, smoke do executável congelado, build limpo e testes visuais/operacionais em Windows.
- [ ] Testar backup/restauração de verdade, retenção, corrupção, migrações e falha durante escrita, sempre em bases descartáveis.
- [ ] Verificar logs sem dados sensíveis, hashes, permissões e política de atualização de dependências.
- [ ] Não alterar nem migrar bases reais durante auditoria.

## 1 — P0: preservar e estabilizar módulos existentes

### Operação

- [x] Importação TXT Neo, classificação de máquina/tecido/tipo/operador, itens e espaços, blocos, fechamento/edição de rolos, PDF/JPG e histórico documentados.
- [x] Metragem real por `HeightMM/1000`; espaço separado de impressão; não descontar 1 m arbitrário por troca de tecido.
- [x] Rolo de teste com sufixo `_TESTE` e exclusão de alertas de pedido já impresso/exportação de contexto (1.6.41).
- [x] Observações e pedido por linha nos comprovantes (1.6.40).
- [~] Validar importação/fechamento/edição/exportação com arquivos reais anonimizados M1/M2, rolos normais e testes, Undo operacional e falhas parciais.

### Planejador

- [x] Cálculo por pixels/DPI, filas, estimativas, rolos, pedaços de tecido, comprovantes e reabertura documentados.
- [~] Validar tamanhos, DPI, margens, espaço, rolos e retalhos em exemplos reais; separar cálculos da UI sem mudar resultados.

### Registros

- [x] Consulta de rolos, itens, eventos, versões anteriores, edição pelo módulo de origem e exportação explícita de contexto JSON para PXToolBox documentadas.
- [x] Exportação com `installationId` e `databaseId` para desambiguar origem; confirmação com mostrar arquivo/copiar caminho.
- [~] Validar pesquisas, reedição, versões e exportações com histórico grande e diferentes bancos.
- [ ] Criar testes de contrato para evolução do JSON, sem confundir etiqueta de pedido informada com identificador comercial formal.

## 2 — P0: rede, concorrência e resiliência

- [~] SQLite usa journal DELETE, timeout e rollback; isso **não certifica** segurança de escrita compartilhada via SMB.
- [ ] Inventariar estações, quem escreve no mesmo `printlogs.db`, desconexões e volume.
- [ ] Testar concorrência e perda de rede em ambiente descartável; definir operação segura e recuperação.
- [ ] Avaliar serviço local/central com acesso coordenado ou banco servidor se a concorrência exigir; não ativar WAL sobre SMB como atalho.
- [ ] Proteger configurações JSON compartilhadas contra conflito de escrita.
- [ ] Garantir reconciliação quando arquivo PDF/JPG for gerado mas registro no banco falhar.

## 3 — P1: ingestão Neo + JetPrime/PrintXP

- [ ] Inventariar formatos reais dos logs JetPrime/PrintXP (uso, tinta, tempos), com exemplos anonimizados.
- [ ] Separar parsers por fonte e manter origem bruta e versão de parser.
- [ ] Importação incremental/idempotente por arquivo e registro, com estado de leitura e tolerância a arquivo ainda sendo escrito.
- [ ] Mapear máquina por identificadores confiáveis, com revisão de ambiguidades.
- [ ] Receber arquivos sincronizados de pastas locais/rede, sem acoplar o domínio à unidade mapeada.
- [ ] Manter dados Neo originais e compatibilidade dos rolos históricos.

## 4 — P1: métricas e conciliação

- [ ] Cruzar eventos Neo (por impressão) com JetPrime/PrintXP (por intervalos/consumo) sem presumir correspondência 1:1.
- [ ] Distinguir produção válida, erro, reposição, altura impressa, espaço, consumo operacional, tempo ativo/parado e tinta.
- [ ] Fórmulas documentadas para eficiência mecânica/útil, velocidade média (m/min), perdas e divergências.
- [ ] Rastrear cada número até os registros originais; marcar incerteza e dados ausentes.
- [ ] Painel por máquina M1/M2, período, tecido, rolo e operador apenas após conciliação confiável.

## 5 — P1: arquitetura modular, sem reescrita prematura

- [ ] Mapear dependências atuais, imports com efeitos de UI e caminhos de configuração.
- [ ] Extrair cálculos e parser puros de `modules/planejador.py` e interfaces de Operação/Configurações gradualmente.
- [ ] Desacoplar relatórios e regras compartilhadas, preservando APIs públicas, formato de banco, CSV, JSON, PDF e nomes de arquivos.
- [ ] Reforçar testes de regressão antes de mover cada módulo.
- [ ] Não converter automaticamente para C#/WPF nem substituir o Nexor Python sem decisão explícita de migração.

## 6 — P2: UX e rastreabilidade operacional

- [ ] Pesquisa unificada de rolos, etiquetas de pedidos informados, arquivos, eventos e versões.
- [ ] Ocorrências, erros e reposições com operador, motivo e histórico.
- [ ] Melhorar navegação, contraste, acessibilidade e produtividade mantendo oito temas e funcionalidades.
- [ ] Expandir smoke de diálogos, relatórios e resolução.

## 7 — P2: planejamento e estoque

- [x] Planejador e cadastro/uso de pedaços de tecido já existem; não recriar do zero.
- [ ] Formalizar estoque físico: rolos de tecido, retalhos, dimensões, localização, reservas, consumo, ajustes e devoluções.
- [ ] Distinguir rolo físico de tecido, rolo operacional de impressão e mapa de Nesting.
- [ ] Vincular planejamento ao executado, com revisão e rastreabilidade de divergências.
- [ ] Respeitar largura, orientação e restrições físicas do tecido; dados devem alimentar o Nesting por contrato.

## 8 — P2: PXToolBox

- [x] Contrato inicial: exportação **manual** de contexto JSON, sem abrir PX/Corel e sem sincronização automática.
- [ ] Versionar contrato de tecido/retalho, mapa, revisão, origem, identificadores idempotentes e consumo.
- [ ] PXToolBox controla geometria/Nesting; Nexor controla materiais, produção e consumo.
- [ ] Importar mapas planejados e comparar com logs de execução sem modificar dados originais silenciosamente.
- [ ] Testes conjuntos, tolerância a versões diferentes e operação independente.

## 9 — P3: expansão controlada

- [ ] Analytics histórico, alertas e previsões somente com métricas verificadas.
- [ ] Multiestação após testes reais de concorrência, latência e volume.
- [ ] Backup remoto e sincronização opcionais; manter operação local em falhas de internet.
- [ ] Integração futura com PX Ecosystem Manager preservando instalador independente.

## Gates de entrega

1. **Implementado** não equivale a **testado** nem a **homologado na fábrica**.
2. Nunca mudar banco, nomes de arquivos ou contratos históricos sem migração e rollback testados.
3. Cada etapa deve ter testes automatizados, dados sintéticos/anonimizados e validação operacional quando aplicável.
4. O fluxo existente de Operação/Planejador/Registros tem prioridade sobre telas novas.
5. Commits em inglês e nenhuma publicação sem autorização.

## Próximas três entregas recomendadas

**A — Auditoria 1.6.41:** validar versão, testes, build, dados, backups e compartilhamento SMB.  
**B — Importação incremental:** Neo + JetPrime/PrintXP com identidade, rastreabilidade e idempotência.  
**C — Conciliação:** métricas verificáveis por máquina e distinção entre impressão, espaço, erro e reposição.
