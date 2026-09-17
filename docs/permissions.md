# Permissões e autorização

O LocusHub tem **dois sistemas de autorização coexistindo**. Este documento explica os dois, como se relacionam, e qual é a autorização "de fato" em cada parte do sistema hoje. Leia isto antes de proteger uma view nova ou de tentar entender por que um usuário vê (ou não vê) uma tela.

## Resumo rápido

| | Sistema legado (`Role`/`CAN_*`) | Sistema novo ("Cargo") |
|---|---|---|
| Onde mora | `apps/accounts/models.py` (`Role`), `apps/accounts/permissions.py` (`CAN_*`, mixins) | `apps/accounts/permission_catalog.py` (`PERMISSION_CATALOG`), `Group`/`Permission` nativos do Django |
| Quem usa hoje | Todas as views de `catalog`, `clients`, `equipment`, `operations`, `maintenance`, `qrcodes`, `dashboard`, e a própria gestão de usuários (`accounts`) | Só `apps.crm` (todas as views) e as telas de gestão de cargos (`accounts/views_roles.py`) |
| Mixin/decorator | `RoleRequiredMixin`, `SuperuserRequiredMixin`, `roles_required()` | `PermissionRequiredMixin` (nativo do Django) + `has_perm()` |
| Cardinalidade por usuário | `user.role` — um único `CharField`, sempre presente | `user.groups` — M2M nativo, mas a aplicação garante ≤1 grupo (ver abaixo) |
| Status | **Autorização de fato** para quase todo o sistema | Aditivo — fundação para uma migração futura "view por view" que ainda não aconteceu |

Um usuário **pode ter `Role` e Cargo ao mesmo tempo, e eles são completamente independentes na prática**: um Admin sem nenhum cargo atribuído continua com acesso total às telas legadas (que checam `role`); um usuário `CONSULTA` com o cargo "Administrador" atribuído continua **bloqueado (403)** nas telas legadas, porque elas nunca checam `groups`/`has_perm`. Isso é comprovado por teste (`apps/accounts/tests/test_user_cargo_integration.py::LegacyAuthorizationIndependentOfCargoTest`).

## Sistema legado — `Role` / `CAN_*`

### `Role` (`apps/accounts/models.py`)

`TextChoices` com 4 valores: `ADMIN` ("Administrador"), `ADMINISTRATIVO`, `OPERACIONAL` ("Operacional/Técnico"), `CONSULTA`. Armazenado em `User.role` (`CharField`, default `CONSULTA`).

### Mixins e decorator (`apps/accounts/permissions.py`)

- **`roles_required(*allowed_roles)`** — decorator para function-based views. `PermissionDenied` se não autenticado ou se `not user.is_superuser and user.role not in allowed_roles`.
- **`RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin)`** — `test_func()` retorna `user.is_superuser or user.role in self.allowed_roles`. `handle_no_permission()`: redireciona a login se anônimo, senão `PermissionDenied` (403).
- **`SuperuserRequiredMixin(LoginRequiredMixin, UserPassesTestMixin)`** — `test_func()` retorna **apenas** `bool(request.user.is_superuser)`, deliberadamente nunca ligado a `role`/`CAN_*` nem a uma `Permission` concedível. Ver "Por que hard delete e gestão de cargo usam isto" abaixo.

### Constantes `CAN_*`

18 constantes, cada uma uma tupla de `Role`:

