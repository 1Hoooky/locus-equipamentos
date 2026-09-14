# apps.accounts

## Objetivo

`apps.accounts` é o app de usuários e autorização de todo o projeto. Contém: o `User` customizado (`AUTH_USER_MODEL = "accounts.User"`); o sistema legado de perfis `Role`/`CAN_*`/`RoleRequiredMixin`/`roles_required` — a autorização de fato usada pela maioria das views do projeto hoje; a arquitetura nova aditiva de "Cargo" (`Group`+`Permission` nativos do Django, aprovada em 09/09/2026); as telas de gestão de usuários e de cargos; o fluxo completo de autenticação (login, logout, recuperação de senha, via views genéricas do Django); e o management command `bootstrap_admin` para provisionamento do primeiro Administrador em ambientes sem shell.

> Para o detalhamento completo dos dois sistemas de autorização, ver **`docs/permissions.md`** — este documento cobre só o que é específico deste app.

## Models

Arquivo: `apps/accounts/models.py`.

- **`Role(TextChoices)`**: `ADMIN`="Administrador", `ADMINISTRATIVO`="Administrativo", `OPERACIONAL`="Operacional/Técnico", `CONSULTA`="Consulta".
- **`User(AbstractUser)`**: `role` (CharField, choices=Role, default=CONSULTA). Métodos `has_role(*roles)`; properties `is_admin`, `is_administrativo_ou_superior`, `is_operacional_ou_superior`. `is_active` (herdado) é reaproveitado como soft-delete, sem duplicar `SoftDeleteModel`. Property `cargo` retorna `self.groups.first()` — assume a invariante "um cargo por usuário", garantida só por `services.set_user_cargo()`, nunca por constraint de banco. `Meta.permissions = [("manage_users", "Pode gerenciar usuários (criar, editar, ativar/desativar)")]`.
- **`RoleProfile(TimeStampedModel)`**: metadados do "Cargo" (decora `Group`, não o substitui). `group` (OneToOne → `Group`, CASCADE), `description`, `is_protected` (BooleanField, default `False` — genérico por design, hoje só `True` para "Administrador"; impede edição/renomeação/exclusão pela tela de cargos, checagem real em `services.py`). `verbose_name="cargo"`. Sem `HistoricalRecords`.

## Services

Arquivo: `apps/accounts/services.py` — único caminho suportado para escrever cargo/user-group e criar/editar/excluir Cargo.

- **`CargoError(ValueError)`** — erro de negócio único do módulo.
- **`set_user_cargo(user, group)`** — `@transaction.atomic`. `group=None` → `user.groups.clear()`; senão `user.groups.set([group])` — sempre **substitui**, nunca acumula.
- **`_validate_codenames(codenames)`** — só aceita codenames presentes em `PERMISSION_CATALOG` (nunca os `add_/change_/delete_/view_` automáticos do Django); levanta `CargoError` para codename desconhecido ou cuja `Permission` ainda não existe no banco (migrations não rodadas).
- **`_ensure_not_protected(group, action)`** — levanta `CargoError` se `group.profile.is_protected`.
- **`CargoData`** (dataclass): `name`, `description=""`, `permission_codenames`.
- **`create_cargo(data)`** — valida nome não vazio e único (case-insensitive), valida codenames; cria `Group` + seta permissions + cria `RoleProfile(is_protected=False)`.
- **`update_cargo(group, data)`** — `_ensure_not_protected` primeiro; valida nome/unicidade (excluindo o próprio pk) e codenames; atualiza `name`/`permissions`/`description`.
- **`delete_cargo(group)`** — `_ensure_not_protected`; se `group.user_set.count() > 0`, rejeita (não deleta cargo com usuários atribuídos); senão `group.delete()`.

## Forms

Arquivo: `apps/accounts/forms.py`.

- `permission_catalog_queryset()` — filtra `Permission.objects` pelas triplas `(codename, app_label, model)` de todo `PERMISSION_CATALOG`.
- `_CargoAssignmentMixin`: campo `cargo` (`ModelChoiceField`, não múltiplo — único caminho de UI para escolher cargo).
- `UserCreateForm(_CargoAssignmentMixin, UserCreationForm)`: `username, first_name, last_name, email, role`.
- `UserUpdateForm(_CargoAssignmentMixin, ModelForm)`: `first_name, last_name, email, role, is_active` — preenche `cargo.initial` a partir de `instance.cargo`; não inclui troca de senha (fluxo separado via "esqueci minha senha").
- `CargoForm(Form)`: `name`, `description`, `permissions` (`ModelMultipleChoiceField` sobre `permission_catalog_queryset()`, `CheckboxSelectMultiple`).

## Views

