# apps.attachments

## Objetivo

<<<<<<< HEAD
Armazenamento genérico de arquivos anexados a qualquer objeto do sistema — implementado em 14/09/2026 como pré-requisito da aba "Anexos" do Hub da Oportunidade (`apps.crm`), que precisa de um lugar real para guardar os PDFs de Proposta Comercial/Contrato. Até então o app era um esqueleto vazio (registrado em `INSTALLED_APPS` mas sem nenhum model/migration real) — ver git history para o estado anterior.

Desenho deliberadamente pequeno: só o suficiente para o consumidor real de hoje (CRM) funcionar, sem inventar recursos não pedidos (galeria, versionamento de arquivo, aprovação, tela de upload manual).

## Models

`Attachment` (`apps/attachments/models.py`):

- `content_type`/`object_id`/`content_object` — `GenericForeignKey`, não uma FK fixa a um único model: o nome do app e o propósito ("fotos/anexos") sempre previram mais de um consumidor (equipamento, cliente, oportunidade...); uma FK fixa exigiria uma segunda tabela quando o próximo consumidor aparecesse.
- `category` — `AttachmentCategory` (`TextChoices`: `ORCAMENTO_PROPOSTA`, `CONTRATO`, `OUTRO`). Pequeno e fechado (não uma entidade configurável como `CommercialSource`) — a especificação que motivou a implementação já lista exatamente essas duas categorias.
- `source` — `AttachmentSource` (`TextChoices`: `SYSTEM`, `USER`). Hoje só `SYSTEM` é usado (PDFs gerados pelo próprio sistema); `USER` existe para um futuro upload manual.
- `file` — `FileField`, `upload_to` dinâmico (`attachments/<app_label>/<model>/<object_id>/<filename>`), namespaced por dono sem o app conhecer nada sobre o consumidor.
- `original_filename`, `description`, `created_by` (`PROTECT`), `created_at`.
- Sem soft delete/histórico/edição — nenhum fluxo de editar/excluir anexo foi pedido; um anexo substituído é um novo `Attachment`, o antigo continua existindo (mesmo espírito de imutabilidade de `Movement`/`StatusHistory`).
- `Meta.permissions`: `view_attachments` (declarada, mas **não** adicionada a `apps.accounts.permission_catalog.PERMISSION_CATALOG` nesta rodada — ver "Permissions" abaixo).

Migration: `0001_initial.py`.

## Services

`apps/attachments/services.py` — único caminho suportado para criar um `Attachment`:

- `create_attachment(NewAttachmentData)` — grava o arquivo (`FileField.save()`) e cria a linha. Valida `category`/`source` contra os `TextChoices`.
- `attachments_for(content_object)` — leitura simples (sem paginação — volume baixo por objeto) de todos os anexos de um objeto, mais recentes primeiro.

Nenhum `update_attachment()`/`delete_attachment()` — ver "Models" acima.

## Forms

Não existe `forms.py` — nenhuma tela própria de upload/edição de anexo nesta rodada; anexos só nascem via `apps.crm.services` (emissão de proposta/geração de contrato).

## Views

Não existe `views.py` próprio de `apps.attachments`. O download autenticado vive em `apps.crm.views.AttachmentDownloadView` (não aqui) — deliberado: só o app que sabe validar "este anexo pertence a ESTE objeto que o usuário tem permissão de ver" pode servir o arquivo com segurança; um endpoint genérico `attachments:download` serviria qualquer anexo de qualquer objeto para quem quer que tivesse `attachments.view_attachments`, sem o contexto de permissão do objeto-dono.

## URLs

Não existe `urls.py` próprio — a rota de download vive em `apps.crm.urls` (`crm:attachment_download`).

## Permissions

`Attachment.Meta.permissions` declara `view_attachments`, mas ela **não** foi adicionada a `PERMISSION_CATALOG` nesta rodada (decisão documentada no relatório final de Produtos e Serviços): hoje o único consumidor real é a aba Anexos do Hub do CRM, gated por `crm.view_opportunities` (a mesma permissão que já protege o resto do Hub) — adicionar uma segunda Permission redundante violaria "evitar excesso de permissions" (especificação de Produtos e Serviços, seção 83). Se um segundo consumidor de `apps.attachments` aparecer no futuro (ex.: fotos de equipamento) com uma audiência de leitura DIFERENTE da do dono do anexo, revisitar essa decisão e então adicionar `attachments.view_attachments` ao catálogo.

## Templates

