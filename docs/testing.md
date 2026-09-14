# Testes

## Como rodar — `pytest`, não `manage.py test`

**Sempre use `pytest`.** `pytest.ini` já aponta `DJANGO_SETTINGS_MODULE = config.settings.test`, o settings correto para a suíte.

```bash
python -m pytest              # tudo
python -m pytest apps/crm     # só um app
python -m pytest -k "hard_delete"   # por nome
```

`python manage.py test` usa `config.settings.dev` por padrão — que tem `AXES_ENABLED=True`. O atalho `self.client.login(...)`, usado em praticamente todo teste do projeto só para autenticar rapidamente antes de testar outra coisa, **não passa `request`** para `axes.backends.AxesStandaloneBackend.authenticate()`, e o django-axes precisa desse `request` para funcionar. Rodar com `manage.py test` produz uma onda de falhas falsas e desconexas em testes que nada têm a ver com login/segurança — não é um "modo mais rigoroso", é o runner errado para este projeto. `config/settings/test.py` desliga `AXES_ENABLED` justamente por isso; o único teste que precisa dele ligado (`apps/accounts/tests/test_axes_lockout.py`) o reativa localmente via `override_settings` e usa requisições HTTP reais (via `Client.post()` contra a view de login, que passa `request` corretamente através do `AuthenticationForm`) em vez de `client.login()`.

> Esta confusão já aconteceu neste projeto: relatórios anteriores chegaram a caracterizar falhas de `manage.py test` como "problemas de infraestrutura pré-existentes" antes de se descobrir que o runner usado estava errado. Registrado aqui para nunca mais acontecer.

## Estado atual da suíte (última execução completa, 14/09/2026 — pós Produtos e Serviços)

```
1163 passed, 4 failed em ~376s (~6min)
```

A suíte cresceu em +65 testes desde a rodada anterior (`apps/crm/tests/test_proposal_services.py` — 44, `apps/crm/tests/test_proposal_views.py` — 17, mais os 4 novos de `apps/attachments/tests.py`), e os 2 arquivos de `apps/accounts`/`apps/crm` tocados pela mudança de contagem de permissões foram atualizados (ver `docs/permissions.md`).

Dos 4 testes que falham numa execução "suja" (rodando a suíte inteira sem isolar `MEDIA_ROOT` primeiro), **3 são pré-existentes e sem relação com Produtos e Serviços**, e **1 foi introduzido e corrigido nesta mesma rodada**:

1. **`apps/core/tests/test_i18n_encoding_audit.py::MojibakeRegressionTest::test_no_mojibake_in_tracked_repository_files`** — pré-existente, bug de auto-referência no próprio teste (varre todo arquivo rastreado procurando os próprios `MOJIBAKE_MARKERS`, sem excluir a si mesmo). Não indica mojibake real.
2. **`apps/catalog/tests/test_model_images.py::ModelImageUrlTemplateTagTest::test_model_with_no_real_file_on_disk_resolves_to_placeholder_url`** — pré-existente (já documentado antes de Produtos e Serviços): a premissa do teste ("AQCP" não tem foto real) deixou de valer porque `static/images/equipment/aqcp.webp` já existe em disco (asset enviado pela Locus depois do teste ter sido escrito). Comportamento do sistema correto; teste desatualizado em relação ao asset — decisão de conteúdo de quem mantém a suíte, não desta rodada.
3. **`apps/equipment/tests/test_public_landing.py::PublicLandingBasicContentTest::test_image_src_points_to_an_existing_static_file`** — mesma causa raiz do item 2 (`9pro.webp`).
4. **`apps/attachments/tests.py::CreateAttachmentTest::test_create_attachment_links_to_generic_object`** — **causa raiz identificada e corrigida nesta rodada**: `MEDIA_ROOT` não era isolado entre execuções de teste (apontava para o `media/` real do projeto). Testes manuais de smoke feitos durante o desenvolvimento desta feature (via `manage.py shell`, antes da suíte pytest existir) já haviam gravado `attachments/crm/opportunity/3/teste.pdf` em disco; a segunda gravação do mesmo nome pelo `FileStorage` do Django gera um sufixo aleatório para não sobrescrever, quebrando a asserção `attachment.file.name.endswith("teste.pdf")`. **Corrigido** adicionando `MEDIA_ROOT = tempfile.mkdtemp(...)` em `config/settings/test.py` — cada execução da suíte agora grava em um diretório novo e descartável, nunca no `media/` real. Ver "Isolamento de MEDIA_ROOT nos testes" abaixo. Reexecutado isoladamente após a correção: `apps/attachments apps/crm/tests/test_proposal_services.py apps/crm/tests/test_proposal_views.py` → 65 passed.

Nenhum dos itens 1–3 foi alterado nesta rodada, em respeito à regra "não apagar/alterar teste sem antes confirmar que o comportamento realmente mudou".

## Isolamento de MEDIA_ROOT nos testes (14/09/2026)

`config/settings/test.py` agora define `MEDIA_ROOT = tempfile.mkdtemp(prefix="locus_test_media_")`. Motivo: `apps.attachments` é o primeiro consumidor real de `FileField` do projeto (usado por `apps.crm` para gravar os PDFs de Proposta/Contrato gerados em `issue_proposal()`/`generate_contract()`); sem um `MEDIA_ROOT` isolado, arquivos gravados por uma execução da suíte (ou por testes manuais fora dela) persistem em disco e podem colidir com o nome de arquivo esperado pela execução seguinte, produzindo falhas não-determinísticas que nada têm a ver com o código sendo testado. O diretório temporário é descartável — não é limpo automaticamente ao final da suíte (o SO libera `/tmp` eventualmente), mas nunca é o `media/` real do projeto.

