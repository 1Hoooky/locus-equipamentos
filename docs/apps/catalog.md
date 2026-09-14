# apps.catalog

## Objetivo

`apps.catalog` cadastra **Categorias** (ex.: Aquecedor, Climatizador) e **Modelos de equipamento** (`EquipmentModel`, ex.: "Aquecedor Pirâmide", `code=AQCP`). O campo `EquipmentModel.code` é a peça central do padrão de número de patrimônio (`LOC-{MODEL_CODE}-{SEQUENCE}`) usado por `apps.equipment`, e fica travado para edição assim que o modelo tem ao menos um `Equipment` vinculado. O app também resolve a imagem comercial estática de cada modelo para a landing pública de QR code. `catalog` **não** gera o código de patrimônio em si — essa lógica (incluindo o lock `select_for_update()` sobre a linha de `EquipmentModel`) vive em `apps.equipment.services`.

## Models

Arquivo: `apps/catalog/models.py`.

- **`Category(TimeStampedModel, SoftDeleteModel)`** — `name` (único), `slug` (auto-preenchido via `slugify` se vazio). `ordering=["name"]`.
- **`EquipmentModel(TimeStampedModel, SoftDeleteModel)`** — `category` (FK, PROTECT), `name`, `code` (único, regex `^[A-Z0-9]{2,20}$`), `manufacturer`, `specs` (JSONField), `last_sequence` (PositiveIntegerField, `editable=False` — só editado por `apps.equipment.services.generate_patrimonio()`/`create_equipment()` sob `select_for_update()`, nunca manualmente). `history = HistoricalRecords()`.
  - `Meta.permissions`: `manage_catalog`, `reclassify_equipment_model` (arquitetura de Cargos — não checadas por nenhuma view deste app, ver Pontos importantes).
  - `clean()`: se o registro já existe e `code` mudou e `has_equipment()` é `True`, levanta `ValidationError` — fonte de verdade da imutabilidade de `code`.
  - `has_equipment()`: `self.equipment_set.exists()`.

## Services

Não existe `apps/catalog/services.py`. A lógica de negócio vive no próprio model (`clean()`, `has_equipment()`) e em módulos utilitários:

- `apps.catalog.images.get_model_image_path(model)` — resolve o caminho estático **pretendido** via `MODEL_IMAGE_MAP` (dict hardcoded, chave = `code.upper()`); `None`/sem código/não mapeado → placeholder. Não checa existência real em disco.
- `apps.catalog.templatetags.model_images._resolve_existing_static_path()` — confirma via `staticfiles.finders.find()` se o arquivo existe; `@lru_cache(maxsize=256)` **por processo** (precisa reiniciar/redeploy para pegar imagem nova).
- `apps/catalog/management/commands/seed_catalog.py` — `@transaction.atomic`, popula via `get_or_create` a partir de `SEED_DATA` (2 categorias, 9 modelos) — idempotente por design.

## Forms

- `CategoryForm(ModelForm)` — `name`, `is_active`.
- `EquipmentModelForm(ModelForm)` — `category, name, code, manufacturer, is_active`. Se a instância já existe **e** `has_equipment()`, desabilita o campo `code` e troca o `help_text` — reforço de UI sobre a regra real garantida por `EquipmentModel.clean()`.

## Views

Arquivo: `apps/catalog/views.py`. Todas as 6 views usam `RoleRequiredMixin` com `CAN_MANAGE_CATALOG = (ADMIN, ADMINISTRATIVO)`. Nenhuma view está desprotegida.

| View | Descrição |
|---|---|
| `CategoryListView` | lista `Category` ordenada por nome |
| `CategoryCreateView` / `CategoryUpdateView` | CRUD de categoria |
| `EquipmentModelListView` | lista modelos com `select_related("category")` |
| `EquipmentModelCreateView` / `EquipmentModelUpdateView` | CRUD de modelo — a trava de `code` acontece no `EquipmentModelForm.__init__` |

## URLs

`app_name="catalog"`, montado como `path("catalogo/", ...)`.

| path | name |
|---|---|
| `categorias/`, `categorias/nova/`, `categorias/<pk>/editar/` | `category_list`, `category_create`, `category_update` |
| `modelos/`, `modelos/novo/`, `modelos/<pk>/editar/` | `model_list`, `model_create`, `model_update` |

