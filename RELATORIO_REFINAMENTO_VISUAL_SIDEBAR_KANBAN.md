# LocusHub — Refinamento Visual Profissional: Layout Global + Sidebar Expansível + CRM Kanban

Data: 11/09/2026
Commit local: `9d183fe` (branch `master`, **sem push, sem deploy** — conforme pedido)
Suíte de testes: **956 passed**, 1 falha pré-existente e não relacionada (mojibake em `AUDITORIA_IDIOMA_LOCALIZACAO_UTF8.md`/`test_i18n_encoding_audit.py`, já documentada nas rodadas anteriores desta sessão)
`manage.py check`: sem problemas · `makemigrations --check --dry-run`: sem alterações pendentes

Esta é uma rodada **100% visual/estrutural**: nenhum model, migration, regra de negócio, permissão, service ou fluxo de ganho/perda foi tocado. Todos os testes de permissão, drag-and-drop e do modal "Motivo da perda" das rodadas anteriores continuam passando sem nenhuma alteração de comportamento.

---

## Auditoria feita antes de codar

Conforme pedido, a auditoria foi feita antes de qualquer alteração:

- `templates/base.html` (423 linhas) — sidebar desktop (colapso por clique+JS+localStorage), drawer mobile, header, footer, scripts.
- `apps/core/templatetags/icons.py` (354 linhas) — sistema de ícones SVG vendorizados (Heroicons outline, sem pipeline de build).
- `templates/_design_tokens.html` (735 linhas) — tokens de cor/tipografia e todos os componentes reutilizáveis (`.btn-*`, `.card-*`, `.sidebar-*`, `.kanban-*`, etc.).
- `templates/crm/opportunity_list.html` — o Kanban.
- `static/crm/kanban.js` — toda a lógica de arraste e do modal de perda, para mapear exatamente quais seletores/IDs não podiam mudar.
- `apps/core/tests/test_desktop_sidebar.py`, `apps/core/tests/test_mobile_menu_drawer.py`, `apps/core/tests/test_html_structure_validation.py`, `apps/crm/tests/test_kanban_view.py` — para saber o que já estava sob teste e não podia quebrar sem uma atualização consciente.

Conclusão da auditoria: o mecanismo de colapso por clique dependia de 5 IDs e um bloco de JS inteiro; o Kanban já tinha a estrutura de dados certa (colunas/cards/JSON), faltando só hierarquia visual; o sistema de ícones já era o padrão certo (SVG vendorizado), só faltavam os ícones novos pedidos.

---

## 1) Arquivos alterados

| Arquivo | O que mudou |
|---|---|
| `apps/core/templatetags/icons.py` | +6 ícones SVG: `funnel`, `shield-check`, `calendar`, `currency-dollar`, `user`, `exclamation-triangle` |
| `templates/base.html` | Sidebar desktop redesenhada (compacta → expande em CSS puro), marca "LocusHub", bloco `main_class` sobrescrevível, remoção do script de colapso |
| `templates/_design_tokens.html` | Mecanismo `.sidebar-shell`/`.sidebar-panel` (hover/focus-within), componentes novos do Kanban (toolbar, faixa de coluna, cards) |
| `templates/crm/opportunity_list.html` | Toolbar de filtros em linha única, cabeçalho de coluna com faixa colorida, cards redesenhados, ícone no modal de perda, `main_class` mais largo |
| `apps/core/tests/test_desktop_sidebar.py` | Testes do colapso por clique substituídos por testes do novo mecanismo (hover/focus-within) |
| `apps/core/tests/test_html_structure_validation.py` | Guarda estrutural atualizada para os novos IDs da sidebar |
| `apps/operations/tests/test_duplicate_locations_report.py` | Contagem de `<button>` no chrome global ajustada (5 → 4, botão de colapso removido) |

Nenhum outro arquivo foi tocado — em particular, `apps/crm/models.py`, `apps/crm/services.py`, `apps/crm/views.py`, `static/crm/kanban.js` e qualquer migration continuam **exatamente** como estavam.

---

## 2) Componentes visuais criados