| Constante | Roles | Usada por |
|---|---|---|
| `CAN_MANAGE_USERS` | ADMIN | accounts (gestão de usuários) |
| `CAN_MANAGE_CATALOG` | ADMIN, ADMINISTRATIVO | catalog |
| `CAN_RECLASSIFY_EQUIPMENT_MODEL` | ADMIN | equipment |
| `CAN_MANAGE_EQUIPMENT` | ADMIN, ADMINISTRATIVO | equipment, qrcodes |
| `CAN_VIEW_ACQUISITION_VALUE` | ADMIN, ADMINISTRATIVO | equipment (ficha pública/privada) |
| `CAN_REGISTER_OPERATIONS` | ADMIN, ADMINISTRATIVO, OPERACIONAL | operations, maintenance |
| `CAN_CHANGE_STATUS_CONDITION` | ADMIN, ADMINISTRATIVO, OPERACIONAL | equipment |
| `CAN_ADD_PHOTOS` | ADMIN, ADMINISTRATIVO, OPERACIONAL | (reservada — hoje `apps.attachments` já tem implementação real, mas o único consumidor é `apps.crm`, gated por `crm.view_opportunities`/Cargo, não por esta constante; ver `docs/apps/attachments.md`) |
| `CAN_EXPORT_DATA` | ADMIN, ADMINISTRATIVO | equipment (export CSV/XLSX) |
| `CAN_IMPORT_LEGACY_SPREADSHEET` | ADMIN | equipment (importação legada) |
| `CAN_SUPERSEDE_EQUIPMENT` | ADMIN | equipment (reemissão) |
| `CAN_VIEW_DIAGNOSTICS` | ADMIN | operations (diagnóstico de duplicatas) |
| `CAN_VIEW_CLIENTS` | ADMIN, ADMINISTRATIVO, OPERACIONAL, CONSULTA | clients, operations (leitura de Location) |
| `CAN_MANAGE_CLIENTS` | ADMIN, ADMINISTRATIVO | clients |
| `CAN_IMPORT_CLIENTS` | ADMIN | clients (importação Auvo) |
| `CAN_MANAGE_LOCATIONS` | ADMIN, ADMINISTRATIVO | operations |
| `CAN_VIEW_MOVEMENTS` | ADMIN, ADMINISTRATIVO, OPERACIONAL, CONSULTA | dashboard (referência de escopo) |
| `CAN_VIEW_MAINTENANCE` | ADMIN, ADMINISTRATIVO, OPERACIONAL, CONSULTA | maintenance, equipment (ficha), dashboard |

`CAN_REGISTER_OPERATIONS` é deliberadamente reaproveitada entre `operations` (instalar/retirar/transferir) e `maintenance` (abrir/concluir/cancelar, registrar higienização) — nenhuma constante nova foi criada só para manutenção.

### Duas constantes removidas deliberadamente (auditoria 25/08/2026)

- **`CAN_EDIT_LOCKED_MODEL_CODE`** — nunca existiu um caminho de exceção real. `EquipmentModel.code` é travado incondicionalmente para **todos**, inclusive Admin/superusuário, em 3 camadas independentes (`EquipmentModelForm`, `EquipmentModelAdmin`, `EquipmentModel.clean()`).
- **`CAN_VIEW_EQUIPMENT`** — nunca foi referenciada; `EquipmentListView`/`EquipmentDetailView` usam só `is_authenticated`, hoje equivalente aos 4 perfis.

Ambas podem "voltar a fazer sentido" se o comportamento real mudar — documentado assim no próprio código-fonte.

## Sistema novo — "Cargo" (`Group` + `Permission`)

Aprovado em 09/09/2026 como uma **fundação aditiva**, não uma migração imediata. Usa os models nativos `django.contrib.auth.models.Group`/`Permission` (que já existiam no schema desde o primeiro commit, via `PermissionsMixin` de `AbstractUser`, mas nunca eram usados).

### `RoleProfile` (`apps/accounts/models.py`)

Decora um `Group` (`OneToOneField`, `CASCADE`) com `description` e `is_protected` (bool, genérico por design — hoje só `True` para o cargo "Administrador", mas a flag existe para suportar um eventual segundo cargo protegido sem mudança de schema).

### `PERMISSION_CATALOG` (`apps/accounts/permission_catalog.py`)

Tupla de 27 `PermissionSpec` (`codename`, `app_label`, `model`, `legacy_constant: str|None`, `legacy_admin_only: bool`):

