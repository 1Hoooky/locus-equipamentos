# Arquitetura

## Visão geral

O LocusHub (Locus Equipamentos) é uma aplicação Django monolítica clássica — sem API REST separada, sem SPA de frontend. Server-rendered com Django Templates, htmx para as poucas interações que precisam de fragmentos assíncronos (listagem agrupada de equipamentos, seleção de movimento de saída na abertura de manutenção), e JavaScript vanilla (sem framework, sem build step) para o resto (autocomplete, Kanban drag-and-drop, modais, buscas incrementais). Tailwind é carregado via CDN — não há pipeline de build de frontend.

Stack: Django 5.0, PostgreSQL (sempre — nem em desenvolvimento se usa SQLite, ver abaixo), `psycopg[binary]` 3.x, `django-simple-history` (auditoria), `django-axes` (bloqueio de força bruta), Argon2 para hash de senha, WeasyPrint (PDF de etiquetas), `qrcode`/`python-barcode`/Pillow (geração de imagem), `openpyxl` (planilhas), `httpx` (consulta de CNPJ à BrasilAPI).

## Por que PostgreSQL também em desenvolvimento e testes

A geração atômica do número de patrimônio (`apps.equipment.services.create_equipment()`) depende de `SELECT ... FOR UPDATE`, que o SQLite não implementa de forma confiável sob concorrência real. Por isso não existe fallback para SQLite neste projeto — nem em dev, nem em testes. Vários testes de concorrência real (`TransactionTestCase` + `threading`) só são confiáveis contra Postgres.

## Os 11 apps locais

Ordem de `LOCAL_APPS` (`config/settings/base.py`):

```
core → accounts → catalog → equipment → clients → operations → maintenance → attachments → qrcodes → dashboard → crm
```

| App | Papel | Doc |
|---|---|---|
| `core` | Base compartilhada: models abstratos, `Address`, hard delete, submissão idempotente, navegação, template tags, sem views/urls próprias | [`docs/apps/core.md`](apps/core.md) |
| `accounts` | Usuários, os dois sistemas de autorização, autenticação | [`docs/apps/accounts.md`](apps/accounts.md), [`docs/permissions.md`](permissions.md) |
| `catalog` | Categorias e Modelos de equipamento (`EquipmentModel.code`, base do patrimônio) | [`docs/apps/catalog.md`](apps/catalog.md) |
| `equipment` | App central: `Equipment`, patrimônio atômico/imutável, histórico, página pública do QR, import/export | [`docs/apps/equipment.md`](apps/equipment.md) |
| `clients` | Cadastro de clientes, endereço fiscal, consulta de CNPJ, importação Auvo | [`docs/apps/clients.md`](apps/clients.md) |
| `operations` | `Location` (unidades) e `Movement` (movimentação imutável) | [`docs/apps/operations.md`](apps/operations.md) |
| `maintenance` | Manutenção (ciclo de vida) e Higienização (evento atômico) | [`docs/apps/maintenance.md`](apps/maintenance.md) |
<<<<<<< HEAD
| `attachments` | Armazenamento genérico de arquivo (desde 14/09/2026: PDFs de Proposta/Contrato do CRM, via `GenericForeignKey`) | [`docs/apps/attachments.md`](apps/attachments.md) |
| `qrcodes` | Geração de QR/código de barras/etiquetas PDF, tudo em memória | [`docs/apps/qrcodes.md`](apps/qrcodes.md) |
| `dashboard` | Home operacional (`/`), agregação read-only | [`docs/apps/dashboard.md`](apps/dashboard.md) |
| `crm` | Funil de vendas (Kanban de Oportunidades) + composição comercial (Proposta/Contrato, desde 14/09/2026), único app 100% na arquitetura de Cargo nova | [`docs/apps/crm.md`](apps/crm.md) |
=======
| `attachments` | Reservado para fotos/anexos — esqueleto vazio, não implementado | [`docs/apps/attachments.md`](apps/attachments.md) |
| `qrcodes` | Geração de QR/código de barras/etiquetas PDF, tudo em memória | [`docs/apps/qrcodes.md`](apps/qrcodes.md) |
| `dashboard` | Home operacional (`/`), agregação read-only | [`docs/apps/dashboard.md`](apps/dashboard.md) |
| `crm` | Funil de vendas (Kanban de Oportunidades), único app 100% na arquitetura de Cargo nova | [`docs/apps/crm.md`](apps/crm.md) |
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

## Mapa de dependências real

Baseado em imports reais (não na ordem de `LOCAL_APPS`, que é só ordem de registro). Uma seta A→B significa "A importa/depende de B":