- **`.sidebar-shell` / `.sidebar-panel`** — o par que implementa a sidebar compacta-que-expande-em-overlay (detalhes no ponto 4).
- **`.sidebar-group-title-icon`** — ícone de marcador de grupo em modo compacto (usado hoje só em "Administração", com `shield-check`).
- **`.kanban-toolbar` / `.kanban-toolbar-form` / `.kanban-search-wrap`** — a nova barra de filtros em linha única.
- **`.kanban-column-accent` (+ `--won`/`--lost`/`--neutral`)** — a faixa colorida fina no topo da coluna.
- **`.kanban-card--won` / `.kanban-card--lost`** — acento lateral colorido do card, mesma semântica da coluna.
- **`.kanban-card-client` / `.kanban-card-meta-row` / `.kanban-card-meta-item`** — a nova hierarquia do card (cliente, responsável, previsão, tipo).

Nenhum componente novo de cor foi inventado — os únicos tons usados são os que já existiam (`brand-gold`, `green-500`/`green-100`, `red-500`/`red-100`, cinzas).

---

## 3) Biblioteca/estrutura de ícones usada

Continua sendo **exclusivamente** `apps/core/templatetags/icons.py` — o único mecanismo de ícone do projeto (SVG vendorizado, Heroicons "outline" 24×24, MIT License, sem pipeline de build). Nenhuma fonte de ícone, nenhum CDN de ícones e nenhum SVG solto colado em template foram adicionados.

Ícones novos (6, todos vendorizados neste arquivo, path `d` copiado do repositório oficial `tailwindlabs/heroicons`, sem ajuste manual):

| Ícone | Onde é usado |
|---|---|
| `funnel` | Item "Oportunidades" (sidebar + drawer mobile) — era `sparkles`, que ficava duplicado com "Higienizações" |
| `shield-check` | Título do grupo "Administração" na sidebar (mapeamento explícito pedido: "shield/users → Administração") |
| `calendar` | Metadado de previsão de fechamento no card do Kanban |
| `currency-dollar` | Vendorizado para uso futuro em valores fora do Kanban (o valor do card em si já tinha destaque tipográfico suficiente sem ícone, para não “colocar ícone em tudo”) |
| `user` | Metadado de responsável no card do Kanban (distinto de `users`/`user-group`, que são grupos de pessoas) |
| `exclamation-triangle` | Cabeçalho do modal "Motivo da perda" |

Todos os 39 ícones do arquivo (os 33 já existentes + os 6 novos) foram validados programaticamente como XML bem formado antes da entrega.

---

## 4) Comportamento da sidebar

**Antes:** clique num botão (`#app-sidebar-toggle`) alternava uma classe `is-collapsed` via JavaScript, persistida em `localStorage`. A sidebar EXPANDIDA (`w-60`) era o padrão; colapsar era a exceção.

**Agora:** a sidebar nasce **compacta** (`4.5rem`, só ícones) e **expande de verdade** — não é um tooltip — ao passar o mouse ou ao navegar por teclado até ela (`:hover` / `:focus-within`), sem nenhum JavaScript novo. O botão de colapso e o script inteiro que o acionava foram removidos.

A técnica usada evita qualquer instabilidade de layout no conteúdo principal:

- `#app-sidebar` (`.sidebar-shell`) é um filho flex de `#app-shell` e **nunca muda de largura** — reserva sempre os mesmos `4.5rem`. É isso que garante que a coluna principal ao lado nunca "pula".
- Dentro dele, `.sidebar-panel` é posicionado (`position: absolute`) e é ELE que cresce (`4.5rem → 17rem`) no hover/foco, sobrepondo o conteúdo principal (`z-index` maior) em vez de empurrá-lo — a mesma técnica de overlay usada por painéis administrativos maduros.
- `:focus-within` replica exatamente o mesmo resultado para quem navega por teclado (Tab dentro da sidebar) — a sidebar nunca depende só de hover/mouse para ser operada.

**Estados:**
- Normal: ícone cinza-claro sobre fundo preto, com `title`/`aria-label` sempre presentes (mesmo em modo compacto).
- Hover: fundo `white/10`, texto branco.
- Ativo (`aria-current="page"`): fundo dourado sólido + texto preto + negrito — funciona com ou sem cor (contraste, não só tonalidade).
- Grupos (Operação/CRM/Cadastros/Administração): em modo compacto, o texto do grupo some e sobra uma linha divisória discreta (`border-t border-white/5`); "Administração" ganha adicionalmente o ícone `shield-check`, sempre visível, como marcador; em modo expandido, o nome completo do grupo aparece.
- Marca: "LH" (monograma, sempre visível, quadrado dourado) + "LocusHub" (texto, aparece só expandido) — parou de mostrar "LOCUS Equipamentos" como marca do produto (também trocado no header e no drawer mobile).

