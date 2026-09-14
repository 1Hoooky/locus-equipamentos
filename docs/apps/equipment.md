# apps.equipment

## Objetivo

`apps.equipment` é o app central do sistema — o model mais referenciado por outros apps. Modela a unidade física de equipamento (`Equipment`) com um número de patrimônio (`patrimonio`, ex.: `LOC-NI23BT-0001`) gerado de forma **atômica e concorrente** na criação, e a partir daí **imutável**. Fornece:

- Cadastro individual e em lote (`create_equipment`, `create_equipment_batch`).
- Ciclo de vida operacional via eventos estruturados obrigatórios com motivo: mudança de `status` (`StatusHistory`) e `condition` (`ConditionHistory`), sempre via services, nunca edição direta.
- Correção de erro de classificação de modelo sem alterar o patrimônio (`reclassify_model` — procedimento padrão) versus reemissão excepcional de um novo patrimônio quando o erro é grave demais (`supersede_equipment` — inativa o antigo e cria um novo).
- Exclusão definitiva (hard delete) restrita a superusuário.
- Listagem agrupada por modelo (HTMX), filtros combinados, exportação CSV/XLSX.
- A página pública acessada via QR code — dupla camada pública/privada com queries deliberadamente diferentes.
- Importação assistida de planilha legada, e ferramenta administrativa de preenchimento em lote de código legado.
- Linha do tempo unificada do equipamento, que funde eventos de `StatusHistory`+`ConditionHistory`+`Movement` (`operations`)+`Maintenance`/`Cleaning` (`maintenance`).

## Models

Arquivo: `apps/equipment/models.py`. (`Category`/`EquipmentModel` vivem em `apps.catalog`.)

- **`Status`** (TextChoices): DISPONIVEL, EM_OPERACAO, MANUTENCAO, INATIVO. **`Condition`**: BOM, MEDIO, RUIM, INUTILIZAVEL.
- **`EquipmentBatch`** — `id` (UUID), `model` (FK, PROTECT), `quantity`, `condition`, `first_patrimonio`/`last_patrimonio`, `created_by`. Serve só para "quais equipamentos nasceram juntos" (deliberadamente **não** usa intervalo numérico de sequência — reclassificação pode tirar um item do intervalo original; usa FK direta `Equipment.batch`).
- **`Equipment(TimeStampedModel, SoftDeleteModel)`**:
  - Identidade permanente: `patrimonio` (único, `editable=False`), `model` (FK, PROTECT), `model_sequence` (`editable=False`).
  - `category` (FK, PROTECT, `editable=False`) — denormalizado de `model.category`, nunca fonte da verdade.
  - Aquisição: `serial_number`, `legacy_code` (sem unique constraint de banco), `supplier`, `acquisition_date`, `acquisition_value`.
  - Operacional: `status`, `condition`.
  - `current_location` (FK → `operations.Location`, SET_NULL); `current_client` (FK → `clients.Client`, SET_NULL, **`editable=False`** — só escrito por `apps.operations.services.create_movement()`).
  - `superseded_by` (OneToOne self, SET_NULL) — só na reemissão excepcional.
  - `batch` (FK, SET_NULL, `editable=False`).
  - `history = HistoricalRecords()`.
  - **`Meta.constraints`**: `UniqueConstraint(model, model_sequence)` — segunda linha de defesa de banco contra patrimônio duplicado.
  - **`Meta.permissions`** (arquitetura de Cargos): `manage_equipment`, `view_acquisition_value`, `change_status_condition`, `add_photos`, `export_data`, `import_legacy_spreadsheet`, `supersede_equipment`.
  - `clean()`: compara `patrimonio`/`model_sequence` persistidos vs novos, levanta `ValidationError` se mudaram.
- **`StatusHistory` / `ConditionHistory`** — `equipment` (FK, CASCADE), `old_value`/`new_value`, `changed_by` (PROTECT), `changed_at`, `reason` (sempre obrigatório). Só criados pelos services.

### Geração atômica

Sem sequence de banco dedicada. O contador é `EquipmentModel.last_sequence` (`apps.catalog`). `create_equipment()` faz `EquipmentModel.objects.select_for_update().get(...)`, incrementa `last_sequence`, usa o valor como `model_sequence`. Trava é por linha do `EquipmentModel` — modelos diferentes cadastram em paralelo livremente. A `UniqueConstraint` de banco é a rede de segurança final.

## Services

Arquivo: `apps/equipment/services.py`.

