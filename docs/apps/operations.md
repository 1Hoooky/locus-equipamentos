# apps.operations

## Objetivo

`apps.operations` cobre dois domínios da "Fase 2 (Operação)":

1. **Location** — unidades/locais físicos onde um equipamento pode estar: unidades de cliente (`type=CLIENTE`) e locais internos da Locus (ESTOQUE, MANUTENÇÃO, TRANSPORTE, OUTRO). Endereço operacional próprio (nunca compartilhado com o fiscal do `Client`).
2. **Movement** — evento estruturado e **imutável** de movimentação de equipamento (instalar, retirar, transferir, retornar, enviar/retornar de manutenção). Grava snapshots imutáveis de nomes (origem/destino/cliente) para a timeline continuar correta mesmo se `Location`/`Client` forem renomeados depois. Dispara efeitos colaterais atômicos: muda `Equipment.status` e sempre atualiza `current_location`/`current_client` juntos.

Mantém ainda uma ferramenta de **diagnóstico somente-leitura** (`find_duplicate_location_groups`) — nunca escreve/apaga.

## Models

Arquivo: `apps/operations/models.py`.

- **`LocationType`** (TextChoices): ESTOQUE, CLIENTE, MANUTENCAO, TRANSPORTE, OUTRO.
- **`Location(TimeStampedModel, SoftDeleteModel)`** — `name`, `type`, `client` (FK, PROTECT, null — só quando `type=CLIENTE`), `address` (OneToOne → `Address`, PROTECT). `history = HistoricalRecords()`. `CheckConstraint` (`type=CLIENTE ⟺ client not null`). `Meta.permissions`: `view_diagnostics`, `manage_locations`.
- **`MovementType`** (TextChoices): INSTALACAO, RETIRADA, TRANSFERENCIA, RETORNO_ESTOQUE, ENVIO_MANUTENCAO, RETORNO_MANUTENCAO, OUTRO.
- **`Movement`** — plain model, **sem** `HistoricalRecords` (imutável por construção). `equipment` (FK, PROTECT), `movement_type`, `origin_location`/`destination_location` (FK, PROTECT, null), `origin_location_name`/`destination_location_name` (snapshot), `origin_client_name`/`destination_client_name` (snapshot — `Movement.client` foi deliberadamente omitido por ser ambíguo entre origem/destino), `reason`, `created_by` (PROTECT). `CheckConstraint`: motivo obrigatório só para `OUTRO`. `Meta.permissions`: `register_operations`, `view_movements`.

**Location principal automática**: `apps.clients.services.create_client()` cria sempre uma `Location(type=CLIENTE)` chamada "Unidade principal" via `create_location()` — nunca criação direta neste app.

## Services

Arquivo: `apps/operations/services.py` (506 linhas) — único caminho suportado.

### Location
- `create_location(data: NewLocationData)` / `update_location(...)` / `update_location_address(...)` — todas `@transaction.atomic`, validam `type`×`client` (duplicando a `CheckConstraint` em Python para erro amigável).

### Movement — locking e regras de transição
- `_TRANSITION_RULES` — tabela status×movimentação (ex.: `INSTALACAO` exige `DISPONIVEL`→`EM_OPERACAO`). `MovementType.OUTRO` deliberadamente fora.
- `_REQUIRED_DESTINATION_TYPE` — mapeia cada tipo ao `LocationType` de destino obrigatório.
- `_BLOCKED_BY_OPEN_MAINTENANCE` — INSTALACAO/RETIRADA/TRANSFERENCIA/ENVIO_MANUTENCAO bloqueados enquanto há `Maintenance` ABERTA+ATIVA (`apps.maintenance.services.has_open_maintenance()`, **import local** dentro de `_validate_transition` — deliberado para não inverter a direção de dependência entre apps).
- `_validate_transition(equipment, movement_type, destination_location)` — função pura; regra específica: `TRANSFERENCIA` para a mesma localização atual é rejeitada.
- **`create_movement(data: NewMovementData)`** — `@transaction.atomic`: `Equipment.objects.select_for_update()` (lock pessimista, base de toda a idempotência/anti-race) → origem sempre derivada do estado já bloqueado (nunca do chamador) → `_validate_transition()` → grava `Movement` com os 4 snapshots → se aplicável, chama `change_status()` (reaproveitado) → `current_location`/`current_client` sempre escritos **juntos**, no mesmo `save()`.

