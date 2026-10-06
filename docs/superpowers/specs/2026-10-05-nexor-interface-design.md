# Nexor — redesign da interface

## Objetivo

Aproximar a interface desktop do Nexor da composição do protótipo HTML, mantendo Tkinter/ttk, os serviços de cálculo, importação, exportação, banco de dados e compatibilidade com registros antigos.

## Decisões

- `Nexor.py` continua sendo o shell: navegação lateral, breadcrumb, conteúdo persistente e barra de status.
- Planejador, Operação e Registros mantêm seus callbacks e modelos; a montagem visual passa a usar cabeçalhos, cartões, abas, tabelas e diálogos organizados.
- Configurações permanece como página, com os oito temas, diretório de trabalho e atalhos para cadastros.
- `core/theme.py` continua sendo a única fonte dos tokens; a aplicação percorre ttk e widgets Tk clássicos, incluindo `Toplevel` existentes e criados posteriormente.
- Não serão adicionadas dependências de frontend nem banco de produção para testes.

## Critérios de aceite

- Todos os controles do inventário permanecem acessíveis e ligados às funções reais.
- A seleção de tema é imediata, persistente e não recria páginas.
- A organização visual cobre as quatro áreas do protótipo: Planejador, Operação, Registros e Configurações/cadastros.
- Código compila, testes de contrato passam e os fluxos de domínio continuam sem alteração semântica.
- Capturas novas serão geradas apenas se o ambiente gráfico estiver disponível; caso contrário, a limitação será documentada.