- `MAX_BATCH_QUANTITY = 500`.
- `build_patrimonio(code, sequence)` → `f"LOC-{code}-{sequence:04d}"`.
- **`create_equipment(data: NewEquipmentData) -> Equipment`** — `@transaction.atomic`. **Função central** e única forma suportada de criar equipamento.
- **`create_equipment_batch(data) -> EquipmentBatch`** — `@transaction.atomic`; chama `create_equipment()` N vezes na mesma transação (falha no meio desfaz tudo).
- **`reclassify_model(*, equipment, new_model, reason, changed_by)`** — `@transaction.atomic`; corrige `model`+`category`, nunca `patrimonio`/`model_sequence`; `reason` obrigatório.
- **`supersede_equipment(*, equipment, new_model, reason, changed_by)`** — `@transaction.atomic`; chama `create_equipment()` para um patrimônio novo, inativa o antigo (`superseded_by`).
- **`change_status(*, equipment, new_status, reason, changed_by)`** / **`change_condition(...)`** — `@transaction.atomic`; valida `reason` não vazio, valor válido e diferente do atual; salva + cria histórico na mesma transação.
- **`get_equipment_history_timeline(equipment) -> list[dict]`** — funde `status_history`, `condition_history`, `movements` (import local de `operations`) e `Maintenance`/`Cleaning` (import local de `maintenance`) num formato comum.
- **Hard delete**: `preview_equipment_hard_delete()` / `hard_delete_equipment(*, equipment_id, actor)` — exige superuser, `select_for_update()`, deleta explicitamente `Cleaning`→`Maintenance`→`Movement` na ordem certa, depois `equipment.delete()`, depois purga `Equipment.history`.

## Forms

`EquipmentCreateForm`, `EquipmentBatchCreateForm`, `EquipmentUpdateForm` (`ModelForm` — só campos de aquisição/notas, nunca `model`/`patrimonio`/`status`/`condition`), `ChangeStatusForm`, `ChangeConditionForm`, `ReclassifyModelForm`, `SupersedeEquipmentForm` (com `confirm_reprint` obrigatório).

## Views

Arquivos: `apps/equipment/views.py`, `views_import.py`.

| View | Proteção | Resumo |
|---|---|---|
| `EquipmentListView` | login (4 perfis) | listagem agrupada por modelo + filtros |
| `EquipmentModelItemsView` | login | fragmento HTMX paginado |
| `EquipmentCreateView` / `Batch*` (3 telas) | `CAN_MANAGE_EQUIPMENT` | fluxo de 3 passos em sessão |
| `EquipmentUpdateView` | `CAN_MANAGE_EQUIPMENT` | edição |
| `EquipmentChangeStatusView` / `ChangeConditionView` | `CAN_CHANGE_STATUS_CONDITION` (inclui OPERACIONAL) | |
| `EquipmentLegacyCodeBulkFillView` | `CAN_MANAGE_EQUIPMENT` | `SubmissionGuard`, revalidação obrigatória no servidor |
| `EquipmentReclassifyView` | `CAN_RECLASSIFY_EQUIPMENT_MODEL` (só ADMIN) | |
| `EquipmentSupersedeView` | `CAN_SUPERSEDE_EQUIPMENT` (só ADMIN) | |
| `EquipmentHardDeleteView` | `SuperuserRequiredMixin` | |
| `EquipmentExportView` | `CAN_EXPORT_DATA` | `?format=csv\|xlsx` |
| **`EquipmentDetailView`** | **sem mixin (pública)** | rota do QR code — ver abaixo |
| `LegacyImportUpload/Review/SummaryView` | `CAN_IMPORT_LEGACY_SPREADSHEET` (só ADMIN) | |

### `EquipmentDetailView` — página do QR code

Anônimo: `.only("patrimonio","model__name","model__code","model__manufacturer","category__name")` — os demais campos **nunca saem do banco** (defesa em profundidade, não só ocultação de template). Autenticado: `.defer()` de campos de aquisição quando sem `CAN_VIEW_ACQUISITION_VALUE`; resumo de manutenção só se `CAN_VIEW_MAINTENANCE`; ações de movimentação só se operacional+.

## URLs

`app_name="equipment"`, montado como `path("equipamentos/", ...)`. Rotas fixas (`novo/`, `lote/...`, `modelo/...`, `exportar/`, `importar/...`) vêm antes da rota catch-all `<str:patrimonio>/`. 18 rotas ao todo, incluindo `<patrimonio>/status/`, `/condicao/`, `/reclassificar/`, `/reemitir/`, `/excluir-definitivamente/`.

## Permissions

`CAN_RECLASSIFY_EQUIPMENT_MODEL=(ADMIN,)`, `CAN_MANAGE_EQUIPMENT=(ADMIN,ADMINISTRATIVO)`, `CAN_VIEW_ACQUISITION_VALUE=(ADMIN,ADMINISTRATIVO)`, `CAN_CHANGE_STATUS_CONDITION=(ADMIN,ADMINISTRATIVO,OPERACIONAL)`, `CAN_EXPORT_DATA=(ADMIN,ADMINISTRATIVO)`, `CAN_IMPORT_LEGACY_SPREADSHEET=(ADMIN,)`, `CAN_SUPERSEDE_EQUIPMENT=(ADMIN,)`, `CAN_VIEW_MAINTENANCE=(4 perfis)`. Hard delete via `SuperuserRequiredMixin`. Django admin: `status`/`condition` são `readonly_fields`; criação passa por `create_equipment()` via `save_model()`.

## Templates

