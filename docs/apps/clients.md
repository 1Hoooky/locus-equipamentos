# apps.clients

## Objetivo

`apps.clients` implementa o cadastro e a operação de Clientes (empresas/pessoas): dados cadastrais (CNPJ/CPF, razão social, contato), endereço fiscal, e a criação automática de uma "unidade" (`Location`, de `apps.operations`) inicial junto com o cliente. Inclui um acelerador de cadastro por consulta de CNPJ (BrasilAPI) e um importador assistido em 3 telas de planilhas exportadas do sistema externo Auvo. Por design explícito: este app **não é um CRM** — funil de vendas/oportunidades vive em `apps.crm`, que reutiliza `Client` sem duplicá-lo.

## Models

Arquivo: `apps/clients/models.py`.

- **`ClientType(TextChoices)`**: `PJ`, `PF`.
- **`Client(TimeStampedModel, SoftDeleteModel)`** — `client_type`, `document` (obrigatório, só dígitos), `company_name`, `trade_name`, `registration_status`, `state_registration`, `phone`, `email`, `contact_name`, `notes`; campos de importação Auvo (`auvo_code`, `external_code`, `municipal_registration`, `icms_taxpayer`, `billing_email`); `fiscal_address` (OneToOne → `Address`, `PROTECT`). `history = HistoricalRecords()`.
  - **Constraints**: `document` e `auvo_code` únicos apenas entre valores não vazios (`UniqueConstraint` condicional), mesmo entre soft-deletados.
  - **`Meta.permissions`**: `view_clients`, `manage_clients`, `import_clients` (catálogo aditivo).
  - `clean()`: normaliza/valida `document` via `validate_document_for_type()`.
  - `display_name()`: `trade_name or company_name or document or f"Cliente #{pk}"` — reaproveitado por snapshots de `Movement` (`apps.operations`).

## Services

Arquivo: `apps/clients/services.py` — único caminho suportado para criar/editar `Client`.

- `create_client(data: NewClientData, *, require_document=True) -> Client` — `@transaction.atomic`. Valida/normaliza documento (obrigatório salvo quando chamado pela importação Auvo, com `require_document=False`); checa duplicidade de `document`/`auvo_code`; cria `fiscal_address` via `apps.core.services.create_address()`; **sempre** cria a `Location` operacional principal (import local de `apps.operations`, para evitar import circular).
- `update_client(*, client, data: ClientUpdateData) -> Client` — `@transaction.atomic`; documento sempre obrigatório.
- `update_fiscal_address(*, client, data, change_reason=...)` — cria o endereço se não existir, senão edita in-place.
- `preview_client_hard_delete(client) -> HardDeleteImpact` / `hard_delete_client(*, client_id, actor)` — checagem dupla de `actor.is_superuser`; `select_for_update()`; captura `ProtectedError` → `HardDeleteBlocked`; deleta `fiscal_address` e o histórico explicitamente após o `Client` sumir.

## Forms

Todos `forms.Form` (não `ModelForm`) — criação real sempre via services.

- `ClientForm` — cobre dados do cliente + endereço fiscal (prefixo `fiscal_`) + endereço/unidade operacional inicial opcional (prefixo `operational_`), com `use_fiscal_as_operational`.
- `CNPJLookupForm` — validação mínima para a ação "Consultar CNPJ" (separado de `ClientForm` para corrigir um bug de validação — ver Pontos importantes).
- `ClientUpdateForm` — edição, sem endereço/unidade.

## Views

Arquivo: `apps/clients/views.py` + `views_import.py` (importação, ver seção dedicada).

| View | Proteção | Descrição |
|---|---|---|
| `ClientListView` | `CAN_VIEW_CLIENTS` (4 perfis) | busca, `paginate_by=50` |
| `ClientDetailView` | `CAN_VIEW_CLIENTS` | detalhe + locations ativas |
| `ClientCreateView` | `CAN_MANAGE_CLIENTS` | `SubmissionGuard`; `action=lookup` consulta BrasilAPI sem salvar; `action=save` cria via `create_client()` |
| `ClientUpdateView` | `CAN_MANAGE_CLIENTS` | edição |
| `ClientFiscalAddressUpdateView` | `CAN_MANAGE_CLIENTS` | edita endereço fiscal |
| `ClientHardDeleteView` | **`SuperuserRequiredMixin`** (não `CAN_MANAGE_CLIENTS`) | preview de impacto + confirmação |

## URLs

`app_name="clients"`, montado como `path("clientes/", ...)`.

| path | name |
|---|---|
| `""`, `novo/` | `list`, `create` |
| `importar/`, `importar/revisar/`, `importar/resumo/` | `import_upload`, `import_review`, `import_summary` |
| `<pk>/`, `<pk>/editar/`, `<pk>/endereco-fiscal/`, `<pk>/excluir-definitivamente/` | `detail`, `update`, `fiscal_address_update`, `hard_delete` |

## Permissions

- `CAN_VIEW_CLIENTS = (ADMIN, ADMINISTRATIVO, OPERACIONAL, CONSULTA)` — todos os 4 perfis.
- `CAN_MANAGE_CLIENTS = (ADMIN, ADMINISTRATIVO)`.
- `CAN_IMPORT_CLIENTS = (ADMIN,)`.
- `ClientHardDeleteView` usa `SuperuserRequiredMixin` puro, deliberadamente desacoplado de `Role`/`CAN_MANAGE_CLIENTS`.
- Catálogo aditivo (`view_clients`/`manage_clients`/`import_clients`) **não é consultado** por nenhuma view deste app.