```
core            (não depende de nenhum outro app local)
  ↑
accounts        → core
  ↑
catalog         → core, accounts
  ↑
equipment       → core, accounts, catalog, clients* , operations** , maintenance**
  ↑
clients         → core, accounts, operations** (import local em create_client)
  ↑
operations      → core, accounts, clients, equipment, maintenance*** (import local em _validate_transition)
  ↑
maintenance     → core, accounts, equipment, operations (topo do módulo — direção "de cima para baixo")
  ↑
<<<<<<< HEAD
attachments     → accounts (desde 14/09/2026: `created_by`; continua sem depender de nenhum app "de domínio" — `content_object` é genérico via `GenericForeignKey`, não um import de `crm`/`equipment`/etc.)

qrcodes         → equipment, catalog, accounts
dashboard       → equipment, maintenance, operations
crm             → clients, core, accounts, catalog****, equipment*****, operations, attachments
=======
attachments     (isolado — sem models, sem imports de outros apps)

qrcodes         → equipment, catalog, accounts
dashboard       → equipment, maintenance, operations
crm             → clients, core, accounts
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7
```

`*` `Equipment.current_client` é FK via string (`"clients.Client"`), sem import direto.
`**` `apps.equipment` importa `apps.operations`/`apps.maintenance` **localmente**, dentro das funções que precisam (`get_equipment_history_timeline`, hard delete) — nunca no topo do módulo, para não criar import circular (`operations`/`maintenance` também referenciam `Equipment`).
`***` `apps.operations._validate_transition()` importa `apps.maintenance.services.has_open_maintenance` **localmente** — decisão arquitetural deliberada: `operations` é uma camada mais antiga/baixa e nunca declara em import-time uma dependência de `maintenance` (camada mais nova/alta), para não arriscar um ciclo quando `maintenance` crescer. `apps.maintenance`, por sua vez, importa `Movement`/`MovementType` de `operations` **no topo** — a direção "correta" é maintenance→operations, não o contrário.
<<<<<<< HEAD
`****` `apps.crm` passou a depender de `apps.catalog.models.EquipmentModel` em 14/09/2026 — `ProposalItem.equipment_model` é uma FK real ao catálogo (nunca a `Equipment`/patrimônio).
`*****` `apps.crm.services.check_availability()` importa `apps.equipment.models.Equipment`/`Status` **localmente** (só leitura, dentro da função) — mesma disciplina de import local usada em outros pontos do projeto para não criar uma dependência de topo desnecessária num app que crm só consulta esporadicamente.

Esse padrão de "import local para evitar ciclo" se repete em `apps.equipment.movement_panel` (import local de `apps.operations`/`apps.maintenance`), em `apps.clients.services.create_client()` (import local de `apps.operations`, que por sua vez depende de `clients.Client`) e em `apps.crm.services.issue_proposal()`/`generate_contract()` (import local de `apps.crm.pdf`, para não acoplar o módulo de services inteiro ao WeasyPrint em import-time).

`apps.core` é a única base sem nenhuma dependência interna — todo o resto do projeto depende dela, direta ou indiretamente. Desde 14/09/2026, `apps.core.models.CompanyProfile` (singleton com os dados da própria Locus, usado nos snapshots de proposta) também vive aqui, seguindo a mesma lógica de "dado compartilhado sem dono de domínio único".
=======

Esse padrão de "import local para evitar ciclo" se repete em `apps.equipment.movement_panel` (import local de `apps.operations`/`apps.maintenance`) e em `apps.clients.services.create_client()` (import local de `apps.operations`, que por sua vez depende de `clients.Client`).

`apps.core` é a única base sem nenhuma dependência interna — todo o resto do projeto depende dela, direta ou indiretamente.
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

## O padrão "services.py" — a regra mais importante do projeto

Todo app com regra de negócio real (`clients`, `equipment`, `operations`, `maintenance`, `crm`, `accounts`) segue o mesmo padrão: um `services.py` com funções que são o **único caminho suportado** para criar/editar/excluir os models desse app. Views e forms nunca chamam `.objects.create()`/`.save()` diretamente para uma escrita que tem regra de negócio — sempre passam pelo service correspondente. Isso garante, de forma consistente em todo o projeto:

- Validação centralizada (nunca duplicada entre view e admin, por exemplo).
- Transação atômica (`@transaction.atomic`) em toda escrita que precisa ser tudo-ou-nada.
<<<<<<< HEAD
- `select_for_update()` nos poucos pontos que precisam de lock pessimista contra concorrência real (geração de patrimônio, criação de movimentação, mudança de etapa de oportunidade, numeração de Proposta/Contrato via `NumberingCounter` desde 14/09/2026).
=======
- `select_for_update()` nos poucos pontos que precisam de lock pessimista contra concorrência real (geração de patrimônio, criação de movimentação, mudança de etapa de oportunidade).
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7
- Histórico (`django-simple-history` via `_change_reason`, ou um model de histórico estruturado dedicado como `StatusHistory`/`OpportunityStageChange`) sempre gerado junto com a escrita, nunca esquecido.
- O Django Admin nunca é um caminho de escrita paralelo — campos sensíveis são `readonly_fields` ou a criação é bloqueada, forçando tudo a passar pelo mesmo service.

