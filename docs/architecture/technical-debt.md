# Nexor: dívida técnica

Referência: consolidação de 05/11/2026, versão 1.6.39. Prioridades consideram risco operacional e custo de alteração. Testes locais reduzem riscos específicos; não certificam a infraestrutura de produção.

**Nota 13/11/2026, versão 1.6.61.** Nenhum item abaixo foi reavaliado ou resolvido pelos incrementos de recurso registrados no `CHANGELOG.md` entre 1.6.40 e 1.6.61 (vendedor/PDF, Prisma, M1, impressão incompleta) — nenhum deles tocou SQLite/SMB, backup, JSON concorrente ou o acoplamento do Planejador descritos na tabela. A única evidência nova e real relacionada a itens já listados: a suíte de testes cresceu pra 442 casos (linha "suíte não cobre interação completa" — continua válida, pois o crescimento foi de testes unitários, não de smoke/visual) e os incrementos leram diretamente a pasta SMB real da M1/M2/M3 para diagnóstico (linha "SQLite em SMB" — não se aplica, já que não é o banco; nenhum item da tabela foi tocado por isso).

**Nota 16/11/2026, versão 1.6.64.** Auditoria P0: suíte cresceu pra 455 casos, todos passando, mais `compileall` limpo. Evidência nova real para a linha "Backup/diagnóstico são APIs técnicas, sem rotina agendada ou restauração homologada": `tests/test_backup_restore_drill.py` (novo) exercita, pela primeira vez, uma restauração de ponta a ponta lida de volta pelas consultas reais do aplicativo (não só `diagnose_database`) e um bloqueio de escrita real (`PRAGMA locking_mode=EXCLUSIVE`, sem mock) — ainda disco local de um processo só, não o compartilhamento SMB real nem concorrência entre estações; a linha "SQLite pode estar em uma pasta SMB" continua com o mesmo "próximo passo" pendente. Para a linha "Fallback Tcl/Tk ... executável incompleto": `dist\Nexor-1.6.64.exe` foi de fato iniciado nesta máquina (processo filho do bootloader abriu com o título de janela esperado) — primeira vez que o executável congelado é iniciado, não só inspecionado; ainda não é smoke visual completo.

| Prioridade | Situação observada | Efeito | Próximo passo e evidência necessária |
| --- | --- | --- | --- |
| Alta | SQLite pode estar em uma pasta SMB acessada por várias estações. | Locking e interrupções de rede podem afetar disponibilidade e integridade. | Mapear concorrência e testar bloqueio/desconexão em ambiente descartável. Avaliar serviço com banco local. |
| Alta | Backup/diagnóstico são APIs técnicas, sem rotina agendada ou restauração homologada. | Uma cópia existente pode não atender ao tempo de recuperação esperado. | Definir frequência, retenção, responsável e ensaio de restauração. |
| Alta | JSON não tem controle de versão ou lock de alteração concorrente. | Escrita atômica preserva arquivos, mas o último gravador pode perder a alteração de outro processo. | Medir uso simultâneo; serializar as preferências efetivamente compartilhadas. |
| Média | Planejador concentra cálculo, UI, filas, relatórios e persistência; Operação/Configurações também têm interfaces extensas. | Alterações de layout e regra têm fronteiras pouco claras. | Extrair funções puras e serviços pequenos com regressão dos resultados conhecidos. |
| Média | Planejador depende de Operação/Configurações; pacotes importam UI no `__init__.py`. | Acoplamento e efeitos de import dificultam execução sem GUI. | Preservar entradas públicas e mover dependências comuns para serviços neutros. |
| Média | Preferências estão distribuídas entre PXCore e caminhos legados Nexor/ProjetoJocasta. | Suporte e recuperação exigem conhecer múltiplas pastas. | Inventariar migrações e testar idempotência; centralizar caminhos sem mudanças silenciosas. |
| Média | Relatórios e registro SQLite são etapas distintas. | Um arquivo pode existir mesmo se a gravação do histórico falhar. | Manter resultado parcial explícito e avaliar retomada sem duplicação. |
| Média | A suíte não cobre interação completa do operador e todos os temas/resoluções. | Regressões de navegação, diálogos e rolagem podem escapar. | Smoke em perfil descartável e roteiro visual curto por fluxo crítico. |
| Média | CI e instalação limpa ainda precisam de evidência externa. | Wheels, Tcl/Tk e permissões podem diferir em outra máquina. | Executar matriz e criar ambiente novo a partir dos manifestos. |
| Média | Fallback Tcl/Tk usa detalhes internos do PyInstaller e layout Windows 8.6. | Atualizações podem produzir um executável incompleto. | Build em saída nova e smoke do executável após atualizar Python/empacotador. |
| Média | Helpers DEV não estão ligados a um fluxo ativo da UI atual. | Hash forte não representa autorização funcional nem proteção contra edição local. | Definir o escopo antes de expor controles DEV; manter permissões do SO. |
| Baixa | Pins sem hashes dos pacotes e sem política de atualização. | Reprodução depende de disponibilidade/procedência dos pacotes. | Atualização controlada e hashes após instalação limpa comprovada. |
| Baixa | Explorer, `os.startfile`, fontes e fallbacks Windows persistem. | Testes Linux não significam suporte à interface Linux/macOS. | Decidir plataformas suportadas e depois homologar adaptadores. |
| Baixa | `PXList.spec`, material legado e planos antigos permanecem. | Podem ser confundidos com o fluxo atual. | Identificar referências antigas; arquivar só com decisão explícita. |

## Melhorias desta etapa e seus limites

JSON atômico e erros explícitos evitam substituir automaticamente configuração danificada por defaults. A recuperação preserva o original, mas não reconstrói valores desconhecidos. PBKDF2 mantém compatibilidade com SHA-1 até autenticação correta e persistida.

SQLite tem espera de bloqueio, fechamento em falhas e rollback; diagnóstico/backup não inicializam ou migram a origem. Logging com rotação registra diagnósticos separados dos dados operacionais. A consolidação preserva regras de produção, IDs, contrato PX Tool Box, versão e locais existentes.

Essas propriedades não resolvem locking defeituoso de rede, concorrência de configuração, perda física do armazenamento, acesso administrativo à estação ou fluxos sem cobertura da interface.

## Referências

- [Estado atual e APIs](current-state.md)
- [Roadmap e critérios de saída](../roadmaps/nexor-modernization-roadmap.md)
- [SQLite: ressalvas de acesso pela rede](https://sqlite.org/useovernet.html)
- [SQLite: condições que podem causar corrupção](https://sqlite.org/howtocorrupt.html)