### Diagnóstico (permanente, só leitura)
- `find_duplicate_location_groups()` — "duplicata" = mesmo `(name, type, client)` com mais de uma `Location` ativa. Reescrita para **número de queries constante (2)** após um **502 em produção** (Render+Neon) causado pela versão anterior (N+1 via `.count()` em loop).

> **Nota sobre a ferramenta de limpeza removida**: uma UI de escrita para desativar `Location`s duplicadas de teste existiu temporariamente e foi **removida** — a tela causava 502 no Render Free mesmo em lotes pequenos, e a limpeza dos grupos de teste era um evento pontual, não uma operação recorrente. Foi substituída pela data migration `0005_deactivate_test_duplicate_locations.py`, que roda uma única vez no `migrate` do deploy, sem depender de HTTP/JS/sessão. `find_duplicate_location_groups()` continua existindo (leitura), usada pelo management command `report_duplicate_locations` e pela tela de diagnóstico — nada mais neste módulo apaga/desativa uma `Location`.

## Forms

`LocationForm`/`LocationUpdateForm` (`forms.Form`, criação via service), `MovementForm` — filtra o dropdown de destino pelo tipo de movimentação já submetido e exclui a localização atual em `TRANSFERENCIA` (rejeita no form, antes do service, um destino manipulado via POST — `create_movement()` continua sendo a autoridade final). `DestinationLocationSelect` injeta `data-type`/`data-search` para o JS de conveniência.

`location_display_label(location)` (renomeada de `_destination_label` em 14/09/2026 — REFINAMENTO VISUAL "Produtos e Serviços" do `apps.crm`; `_destination_label` continua existindo como alias, nada quebrou) — rótulo "Cliente — Unidade"/só "Cliente" (quando o cliente só tem 1 unidade ativa) de uma `Location` do tipo CLIENTE. Nome público de propósito: reaproveitada por `apps.crm.forms.ProposalConditionsForm` (campo "Local de entrega/operação") para resolver o mesmo problema de exibição sem duplicar a lógica — qualquer novo select de `Location` em outro app deveria reaproveitar esta função, nunca reimplementá-la.

## Views

Arquivo: `apps/operations/views.py`. Guards de submissão: `_location_create_guard`, `_movement_guard(patrimonio)` (escopo por equipamento).

| View | Proteção | Resumo |
|---|---|---|
| `LocationListView` / `LocationDetailView` | `CAN_VIEW_CLIENTS` | |
| `LocationCreateView` | `CAN_MANAGE_LOCATIONS` | `SubmissionGuard`; reenvio detectado redireciona sem criar nada |
| `LocationUpdateView` / `LocationAddressUpdateView` | `CAN_MANAGE_LOCATIONS` | |
| `MovementCreateView` | `CAN_REGISTER_OPERATIONS` | única view genérica para instalar/retirar/transferir — o `movement_type` escolhido determina a regra aplicada |
| `DuplicateLocationsReportView` | `CAN_VIEW_DIAGNOSTICS` (só ADMIN) | só leitura |

## URLs

`app_name="operations"`, montado como `path("operacao/", ...)`. Rotas: `unidades/`, `unidades/novo/`, `unidades/<pk>/`, `unidades/<pk>/editar/`, `unidades/<pk>/endereco/`, `movimentar/<patrimonio>/`, `diagnostico/locations-duplicadas/`.

## Permissions

`CAN_VIEW_CLIENTS` (leitura de Location, reaproveitada), `CAN_MANAGE_LOCATIONS=(ADMIN,ADMINISTRATIVO)`, `CAN_REGISTER_OPERATIONS=(ADMIN,ADMINISTRATIVO,OPERACIONAL)` (compartilhada com `apps.maintenance`), `CAN_VIEW_DIAGNOSTICS=(ADMIN,)`. Catálogo aditivo (`view_diagnostics`, `manage_locations`, `register_operations`, `view_movements`) declarado mas não consultado pelas views.

