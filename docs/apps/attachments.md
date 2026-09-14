# apps.attachments

## Objetivo

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

## JavaScript

Nenhum.

## Dependências

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
