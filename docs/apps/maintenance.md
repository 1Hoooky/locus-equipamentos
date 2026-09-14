# apps.maintenance

## Objetivo

`apps.maintenance` (verbose_name "Manutenção e Higienização") é o domínio **técnico** do sistema, deliberadamente separado de `apps.operations` (domínio físico: onde o equipamento está) e de `apps.equipment` (cadastro/estado corrente). Cobre dois fluxos:

- **Maintenance**: ficha com ciclo de vida ABERTA → CONCLUIDA/CANCELADA (preventiva/corretiva), com restauração automática do `Equipment.status` quando aplicável.
- **Cleaning**: evento atômico de higienização, sem ciclo de estado, nunca editado após criado.

Regra central: só `apps.operations.services.create_movement()` escreve `Equipment.current_location`/`current_client`; `Maintenance`/`Cleaning` só mudam `Equipment.status`/`condition`, sempre via `apps.equipment.services.change_status()`/`change_condition()` — nunca atribuição direta.

## Models

Arquivo: `apps/maintenance/models.py`.

- **`MaintenanceType`**: PREVENTIVA, CORRETIVA. **`MaintenanceStatus`**: ABERTA, CONCLUIDA, CANCELADA.
- **`Maintenance(TimeStampedModel, SoftDeleteModel)`** — `equipment` (FK, PROTECT), `maintenance_type`, `status` (default ABERTA), `diagnosis`, `service_performed` (exigido no fechamento), `condition_before`/`condition_after`, `status_before` (snapshot para restauração — semântica especial quando `departure_movement` preenchido, ver Pontos importantes), `departure_movement`/`return_movement` (OneToOne opcional → `Movement`, PROTECT), `responsible` (PROTECT), `notes`, `next_due_at` (informativo), `closed_at`, `created_by`. `history = HistoricalRecords()`.
  - **Constraints**: conclusão exige `service_performed`; `closed_at` coerente com status; **`UniqueConstraint` condicional** — no máximo uma Maintenance `ABERTA+ativa` por equipamento.
  - `Meta.permissions`: `view_maintenance_and_cleaning`.
- **`Cleaning(TimeStampedModel, SoftDeleteModel)`** — `equipment` (FK, PROTECT), `performed_at`, `responsible` (PROTECT), `notes`, `next_due_at`, `movement` (FK opcional, PROTECT), `created_by`. **Sem `HistoricalRecords()`** (evento atômico — corrigir = `is_active=False` + novo registro).

## Services

Arquivo: `apps/maintenance/services.py` (~330 linhas de docstring com 3 matrizes de decisão).

- `has_open_maintenance(equipment) -> bool` — ponto de integração único para `apps.operations._validate_transition()`.
- **`open_maintenance(data)`** — `@transaction.atomic`. `select_for_update()` no `Equipment`; rejeita se já há manutenção aberta. Sem `departure_movement`: exige `DISPONIVEL`/`EM_OPERACAO`, chama `change_status(MANUTENCAO)`. Com `departure_movement`: valida 5 condições (mesmo equipamento, tipo `ENVIO_MANUTENCAO`, não reclamado antes, `equipment.status==MANUTENCAO`), não altera status.
- **`close_maintenance(*, maintenance, data)`** — `@transaction.atomic`; exige ABERTA + `service_performed`; valida `return_movement` opcional (7 checagens, incluindo ordem cronológica); `_restore_status_if_owned()`; `status=CONCLUIDA`.
- **`cancel_maintenance(*, maintenance, cancelled_by, reason="")`** — `_restore_status_if_owned()`; `status=CANCELADA`.
- `_restore_status_if_owned()` — só restaura se `departure_movement_id is None` E `status_before` preenchido E `equipment.status==MANUTENCAO` no momento (**idempotente** — se um `Movement` externo já mudou o status, não faz nada).
- `create_cleaning(data)` / `cancel_cleaning(*, cleaning)` — sem lock (evento sem concorrência crítica de status); `cancel_cleaning` rejeita se já `is_active=False`.
- `get_equipment_maintenance_summary(equipment, limit=5) -> dict` — 3 queries fixas, sem N+1 (testado).

**Transições bloqueadas e testadas**: duas Maintenance ABERTA+ativa simultâneas; concluir/cancelar não-ABERTA; concluir sem `service_performed`; `departure_movement`/`return_movement` reclamado duas vezes; `return_movement` anterior à abertura/ao `departure_movement`; `RETORNO_MANUTENCAO` sem `departure_movement`.

## Forms

Todos `forms.Form` (espelham os dataclasses dos services): `MaintenanceOpenForm` (queryset exclui equipamento com manutenção aberta; `departure_movement` dinâmico por equipamento), `MaintenanceCloseForm`, `MaintenanceCancelForm` (`reason` com `min_length=3`, mais estrito que o service), `CleaningForm`, `CleaningCancelForm`.

## Views

Arquivo: `apps/maintenance/views.py`. Erros de domínio (`ValueError`) viram `form.add_error(None, ...)`, nunca HTTP 500.