Ver `docs/flows.md` para os fluxos concretos mais importantes.

## Soft delete vs. hard delete

- **`SoftDeleteModel`** (`apps.core.models`, campo `is_active`) é a via normal e universal de "exclusão" para praticamente todo model do sistema. **Não** filtra automaticamente (sem manager mágico) — cada view/query decide explicitamente se quer só ativos.
- **Hard delete** (exclusão física, `apps.core.hard_delete`) é uma capacidade adicional, muito mais restrita: só `Client`, `Equipment` e `Opportunity` a têm, sempre atrás de `SuperuserRequiredMixin` (nunca `Role.ADMIN` nem uma `Permission` concedível — ver `docs/permissions.md`), sempre com uma tela de confirmação mostrando o impacto (`HardDeleteImpact`), e sempre com `actor.is_superuser` checado de novo dentro do service (defesa em profundidade). Foi introduzida durante o desenvolvimento para limpar dados de teste sem poluir o banco — não é uma feature "operacional" pensada para uso corrente.

## Idempotência de formulário

`apps.core.submission.SubmissionGuard` protege contra duplo-submit (duplo clique, F5 após POST). A primeira versão guardava o token só na sessão, o que tinha uma race condition real sob requisições concorrentes (a sessão não é read-modify-write atômica entre requests). A versão corrigida move a autoridade de consumo para uma constraint `UNIQUE` no banco (`ConsumedSubmissionToken`) — testado com `TransactionTestCase`+threads em `apps.operations`/`apps.maintenance`. Usado em: criação de cliente, criação de localização, criação de movimentação (escopo por equipamento), abertura/conclusão/cancelamento de manutenção, criação/cancelamento de higienização, preenchimento em lote de código legado.

## Autorização

Ver **`docs/permissions.md`** — dois sistemas coexistem (`Role`/`CAN_*` legado, autorização de fato hoje; e "Cargo"/`Group`/`Permission` novo, aditivo, usado só por `apps.crm` e pela própria gestão de cargos).

## Configuração (`config/settings/`)

- **`base.py`** — tudo que é comum. Nenhuma credencial hardcoded — tudo via `python-decouple` (`.env`). `PostgreSQL` sempre. `PASSWORD_HASHERS` com Argon2 primeiro (troca automática no próximo login de hashes legados). `django-axes` configurado com `AxesStandaloneBackend` **antes** de `ModelBackend`, e `AxesMiddleware` como **último** middleware (exigência da própria lib). `AUTH_PASSWORD_VALIDATORS` (mínimo 10 caracteres + validadores padrão do Django). `SITE_BASE_URL` fixo via `.env` (nunca derivado do `Host` da requisição) — garante que o QR físico impresso aponte sempre para o mesmo lugar.
- **`dev.py`** — herda `base`, `DEBUG=True`, e-mail via console backend (sem provedor transacional configurado ainda).
- **`test.py`** — herda `dev`, com uma única diferença: `AXES_ENABLED=False` (o atalho `client.login()` do Django não passa `request` para `authenticate()`, o que quebraria a suíte inteira se o axes estivesse ligado; `test_axes_lockout.py` religa via `override_settings` e usa requisições HTTP reais). **É o settings correto para rodar a suíte** — `pytest.ini` já aponta para ele. Rodar com `python manage.py test` usa `config.settings.dev` (axes ligado) e produz falhas falsas generalizadas — ver `docs/testing.md`.
- **`prod.py`** / **`render.py`** — ver `docs/deployment.md`.

## Extensões de banco

`pg_trgm` (Postgres), ativada por `apps.clients` migration `0006_pg_trgm_extension.py` — usada pelo autocomplete de cliente do CRM (`TrigramWordSimilarity`). É a única migration do projeto escrita à mão (não gerada por `makemigrations`).

## Padrões de auditoria/histórico

- **`django-simple-history`** (`HistoricalRecords`) em quase todo model de domínio — `Client`, `Address`, `EquipmentModel`, `Equipment`, `Location`, `Maintenance`, `Opportunity`. Grava `_change_reason` quando o service o define explicitamente.
- **Histórico estruturado dedicado** onde uma simples tabela de snapshot não bastava: `StatusHistory`/`ConditionHistory` (equipment), `OpportunityStageChange` (crm) — sempre com `reason` obrigatório, `changed_by`, `changed_at`.
- **`Movement`** (operations) e **`Cleaning`** (maintenance) são, eles mesmos, o registro de auditoria — por isso não têm `HistoricalRecords` própria (não faz sentido "auditar a auditoria" de um evento imutável).
