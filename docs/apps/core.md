# apps.core

## Objetivo

`apps.core` é o app base/compartilhado do LocusHub. Não tem `urls.py`, não expõe nenhuma rota própria e `views.py`/`admin.py` são apenas o boilerplate vazio gerado pelo `startapp`. Suas responsabilidades reais são de infraestrutura, reaproveitada por todos os outros apps de domínio:

- Abstract base models (`TimeStampedModel`, `SoftDeleteModel`) usados por 7 apps.
- Model concreto `Address`, compartilhado por `clients` (endereço fiscal) e `operations` (endereço de `Location`) — nunca a mesma linha entre os dois.
- Idempotência de formulário (proteção contra duplo-submit) via `SubmissionGuard` + model `ConsumedSubmissionToken`.
- Infraestrutura de "hard delete" (exclusão física, restrita a superusuário) reaproveitada por `clients`, `equipment` e `crm`.
- Lógica de navegação/sidebar (`active_nav_group`) — fonte única de qual grupo do menu deve aparecer destacado, usada tanto pela sidebar desktop quanto pelo drawer mobile.
- Context processor global (`commercial_links`) injetado em todos os templates.
- Template tags compartilhadas: ícones SVG vendorizados (`icons.py`), navegação (`nav.py`), formatação de moeda BRL (`currency.py`), paginação preservando querystring (`pagination_tags.py`).
- `AddressForm`/`HardDeleteConfirmForm` reaproveitados por múltiplos apps.
- `services.py`: único ponto de criação/edição de `Address`.

## Models

Arquivo: `apps/core/models.py`.

- **`TimeStampedModel`** (abstract) — `created_at` (`auto_now_add`), `updated_at` (`auto_now`).
- **`SoftDeleteModel`** (abstract) — campo único `is_active = BooleanField(default=True)`. **Não** substitui o manager padrão por um que filtra `is_active=True` automaticamente — decisão deliberada contra managers "mágicos" que escondem inativos sem que cada tela decida explicitamente (fonte clássica de bugs, ex.: um relatório onde equipamento "some").
- **`ConsumedSubmissionToken`** (concreto) — `token` (CharField 64, único), `scope` (CharField 150), `created_at`. Não herda `TimeStampedModel` (linhas são imutáveis, só registram consumo de um token). `verbose_name = "token de submissão consumido"`.
- **`Address(TimeStampedModel)`** — `cep`, `logradouro`, `numero`, `complemento`, `bairro`, `cidade`, `uf`, `reference_notes` (todos `blank=True`). `history = HistoricalRecords()` (django-simple-history, independente do histórico de `Client`/`Location`). Usado via `OneToOneField(Address, on_delete=PROTECT)` em `Client.fiscal_address` e `Location.address`.

### Quem herda `TimeStampedModel`/`SoftDeleteModel`

| App | Model | Bases |
|---|---|---|
| catalog | `Category`, `EquipmentModel` | `TimeStampedModel, SoftDeleteModel` |
| crm | `CommercialSource`, `OpportunityStage`, `LossReason` | `TimeStampedModel, SoftDeleteModel` |
| crm | `Opportunity` | só `TimeStampedModel` (sem fluxo de excluir/desativar) |
| maintenance | `Maintenance`, `Cleaning` | `TimeStampedModel, SoftDeleteModel` |
| operations | `Location` | `TimeStampedModel, SoftDeleteModel` |
| clients | `Client` | `TimeStampedModel, SoftDeleteModel` |
| equipment | `Equipment` | `TimeStampedModel, SoftDeleteModel` |
| accounts | `RoleProfile` | só `TimeStampedModel` |
| accounts | `User` | nenhuma — usa o `is_active` nativo de `AbstractUser` em vez de duplicar `SoftDeleteModel` |

## Services

Arquivo: `apps/core/services.py`.

- **`AddressData`** (dataclass): `cep, logradouro, numero, complemento, bairro, cidade, uf, reference_notes`. `is_blank()` — `True` se todos os campos (exceto `reference_notes`) estiverem vazios.
- **`create_address(data) -> Address | None`**: retorna `None` se `data` for `None`/vazio; senão cria uma linha nova. **Nunca reaproveita** uma linha existente, mesmo com valores idênticos — cada chamada cria um `Address` novo (regra de negócio explícita).
- **`update_address(*, address, data, change_reason=...) -> Address`**: atualiza os 7 campos in-place e salva (`_change_reason` para o django-simple-history). Nunca exclui+recria.
- Chamado por `apps.clients.services` (endereço fiscal) e `apps.operations.services` (endereço operacional de `Location`).