- **18 entradas espelham 1:1 as 18 constantes `CAN_*`** listadas acima (mesmos codenames/app/model), com `legacy_constant` apontando para o nome da constante original — rastreabilidade explícita.
- **9 entradas são exclusivas de `apps.crm`**, com `legacy_constant=None` — nasceram direto na arquitetura nova, nunca passaram por `CAN_*`. As 7 originais (10/09/2026): `view_opportunities`, `add_opportunities`, `change_opportunities`, `change_opportunity_stage`, `view_commercial_activities`, `add_commercial_activities`, `manage_commercial_settings`. Mais 2 de 14/09/2026 (Produtos e Serviços/Proposta Comercial): `issue_proposal_documents` (emitir Proposta em PDF) e `generate_contract` (gerar Contrato em PDF) — o restante da nova área comercial (adicionar/editar/remover item, salvar condições, criar nova versão) reaproveita `change_opportunities`, e aceitar reaproveita `change_opportunity_stage`, seguindo à risca "evitar excesso de permissions" (ver `docs/apps/crm.md` para o raciocínio completo).

`MODULE_LABELS` mapeia `app_label`→rótulo amigável para a tela de gestão de cargos (7 chaves: `accounts`, `catalog`, `equipment`, `operations`, `clients`, `maintenance`, `crm`).

Classificação de sensibilidade em 3 níveis (documentada no próprio módulo):
- **Nível A** — operacional configurável (`legacy_admin_only=False`).
- **Nível B** — sensível, hoje só Admin (`legacy_admin_only=True`) — 6 das 18 legadas.
- **Nível C** — ações de segurança do sistema (gestão de cargos, hard delete) — **não estão no catálogo**, permanecem exclusivamente `is_superuser` em código, nunca uma `Permission` concedível.

### `services.py` — único caminho de escrita

- `set_user_cargo(user, group)` — sempre `.set([group])` (substitui, nunca acumula) ou `.clear()`.
- `create_cargo`/`update_cargo`/`delete_cargo` — validam nome único, codenames restritos ao catálogo (nunca os `add_/change_/delete_/view_` automáticos do Django), e respeitam `is_protected` (`_ensure_not_protected`).

### Seed (migrations `apps.accounts` 0003/0004)

9 `Group` iniciais: 4 espelhando `Role` (permissões calculadas programaticamente a partir do catálogo, nunca copiadas à mão) + 5 vazios reservados (Financeiro, Marketing, TI, Backoffice, Comercial) para crescimento futuro. Todo `User` existente foi retroativamente associado ao `Group` correspondente ao seu `role` (`0004_backfill_user_cargos.py`).

## "Um cargo por usuário" é regra de aplicação, não de banco

`User.groups` é M2M nativo do Django — tecnicamente permite N grupos. A garantia de cardinalidade ≤1 existe **só** porque `set_user_cargo()` é o único ponto de escrita suportado (nunca `user.groups.add()`/`.set()` direto em view/form) e sempre substitui a lista inteira. Um modelo `through` customizado para expressar essa cardinalidade no schema foi deliberadamente rejeitado na arquitetura aprovada.

## Por que hard delete e gestão de cargo usam `SuperuserRequiredMixin`, não uma Permission

Se "editar cargos" fosse uma `Permission` normal, um cargo com essa permissão poderia se auto-conceder qualquer outra permissão do sistema, inclusive a de gerenciar cargos — uma escalação de privilégio trivial. Por isso a gestão de Cargo (`RoleCreateView`/`UpdateView`/`DeleteView`, em `apps/accounts/views_roles.py`) e toda operação de hard delete do projeto (`ClientHardDeleteView`, `EquipmentHardDeleteView`, `OpportunityHardDeleteView`) usam **`SuperuserRequiredMixin`** — checam só `is_superuser`, nunca `role`, nunca uma `Permission` concedível. Essas ações são classificadas como "Nível C" e ficam estruturalmente fora do que qualquer `Permission` consegue conceder.

Cada `hard_delete_*()` (em `apps.clients.services`, `apps.equipment.services`, `apps.crm.services`) verifica `actor.is_superuser` **dentro do próprio service**, não só na view — defesa em profundidade.

## Botão escondido ≠ bloqueio no backend