| View | Proteção |
|---|---|
| `MaintenanceListView` / `MaintenanceDetailView` | `CAN_VIEW_MAINTENANCE` |
| `MaintenanceOpenView` | `CAN_REGISTER_OPERATIONS`; `SubmissionGuard` |
| `DepartureMovementOptionsView` | `CAN_REGISTER_OPERATIONS`; fragmento htmx |
| `MaintenanceCloseView` / `MaintenanceCancelView` | `CAN_REGISTER_OPERATIONS`; checam `status==ABERTA` antes de renderizar |
| `CleaningListView` / `CleaningDetailView` | `CAN_VIEW_MAINTENANCE` |
| `CleaningCreateView` / `CleaningCancelView` | `CAN_REGISTER_OPERATIONS` |

## URLs

`app_name="maintenance"`, montado como `path("manutencao/", ...)`. Rotas: `manutencoes/`, `manutencoes/abrir/`, `manutencoes/abrir/movimentos-envio/`, `manutencoes/<pk>/`, `/concluir/`, `/cancelar/`, `higienizacoes/` (+ análogas).

## Permissions

`CAN_VIEW_MAINTENANCE=(4 perfis)` (leitura), `CAN_REGISTER_OPERATIONS=(ADMIN,ADMINISTRATIVO,OPERACIONAL)` (escrita, constante compartilhada com `apps.operations` desde a Fase 1). Catálogo aditivo declara `view_maintenance_and_cleaning`, não consultado pelas views nesta rodada.

## Templates

`templates/maintenance/`: `maintenance_list.html`, `maintenance_open_form.html`, `maintenance_detail.html`, `maintenance_close_form.html`, `maintenance_cancel_confirm.html`, `cleaning_list.html`, `cleaning_form.html`, `cleaning_detail.html`, `cleaning_cancel_confirm.html`, `_departure_movement_options.html` (fragmento htmx). Listas com versão responsiva (tabela desktop + cards mobile).

## JavaScript

Inline em `maintenance_open_form.html`: busca incremental client-side no `<select>` de equipamento (mesma técnica de `operations/movement_form.html`); integração htmx (troca de equipamento dispara `GET` para repopular `departure_movement` sem reload — com JS desabilitado, o campo fica estático, o service continua sendo a autoridade final).

## Dependências

`apps.accounts` (User, CAN_REGISTER_OPERATIONS, CAN_VIEW_MAINTENANCE, RoleRequiredMixin); `apps.core` (SoftDeleteModel, TimeStampedModel, SubmissionGuard); `apps.equipment` (Condition, Equipment, Status, `change_condition`/`change_status`); `apps.operations` (Movement, MovementType); `django-simple-history`. **Não** importa `apps.operations.services` (evita ciclo).

## Quem chama apps.maintenance

`apps.operations.services._validate_transition()` (import local de `has_open_maintenance`); `apps.equipment.services.get_equipment_history_timeline()`/hard delete (import local de `Cleaning`/`Maintenance`); `apps.equipment.views.EquipmentDetailView` (resumo na ficha); `apps.equipment.movement_panel` (bloqueio por manutenção aberta); `apps.dashboard.services` (cards de manutenções abertas); `apps.core.nav`.

## Testes

11 arquivos em `apps/maintenance/tests/`, incluindo `test_maintenance_movement_concurrency.py` (`TransactionTestCase`+threading, dois cenários de corrida real via Postgres `select_for_update()`), `test_maintenance_lists_filters_pagination_queries.py` (3 testes de N+1 via `CaptureQueriesContext`), e testes explícitos de idempotência (`IdempotenciaRestauracaoTest`) e double-submit.

## Migrations

4 migrations: `0001_initial`, `0002_maintenance_aberta_ativa_constraint.py` (corrige a `UniqueConstraint` para incluir `is_active`), `0003_alter_cleaning_movement_and_more.py` (só help_texts), `0004_seed_cargo_architecture_base.py` (permissão nova).

## Pontos importantes

- **Armadilha central de `status_before`**: só é usado para restaurar quando `departure_movement is None`; com `departure_movement`, o campo vale apenas `MANUTENCAO` e é puramente informativo — usá-lo ingenuamente como "status genuíno anterior" é um erro documentado explicitamente no docstring do model.
- **Imports locais deliberados** em `apps.operations`/`apps.equipment`/`apps.equipment.movement_panel` evitam que camadas "de baixo" declarem em import-time uma dependência de `apps.maintenance` (camada mais alta), prevenindo ciclo futuro.
- **Cleaning é imutável por design** — nunca há `UPDATE` de um registro já criado; corrigir = `cancel_cleaning()` + novo registro.
- **`next_due_at`** (ambos os models) é puramente informativo — nenhum motor de recorrência/job; recorrência de verdade exigiria um model novo.
- **Admin bloqueia criação/edição direta** (`has_add_permission=False`, campos `readonly_fields`) — reforça que services são o único caminho de escrita, mesmo via Django admin.
- Nenhum TODO/FIXME literal encontrado.