### `hard_delete.py`

- `HardDeleteBlocked(Exception)` — levantada quando um `on_delete=PROTECT` aponta para um registro compartilhado.
- `HardDeleteAuthorizationError(PermissionError)` — levantada se `actor` não é `is_superuser` (defesa em profundidade — a view já bloqueia antes).
- `HardDeleteImpact` (`@dataclass(frozen=True)`): `target_label`, `dependents: dict[str, int]`, `total_dependents`.
- `describe_protected_error(exc, *, subject)`: agrupa `exc.protected_objects` por `verbose_name_plural`, monta mensagem legível em vez do traceback cru do Django.
- Usado por `apps.clients.services.hard_delete_client`, `apps.equipment.services.hard_delete_equipment`, `apps.crm.services.hard_delete_opportunity` — cada um verifica `actor.is_superuser` dentro do próprio service, não só na view.

### `submission.py` — `SubmissionGuard(scope)`

- `issue(request)`: expurga tokens consumidos com mais de 7 dias, gera `uuid4().hex`, grava na sessão.
- `pending(request)`: retorna o token já pendente ou emite um novo (usado em re-renderizações que não consomem, ex. "Consultar CNPJ").
- `consume_if_valid(request)`: compara o token do POST com o da sessão; tenta `ConsumedSubmissionToken.objects.create(...)` dentro de `transaction.atomic()` — o índice `UNIQUE` do banco decide a corrida entre requisições concorrentes (não a sessão, que não é read-modify-write atômica entre requests). A primeira a inserir prossegue; as demais recebem `IntegrityError` → `False`.
- Nasceu no cadastro de cliente e foi generalizado; usado hoje por `clients`, `operations`, `maintenance`, `equipment`.

### `nav.py`

Função pura `active_nav_group(view_name, app_name)` — sem request, sem DB. Retorna `"crm"`, `"operacao"`, `"cadastros"`, `"configuracoes"` ou `None`, com base em dicionários/sets estáticos de nomes de view. Nunca decide se um item deve *aparecer* (isso é `RoleRequiredMixin`/`perms.*` nas views/templates) — só qual grupo deve estar aberto/destacado. Usada tanto pela sidebar desktop quanto pelo drawer mobile, garantindo que nunca divirjam.

### `context_processors.py`

`commercial_links(request)` injeta em todo template um dict com 5 chaves lidas de `settings` (`LOCUS_INSTAGRAM_URL`, `LOCUS_SITE_URL`, `LOCUS_WHATSAPP_URL`, `LOCUS_ORCAMENTO_URL`, `LOCUS_EQUIPAMENTOS_URL`). Cada valor pode ser string vazia; é responsabilidade do template não renderizar o CTA quando vazio. Consumido só por `templates/equipment/detail_public.html` e `templates/base_public.html`.

## Forms

- **`AddressForm(ModelForm)`** — os 8 campos de `Address`, labels em pt-BR, `class="field-input"` em todos os widgets. Reusado por `clients` (fiscal) e `operations` (operacional).
- **`HardDeleteConfirmForm(Form)`** — campo único `confirm` (BooleanField, required), usado pelas 3 telas de hard delete do sistema (Cliente/Equipamento/Oportunidade).

## Views

`apps/core/views.py` está vazio (boilerplate do `startapp`). Nenhuma view real neste app.

## URLs

`apps/core` **não tem `urls.py`**. Como não tem views próprias, não há nada a expor; `config/urls.py` não referencia `core`. O app é consumido inteiramente como biblioteca (models, services, forms, templatetags).

## Permissions

Não aplicável — sem views, sem rotas. As funções de `hard_delete.py` exigem `actor.is_superuser`, mas quem aplica isso são as views/services dos apps que consomem `core`.

## Templates

`apps/core` não tem diretório de templates próprio. Os templates-base do projeto ficam em `/templates/` na raiz:

- `templates/base.html` — base para páginas internas autenticadas (sidebar desktop + drawer mobile, consomem `{% active_nav_group %}`).
- `templates/base_public.html` — base da landing pública (usa `commercial_links` do context processor).

### Template tags (`apps/core/templatetags/`)