Padrão consistente em todo o projeto: a UI pode esconder um botão/link com base em `perms.*`/roles, mas isso é só conveniência — a autorização real está sempre na view (`RoleRequiredMixin`/`PermissionRequiredMixin`) e, para as ações mais sensíveis, também no service (`_ensure_not_protected`, checagem de `is_superuser`, etc.). Isso é comprovado por testes explícitos em `apps.crm` (POST manual de campos de perda/ganho sem permissão é bloqueado mesmo que o botão nunca tivesse aparecido; o mesmo vale para todas as ações de Produtos e Serviços — adicionar item, salvar condições, emitir, gerar contrato, aceitar) e em `apps.accounts` (POST direto em cargo protegido é rejeitado mesmo que a UI nem renderize o form).

## Nota sobre `apps.crm` — checagem manual de permissão dentro de uma view (14/09/2026)

`ProposalGenerateDocumentView` é uma exceção deliberada ao padrão de "uma `permission_required` fixa por classe": como a mesma view atende três `document_type` diferentes (PROPOSTA exige `crm.issue_proposal_documents`; CONTRATO/PROPOSTA_E_CONTRATO exigem `crm.generate_contract`), a permissão correta só é conhecida depois de ler o corpo do POST. A view usa `crm.view_opportunities` como piso de acesso na classe e levanta `PermissionDenied` explicitamente dentro de `post()` conforme o `document_type` submetido — documentado aqui para não ser confundido com um esquecimento de `permission_required` na próxima auditoria.

**Segundo exemplo (16/09/2026, Tabela de Preços V1)**: `PriceTableItemRowView` atende leitura (GET de uma linha, disponível para qualquer um com `crm.view_price_table`) e escrita (`?modo=editar`/POST, restrita a `crm.change_price_table`) na MESMA classe/URL — mesma justificativa do exemplo acima (a permissão certa depende de QUAL ação está sendo pedida, não só de "qual view"). `permission_required = "crm.view_price_table"` na classe é o piso; `request.user.has_perm("crm.change_price_table")` checado manualmente antes de renderizar o modo de edição OU processar o POST, levantando `PermissionDenied` (403) quando ausente — testado explicitamente com acesso direto por URL (sem passar pelo botão de lápis, que nem aparece para quem não tem a permissão).

**Terceiro exemplo (16/09/2026, RODADA 1 — Matriz de Preços de Locação)**: `PriceTableRateCellView` (célula equipamento×prazo da matriz) segue EXATAMENTE o mesmo desenho do exemplo acima, reaproveitando as MESMAS duas permissões (`crm.view_price_table`/`crm.change_price_table`) — nenhuma permissão nova foi criada para a matriz. A decisão de produto foi deliberada: "preço é informação sensível" vale igual para a lista flat (Venda/Serviço) e para a matriz (Locação), então não haveria nenhum ganho em separar as duas em permissões distintas — ver `docs/apps/crm.md`, seção Permissions, para a análise completa.

## Django Admin

O admin nunca é a interface operacional principal — é ferramenta técnica/contingência. Vários `ModelAdmin` (`EquipmentAdmin`, `MaintenanceAdmin`, `CleaningAdmin`) marcam campos sensíveis como `readonly_fields` ou bloqueiam `has_add_permission`, forçando toda escrita relevante a passar pelos services (garante que histórico/`StatusHistory`/`ConditionHistory` nunca fiquem incompletos).

## Ao proteger uma view nova

1. Se o app já existe e usa `RoleRequiredMixin`/`CAN_*` (todo mundo, exceto `crm`), siga o padrão do app: adicione uma constante `CAN_*` nova só se nenhuma existente descrever a regra, e reaproveite quando fizer sentido (como `CAN_REGISTER_OPERATIONS`).
2. Se o app é novo (ou se decidiu-se migrar para a arquitetura de Cargo), siga o padrão de `apps.crm`: declare `Permission`s em `Meta.permissions` do model relevante, registre no `PERMISSION_CATALOG`, use `PermissionRequiredMixin`.
3. Nunca misture os dois sistemas na mesma view.
4. Ações de exclusão física (hard delete) ou de gestão de autorização em si sempre usam `SuperuserRequiredMixin`, nunca uma `Permission`/`Role`.
