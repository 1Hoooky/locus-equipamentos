# Locus Locações — Refinamento da Sidebar / Reorganização da Arquitetura de Navegação + Scroll Horizontal do Kanban

Data: 11/09/2026
Commit local: `650ee59` (branch `master`, **sem push, sem deploy** — conforme pedido)
Suíte de testes: **980 passed**, 1 falha pré-existente e não relacionada (mojibake em `AUDITORIA_IDIOMA_LOCALIZACAO_UTF8.md`/`test_i18n_encoding_audit.py`, já documentada nas rodadas anteriores desta sessão — o próprio arquivo de auditoria contém, de propósito, exemplos de mojibake como parte do que ele documenta)
`manage.py check`: sem problemas · `makemigrations --check --dry-run`: sem alterações pendentes — **nenhuma migration nesta tarefa**, como pedido

Esta é uma rodada **100% de navegação/UI**: nenhum model, migration, view nova, URL, service, regra de negócio ou permissão foi criado/alterado. Toda checagem de visibilidade (`perms.crm.*`, `user.is_admin`, `user.is_superuser`, `user.is_administrativo_ou_superior`, `RoleRequiredMixin`/`allowed_roles`) é exatamente a mesma de antes — só reorganizada visualmente.

---

## Branding

Nos dois pedidos que chegaram no meio da auditoria desta tarefa, a marca foi trocada de **"LH"/"LocusHub"** para **"LL"/"Locus Locações"**: "LL" é o monograma exibido com a sidebar compacta (fechada); "Locus Locações" é o texto completo, exibido com a sidebar expandida (hover/foco), no drawer mobile, no header (usuário anônimo/mobile) e no rodapé. Aplicado em `templates/base.html`, `templates/crm/opportunity_list.html` (título da aba) e nos testes que verificavam a string antiga.

---

## 1) Estrutura final da sidebar

Ordem fixa, cada grupo com ícone + nome + seta indicadora, expansível/recolhível:

```
Início                                  (ação independente, fora de qualquer grupo)

▾ CRM                                   (só aparece com alguma permissão comercial)
    Funil                     -> crm:opportunity_list
    Origens                   -> crm:commercial_source_list      (perms.crm.manage_commercial_settings)
    Etapas                    -> crm:opportunity_stage_list       (perms.crm.manage_commercial_settings)
    Motivos de perda          -> crm:loss_reason_list             (perms.crm.manage_commercial_settings)

▾ Operação
    Equipamentos               -> equipment:list
    Manutenções                -> maintenance:maintenance_list
    Higienizações               -> maintenance:cleaning_list

▾ Cadastros
    Clientes                    -> clients:list
    Colaboradores                -> accounts:user_list           (is_admin/is_superuser — era "Usuários")
    Unidades                    -> operations:location_list
    Categorias                   -> catalog:category_list         (is_administrativo_ou_superior/is_superuser)
    Modelos                      -> catalog:model_list             (is_administrativo_ou_superior/is_superuser)

▾ Configurações do sistema        (só aparece para is_admin/is_superuser)
    Importar planilha            -> equipment:import_upload
    Cargos                        -> accounts:role_list            (só is_superuser)
    Diagnóstico de unidades      -> operations:duplicate_locations_report
```

O drawer mobile usa exatamente esta mesma estrutura/ordem/permissões (fonte única de verdade compartilhada — ver seção 5).

---

## 2) Arquivos alterados/criados

