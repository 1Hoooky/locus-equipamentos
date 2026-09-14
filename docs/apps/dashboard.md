# apps.dashboard

## Objetivo

`apps.dashboard` implementa a **Home operacional** do LocusHub: uma única rota raiz (`"/"`) que agrega, em somente-leitura, indicadores e listas vindos de `apps.equipment`, `apps.maintenance` e `apps.operations`. Não é um dashboard analítico com gráficos — é uma tela de "visão geral + atalhos de navegação" para qualquer usuário autenticado, com escopo deliberadamente restrito (sem higienizações recentes, sem total de clientes/unidades, sem gráficos, sem métricas por funcionário).

## Models

`apps/dashboard/models.py` não define nenhum model. Consistente com `migrations/`, que só tem `__init__.py`. O app é puramente agregador de dados de outros apps.

## Services

Arquivo: `apps/dashboard/services.py`.

- `HomeStatusCounts(disponiveis, em_operacao, em_manutencao)` (dataclass frozen).
- `get_equipment_status_counts()` — 1 query agregada (`GROUP BY status`).
- `get_open_maintenance_count()` — `Maintenance.objects.filter(status=ABERTA, is_active=True).count()`. Distinto do card "Em manutenção" (que é `Equipment.status`) — os dois podem divergir por design.
- `get_recent_movements(limit=5)`, `get_open_maintenances(limit=5)`, `get_equipment_needing_attention(limit=5)` (condição RUIM/INUTILIZAVEL) — todos com `select_related` e `[:limit]` no banco.
- `build_home_context()` — chama as 5 funções acima. **Total: 5 queries fixas por carregamento**, nenhuma escala com o volume de dados — provado por teste dedicado de orçamento de queries.

## Forms

Nenhum — app só de leitura.

## Views

`DashboardHomeView(LoginRequiredMixin, TemplateView)` — única view, `template_name="dashboard/home.html"`, `get_context_data` chama `build_home_context()`.

## URLs

`path("", include("apps.dashboard.urls"))` — primeira rota `include` do projeto, ou seja, a raiz `/`. `name="dashboard:home"`.

## Permissions

Apenas `LoginRequiredMixin` — **nenhum `RoleRequiredMixin`/`CAN_*` dedicado**. Decisão deliberada e documentada: os 4 perfis já têm permissão de consulta sobre tudo que a Home mostra (via `CAN_VIEW_MOVEMENTS`/`CAN_VIEW_MAINTENANCE`, que listam os 4 roles). Qualquer usuário autenticado vê a Home igual; anônimo é redirecionado ao login.

## Templates

Único template: `templates/dashboard/home.html` (raiz do projeto). 4 cards de status (cada um linkando para a listagem filtrada correspondente), 3 colunas de listas (Movimentações recentes, Manutenções abertas, Equipamentos que exigem atenção — com badges de severidade), `empty-state` quando vazias.

## JavaScript

Nenhum — 100% server-rendered, sem AJAX/gráficos (reforçado por teste negativo que confere ausência de `<canvas>`/`chart.js`).

## Dependências

`apps.equipment.models` (`Condition`, `Equipment`, `Status`); `apps.maintenance.models` (`Maintenance`, `MaintenanceStatus`); `apps.operations.models` (`Movement`). Nenhuma dependência de `clients`, `crm`, `catalog`, `qrcodes`, `accounts` (além de `LoginRequiredMixin`).

## Quem chama apps.dashboard

`config/urls.py` (raiz `""`); `config/settings/base.py` (`LOGIN_REDIRECT_URL="dashboard:home"`); `apps.core.nav` (reconhece `dashboard:home` para o menu).

## Testes

`apps/dashboard/tests/test_home_view.py`, 4 classes: acesso (matriz de roles + anônimo), conteúdo (cards refletem contagens reais, teste negativo de escopo), e **`DashboardHomeQueryBudgetTest`** — compara nº de queries com 3 vs. 12 registros semeados e assere que é idêntico (prova automatizada de ausência de N+1/escala).

## Migrations

Nenhuma (só `__init__.py`).

## Pontos importantes

- **Query budget é um requisito de design explícito e testado** — no máximo 5 consultas fixas por carregamento, com teste que falha se esse número crescer com o volume de dados.
- **`is_active=True` filtrado manualmente em cada query** — `SoftDeleteModel` não filtra automaticamente; um indicador novo adicionado sem esse filtro incluiria equipamentos "excluídos".
- **Sem cache** (`cache_page`) — aceitável dado o baixo custo atual; ponto a observar se o volume crescer.
- **Escopo restrito é decisão aprovada e protegida por teste** de regressão, não descuido.
- **Nenhum `RoleRequiredMixin`** é decisão deliberada — mas significa que um role novo introduzido sem as mesmas permissões de `CAN_VIEW_MOVEMENTS`/`CAN_VIEW_MAINTENANCE` faria a Home vazar dados sem que ninguém tenha atualizado esta view.
- Nenhum TODO/FIXME encontrado.