## Permissions

Autorização real: `RoleRequiredMixin` + `CAN_MANAGE_CATALOG = (ADMIN, ADMINISTRATIVO)`. Superusuário sempre passa.

Catálogo novo (aditivo, não usado pelas views): `manage_catalog`, `reclassify_equipment_model` (declaradas em `EquipmentModel.Meta.permissions`). **`reclassify_equipment_model` é enforced fora deste app** — em `apps/equipment/views.py` (`CAN_RECLASSIFY_EQUIPMENT_MODEL = (ADMIN,)`), não há view de reclassificação dentro de `catalog`.

## Templates

`templates/catalog/`: `category_list.html`, `category_form.html`, `model_list.html`, `model_form.html`. A template tag `model_image_url`/`model_has_commercial_image` é destinada a `templates/equipment/detail_public.html` (fora deste app, conforme docstring do módulo).

## JavaScript

Nenhum encontrado — nem nos templates de `catalog`, nem em `static/`.

## Dependências

`apps.core.models` (`TimeStampedModel`, `SoftDeleteModel`); `apps.accounts.permissions` (`CAN_MANAGE_CATALOG`, `RoleRequiredMixin`); `simple_history`; `django.contrib.staticfiles.finders`. `catalog` **não importa** de `equipment`, `crm`, `qrcodes`, `operations`, `maintenance`, `attachments`, `dashboard` — é um app "de baixo nível" na árvore de dependências.

## Quem chama apps.catalog

- `apps.equipment` — consumidor principal e mais acoplado: FK direta (`Equipment.model`, `EquipmentBatch.model`, `PROTECT`), geração de patrimônio, importação legada, código em lote.
- `apps.qrcodes` — busca de `EquipmentModel` por PK para gerar etiqueta/QR.
- `config/urls.py` — inclui `apps.catalog.urls` sob `catalogo/`.
- Vários testes de outros apps referenciam `Category`/`EquipmentModel` incidentalmente (fixtures).

## Testes

`apps/catalog/tests/`:

- `test_catalog_views.py` — matriz de permissão das 6 views; `code` editável antes de vínculo, travado depois (mesmo tentando forçar via POST).
- `test_model_images.py` — `get_model_image_path()`, template tag (fallback para placeholder, URL sempre `/static/...`), renderização real via `{% load model_images %}`.

## Migrations

1. `0001_initial.py` — `Category`, `EquipmentModel`, `HistoricalEquipmentModel`.
2. `0002_alter_historicalequipmentmodel_history_change_reason.py` — `history_change_reason` de `CharField` para `TextField`.
3. `0003_seed_cargo_architecture_base.py` (09/09/2026) — só `AlterModelOptions`, adiciona `permissions` novas ao `Meta`.

## Pontos importantes

- **A trava de `code` é garantida em 3 camadas independentes** (defesa em profundidade): `EquipmentModelForm.__init__` (desabilita o campo), `EquipmentModelAdmin.get_readonly_fields`, e `EquipmentModel.clean()` (a única que de fato impede via `ValidationError`, independente de UI).
- **A trava vale para TODOS os perfis, inclusive Admin/superusuário** — a constante `CAN_EDIT_LOCKED_MODEL_CODE` foi deliberadamente removida (25/08/2026) porque sugeria um "caminho excepcional" que não existe.
- **`last_sequence` é `editable=False`** e nunca deve ser tocado fora de `apps.equipment.services` — é o contador atômico da geração de patrimônio.
- **As Permissions declaradas em `EquipmentModel.Meta.permissions` não são usadas por nenhuma view de `catalog`** — só pelo catálogo aditivo e pela tela de gestão de cargos. `reclassify_equipment_model` como permissão de negócio não tem view correspondente dentro de `catalog`; a ação real vive em `apps.equipment`.
- **`images.py` e a template tag `model_images.py` são camadas deliberadamente separadas**: uma decide o caminho pretendido, a outra confirma a existência real em disco com cache por processo — adicionar uma imagem nova exige editar `MODEL_IMAGE_MAP` manualmente e reiniciar o processo para o cache pegar.
- **Templates ficam fora de `apps/catalog/`**, em `templates/catalog/` na raiz do projeto (padrão do projeto todo).
- Nenhum TODO/FIXME literal encontrado.
