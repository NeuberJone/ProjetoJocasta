# Nexor

Aplicativo desktop para acompanhar a produção de impressão têxtil, planejar filas e consultar o histórico de rolos. O repositório mantém o nome histórico ProjetoJocasta; o produto e o ponto de entrada atuais são **Nexor**, em `Nexor.py`.

**Versão:** 1.6.66, definida em [`core/version.py`](core/version.py). A consolidação original (05/11/2026) foi feita na 1.6.39; desde então, uma série de incrementos de recurso (vendedor/PDF, Prisma no Planejador/Operação, M1/M2/M3, correção de truncamento — ver [`CHANGELOG.md`](CHANGELOG.md)) e uma auditoria P0 (16/11/2026: suíte isolada com 455 casos, `compileall` limpo, `dist\Nexor-1.6.64.exe` iniciado e confirmado nesta máquina — ver [roadmap de modernização](docs/roadmaps/nexor-modernization-roadmap.md)) avançaram a versão sem reabrir os critérios de aceitação da Fase 1. Nenhum instalador ou pacote de distribuição foi produzido.

## Funcionalidades atuais

| Área | Responsabilidade |
| --- | --- |
| Operação | Importar logs TXT de impressão, identificar máquina/tecido/tipo/operador, organizar itens e espaços, pré-visualizar o vendedor/PDF sugerido de cada pedido (confirmar ou corrigir antes de salvar), fechar ou editar rolos e gerar PDF/JPG. |
| Planejador | Calcular metragem de imagens a partir de pixels e DPI, estimar tempo, organizar filas/rolos e pedaços de tecido, gerar comprovantes e reabrir rolos. |
| Registros | Consultar rolos, itens, eventos e versões anteriores; reabrir um rolo no módulo de origem, exportar contexto de produção para o PX Tool Box e identificar o vendedor/PDF original de cada pedido (localização automática ou manual, abrir PDF/pasta). |
| Gerenciamento e ajuda | Cadastrar impressoras (velocidade manual ou detectada a partir de logs .txt reais) e tecidos, configurar regras de classificação/exportação, escolher temas, consultar o manual e as notas da versão. |
| Configurações · Vendedores | Cadastrar vendedores e as pastas de rede com as artes originais de cada um, com teste de acesso à pasta, e atualizar o índice local usado para localizar os pedidos em Registros. |

Os PDFs/JPGs e o histórico SQLite são locais ou ficam na pasta de produção configurada. O texto de pedido extraído de um arquivo é uma etiqueta operacional; o Nexor não mantém um cadastro formal de pedidos comerciais.

## Desenvolvimento