| Arquivo | O que mudou |
|---|---|
| `apps/core/nav.py` *(novo)* | Função pura `active_nav_group(view_name, app_name)` — decide qual dos 4 grupos deve abrir sozinho na página atual. Sem request/DB, testável isoladamente. |
| `apps/core/templatetags/nav.py` *(novo)* | Template tag `{% active_nav_group as current_group %}`, fino adaptador sobre a função pura acima. |
| `apps/core/tests/test_nav.py` *(novo)* | 15 testes unitários da função pura (todas as combinações de app/grupo, incluindo os 3 apps que espalham rotas por mais de um grupo). |
| `apps/core/templatetags/icons.py` | +4 ícones SVG vendorizados: `bolt` (ícone do grupo Operação), `folder` (ícone do grupo Cadastros), `x-circle` (item Motivos de perda), `identification` (item Colaboradores). |
| `templates/base.html` | Reescrita da sidebar desktop e do drawer mobile: 4 grupos em acordeão (era 3 grupos estáticos + Administração separada), branding "LL"/"Locus Locações", JS novo de acordeão (abrir/fechar grupo + persistência de UI em localStorage). |
| `templates/_design_tokens.html` | Novas classes `.sidebar-group*`/`.mobile-menu-group*` (botão de acordeão, corpo do grupo, seta rotativa); regras de compacto/expandido estendidas para os grupos; barra de rolagem horizontal do Kanban estilizada (nunca escondida). |
| `templates/crm/opportunity_list.html` | Título da aba atualizado; decisão sobre o botão "Configurações comerciais" documentada inline (ver seção 4). |
| `static/crm/kanban.js` | +wheel-to-horizontal-scroll (com as 3 checagens de conflito) e +auto-scroll durante o arraste perto da borda do quadro. |
| `apps/core/tests/test_desktop_sidebar.py` | Reescrito para a nova estrutura de 4 grupos/acordeão/branding — cobre taxonomia, ordem, abertura automática, matriz de permissão (inclusive CRM). |
| `apps/core/tests/test_mobile_menu_drawer.py` | Idem, para o drawer. |
| `apps/operations/tests/test_duplicate_locations_report.py` | Contagem de `<button>` do chrome global atualizada (+6, um botão de acordeão por grupo × sidebar+drawer). |

---

## 3) URLs reaproveitadas — nenhuma nova

Todo item do menu aponta para a MESMA rota (`name`/namespace) que já existia antes desta rodada. Nenhuma view, nenhum `path()` novo foi criado. A troca de rótulo "Usuários" → "Colaboradores" continua resolvendo `accounts:user_list` (`/contas/usuarios/`), com a mesma permissão (`is_admin`/`is_superuser`, `CAN_MANAGE_USERS`/`RoleRequiredMixin` na view).

---

## 4) Nomenclaturas visuais alteradas

- "Usuários" → **"Colaboradores"** (mesma URL/permissão).
- "Administração" → **"Configurações do sistema"** (mesmo conjunto de itens administrativos, mais Cargos/Diagnóstico/Importar, já revisados individualmente antes de mover).
- "Config. comerciais" (um único link agregador) → **3 itens diretos**: Origens / Etapas / Motivos de perda.
- Marca: "LH"/"LocusHub" → **"LL"/"Locus Locações"**.
- **Decisão documentada sobre o botão "Configurações comerciais" dentro da própria tela do Funil**: mantido (não removido). Ele deixou de ser o único caminho até Origens/Etapas/Motivos de perda — agora há itens diretos na sidebar/drawer — mas continua como atalho de contexto (o usuário está trabalhando no funil e pode preferir não abrir a sidebar). A decisão está documentada como comentário no próprio `templates/crm/opportunity_list.html`, junto ao botão.

---

## 5) Regras de exibição por permissão (sem nenhuma alteração de regra em si)

- CRM: grupo inteiro some se `perms.crm.view_opportunities` e `perms.crm.manage_commercial_settings` forem ambos falsos. Dentro do grupo, Funil exige a primeira permissão; Origens/Etapas/Motivos de perda exigem a segunda — cada item, individualmente, exatamente como antes.
- Operação e Cadastros nunca ficam vazios para um autenticado (Equipamentos/Manutenções/Higienizações e Clientes/Unidades não têm gate extra) — Categorias/Modelos/Colaboradores continuam exigindo `is_administrativo_ou_superior`/`is_admin` (ou superusuário) dentro de Cadastros.
- Configurações do sistema: grupo inteiro só renderiza com `is_admin` ou `is_superuser` (mesma condição de antes, só que agora também controla a visibilidade do GRUPO, não só dos itens). Cargos exige adicionalmente `is_superuser`.
- **Grupo vazio nunca aparece** — coberto por teste (`CrmSidebarGroupTest.test_group_absent_without_any_crm_permission`, `DesktopSidebarPermissionMatrixTest.*`).
- A fonte de verdade de qual grupo abre sozinho (`apps.core.nav.active_nav_group`) é usada IGUALMENTE pela sidebar e pelo drawer — testado para os 3 apps que espalham rotas por mais de um grupo (`equipment`, `accounts`, `operations`).

---

## 6) Comportamento do dropdown/acordeão