## Configuração

- `pytest.ini` — `DJANGO_SETTINGS_MODULE = config.settings.test`; `python_files = tests.py test_*.py *_tests.py` (coleta em **qualquer diretório**, não só pacotes `tests/` — é por isso que `apps/core/test_icons_templatetag.py`, solto na raiz do app, é coletado normalmente; ver `docs/apps/core.md`).
- `config/settings/test.py` herda `dev.py` com `AXES_ENABLED=False` (ver acima).
- Banco: sempre PostgreSQL real — nenhum teste roda contra SQLite (a geração atômica de patrimônio depende de `SELECT FOR UPDATE`, que o SQLite não implementa de forma confiável).

## Testes de concorrência real

Vários fluxos críticos têm cobertura de concorrência genuína via `TransactionTestCase` + `threading` (não só teste unitário da lógica sequencial):

| Teste | O que valida |
|---|---|
| `apps/equipment/tests/test_patrimonio_generation.py` | N cadastros concorrentes do mesmo modelo geram `model_sequence` únicos/sequenciais/sem lacunas |
| `apps/operations/tests/test_movement_concurrency.py` | Duas `INSTALACAO` simultâneas no mesmo equipamento: exatamente 1 sucesso, 1 `ValueError` |
| `apps/operations/tests/test_double_submit_concurrency.py` | Double-submit com o MESMO token de sessão sob concorrência: o índice `UNIQUE` do banco decide, nunca 2 criações |
| `apps/maintenance/tests/test_maintenance_movement_concurrency.py` | Abrir manutenção vs. instalar simultaneamente; fechar manutenção vs. instalar simultaneamente |
| `apps/maintenance/tests/test_maintenance_movement_vinculos_auditoria.py` | Corrida por reclamar o mesmo `departure_movement` duas vezes |
| `apps/crm/tests/test_stage_change_concurrency.py` | Duas mudanças de etapa simultâneas na mesma oportunidade nunca produzem estado incoerente |

`NumberingCounter` (`apps.crm`, base da numeração de Proposta/Contrato) segue o mesmo padrão de lock pessimista de `EquipmentModel.last_sequence`, mas **não** ganhou um teste de concorrência real dedicado nesta rodada (a spec não exigiu explicitamente e o padrão já está coberto estruturalmente pelos testes de `test_patrimonio_generation.py` sobre o mesmo mecanismo) — sinalizado aqui como candidato natural a um teste `TransactionTestCase`+`threading` futuro, seguindo o modelo já existente.

Estes testes só são confiáveis contra PostgreSQL real — documentado explicitamente nos próprios docstrings (SQLite sem `SELECT FOR UPDATE` confiável não reproduz a corrida).

## Testes de orçamento de queries (N+1)

Vários apps têm testes dedicados que comparam a contagem de queries entre um cenário com poucos registros e um com muitos, via `django.test.utils.CaptureQueriesContext`, para provar ausência de N+1:

- `apps/equipment/tests/test_equipment_grouped_listing.py` — listagem agrupada por modelo (1 query fixa).
- `apps/dashboard/tests/test_home_view.py::DashboardHomeQueryBudgetTest` — Home operacional (5 queries fixas).
- `apps/maintenance/tests/test_maintenance_lists_filters_pagination_queries.py` — 3 testes dedicados (listas + resumo na ficha).

## django-axes (força bruta)

`AXES_ENABLED=False` em `test.py` por padrão. Só `apps/accounts/tests/test_axes_lockout.py` o reativa (`override_settings(AXES_ENABLED=True)`) e usa requisições HTTP reais (`self.client.post(reverse("accounts:login"), ...)`), nunca `self.client.login()`, precisamente porque é o único caminho que passa `request` corretamente para o backend do axes.

## Organização por app

Cada app de domínio tem seu próprio pacote `tests/` (exceto a exceção pontual documentada em `docs/apps/core.md`). Ver a seção "Testes" de cada `docs/apps/<app>.md` para a lista completa de arquivos e o que cada um cobre. Volume aproximado por app (linhas de teste): `equipment` e `operations` são os mais extensos (~2200+ linhas cada), refletindo a complexidade de concorrência/imutabilidade desses dois domínios.

## Convenções observadas na suíte

- Testes de serviço isolam a camada de negócio (chamam `services.*` diretamente, sem HTTP).
- Testes de view cobrem a matriz de permissões (os 4 perfis + anônimo) como padrão mínimo para toda tela nova.
- Testes de segurança dedicados (`test_security.py` em `crm`, por exemplo) cobrem IDOR, CSRF, e integridade a nível de banco (`CheckConstraint`) além da UI.
- HTTP externo é sempre mockado nos testes (`apps/clients/tests/test_lookup_service.py` mocka `httpx.get` para a BrasilAPI) — a suíte nunca depende de rede real.
- "Não apagar teste só porque testa comportamento antigo, sem confirmar que o comportamento deixou de existir" é uma regra seguida ativamente neste projeto (ver os 2 testes de imagem descritos acima, que ficaram desatualizados em relação a um asset, não ao código).