- **`icons.py`** — `{% icon name size="normal" extra_class="" %}` e `{% brand_icon name %}`. ~40 ícones vendorizados (Heroicons "outline", MIT License) copiados como paths SVG — sem pacote npm, sem CDN de ícones. Nome desconhecido → comentário HTML escapado, nunca exceção nem HTML não escapado. 2 tamanhos: `normal` (20px), `compact` (16px).
- **`nav.py`** — `{% active_nav_group as current_group %}`, delega a `apps.core.nav.active_nav_group`.
- **`currency.py`** — filtro `{{ valor|brl }}` / `format_brl(value)`. Formata `Decimal` como `"R$ 1.234,56"`; `None`/`""` → `"—"`; nunca converte para `float`, nunca levanta exceção.
- **`pagination_tags.py`** — `{% url_replace request field value %}`, sobrescreve só um parâmetro da querystring atual, preservando os demais filtros.

## JavaScript

Nenhum JS específico do app `core`. `templates/base.html` carrega htmx via CDN e Tailwind via CDN (sem pipeline de build de frontend). JS específico por feature fica em `static/crm/*.js` e `static/qrcodes/*.js`.

## Dependências

`apps.core` importa apenas de Django e de `django-simple-history` (`HistoricalRecords`). **Não importa nenhum outro app do projeto** — é a base, sem dependências internas.

## Quem chama apps.core

Todos os 8 apps de domínio (`accounts`, `catalog`, `clients`, `crm`, `equipment`, `maintenance`, `operations` — e `qrcodes`/`dashboard` indiretamente via os demais) importam de `apps.core`, além de `config/settings/base.py` (`INSTALLED_APPS`, context processor).

## Testes

12 arquivos em `apps/core/tests/` (128 testes coletados no total):

- `test_address.py` — histórico de edição, `PROTECT` contra exclusão referenciada, `create_address()` (`None`/vazio, duas chamadas idênticas criam linhas independentes).
- `test_desktop_sidebar.py` — 4 grupos em acordeão, matriz de permissões por role.
- `test_hard_delete.py` — `describe_protected_error`, `HardDeleteImpact.total_dependents`.
- `test_html_structure_validation.py` + `html_validation.py` (utilitário, não teste — parser HTML puro, deliberadamente sem BeautifulSoup/lxml, que "repara" HTML quebrado em vez de denunciar).
- `test_i18n_encoding_audit.py` — auditoria de idioma/UTF-8/pt-BR extensa (430 linhas).
- `test_mobile_menu_drawer.py` — drawer mobile, mesma matriz de permissões da sidebar.
- `test_nav.py` — testes puros de `active_nav_group`.
- `test_navigation_redundancy_audit.py` — regressão de navegação redundante removida.
- `test_no_leaked_template_comments.py` — regressão de comentário Django multi-linha vazando como texto literal.
- `test_public_login_cta.py` — CTA "Entrar" na landing pública.
- **`apps/core/test_icons_templatetag.py`** — solto na raiz do app, fora de `tests/`. Ver Pontos importantes.

## Pontos importantes

- **`SoftDeleteModel` e `hard_delete.py` coexistem por design**: soft delete continua sendo a via de exclusão normal e universal para todos os usuários; hard delete é uma capacidade adicional, muito mais restrita (só `is_superuser` puro, nunca `Role.ADMIN` nem uma `Permission` concedível), criada porque o sistema ainda está em desenvolvimento e precisa limpar dados de teste sem poluir o banco. Nenhuma `Permission` de hard delete foi adicionada ao catálogo de propósito.
- **`SoftDeleteModel.is_active` não filtra nada automaticamente** — cada app decide explicitamente na sua queryset/view.
- **`Opportunity` (CRM) não herda `SoftDeleteModel`** e **`accounts.User` também não** (usa o `is_active` nativo de `AbstractUser`) — duas exceções deliberadas e documentadas no próprio código.
- **Race condition histórica documentada e corrigida em `submission.py`**: a proteção original (token só em sessão) tinha uma race condition real com dois POSTs quase simultâneos; a correção move a autoridade de consumo para o índice `UNIQUE` do banco.
- **`apps/core/test_icons_templatetag.py` fora de `apps/core/tests/`**: é coletado normalmente pelo pytest (confirmado por execução real — `pytest.ini` usa `python_files = tests.py test_*.py *_tests.py` sem restrição de diretório), mas é a única inconsistência de organização de testes em todo o repositório. Não há comentário explicando a exceção; provavelmente um artefato de quando `apps/core/tests/` ainda não existia como pacote. Não foi corrigido nesta rodada de limpeza por não ser código morto nem risco funcional — é só uma observação para quem for mexer no app.
- Nenhum TODO/FIXME encontrado no código deste app.