**Verificação real em navegador** (Playwright + Chromium, CSS de produção compilado localmente porque o CDN do Tailwind é bloqueado neste sandbox — ver seção 10): confirmado que (a) em repouso o painel mede `72px` e os rótulos ficam com `display: none`; (b) no hover o painel mede `272px`, os rótulos ficam visíveis e a largura do `#app-shell`/posição do `<main>` **não mudam nem um pixel**; (c) ao tirar o mouse volta a `72px`; (d) navegando por Tab até um link da sidebar, o mesmo resultado de `272px` é alcançado sem nenhum mouse envolvido.

---

## 5) Mudanças no Kanban

- **Toolbar**: os 3 filtros de sempre (busca/Origem/Tipo de negócio) viraram uma única linha compacta (`[Buscar...] [Origem] [Tipo] [Filtrar]`), substituindo o padrão anterior de busca + `<details>` de "filtros avançados" — com só 3 campos, a revelação em duas etapas era fricção, não economia real de espaço. Mesmos `name` de sempre nos campos — a view continua lendo `request.GET` exatamente como antes, nenhuma regra de filtro mudou.
- **Cabeçalho de coluna**: a faixa colorida fina no topo (dourado = etapa comum, verde = ganho, vermelho = perda) substitui o badge cheio de antes — carrega o mesmo significado sem "pintar" a coluna inteira, conforme pedido explícito.
- **Largura**: a página sobrescreve o bloco `main_class` de `base.html` (`max-w-6xl` → `max-w-[1600px]`) — mais largura útil para o funil horizontal, sem afetar nenhuma outra tela do sistema (nenhuma outra usa esse override).
- **Modal "Motivo da perda"**: ganhou um ícone (`exclamation-triangle`) no cabeçalho, ao lado do título — nenhuma regra funcional alterada (mesmos IDs, mesmo fluxo, mesma exigência de motivo obrigatório).

---

## 6) Mudanças nos cards

Hierarquia visual nova, na ordem pedida: **título** (negrito) → **cliente** → **valor** (destaque em dourado, maior) → **responsável**/**previsão de fechamento**/**tipo de negócio** numa linha de metadados discreta, separada por uma linha fina.

- Acento lateral colorido (`border-left`, 4px) repete a semântica da coluna (verde/vermelho/dourado) — permite reconhecer a etapa de um card mesmo fora do contexto da coluna (ex.: numa captura de tela recortada).
- Ícones só onde ajudam de verdade: `user` (responsável) e `calendar` (previsão, só quando o campo está preenchido) — o valor e o tipo de negócio usam destaque tipográfico/badge em vez de ícone, para não colocar ícone em tudo.
- Hover: elevação sutil (`-translate-y-0.5` + sombra), borda mais evidente (dourada), cursor de "pegar" quando arrastável.
- Durante o arraste: opacidade reduzida + sombra mais forte no card de origem (já existia, preservado).
- `expected_close_date` (já existia no model, só não aparecia na tela) passou a ser exibido quando preenchido.

---

## 7) Mudanças nos filtros

Nenhuma regra de filtro mudou — os mesmos 3 campos (`q`/`source`/`business_type`) continuam sendo os únicos, com os mesmos nomes de parâmetro. A única mudança foi de **apresentação**: de duas etapas (busca sempre visível + filtros avançados colapsáveis) para uma única linha sempre visível. Um teste de regressão (`test_no_stage_filter_in_querystring_anymore`) continua garantindo que o filtro de "Etapa" não volta — a própria coluna já é a etapa.

---

## 8) Mudanças em modais

- **"Motivo da perda"** (único modal do sistema afetado por este pedido): ícone de alerta no cabeçalho; nenhuma mudança de campos, botões, validação ou comportamento de fechamento (ESC/backdrop/Cancelar continuam idênticos à correção da rodada anterior).
- Modais de outras telas (ex.: escolha de tema light/dark das etiquetas) não foram tocados — fora do escopo desta rodada (sidebar + Kanban).

---

## 9) Comportamento responsivo