`templates/equipment/`: `list.html`, `_model_group_items.html`, `equipment_form.html`, `batch_*.html` (3), `change_status.html`, `change_condition.html`, `reclassify.html`, `supersede.html`, `detail_private.html`, **`detail_public.html`** (página do QR), `hard_delete_confirm.html`, `import_*.html` (3), `legacy_code_bulk_fill*.html` (2).

## JavaScript

Sem `.js` dedicado — inline em `list.html` (grupos colapsáveis + carregamento HTMX) e `detail_private.html` (disclosure administrativo). `list.html` e `batch_result.html` incluem `static/qrcodes/label_theme_modal.js` (pertence a `apps.qrcodes`).

## Export / Filters / Grouping / Legacy tools / Movement panel

- **`export.py`** — CSV (BOM UTF-8 para Excel) e XLSX (`openpyxl`) com 13 colunas fixas.
- **`filters.py`** — `filter_equipment_queryset()` compartilhado entre listagem, fragmento HTMX e export; PK/UUID inválidos são ignorados silenciosamente (não derrubam com 500).
- **`grouping.py`** — `build_model_groups()`: **uma única query** agregada (`annotate`+`Count(filter=Q(...))`) para os badges por status, sem N+1 (auditado explicitamente por teste).
- **`legacy_code_bulk.py`** — ferramenta **ativa** (não é código morto) de correção pós-fato de `legacy_code`; `apply_legacy_code_bulk_fill()` **recalcula a prévia do zero no servidor**, nunca confia na prévia do navegador/sessão.
- **`legacy_import.py`** — parser da planilha legada real (`Estoque.Atualizado.xlsx`); sugestão automática de `EquipmentModel` via `difflib.SequenceMatcher` (threshold 0.6).
- **`movement_panel.py`** — módulo de apresentação (nunca escreve) para o painel "Movimentar equipamento"; lê estruturas internas de `apps.operations` (import local) para decidir quais ações mostrar — prévia sem lock, a autoridade final continua sendo `create_movement()`.

## Dependências

`apps.accounts` (User, Role, CAN_*, mixins); `apps.catalog` (Category, EquipmentModel); `apps.core` (bases, hard_delete, submission); `apps.clients` (Client, via string); `apps.operations` (import local: Location, Movement, regras de transição); `apps.maintenance` (import local: Cleaning, Maintenance, resumo); `apps.qrcodes` (admin importa `LABEL_THEME_LIGHT`); `django-simple-history`, `openpyxl`.

## Quem chama apps.equipment

`apps.catalog` (reverse FK `equipment_set`), `apps.operations` (`Movement.equipment`, regras sobre `Equipment.status`), `apps.maintenance` (`Maintenance.equipment`/`Cleaning.equipment`, grava status/condition só via `apps.equipment.services`), `apps.qrcodes` (toda geração de QR/etiqueta), `apps.dashboard` (contadores). `apps.attachments` **não** referencia `apps.equipment` apesar do nome sugerir anexos de equipamento (app vazio). Desde a RODADA 3 do CRM (14/09/2026), `apps.crm.models.OpportunityEquipment` também referencia `Equipment` (via string reference, `on_delete=PROTECT` — nunca apagado por lá) e `apps.crm.views.OpportunityEquipmentSearchView` reaproveita `apps.equipment.filters.filter_equipment_queryset()` para a busca de patrimônio disponível; nenhum dos dois grava `Equipment.status`/`current_location` diretamente — isso continua sendo 100% `apps.operations.services.create_movement()`.

## Testes

18 arquivos em `apps/equipment/tests/`, cobrindo CRUD, lote (com teste de concorrência real via `TransactionTestCase`+threads — `test_patrimonio_generation.py`, só confiável em Postgres), hard delete, timeline, painel de movimentação, export, imutabilidade/reclassificação, preenchimento de código legado (20 cenários), importação legada, paginação/filtros, landing pública (sem vazamento de dados operacionais).

## Migrations

6 migrations, destaque para `0001_initial.py` (`UniqueConstraint uniq_model_sequence_per_model` — a constraint que sustenta a geração atômica) e `0005_alter_equipment_current_client_and_more.py` (torna `current_client` `editable=False`).

## Pontos importantes

- **Imutabilidade do patrimônio em 5 camadas**: campo `editable=False`, `Equipment.clean()`, ausência nos forms, `readonly_fields` no admin, e `UniqueConstraint` de banco como última linha de defesa.
- **Reclassificação vs Reemissão**: `reclassify_model()` é correção padrão sem custo físico (patrimônio/etiqueta continuam válidos); `supersede_equipment()` é procedimento excepcional que cria um equipamento novo e exige reimpressão física (checkbox `confirm_reprint`).
- **Lock por linha de `EquipmentModel`, não por tabela** — modelos diferentes cadastram em paralelo; mesmo modelo serializa. `MAX_BATCH_QUANTITY=500` existe porque lotes grandes travam a linha por muitas queries seguidas.
- **`movement_panel.available_movement_actions()` é deliberadamente sem lock** — só prévia visual; a corrida possível é aceitável porque `create_movement()` valida de novo, com lock, no submit real.
- Nenhum TODO/FIXME encontrado.