### `views.py` — gestão de usuários (todas `RoleRequiredMixin`, `CAN_MANAGE_USERS` = só `Role.ADMIN`, superuser sempre passa)

- `UserListView` — lista todos os usuários.
- `UserCreateView` — GET/POST via `UserCreateForm` + `set_user_cargo()`.
- `UserUpdateView` — trava explícita: se `user.pk == request.user.pk` e o POST tenta desmarcar `is_active`, bloqueia a autodesativação (200 com erro, sem redirect).

### `views_roles.py` — gestão de Cargos (todas `SuperuserRequiredMixin` — `is_superuser` puro, não `Role.ADMIN`)

- `RoleListView` — lista `Group` com `select_related("profile")`.
- `RoleCreateView` — GET/POST via `CargoForm` + `create_cargo`; `CargoError` vira `form.add_error(None, ...)`.
- `RoleUpdateView` — se `is_protected`, bloqueia antes de instanciar o form; senão `update_cargo`.
- `RoleDeleteView` — só `post()`; `CargoError` vira `messages.error`, sempre redireciona.

## URLs

`app_name="accounts"`, montado em `config/urls.py` como `path("contas/", include("apps.accounts.urls"))`.

| name | path |
|---|---|
| `accounts:login` / `logout` | `contas/login/` / `contas/logout/` |
| `accounts:user_list` / `user_create` / `user_update` | `contas/usuarios/...` |
| `accounts:role_list` / `role_create` / `role_update` / `role_delete` | `contas/cargos/...` |
| `accounts:password_reset*` (4 rotas) | `contas/senha/redefinir/...` |

As views de reset de senha sobrescrevem `success_url` explicitamente (`reverse_lazy("accounts:password_reset_done")` etc.) — ver Pontos importantes. `settings.LOGIN_URL="accounts:login"`, `LOGIN_REDIRECT_URL="dashboard:home"`, `LOGOUT_REDIRECT_URL="accounts:login"`.

## Permissions

Ver **`docs/permissions.md`** para a matriz completa. Resumo do que é específico deste app:

- `CAN_MANAGE_USERS = (Role.ADMIN,)` protege `views.py`.
- Gestão de Cargo (`views_roles.py`) usa **`SuperuserRequiredMixin`**, nunca `RoleRequiredMixin`/`CAN_*` — checa só `is_superuser`, deliberadamente desligado de qualquer `Permission` concedível (ver Pontos importantes).
- `apps.accounts.permission_catalog.PERMISSION_CATALOG` é a fonte única do sistema de Cargo novo — 25 entradas (18 espelhando `CAN_*` legadas + 7 exclusivas do `crm`).

## Templates

`templates/accounts/` (8 arquivos) + `templates/registration/password_reset_email.html`:

- `login.html` — form sem `action` própria, campo hidden `next` renderizado condicionalmente.
- `user_list.html`, `user_form.html` (trata `is_active` de forma especial: aviso "você não pode desativar o próprio usuário").
- `role_list.html`, `role_form.html` (checklist de permissões renderizado manualmente por módulo via `permission_groups`, não `{{ form.permissions }}` cru; cargo protegido mostra só um alerta, sem form).
- `password_reset*.html` (4 telas padrão do fluxo Django).
- `templates/registration/password_reset_email.html` — versão própria, só para corrigir o nome de rota namespaced no link (ver Pontos importantes).

## JavaScript

Nenhum arquivo `.js` dedicado. Único JS é inline: `onsubmit="return confirm(...)"` em `role_list.html` para confirmar exclusão de cargo.

## Dependências

`apps.accounts` importa de `apps.core.models.TimeStampedModel` (base de `RoleProfile`) e de `django.contrib.auth`/`contenttypes`. **Não importa nada** de `catalog`, `equipment`, `clients`, `operations`, `maintenance`, `attachments`, `qrcodes`, `dashboard`, `crm` — é a base de autorização, não um consumidor.

## Quem chama apps.accounts

Praticamente todos os apps do projeto:

- Todos os apps de domínio pré-existente (`catalog`, `clients`, `equipment`, `operations`, `maintenance`, `qrcodes`, `dashboard`) usam **exclusivamente** `RoleRequiredMixin`/`CAN_*`/`roles_required`.
- `apps.crm` é o **único** app que usa `PermissionRequiredMixin`/`has_perm()` do sistema novo (`permission_required = "crm.<codename>"`).
- `apps.core.hard_delete` usa `SuperuserRequiredMixin` como padrão para toda operação de hard delete do projeto.
- `apps.core.nav` referencia nomes de rota `accounts:*` (não código Python) para destacar o grupo de menu ativo.
- Todos os apps importam `User`/`Role` para FK de autoria (`created_by`, etc.).

## Testes

9 arquivos em `apps/accounts/tests/` (1208 linhas):