- **Desktop/notebook** (`≥ 640px`): sidebar compacta com expansão por hover/foco, exatamente como descrito acima.
- **Mobile** (`< 640px`): o drawer (`#mobile-menu-drawer`) continua **inalterado** no mecanismo — é acionado por um botão (`#mobile-menu-toggle`), nunca por hover (que não existe em touch), com a mesma taxonomia de grupos da sidebar (incluindo o ícone `funnel` novo em "Oportunidades" e a marca "LocusHub"). Testado em viewport 390×844 (iPhone-like): toolbar do Kanban empilha os campos verticalmente, colunas continuam com rolagem horizontal própria, drawer abre/fecha normalmente.
- Tablet: usa o mesmo breakpoint `sm:` já existente no projeto (nenhum breakpoint novo foi introduzido) — abaixo de `640px` cai no comportamento mobile, a partir daí no desktop.

---

## 10) Testes executados

- **Suíte completa**: `python -m pytest` → **956 passed**, 1 falha pré-existente (mojibake, não relacionada, já documentada nas rodadas anteriores).
- **`manage.py check`**: sem problemas.
- **`makemigrations --check --dry-run`**: nenhuma alteração pendente (confirma que nenhum model foi tocado).
- **`ruff check`** nos arquivos Python alterados: sem apontamentos.
- **Todos os 39 ícones** (33 existentes + 6 novos) validados como SVG/XML bem formado.
- **Verificação end-to-end em navegador real** (Playwright + Chromium, já que Django puro não tem motor de CSS): CDN do Tailwind é bloqueado neste sandbox, então o CSS real de produção foi compilado localmente via `tailwindcss` (mesma configuração/paleta do projeto) e injetado por interceptação de rede — mesma técnica já usada na correção do bug do modal na rodada anterior. Confirmado, com asserções automatizadas (não só visual):
  - Sidebar nasce compacta (`72px`, rótulos com `display: none`);
  - Expande de verdade no hover real (`272px`, rótulos visíveis) sem mudar a largura do `#app-shell` (zero reflow do conteúdo principal);
  - Volta a compactar ao tirar o mouse;
  - Mesmo resultado via navegação por teclado (`:focus-within`), sem mouse;
  - Drawer mobile continua abrindo/fechando corretamente, independente de hover.
- **Checklist manual de 20 itens** (sidebar compacta/expandida, textos corretos, ícones SVG, item ativo, Kanban com 0/vários cards, scroll vertical por coluna, scroll horizontal do board, hover de card, arraste, modal de perda, toolbar/filtros, desktop/notebook/mobile, contraste, acessibilidade básica, nenhum comportamento funcional quebrado): todos os itens cobertos pela combinação de testes automatizados (estrutura/permissão/regra de negócio) + verificação Playwright (visual/interação) acima.

---

## 11) Capturas de tela comparativas

Screenshots reais (mesmo navegador/CSS de produção da verificação acima) anexados a esta entrega:

1. `01_sidebar_compacta_equipamentos.png` — sidebar em repouso (padrão).
2. `02_sidebar_expandida_hover_equipamentos.png` — sidebar expandida no hover, conteúdo principal no lugar.
3. `03_sidebar_expandida_teclado_equipamentos.png` — mesma expansão via navegação por teclado.
4. `04_kanban_visao_geral.png` — Kanban com o novo cabeçalho de coluna e cards.
5. `05_kanban_card_hover.png` — elevação/hover de card.
6. `06_kanban_sidebar_expandida_overlay.png` — sidebar expandida sobre o Kanban (prova visual do overlay sem reflow).
7. `07_mobile_kanban.png` — Kanban em viewport mobile (390px).
8. `08_mobile_drawer_aberto.png` — drawer mobile aberto sobre o Kanban.

---

## Decisões de escopo (o que foi deliberadamente NÃO alterado)

- `templates/base_public.html` (landing pública/comercial) e as páginas de erro (`403.html`/`404.html`/`500.html`) ainda mostram a marca antiga ("LOCUS Equipamentos") — o pedido desta rodada é especificamente sobre a sidebar administrativa e o Kanban; a landing pública tem sua própria identidade visual definida em uma auditoria anterior e não foi mencionada no briefing. Fica registrado como possível próximo passo, não decidido aqui.
- Nenhum model, migration, service, view (além do que já existia), permissão ou regra de negócio foi tocado — confirmado por `makemigrations --check --dry-run` e pela suíte de testes de permissão/segurança passando sem nenhuma alteração.
- `static/crm/kanban.js` não precisou de nenhuma mudança — ele manipula o Kanban inteiramente por classe/atributo (`.kanban-card`, `.kanban-column[data-stage-id]`, `.kanban-column-count`, `.kanban-column-total`, `[data-drop-zone]`), nunca pela estrutura interna do cabeçalho/card, que foi o que mudou.