- Cada grupo é um `<button aria-expanded="…">` semântico (nunca uma `<div>` clicável) com corpo (`.sidebar-group-body`/`.mobile-menu-group-body`) que some/aparece lendo o `aria-expanded` do botão irmão — mesmo padrão de disclosure já usado em `.model-group-toggle` no projeto.
- O grupo da página atual nasce **sempre aberto**, renderizado assim pelo próprio servidor (Django, via `current_group`) — o usuário nunca precisa abrir manualmente um grupo para descobrir onde está.
- Clicar em qualquer grupo abre/fecha (JS puro, `[data-group-toggle]`). Grupos que o usuário abriu manualmente (fora do grupo ativo) ficam lembrados entre recarregamentos via `localStorage` (`locus:sidebarOpenGroups`) — **nunca guarda nenhuma decisão de autorização**, é só uma preferência de UI; o grupo da própria página atual nunca é persistido (sempre reabre sozinho, de qualquer estado anterior).
- Seta (`chevron-down`) rotaciona 90° conforme `aria-expanded`.

---

## 7) Comportamento compacto/expandido (desktop)

- Mecanismo de hover/foco herdado da rodada anterior, sem alteração (`.sidebar-shell`/`.sidebar-panel`, CSS puro).
- **Compacto**: mostra só Início + um ícone por grupo renderizado (o corpo do grupo fica escondido mesmo que `aria-expanded="true"` — regra dedicada, testada via Playwright).
- **Hover/foco**: nomes de grupo, seta e o corpo do grupo cuja `aria-expanded="true"` aparecem; os demais continuam escondidos até o usuário clicar.
- Ícone do item ativo dentro do grupo recebe o destaque dourado de sempre (`.sidebar-link-active`).

---

## 8) Comportamento mobile

- Drawer não depende de hover (não faz sentido em touch) — continua 100% dependente de clique/JS, mecânica de abrir/fechar preservada sem alteração.
- Mesma taxonomia/ordem/permissões da sidebar desktop, agora também em acordeão (era um `<p>` de título estático).

---

## 9) SVGs usados (novos nesta rodada)

`bolt` (grupo Operação), `folder` (grupo Cadastros), `x-circle` (Motivos de perda), `identification` (Colaboradores) — Heroicons "outline" 24×24, MIT License, mesmo padrão de vendorização já usado no projeto (`apps/core/templatetags/icons.py`). Reaproveitados como ícone de GRUPO: `funnel` (CRM) e `cog-6-tooth` (Configurações do sistema). Todos passam no teste de boa-formação de XML (`apps/core/test_icons_templatetag.py`).

---

## 10) Scroll horizontal do Kanban

- Roda do mouse/trackpad sobre a área do Kanban agora rola o funil horizontalmente (para baixo → direita, para cima → esquerda) — implementado com `wheel` + `{ passive: false }` em `static/crm/kanban.js`.
- Gesto nativo de trackpad horizontal nunca é interceptado (`Math.abs(deltaX) > Math.abs(deltaY)` → sai sem `preventDefault`).
- Coluna com scroll vertical próprio disponível NESSA direção tem prioridade — o funil só assume quando a coluna não tem mais para onde rolar.
- O funil só intercepta o gesto quando de fato tem para onde rolar horizontalmente naquela direção — nos limites, devolve o gesto ao navegador (nunca trava a página).
- Barra de rolagem horizontal permanece sempre visível/funcional (nunca `overflow: hidden`), estilizada discretamente na identidade Locus (trilho neutro, "polegar" dourado).
- Auto-scroll suave (`requestAnimationFrame`) ao arrastar um card perto da borda esquerda/direita do quadro — para assim que o arraste termina (`dragend`).
- Nada disso toca em permissão, na transição de etapa (`change_opportunity_stage`), em CSRF, `transaction.atomic`/`select_for_update` ou no histórico — é só `scrollLeft`, puramente visual.

---

## 11) Testes realizados