- `test_axes_lockout.py` — django-axes (religa `AXES_ENABLED` via `override_settings`, desligado por padrão em `test.py`).
- `test_login_next_redirect.py` — fluxo "QR→login→mesma ficha", proteção open-redirect.
- `test_password_reset.py` — fluxo completo via e-mail real (`mail.outbox`).
- `test_permissions.py` — matriz do sistema legado.
- `test_roles_foundation.py` — integridade do `PERMISSION_CATALOG` (25 entradas, 1:1 com `CAN_*`, estado das migrations de seed).
- `test_roles_services.py` — `set_user_cargo`/`create_cargo`/`update_cargo`/`delete_cargo`.
- `test_roles_views.py` — só superusuário acessa telas de cargo (Admin comum recebe 403).
- `test_user_cargo_integration.py` — prova explícita de independência entre `Role` legado e "Cargo" novo.
- `test_user_management.py` — CRUD de usuários, autodesativação bloqueada.

## Migrations

1. `0001_initial.py` — cria `User`.
2. `0002_seed_cargo_architecture_base.py` (09/09/2026) — `Meta.permissions` no `User`; cria `RoleProfile`.
3. `0003_seed_cargos.py` — data migration: cria os 9 `Group` iniciais (4 espelhando `Role` + 5 vazios reservados: Financeiro, Marketing, TI, Backoffice, Comercial), `RoleProfile` para cada um. Reverso é no-op deliberado.
4. `0004_backfill_user_cargos.py` — data migration: atribui a cada `User` existente o `Group` correspondente ao seu `role` atual. Idempotente, reverso no-op.

## Bootstrap (`management/commands/bootstrap_admin.py`)

`python manage.py bootstrap_admin`, chamado automaticamente pelo entrypoint do container no boot — nunca exposto por rota HTTP. Cria o primeiro Administrador em plataformas sem shell/SSH (ex.: Render Free); no VPS o admin é criado via `createsuperuser` normal. Lê `BOOTSTRAP_ADMIN_USERNAME`/`EMAIL`/`PASSWORD` via variáveis de ambiente; sem valores vazios, não faz nada. **Idempotente**: se já existe usuário com esse username, não faz nada — nunca altera/promove uma conta existente. Valida a senha com `validate_password()` (mesma política do resto do sistema). Recomenda remover as variáveis de ambiente após o primeiro boot.

## Pontos importantes

- **Os dois sistemas de autorização coexistem, mas só um é "de fato" hoje**: `Role`/`CAN_*`/`RoleRequiredMixin` continuam sendo a autorização real de toda view pré-existente. O sistema de Cargo é aditivo — hoje só é checado de fato por `apps.crm` e pelas próprias telas de gestão de cargos. As migrations de seed preparam o terreno para uma migração futura "view por view" que ainda não aconteceu.
- **"Um cargo por usuário" é regra de aplicação, não de banco** — `User.groups` é M2M nativo (tecnicamente permite N grupos); a cardinalidade ≤1 depende inteiramente de `set_user_cargo()` ser o único ponto de escrita. Um modelo `through` customizado foi deliberadamente rejeitado.
- **`SuperuserRequiredMixin` e prevenção de escalação de privilégio**: checa só `is_superuser`, nunca uma `Permission` concedível — se "editar cargos" fosse uma Permission normal, um cargo com essa permissão poderia se auto-conceder qualquer outra, inclusive gerenciar cargos. Por isso gestão de Cargo (e hard delete em outros apps) é "Nível C", estruturalmente fora do que qualquer Permission consegue conceder.
- **Duas constantes `CAN_*` foram removidas deliberadamente** (auditoria 25/08/2026): `CAN_EDIT_LOCKED_MODEL_CODE` (não existe caminho de exceção real para editar `EquipmentModel.code` após vínculo — trava incondicional em 3 camadas) e `CAN_VIEW_EQUIPMENT` (nunca foi referenciada).
- **Bug histórico de redirect de reset de senha**: o template padrão do Django usa o nome de rota **sem** namespace no e-mail de reset, mas o projeto só registra a rota namespaced — quebrava com `NoReverseMatch` na primeira solicitação real (só apareceu ao escrever o teste de integração HTTP completo). Corrigido com um `templates/registration/password_reset_email.html` próprio.
- **Um usuário pode ter `Role` E `Cargo` simultaneamente, e são totalmente independentes na prática** — um Admin sem nenhum cargo atribuído continua com acesso total legado; um usuário `CONSULTA` com o cargo "Administrador" continua bloqueado (403) pelas views legadas, que checam `role`, não `groups`/`has_perm`.
- **`RoleProfile.is_protected` é genérica por design** — não hardcoded comparando nome, para já suportar um eventual segundo cargo protegido sem mudança de schema.