## Templates

`templates/operations/`: `location_list.html`, `location_detail.html`, `location_form.html`, `location_update_form.html`, `location_address_form.html`, `movement_form.html` (com JS embutido), `duplicate_locations_report.html` ("Esta tela não apaga, não edita e não consolida nada").

## JavaScript

Embutido em `movement_form.html`: reflete `_REQUIRED_DESTINATION_TYPE` no cliente para re-filtrar o `<select>` de destino sem reload; **pesquisa incremental de destino Cliente** (normaliza acentos, filtra via `data-search`); exclui a localização atual quando `TRANSFERENCIA`. Só melhoria de UX — a segurança real é a queryset do backend.

## Dependências

`apps.accounts` (User, permissions); `apps.clients.models.Client`; `apps.core` (Address, SoftDeleteModel, TimeStampedModel, services, forms, submission); `apps.equipment` (Equipment, Status; `change_status`); `apps.maintenance.services.has_open_maintenance` (**import local**, para não inverter a direção de dependência); `django-simple-history`.

## Quem chama apps.operations

`apps.equipment.movement_panel` (lê `_TRANSITION_RULES`/`_BLOCKED_BY_OPEN_MAINTENANCE`/`MOVEMENT_TYPE_CHOICES` via import local, só apresentação), `apps.equipment.services` (timeline, hard delete), `apps.clients.services.create_client()` (Location principal, import local), `apps.maintenance` (importa `Movement`/`MovementType` no topo — direção oposta, "de cima para baixo"), `apps.dashboard.services` (estatísticas), `apps.core.nav` (destaque de menu). Desde a RODADA 3 do CRM (14/09/2026), `apps.crm.services.link_equipment_to_opportunity()`/`unlink_equipment_from_opportunity()` também chamam `create_movement()` (`MovementType.INSTALACAO`/`RETIRADA`) para vincular/desvincular patrimônio a uma `Opportunity` — mesmo caminho de sempre, nenhuma lógica nova aqui; `apps.crm` também reaproveita a `Permission` `operations.register_operations` (ver `docs/apps/crm.md`, seção Equipamentos) em vez de criar uma permissão própria.

## Testes

11 arquivos em `apps/operations/tests/` (~2247 linhas), incluindo dois testes de concorrência real com `TransactionTestCase`+threads (`test_movement_concurrency.py`, `test_double_submit_concurrency.py`), e testes dedicados às 3 data migrations (`test_seed_internal_locations.py`, `test_backfill_principal_locations.py`, `test_deactivate_test_duplicate_locations.py` — 13 cenários), e `test_duplicate_locations_report.py` (confirma ausência de qualquer ação destrutiva na tela).

## Migrations

6 migrations, incluindo 3 data migrations relevantes: `0003_seed_internal_locations.py` (seed das Locations internas, idempotente), `0004_backfill_principal_locations.py` (Location principal para clientes legados), `0005_deactivate_test_duplicate_locations.py` (substitui a UI de limpeza removida — desativa só as Locations de teste sem nenhum `Movement` referenciando, reverse deliberadamente no-op).

## Pontos importantes

- **Duas armadilhas de concorrência resolvidas e testadas com threads reais**: dupla movimentação simultânea (via `select_for_update()` no `Equipment`) e double-submit em sessão Django (a sessão não é read-modify-write atômica entre requests — corrigido movendo a autoridade para a constraint `UNIQUE` de `ConsumedSubmissionToken`, em `apps.core`).
- **Direção de dependência arquitetural deliberada**: `apps.operations` nunca importa `apps.maintenance` no topo do módulo — só localmente, para não criar risco de ciclo.
- **`current_location`/`current_client` sempre escritos juntos** — nunca há uma janela onde um reflete o movimento e o outro não.
- **Sem `UNIQUE(name)` em `Location`, por decisão de projeto** — unidades homônimas de clientes diferentes são legítimas.
- **502 em produção (Render Free + Neon)** foi a causa raiz que motivou tanto a reescrita de `find_duplicate_location_groups()` quanto a remoção completa da UI de limpeza em lote.
- Nenhum TODO/FIXME literal encontrado.