- `apps/core/tests/test_nav.py` (novo, 15 testes) — função pura de decisão de grupo.
- `apps/core/tests/test_desktop_sidebar.py` (reescrito) — acessibilidade, taxonomia/ordem dos 4 grupos, mecanismo de hover/foco herdado, abertura automática por grupo, matriz de permissão completa (Consulta/Administrativo/Admin/superusuário), grupo CRM (ausência sem permissão, presença com os 4 itens).
- `apps/core/tests/test_mobile_menu_drawer.py` (reescrito) — mesma cobertura, no drawer.
- `apps/core/tests/test_html_structure_validation.py` — HTML continua bem formado em toda a matriz de perfil (sem alteração de asserções, só validado contra a nova estrutura).
- `apps/operations/tests/test_duplicate_locations_report.py` — contagem de `<button>` do chrome global atualizada e revalidada.
- `apps/core/test_icons_templatetag.py` — os 4 ícones novos passam na checagem de XML bem formado.
- `apps/crm/*` (83 testes) — nenhuma regressão (permissão, IDOR, drag-and-drop, matriz de perfis).
- Verificação visual end-to-end via Playwright + Chromium (CSS real do Tailwind compilado localmente, mesma técnica das rodadas anteriores) — script solto em `/tmp/.../scratchpad/verify_sidebar_reorg.py`, screenshots anexados. Cobre: marca "LL"/"Locus Locações"; sidebar compacta mostrando só ícone por grupo; hover expandindo de verdade; grupo ativo abrindo sozinho (Equipamentos → Operação, Cargos → Configurações do sistema); clique abrindo/fechando um grupo não-ativo; ordem dos 4 grupos (desktop e mobile); drawer mobile com o mesmo comportamento (Clientes → Cadastros); scroll horizontal do Kanban via roda do mouse (nos dois sentidos); barra de rolagem nunca escondida; auto-scroll ao arrastar perto da borda direita, parando no `dragend`.

### Checklist de validação do pedido original (28 itens da Parte 1 + 14 da Parte 2)

Todos os itens abaixo foram verificados (via teste automatizado, Playwright, ou ambos):

**Parte 1 — sidebar/drawer**: admin vê todos os grupos permitidos · CRM aparece primeiro · Operação segundo · Cadastros terceiro · Configurações do sistema por último · Funil/Origens/Etapas/Motivos de perda/Equipamentos/Manutenções/Higienizações/Clientes/Colaboradores/Unidades/Categorias/Modelos cada um abre a tela correta · usuário sem `manage_commercial_settings` não vê Origens/Etapas/Motivos de perda · usuário sem acesso administrativo não vê "Configurações do sistema" · grupo vazio nunca renderiza · página atual auto-abre seu próprio grupo · item ativo é destacado corretamente · sidebar compacta funciona · hover/expansão funciona · dropdown/acordeão funciona · drawer mobile funciona · todo ícone é SVG · nenhum link perdeu sua proteção de backend (matriz de permissão revalidada ponta a ponta).

**Parte 2 — scroll do Kanban**: roda do mouse sobre o Kanban · rola para a direita · rola para a esquerda · trackpad horizontal nativo preservado · barra inferior continua visível/funcional · coluna com scroll vertical próprio é respeitada · página com scroll vertical não trava · arraste perto da borda direita auto-rola · arraste perto da borda esquerda auto-rola (mesma lógica, direção espelhada) · muitos cards (testado com 6 oportunidades numa etapa) · muitas etapas (6 etapas, todas visíveis via scroll) · notebook (1440×900) · mobile/touch (drawer testado a 390×844 — o Kanban em si mantém a mesma estrutura de scroll horizontal por toque nativo do navegador, sem nenhuma dependência de mouse).

---

## 12) `python manage.py check`

```
System check identified no issues (0 silenced).
```

## 13) `python manage.py makemigrations --check --dry-run`

```
No changes detected
```

Nenhuma migration foi criada nesta tarefa, como pedido.

---

## Resultado da suíte completa

```
980 passed, 1 failed (pré-existente, não relacionada) in ~327s
```

A única falha é `MojibakeRegressionTest.test_no_mojibake_in_tracked_repository_files`, já documentada em rodadas anteriores desta sessão: o próprio arquivo `AUDITORIA_IDIOMA_LOCALIZACAO_UTF8.md` e o teste que o audita contêm, de propósito, exemplos de sequências de mojibake como parte do que documentam — não é uma regressão desta tarefa.

---

## O que NÃO foi feito (por design, conforme pedido)

- Nenhum model, campo, migration, app ou nome de model foi alterado (`User` continua `User`, `accounts` continua `accounts`).
- Nenhuma permissão nova foi criada.
- Nenhuma URL/view duplicada.
- Nenhuma proteção de backend removida.
- Nenhuma decisão de autorização em JavaScript — localStorage guarda só preferência de UI (quais grupos, além do ativo, o usuário deixou abertos).
- Commit feito **só localmente** (`650ee59`) — sem `git push`, sem deploy.