Base inspecionada: **Python 3.13.7 de 64 bits no Windows**, com Tcl/Tk 8.6. Tkinter faz parte da instalação do Python e não é instalado por `pip`.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --requirement requirements.txt
.\.venv\Scripts\python.exe Nexor.py
```

No Linux, crie o ambiente com `python3.13 -m venv .venv` e use `.venv/bin/python`. Os testes de lógica também são previstos para Linux; recursos que abrem arquivos/pastas usam APIs do Windows e a operação completa da interface fora dele ainda exige adaptação e validação.

As dependências de execução estão fixadas em [`requirements.txt`](requirements.txt): Pillow 11.0.0, PyMuPDF 1.27.1, ReportLab 4.0.7 e tkinterdnd2 0.4.3. São as versões encontradas no ambiente existente, sem atualização nesta etapa. `sqlite3`, `unittest`, derivação de senhas e logging usam a biblioteca padrão.

Instalação nova a partir dos manifestos (16/11/2026): `.venv` criado do zero com `py -3.13 -m venv .venv` (nenhum existia neste ambiente) e `requirements.txt`/`requirements-build.txt` instalados nele sem erro; a suíte isolada (461 testes) e `compileall` passaram usando esse `.venv` recém-criado. Não cobre um build de validação a partir desse `.venv` nem CI remota (ver [roadmap de modernização](docs/roadmaps/nexor-modernization-roadmap.md)); os pins continuam sem hashes dos pacotes.

## Testes isolados

```powershell
.\.venv\Scripts\python.exe scripts/run-tests-isolated.py -v
.\.venv\Scripts\python.exe -m compileall -q Nexor.py core modules scripts
```

O runner define os diretórios de perfil, configuração e temporários **antes de importar** o aplicativo. Cada execução usa uma pasta temporária em `build/test-runs/`, removida ao terminar, e um `base_dir` próprio. Testes que substituem caminhos devem manter esse isolamento. Para filtrar: `python scripts/run-tests-isolated.py -p test_operacao_parser.py -v`.

Use esse comando para a suíte; a descoberta direta pode resolver caminhos de configurações durante imports. Os testes automatizados não exigem logs reais, banco de produção ou uma janela Tk aberta. A [CI](.github/workflows/tests.yml) executa unittest e compilação em Python 3.13 no Windows e no Linux; não publica arquivos e não gera builds.

O comando de descoberta de referência abaixo requer que perfil, configurações, pasta base e temporários já estejam isolados antes dos imports. O runner acima prepara esse ambiente automaticamente e é a opção recomendada para uso local:

```powershell
python -m unittest discover -s tests -v
```

O smoke opcional da interface exige Windows, sessão gráfica e Tcl/Tk funcionando: `python scripts/smoke-ui-isolated.py`. Ele usa dados descartáveis em `build/ui-smoke/` e janela transparente. Nesta etapa, verificou startup, seis páginas, oito temas e navegação a 980×600, além de preservar uma configuração inválida e manter ajuda acessível. Não substitui revisão visual nem teste com impressora/rede.

## Dados e manutenção

Configuração principal: `%APPDATA%\PXCore\config.json`; configurações compartilhadas por módulo: `%APPDATA%\PXCore\modules\`. Cadastros e a configuração legada da Operação mantêm seus caminhos existentes. O banco é `<base_dir>\data\printlogs.db`, com o `base_dir` salvo na configuração. Alterar essa pasta seleciona outra base; não transfere o histórico automaticamente.

Falhas de leitura, JSON inválido e falhas de gravação passam a ser explícitas. A recuperação de configuração requer uma chamada deliberada e preserva uma cópia do arquivo inválido. Diagnóstico e backup SQLite usam uma conexão separada à origem, sem executar migrações. As APIs, os caminhos completos e as limitações de rede estão em [estado atual da arquitetura](docs/architecture/current-state.md).

O log técnico usa `%LOCALAPPDATA%\Nexor\logs`, separado dos logs das impressoras e dos eventos de produção. Ele registra origem, nível e contexto técnico sem incluir senhas ou conteúdo de pedidos. Consulte a [dívida técnica](docs/architecture/technical-debt.md) para as limitações restantes.

## Build Windows

O arquivo oficial é [`Nexor.spec`](Nexor.spec), com módulos dinâmicos, tkinterdnd2 e `CHANGELOG.md`. `requirements-build.txt` inclui o runtime e fixa PyInstaller 6.16.0, seus hooks e dependências para Windows. `PXList.spec` é uma referência antiga e aponta para um entrypoint ausente; não é o build do Nexor.

Quando um build de validação for solicitado, use saídas novas para preservar `build/` e `dist/` existentes:

```powershell
.\.venv\Scripts\python.exe -m pip install --requirement requirements-build.txt
$buildId = "validation-" + [guid]::NewGuid().ToString("N")
.\.venv\Scripts\python.exe -m PyInstaller --distpath "dist\$buildId" --workpath "build\$buildId" Nexor.spec
```

O spec prefere a detecção padrão de Tcl/Tk. O fallback existente para Python portátil Windows/Tcl/Tk 8.6 só é aplicado quando o hook falha e todos os arquivos esperados existem. A adaptação depende de detalhes internos do PyInstaller e precisa de teste do executável ao alterar Python ou o empacotador. O build isolado em `dist/foundation-validation-20261105-144030/` foi inspecionado: contém `CHANGELOG.md`, Tcl/Tk e seus arquivos de inicialização. Na auditoria P0 de 16/11/2026, `dist\Nexor-1.6.64.exe` foi de fato iniciado nesta máquina (processo real, filho do bootloader onefile, com o título de janela esperado) e encerrado sem travar — primeira vez que o executável congelado roda, não só é inspecionado; ainda não é smoke visual completo. Nenhum instalador ou pacote de distribuição foi produzido.

## Documentação

- [Arquitetura e estado atual](docs/architecture/current-state.md)
- [Dívida técnica e riscos conhecidos](docs/architecture/technical-debt.md)
- [Roadmap de modernização](docs/roadmaps/nexor-modernization-roadmap.md)
- [Histórico de versões](CHANGELOG.md)
- [Regras do editor visual de tipos](docs/relatorio-editor-visual-tipos-impressao.md)

Autor: [Neuber Jone](https://github.com/NeuberJone).