Nenhum próprio — a listagem/download de anexos é renderizada dentro de `templates/crm/opportunity_detail.html` (aba "Anexos").
=======
`apps.attachments` está registrado em `INSTALLED_APPS` (`config/settings/base.py`) mas é hoje um **esqueleto vazio** — reservado para uma futura funcionalidade de fotos/anexos de equipamento (prevista na tela de cadastro, mas não é critério de aceite explícito da especificação original). Não é código morto no sentido de "sobrou de algo que existiu": nunca foi implementado.

## Models

`apps/attachments/models.py` contém só o boilerplate do `startapp` (`from django.db import models` + comentário). **Nenhum model, nenhuma migration real** (`migrations/` só tem `__init__.py`).

## Services

Não existe `services.py`.

## Forms

Não existe `forms.py`.

## Views

`apps/attachments/views.py` é boilerplate vazio (`from django.shortcuts import render`).

## URLs

Não existe `urls.py`. Não há rota nenhuma para este app.

## Permissions

Não aplicável — sem views, sem models.

## Templates

Nenhum.
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

## JavaScript

Nenhum.

## Dependências

<<<<<<< HEAD
`django.contrib.contenttypes` (`GenericForeignKey`), `apps.accounts.models.User`.

## Quem chama apps.attachments

`apps.crm.services` (`issue_proposal()`/`generate_contract()`, via `create_attachment()`) e `apps.crm.views` (`AttachmentDownloadView`, `OpportunityDetailView` via `attachments_for()`).

## O que apps.attachments chama

`apps.accounts.models.User` (FK `created_by`), `django.contrib.contenttypes`.

## Testes

`apps/attachments/tests.py` — criação via `content_object` genérico, filtro por objeto (`attachments_for`), rejeição de categoria inválida, ausência deliberada de `update_attachment`. Cobertura do fluxo real (emissão de proposta cria o Anexo certo) fica em `apps.crm.tests.test_proposal_services`.

## Migrations

`0001_initial.py` — cria `Attachment` (14/09/2026).

## Pontos importantes

- **`GenericForeignKey`, não uma FK fixa** — decisão deliberada para não precisar de uma segunda tabela quando o próximo consumidor aparecer (fotos de equipamento, anexos de cliente, etc.).
- **Sem storage paralelo**: a especificação de Produtos e Serviços exigia explicitamente "não criar storage paralelo" — como não havia NENHUM módulo de anexos real antes desta rodada (apesar do nome sugerir o contrário), implementar aqui é a única forma de cumprir essa regra sem inventar uma segunda arquitetura dentro de `apps.crm`.
- **Download sempre autenticado** (`crm:attachment_download`), nunca um link `/media/` direto — os PDFs contêm dados comerciais sensíveis (endereço/documento do cliente, valores), e o Nginx/WhiteNoise que serve `/media/` em produção não aplica nenhuma checagem de permissão do Django.
=======
Nenhuma — o app não importa nada além do boilerplate padrão do Django.

## Quem chama apps.attachments

Nenhum outro app importa ou referencia `apps.attachments` — confirmado por busca textual em todo o projeto. Em particular, **não** tem FK para `Equipment` apesar do nome sugerir "anexos de equipamento" — a expectativa de que `apps.equipment`/`apps.crm` dependessem deste app não se confirma no código atual (a aba "Arquivos" da ficha de oportunidade do CRM, por exemplo, foi deliberadamente omitida por causa disso).

## O que apps.attachments chama

Nada.

## Testes

`apps/attachments/tests.py` é o stub padrão do `startapp` (`# Create your tests here.`), sem nenhum teste real.

## Migrations

Nenhuma.

## Pontos importantes

- **Mantido no repositório propositalmente**, não removido durante a limpeza desta rodada: é um placeholder para uma feature futura já prevista no roadmap ("fotos/anexos de equipamento"), não um resíduo de algo que existiu e foi abandonado. Removê-lo exigiria voltar a criá-lo do zero (registro em `INSTALLED_APPS`, `AppConfig`, etc.) no dia em que a feature for priorizada.
- Se/quando esta funcionalidade for implementada, o padrão esperado pelo resto do projeto é: um `services.py` como único caminho de escrita, permissões via o catálogo aditivo (`apps.accounts.permission_catalog`, seguindo o padrão de `apps.crm`, já que é um app novo) ou via `RoleRequiredMixin`/`CAN_*` (seguindo o padrão legado da maioria dos apps) — a escolha entre os dois sistemas deve ser deliberada, não incidental (ver `docs/permissions.md`).
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7
