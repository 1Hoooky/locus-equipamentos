# apps.crm

## Objetivo

`apps.crm` é o funil de vendas/CRM do LocusHub: gerencia `Opportunity` desde a criação até o fechamento (ganho ou perdido), organizadas num Kanban por `OpportunityStage` configurável. Reutiliza `apps.clients.models.Client` como fonte oficial de cliente (nunca cópia, nunca escreve). Inclui registro de atividades comerciais (`CommercialActivity`), histórico estruturado de mudança de etapa (`OpportunityStageChange`) e configuração de Origem/Etapa/Motivo de perda. Propostas, contratos, agenda central, dashboard, financeiro, comissão, automações e integrações externas ficam para etapas futuras.

## Models

Arquivo: `apps/crm/models.py`.

- `CommercialSource`, `OpportunityStage` (com `is_won`/`is_lost`, `CheckConstraint` impede ambos simultâneos), `LossReason` — todos `TimeStampedModel, SoftDeleteModel`, configuráveis (não `TextChoices`).
- `BusinessType` (TextChoices, fixo): LOCACAO, VENDA, SERVICO.
- **`Opportunity(TimeStampedModel)`** — **não** `SoftDeleteModel** (sem fluxo de excluir/desativar, só hard delete). `client` (FK, PROTECT), `title`, `owner` (FK User, PROTECT), `source` (FK, PROTECT), `business_type`, `stage` (FK, PROTECT), `expected_close_date`, `estimated_value`, `notes`, `loss_reason` (FK, PROTECT, nullable), `loss_notes`, `won_at`, `lost_at`, `closed_value`, `created_by` (PROTECT). `history = HistoricalRecords()`. `CheckConstraint`s: não ganho+perdido simultâneo, valores ≥0. `Meta.permissions`: `view_opportunities`, `add_opportunities`, `change_opportunities`, `change_opportunity_stage`.
- **`OpportunityStageChange`** — histórico estruturado append-only: `opportunity` (CASCADE), `from_stage`/`to_stage` (PROTECT), `changed_by` (PROTECT), `changed_at`, `reason`.
- `ActivityType` (TextChoices). **`CommercialActivity`** — `opportunity` (CASCADE), `activity_type`, `description`, `occurred_at`, `scheduled_for` (alimentará futura Agenda Central), `completed_at`, `created_by` (PROTECT). Sem histórico (sem fluxo de edição/exclusão). `Meta.permissions`: `view_commercial_activities`, `add_commercial_activities`.

## Services

Arquivo: `apps/crm/services.py`.

- `eligible_owner_queryset()` — usuários ativos com `is_superuser` ou permission `crm.add_opportunities`.
- `create_opportunity(data)` — `@transaction.atomic`; rejeita etapa ganha/perdida/inativa; cria `Opportunity` + 1ª linha de `OpportunityStageChange`.
- `update_opportunity(*, opportunity, data, changed_by)` — só campos cadastrais; nunca `client`/`stage`/campos de fechamento.
- **`change_opportunity_stage(*, opportunity_id, new_stage, changed_by, reason="", loss_reason=None, loss_notes="", closed_value=None)`** — `@transaction.atomic` + `select_for_update()` (testado com concorrência real). Único caminho de escrita de `stage`/`won_at`/`lost_at`/`loss_reason`/`closed_value`. Regras: rejeita mesma etapa/etapa inativa; ganho → seta `won_at`, limpa perda; perda → exige `loss_reason`; etapa intermediária → reabre, limpa todo estado de fechamento. Sempre cria `OpportunityStageChange`.
- `create_activity(data)` — valida `activity_type`.
- `preview_opportunity_hard_delete()` / `hard_delete_opportunity(*, opportunity_id, actor)` — `select_for_update()`, exige `actor.is_superuser`, cascade automático de stage_changes/activities.

## Forms

- **`ClientAutocompleteWidget`** — renderiza `<input>` de busca (sem `name`, nunca enviado) + `<input type="hidden">` (único valor visto pelo Django) + dropdown; o campo continua um `ModelChoiceField` normal — a validação real é 100% do `ModelChoiceField.clean()`.
- `OpportunityCreateForm` — `client` (autocomplete), `title`, `owner`, `source`, `business_type`, `stage` (restrito a ativas/não-ganhas/não-perdidas), `notes`. **`estimated_value`/`expected_close_date` removidos da criação** (12/09/2026 — pensados para preenchimento futuro automático via equipamentos vinculados).
- `OpportunityUpdateForm` — sem campo `client` (imutável pós-criação).
- `OpportunityStageChangeForm` — `loss_reason` obrigatório via `clean()` se `stage.is_lost`.
- `CommercialActivityForm`, `CommercialSourceForm`/`OpportunityStageForm`/`LossReasonForm` (ModelForms de configuração).

## Views

Arquivo: `apps/crm/views.py`. **Único app que usa `LoginRequiredMixin`+`PermissionRequiredMixin`** (não `RoleRequiredMixin`), exceto hard delete (`SuperuserRequiredMixin`).

| View | `permission_required` |
|---|---|
| `OpportunityListView` (Kanban) / `OpportunityDetailView` | `crm.view_opportunities` |
| `OpportunityCreateView` / `OpportunityClientAutocompleteView` | `crm.add_opportunities` |
| `OpportunityUpdateView` | `crm.change_opportunities` |
| `OpportunityHardDeleteView` | `SuperuserRequiredMixin` (fora do catálogo) |
| `OpportunityStageChangeView` | `("crm.view_opportunities", "crm.change_opportunity_stage")` |
| `CommercialActivityCreateView` | `("crm.view_opportunities", "crm.add_commercial_activities")` |
| `CommercialSource*`/`OpportunityStage*`/`LossReason*` (9 views) | `crm.manage_commercial_settings` |

### `OpportunityClientAutocompleteView`

`MIN_QUERY_LENGTH=3`, `SIMILARITY_THRESHOLD=0.2`, `RESULT_LIMIT=20`. Pesquisa `trade_name`/`company_name`/`document` de clientes **ativos** via `icontains`/`istartswith` e `TrigramWordSimilarity` (Postgres `pg_trgm`, extensão ativada em `apps.clients` migration `0006`). Ordenação em 3 níveis: prefixo exato > contém > só similaridade. Resposta mínima: `{"id", "name"}` — nunca documento/telefone/e-mail.

`OpportunityCreateView` suporta modo AJAX (header `X-Requested-With`) para o drawer de criação rápida, e modo tradicional como fallback sem JS — mesma view/form/service para os dois.

## URLs

`app_name="crm"`, montado como `path("crm/", ...)`. 17 rotas: `oportunidades/` (+ CRUD, autocomplete, etapa, hard delete, atividades) e `configuracoes/` (origens, etapas, motivos de perda).

## Permissions

7 `PermissionSpec` com `app_label="crm"` — **as únicas do catálogo sem equivalente legado** (`legacy_constant=None`): `view_opportunities`, `add_opportunities`, `change_opportunities`, `change_opportunity_stage`, `view_commercial_activities`, `add_commercial_activities`, `manage_commercial_settings`. `OpportunityHardDeleteView` fica fora do catálogo (`SuperuserRequiredMixin`/`is_superuser` puro — "Nível C").

## Templates

`templates/crm/`: `opportunity_list.html` (Kanban + drawer de criação rápida + toolbar de filtros), `_opportunity_kanban_card.html` (fonte única do card, reusada via `render_to_string` na resposta JSON), `_opportunity_quick_create_fields.html` (parcial reenviado como fragmento AJAX em erro), `opportunity_form.html`, `opportunity_detail.html` (abas Visão geral/Atividades/Equipamentos/Histórico), `opportunity_hard_delete_confirm.html`, e os CRUDs simples de configuração.

## JavaScript

`static/crm/*.js`: **`client_autocomplete.js`** (debounce 275ms, `AbortController` para descartar respostas obsoletas), **`kanban.js`** (drag-and-drop nativo HTML5, POST via `fetch`, move o card no DOM só após confirmação do backend — nunca otimista), **`opportunity_detail.js`** (roteia submits de mudança de etapa para o modal de perda/ganho conforme `data-is-lost`/`data-is-won` na `<option>`), **`opportunity_quick_create.js`** (drawer com focus trap, estado "sujo" com confirmação de descarte).

## Dependências

`apps.clients.models.Client`; `apps.core` (SoftDeleteModel, TimeStampedModel, hard_delete, `HardDeleteConfirmForm`, `format_brl`); `apps.accounts` (User, `SuperuserRequiredMixin`); `django.contrib.postgres.search.TrigramWordSimilarity`; `simple_history`.

## Quem chama apps.crm

`config/urls.py`/`settings.py` (registro padrão); `templates/base.html` (menu condicionado a `perms.crm.*`). Nenhum outro app importa `apps.crm.views`/`forms` diretamente — o acoplamento externo é só leitura unidirecional de `Client`.

## Testes

9 arquivos em `apps/crm/tests/`: `test_client_autocomplete.py` (23 testes), `test_kanban_view.py`, `test_opportunity_detail_redesign.py`, `test_opportunity_hard_delete.py`, `test_permission_matrix.py`, `test_quick_create_drawer.py`, `test_security.py` (IDOR, CSRF, integridade won/lost a nível de banco), `test_services.py`, `test_stage_change_concurrency.py` (`TransactionTestCase`).

## Migrations

Apenas `0001_initial.py` (10/09/2026). A extensão `pg_trgm` está em `apps.clients` (`0006_pg_trgm_extension.py`), **não** em `apps.crm`.

## Pontos importantes

- **Único app nascido 100% na arquitetura de Cargo** — as 7 permissions `crm.*` são as únicas do catálogo sem `legacy_constant`. CRM foi construído depois da aprovação da nova arquitetura, então nunca passou pelo sistema legado.
- **Botão escondido ≠ bloqueio no backend** — a autorização real é sempre `PermissionRequiredMixin`; POST manual de campos de perda/ganho sem permissão é bloqueado mesmo que o botão nunca tivesse aparecido (testado explicitamente).
- **`get_object_or_404` sem filtro por usuário/dono é deliberado** — a proteção contra IDOR é a permissão (`view_opportunities`), não esconder o PK.
- **Dupla camada de validação**: toda regra crítica (ganho/perda mutuamente exclusivos, valores não-negativos) tem `CheckConstraint` no banco E validação explícita em `clean()`/services.
- **`TrigramWordSimilarity` vs `TrigramSimilarity`**: escolha documentada por medição manual — `word_similarity` mede o melhor trecho contínuo do nome, mais adequado para buscas curtas contra nomes longos.
- **Aba "Equipamentos" na ficha é estado vazio estático** — não existe vínculo Oportunidade↔Equipamento implementado. Aba "Arquivos" omitida (app `attachments` vazio).
- Sem TODOs/FIXMEs literais — decisões pendentes são documentadas em prosa nas docstrings.