## Templates

`templates/clients/`: `client_list.html`, `client_form.html` (com JS, ver abaixo), `client_detail.html`, `client_update_form.html`, `client_fiscal_address_form.html`, `client_hard_delete_confirm.html`, `import_upload.html`, `import_review.html`, `import_summary.html`.

## JavaScript

Só em `client_form.html`: melhoria de UX pura — ao marcar `use_fiscal_as_operational`, copia em tempo real os campos `fiscal_*` para `operational_*` e os torna read-only. A cópia que garante integridade real é feita no backend (`ClientForm.clean()`); funciona sem JS.

## Dependências

`apps.core` (`Address`, `SoftDeleteModel`, `TimeStampedModel`, `services`, `forms`, `hard_delete`, `submission`); `apps.accounts.permissions`; `apps.operations` (`LocationType`, `create_location` — import local dentro de `create_client()` para evitar ciclo); bibliotecas externas `openpyxl` (planilha) e `httpx` (BrasilAPI); `django-simple-history`.

## Quem chama apps.clients

- **`apps.crm`** — reutiliza `Client` diretamente (só leitura, nunca escreve).
- **`apps.operations`** — `Location.client` (FK).
- **`apps.equipment`** — `Equipment.current_client` (FK, via string).
- **`apps.maintenance`, `apps.dashboard`** — testes/fixtures.
- **`apps.accounts`** — catálogo de permissões registra `view_clients`/`manage_clients`/`import_clients`.
- `config/urls.py` monta `clientes/`.

`apps.clients` **não importa** de `apps.crm` nem `apps.maintenance` — a dependência é unidirecional.

## O que apps.clients chama

`apps.core.services` (endereço), `apps.operations.services.create_location` (import local), `apps.accounts.permissions`.

## Testes

9 arquivos em `apps/clients/tests/`:

- `test_client_services.py`, `test_client_views.py` (matriz de permissões + fluxo de consulta CNPJ), `test_client_detail_view.py`, `test_client_double_submit.py`, `test_client_hard_delete.py`, `test_client_list_pagination.py`, `test_import_auvo.py` (parser puro), `test_import_auvo_views.py` (fluxo HTTP), `test_lookup_service.py` (BrasilAPI sempre mockado via `httpx.get`), `test_validators.py` (CNPJ/CPF).

## Migrations

6 migrations: `0001_initial` → `0006_pg_trgm_extension.py` (12/09/2026, escrita à mão — ativa a extensão Postgres `pg_trgm` usada pelo **autocomplete de clientes do CRM**, não adiciona coluna nenhuma em `Client`).

## Import Auvo (`import_auvo.py` + `views_import.py`)

Parser puro (nada grava no banco). Formato: exportação real do Auvo (`.xlsx`, homologada com 716 clientes reais), cabeçalho fixo na linha 1, linha 2 sempre explicativa e ignorada (`FIRST_DATA_ROW=3`), colunas resolvidas **por nome do cabeçalho**. `REQUIRED_HEADERS` com 26 colunas — falta alguma → `ClientImportError` antes de processar.

Classificação por linha: `NOVO`, `JA_EXISTENTE` (por `auvo_code` ou `document` já no banco), `POSSIVEL_DUPLICADO` (só linhas **sem** documento, similaridade de nome ≥ 0.92 via `difflib`), `INVALIDO` (documento com dígito verificador errado, contagem de dígitos incorreta, ou sem nome/razão social).

Fluxo de 3 telas (`views_import.py`, todas `CAN_IMPORT_CLIENTS`): upload → revisão (confirma, chama `create_client(..., require_document=False)` linha a linha) → resumo. **Estado inteiro em sessão**, sem tabela de auditoria de importação — o único rastro é o `_change_reason` do `HistoricalClient`.

## Validators (`validators.py`)

`normalize_document`, `is_valid_cnpj` (algoritmo oficial de 2 dígitos verificadores, rejeita dígitos repetidos), `is_valid_cpf` (idem, preparado para futura Fase 2 de Pessoa Física — hoje só CNPJ é exigido pela UI de consulta), `validate_document_for_type`.

## Pontos importantes

- **Import circular evitado com import local**: `create_client()` importa `apps.operations` dentro da função, não no topo do módulo.
- **`ClientHardDeleteView` é a única view fora de `RoleRequiredMixin`** — `SuperuserRequiredMixin`, deliberadamente desacoplado de `Role`/`CAN_MANAGE_CLIENTS` para não permitir escalação via arquitetura de Cargos.
- **`require_document=False` é uma "porta lateral" única**: só usada pela importação Auvo — testada explicitamente (`ManualCreationStillRequiresDocumentTest`) para garantir que não vaza para o cadastro manual.
- **`icms_taxpayer` é salvo cru**, sem interpretação — decisão explícita até confirmação com o usuário sobre a semântica real do valor.
- **`Client.document` é editável depois da criação** — diferente de identificadores imutáveis por design em outros apps (ex.: patrimônio de equipamento).
- **Location principal sempre criada com `Client`** — mudança de comportamento pós-reteste (antes só nascia se o usuário digitasse um nome).
- **`BrasilAPICompanyLookupProvider`** — timeouts curtos e sem retry por design (consulta externa nunca pode travar o cadastro manual). Provider plugável via `settings.COMPANY_LOOKUP_PROVIDER`.
- Nenhum TODO/FIXME literal encontrado.
