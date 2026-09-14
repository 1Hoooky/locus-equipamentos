# apps.crm

## Objetivo

<<<<<<< HEAD
`apps.crm` é o funil de vendas/CRM do LocusHub: gerencia `Opportunity` desde a criação até o fechamento (ganho ou perdido), organizadas num Kanban por `OpportunityStage` configurável. Reutiliza `apps.clients.models.Client` como fonte oficial de cliente (nunca cópia, nunca escreve). Inclui registro de atividades comerciais (`CommercialActivity`), histórico estruturado de mudança de etapa (`OpportunityStageChange`) e configuração de Origem/Etapa/Motivo de perda.

Desde 14/09/2026 (implementação "Produtos e Serviços"), também inclui a composição comercial completa de uma negociação: `Proposal`/`ProposalVersion`/`ProposalItem`/`Contract` — versionamento, snapshots, cálculo financeiro, emissão de PDF (Proposta Comercial/Contrato) e aceite (que fecha a `Opportunity` via `change_opportunity_stage()`, nunca um caminho paralelo). Agenda central, dashboard, financeiro, comissão, automações, integrações externas e **tabela de preços** (`PriceTable`) ficam para etapas futuras — ver seção "Preparação para PriceTable" no relatório final.
=======
`apps.crm` é o funil de vendas/CRM do LocusHub: gerencia `Opportunity` desde a criação até o fechamento (ganho ou perdido), organizadas num Kanban por `OpportunityStage` configurável. Reutiliza `apps.clients.models.Client` como fonte oficial de cliente (nunca cópia, nunca escreve). Inclui registro de atividades comerciais (`CommercialActivity`), histórico estruturado de mudança de etapa (`OpportunityStageChange`) e configuração de Origem/Etapa/Motivo de perda. Propostas, contratos, agenda central, dashboard, financeiro, comissão, automações e integrações externas ficam para etapas futuras.
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

## Models

Arquivo: `apps/crm/models.py`.

- `CommercialSource`, `OpportunityStage` (com `is_won`/`is_lost`, `CheckConstraint` impede ambos simultâneos), `LossReason` — todos `TimeStampedModel, SoftDeleteModel`, configuráveis (não `TextChoices`).
- `BusinessType` (TextChoices, fixo): LOCACAO, VENDA, SERVICO.
- **`Opportunity(TimeStampedModel)`** — **não** `SoftDeleteModel** (sem fluxo de excluir/desativar, só hard delete). `client` (FK, PROTECT), `title`, `owner` (FK User, PROTECT), `source` (FK, PROTECT), `business_type`, `stage` (FK, PROTECT), `expected_close_date`, `estimated_value`, `notes`, `loss_reason` (FK, PROTECT, nullable), `loss_notes`, `won_at`, `lost_at`, `closed_value`, `created_by` (PROTECT). `history = HistoricalRecords()`. `CheckConstraint`s: não ganho+perdido simultâneo, valores ≥0. `Meta.permissions`: `view_opportunities`, `add_opportunities`, `change_opportunities`, `change_opportunity_stage`.
- **`OpportunityStageChange`** — histórico estruturado append-only: `opportunity` (CASCADE), `from_stage`/`to_stage` (PROTECT), `changed_by` (PROTECT), `changed_at`, `reason`.
- `ActivityType` (TextChoices). **`CommercialActivity`** — `opportunity` (CASCADE), `activity_type`, `description`, `occurred_at`, `scheduled_for` (alimentará futura Agenda Central), `completed_at`, `created_by` (PROTECT). Sem histórico (sem fluxo de edição/exclusão). `Meta.permissions`: `view_commercial_activities`, `add_commercial_activities`.

<<<<<<< HEAD
### Produtos e Serviços / Proposta Comercial (14/09/2026)

- `NumberingCounter` — contador dedicado (`key` único + `last_value`), lido/incrementado sempre sob `select_for_update()` em `_next_document_number()` (`services.py`) — mesmo padrão já usado por `EquipmentModel.last_sequence` (`apps.equipment`), nunca `COUNT(*)+1`. Hoje só duas `key`s existem em uso: `"proposal"` (prefixo `PROP-`) e `"contract"` (prefixo `CONTR-`).
- `PaymentMethod` (TextChoices, fixo): PIX, BOLETO, CARTAO, TRANSFERENCIA, OUTRO (com `payment_method_other` de texto livre em `ProposalVersion` quando `OUTRO`).
- `ProposalVersionStatus` (TextChoices, fixo): DRAFT, ISSUED, ACCEPTED — nunca um quarto estado "recusado"/"perdido" (perda continua sendo só de `Opportunity`, via `change_opportunity_stage()`).
- **`Proposal(TimeStampedModel)`** — `opportunity` (FK CASCADE — apagar a oportunidade apaga suas propostas, mas `Contract.proposal_version` é PROTECT, então uma proposta com contrato emitido bloqueia o hard delete via a mesma engrenagem de `describe_protected_error`/`HardDeleteBlocked` já existente), `number` (único, `editable=False`, gerado via `NumberingCounter`), `created_by` (PROTECT). **Deliberadamente sem campo `status` próprio** — a propriedade `display_status` sempre deriva de `latest_version.status`; guardar um segundo campo de status em `Proposal` criaria duas fontes de verdade que podem divergir (a mesma armadilha que a especificação alerta em outro contexto, seção 75) sempre que uma nova versão for criada sem sincronizar os dois. `Meta.permissions`: `issue_proposal_documents`.
- **`ProposalVersion(TimeStampedModel)`** — `proposal` (FK CASCADE), `version_number`, `status` (`ProposalVersionStatus`), `price_table_label` (texto livre — único "gancho" para a futura `PriceTable`, não uma FK, para não acoplar a nenhum desenho futuro ainda não aprovado). Campos de condição/logística: `payment_method`/`payment_method_other`/`payment_condition`, `contracted_start_date`/`contracted_end_date`, `expected_delivery_date`/`expected_delivery_time`, `expected_pickup_date`/`expected_pickup_time`, `delivery_location` (FK `operations.Location`, PROTECT, opcional). Financeiro (todos `Decimal`, nunca float): `subtotal`, `general_discount`, `interest_amount`, `freight_amount`, `total` — todos calculados exclusivamente por `calculate_proposal_version()` (`services.py`), nunca escritos à mão em view/form. Texto livre: `special_clauses`, `payment_info_notes`, `general_notes`. Snapshot de cliente/empresa/vendedor (`client_name_snapshot`, `client_document_snapshot`, `client_contact_snapshot`, `client_phone_snapshot`, `client_email_snapshot`, `client_address_snapshot`, `company_name_snapshot`, `company_document_snapshot`, `company_address_snapshot`, `company_phone_snapshot`, `company_email_snapshot`, `seller_snapshot`) — preenchidos uma única vez em `issue_proposal()`, nunca recalculados depois (mesmo que o cliente/`CompanyProfile`/catálogo mudem). `issued_at`/`issued_by`/`accepted_at`/`accepted_by`. `Meta`: `UniqueConstraint(proposal, version_number)`; `CheckConstraint`s garantindo subtotal/total/desconto/juros/frete ≥ 0 (nunca total negativo, nem por bug de aplicação); `Meta.permissions`: `generate_contract`. Propriedade `is_editable` = `status == DRAFT` — é o único ponto que decide se a UI mostra campos editáveis ou só leitura.
- **`ProposalItem`** — `proposal_version` (FK CASCADE), `equipment_model` (FK `catalog.EquipmentModel`, **PROTECT** — nunca uma FK a `Equipment`/patrimônio físico: a composição da proposta é sempre por modelo/quantidade, nunca por número de série específico, conforme a especificação seção ~15-20), `description_snapshot` (congela a descrição do modelo no momento em que o item foi adicionado), `quantity` (`PositiveIntegerField`), `unit_price`, `item_discount_percent`, `line_total` (calculado, nunca editado direto), `notes`, `order`. `CheckConstraint`s: quantity > 0, unit_price ≥ 0, desconto entre 0 e 100, line_total ≥ 0.
- **`Contract`** — `proposal_version` (FK **PROTECT** — um contrato nunca é apagado em cascata junto da proposta/versão, é a trava que bloqueia hard delete de oportunidades com contrato emitido), `number` (único, via `NumberingCounter`), `created_by` (PROTECT), `created_at`, `legal_text_is_placeholder` (`BooleanField`, default `True`) — documenta explicitamente que o texto jurídico usado no PDF é placeholder (a especificação seção 106 proíbe inventar cláusulas legais reais); o PDF do contrato exibe um aviso visível disso enquanto o campo for `True`. Sem model de "aceite de contrato" separado — aceite é sempre de `ProposalVersion` (ver Services), o Contrato é só o documento gerado a partir de uma versão já emitida.

=======
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7
## Services

Arquivo: `apps/crm/services.py`.

- `eligible_owner_queryset()` — usuários ativos com `is_superuser` ou permission `crm.add_opportunities`.
- `create_opportunity(data)` — `@transaction.atomic`; rejeita etapa ganha/perdida/inativa; cria `Opportunity` + 1ª linha de `OpportunityStageChange`.
- `update_opportunity(*, opportunity, data, changed_by)` — só campos cadastrais; nunca `client`/`stage`/campos de fechamento.
- **`change_opportunity_stage(*, opportunity_id, new_stage, changed_by, reason="", loss_reason=None, loss_notes="", closed_value=None)`** — `@transaction.atomic` + `select_for_update()` (testado com concorrência real). Único caminho de escrita de `stage`/`won_at`/`lost_at`/`loss_reason`/`closed_value`. Regras: rejeita mesma etapa/etapa inativa; ganho → seta `won_at`, limpa perda; perda → exige `loss_reason`; etapa intermediária → reabre, limpa todo estado de fechamento. Sempre cria `OpportunityStageChange`.
- `create_activity(data)` — valida `activity_type`.
<<<<<<< HEAD
- `preview_opportunity_hard_delete()` / `hard_delete_opportunity(*, opportunity_id, actor)` — `select_for_update()`, exige `actor.is_superuser`, cascade automático de stage_changes/activities. Desde 14/09/2026 a prévia também soma "propostas (com versões e itens)" como dependente; se alguma versão já tiver `Contract` (PROTECT), o hard delete é bloqueado pela mesma engrenagem `HardDeleteBlocked`/`describe_protected_error` já usada para outros FKs protegidos — nenhuma lógica nova de bloqueio foi criada.

### Produtos e Serviços / Proposta Comercial (14/09/2026)

- `_require_draft(version)` — helper interno; toda função que edita uma `ProposalVersion` chama isso primeiro e levanta `ValueError` se `status != DRAFT` (é o mecanismo real de imutabilidade pós-emissão, não só uma checagem de UI).
- `_next_document_number(*, key, prefix)` — `@transaction.atomic`, `get_or_create` + `select_for_update()` + incremento de `NumberingCounter`, retorna `f"{prefix}-{last_value:06d}"`. Mesmo padrão de `EquipmentModel.last_sequence`.
- **`calculate_proposal_version(version)`** — fonte única de verdade do financeiro (spec seção 24): para cada item, `gross = unit_price * quantity`, aplica `item_discount_percent`, soma tudo em `subtotal`; `total = subtotal - general_discount + interest_amount + freight_amount`. Levanta `ValueError` se o total resultante for negativo — **nunca** arredonda/trava silenciosamente para zero. Sempre `Decimal`. Chamada por toda operação que muda item ou condições, nunca calculada na view/template.
- `create_proposal(*, opportunity, created_by)` / `get_or_create_active_proposal(*, opportunity, created_by)` — cria `Proposal` (numerada) + 1ª `ProposalVersion` (DRAFT); a segunda é o acessor canônico usado tanto pela tela (`OpportunityDetailView.get()`) quanto pelos endpoints POST de item (`_get_editable_version_or_404`), garantindo que adicionar o primeiro item nunca depende de uma visita prévia à página.
- `ProposalItemData` + `_validate_item_fields()` — quantity > 0, unit_price ≥ 0, desconto 0–100.
- `add_proposal_item()` / `update_proposal_item()` / `remove_proposal_item()` — todas chamam `_require_draft()` primeiro, depois `calculate_proposal_version()`.
- `ProposalConditionsData` + `update_draft_conditions()` — grava condições comerciais/logística/financeiro/texto livre de uma vez; valida `general_discount`/`interest_amount`/`freight_amount` ≥ 0; recalcula ao final.
- `AvailabilityResult` (`requested`, `available`, propriedade `missing`) + `check_availability(*, equipment_model, requested_quantity)` — **somente leitura**: conta `Equipment` ativo com `status=DISPONIVEL` do modelo pedido, reaproveitando o campo operacional real (`apps.equipment.models.Equipment.status`) já usado pelo resto do sistema. Nunca cria reserva/movimento, nunca seleciona patrimônio específico (spec seção ~40-45).
- `_format_address_snapshot()` / `_format_company_address_snapshot()` — formatadores internos usados só por `issue_proposal()`.
- **`issue_proposal(*, proposal_version, issued_by)`** — `@transaction.atomic`; exige DRAFT e ≥1 item; recalcula; congela snapshot de cliente (de `opportunity.client`), empresa (de `get_company_profile()`) e vendedor (`str(opportunity.owner)`); muda status para ISSUED; gera o PDF (`apps.crm.pdf.render_proposal_pdf`) e cria o `Attachment` (categoria `ORCAMENTO_PROPOSTA`, origem `SYSTEM`). A partir daqui a versão vira imutável (`is_editable=False`).
- `create_new_version(*, proposal, created_by)` — exige que a última versão exista e **não** esteja DRAFT; clona condições + itens para uma nova `ProposalVersion` (`version_number + 1`, DRAFT); recalcula. É o único caminho para "editar" uma proposta já emitida — nunca uma edição silenciosa da versão antiga.
- `generate_contract(*, proposal_version, created_by)` — rejeita se a versão ainda for DRAFT; numera via `NumberingCounter` (prefixo `CONTR-`); cria `Contract`; gera PDF (`render_contract_pdf`) e `Attachment` (categoria `CONTRATO`).
- `DocumentType` (TextChoices): PROPOSTA, CONTRATO, PROPOSTA_E_CONTRATO — **sempre dois documentos distintos quando ambos são pedidos, nunca um PDF híbrido** (spec: "Proposta Comercial" e "Contrato" são documentos separados).
- `generate_documents(*, proposal_version, document_type, actor)` — `@transaction.atomic`; orquestra `issue_proposal()`/`generate_contract()` conforme `document_type` (emite automaticamente se ainda DRAFT e o contrato foi pedido diretamente); retorna um dict só com as chaves geradas.
- `acceptable_proposal_versions(opportunity)` — QuerySet de versões ISSUED (ainda não aceitas) de todas as `Proposal`s da oportunidade — é o universo válido usado para validar o POST de aceite (proteção IDOR).
- **`accept_proposal_version(*, proposal_version, accepted_by, won_stage)`** — `@transaction.atomic`; exige ISSUED; marca ACCEPTED/`accepted_at`/`accepted_by`; único efeito colateral sobre `Opportunity` é chamar o `change_opportunity_stage()` já existente (`closed_value=proposal_version.total`) — "aceitar" nunca é um caminho de escrita paralelo ao Kanban, é literalmente o mesmo service que já fazia isso antes desta implementação. "Criar/salvar" ≠ "emitir" ≠ "aceitar": são três verbos/três funções diferentes, nunca fundidos.
- `TimelineEntry` (`when`, `label`, `actor`) + `build_opportunity_timeline(opportunity)` — mescla `OpportunityStageChange` com eventos de criação/emissão/aceite de `Proposal`/`ProposalVersion`/`Contract` num único histórico ordenado; **nenhuma tabela nova de log foi criada** — reaproveita os timestamps que cada model já tinha.
=======
- `preview_opportunity_hard_delete()` / `hard_delete_opportunity(*, opportunity_id, actor)` — `select_for_update()`, exige `actor.is_superuser`, cascade automático de stage_changes/activities.
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

## Forms

- **`ClientAutocompleteWidget`** — renderiza `<input>` de busca (sem `name`, nunca enviado) + `<input type="hidden">` (único valor visto pelo Django) + dropdown; o campo continua um `ModelChoiceField` normal — a validação real é 100% do `ModelChoiceField.clean()`.
- `OpportunityCreateForm` — `client` (autocomplete), `title`, `owner`, `source`, `business_type`, `stage` (restrito a ativas/não-ganhas/não-perdidas), `notes`. **`estimated_value`/`expected_close_date` removidos da criação** (12/09/2026 — pensados para preenchimento futuro automático via equipamentos vinculados).
- `OpportunityUpdateForm` — sem campo `client` (imutável pós-criação).
- `OpportunityStageChangeForm` — `loss_reason` obrigatório via `clean()` se `stage.is_lost`.
- `CommercialActivityForm`, `CommercialSourceForm`/`OpportunityStageForm`/`LossReasonForm` (ModelForms de configuração).
<<<<<<< HEAD
- **`ProposalItemForm`** (14/09/2026) — `equipment_model` (`ModelChoiceField` sobre `EquipmentModel` ativo — nunca `Equipment`/patrimônio), `quantity` (`IntegerField`, `min_value=1`), `unit_price` (`DecimalField`, `min_value=0`), `item_discount_percent` (opcional, 0–100), `notes`.
- **`ProposalConditionsForm`** — todos os campos de condição/período/logística/financeiro/texto livre de `ProposalVersion`. `clean()`: `payment_method_other` obrigatório quando `payment_method=OUTRO`; `contracted_end_date` ≥ `contracted_start_date`.
- **`DocumentGenerationForm`** — `document_type` (`ChoiceField` sobre `DocumentType`).
- **`AcceptProposalVersionForm`** — `proposal_version` (`IntegerField`, `HiddenInput` — validado contra `acceptable_proposal_versions()` na view, não só aqui), `stage` (`ModelChoiceField` restrito a etapas ativas com `is_won=True`).
=======
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

## Views

Arquivo: `apps/crm/views.py`. **Único app que usa `LoginRequiredMixin`+`PermissionRequiredMixin`** (não `RoleRequiredMixin`), exceto hard delete (`SuperuserRequiredMixin`).

| View | `permission_required` |
|---|---|
| `OpportunityListView` (Kanban) / `OpportunityDetailView` | `crm.view_opportunities` |
| `OpportunityCreateView` / `OpportunityClientAutocompleteView` | `crm.add_opportunities` |
| `OpportunityUpdateView` | `crm.change_opportunities` |
| `OpportunityHardDeleteView` | `SuperuserRequiredMixin` (fora do catálogo) |
| `OpportunityStageChangeView` | `("crm.view_opportunities", "crm.change_opportunity_stage")` |
| `CommercialActivityCreateView` | `("crm.view_opportunities", "crm.add_commercial_activities")` |
| `CommercialSource*`/`OpportunityStage*`/`LossReason*` (9 views) | `crm.manage_commercial_settings` |
<<<<<<< HEAD
| `ProposalItemAddView`/`ProposalItemUpdateView`/`ProposalItemRemoveView`/`ProposalConditionsSaveView`/`ProposalNewVersionView` | `("crm.view_opportunities", "crm.change_opportunities")`, **POST-only** |
| `ProposalGenerateDocumentView` | `crm.view_opportunities` na classe + checagem manual no `post()` conforme `document_type`: PROPOSTA exige `crm.issue_proposal_documents`; CONTRATO/PROPOSTA_E_CONTRATO exigem `crm.generate_contract` (`PermissionDenied` explícito) — **POST-only** |
| `ProposalAcceptVersionView` | `("crm.view_opportunities", "crm.change_opportunity_stage")`, **POST-only** |
| `AvailabilityCheckView` | `crm.view_opportunities`, GET (só leitura, não muda estado — permitido por GET pela spec) |
| `AttachmentDownloadView` | `crm.view_opportunities`, GET; valida que o `Attachment` pertence à `Opportunity` do PK da URL antes de servir o arquivo |

### Produtos e Serviços — detalhes das views (14/09/2026)

Todas as ações que mudam estado (`add`/`update`/`remove` de item, salvar condições, nova versão, gerar documento, aceitar) são **POST-only com CSRF**, nunca GET — inclusive as que a UI só expõe via botão de formulário, nunca um `<a href>` solto (mesma disciplina do resto do projeto: "botão escondido não é a proteção real").

`_get_editable_version_or_404(request, opportunity)` — helper interno usado pelas views de item; **chama `get_or_create_active_proposal()`** em vez de exigir uma `Proposal` pré-existente, para que os endpoints de item nunca dependam de o usuário já ter visitado a página de detalhe antes de adicionar o primeiro item (corrigido durante os testes — ver `docs/testing.md`).

`ProposalAcceptVersionView` valida o `proposal_version` submetido contra `acceptable_proposal_versions(opportunity)` (não apenas `get_object_or_404` solto) — proteção IDOR explícita: um usuário não pode aceitar uma versão que não pertence à oportunidade da URL, nem uma versão que já não esteja ISSUED.
=======
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7

### `OpportunityClientAutocompleteView`

`MIN_QUERY_LENGTH=3`, `SIMILARITY_THRESHOLD=0.2`, `RESULT_LIMIT=20`. Pesquisa `trade_name`/`company_name`/`document` de clientes **ativos** via `icontains`/`istartswith` e `TrigramWordSimilarity` (Postgres `pg_trgm`, extensão ativada em `apps.clients` migration `0006`). Ordenação em 3 níveis: prefixo exato > contém > só similaridade. Resposta mínima: `{"id", "name"}` — nunca documento/telefone/e-mail.

`OpportunityCreateView` suporta modo AJAX (header `X-Requested-With`) para o drawer de criação rápida, e modo tradicional como fallback sem JS — mesma view/form/service para os dois.

## URLs

<<<<<<< HEAD
`app_name="crm"`, montado como `path("crm/", ...)`. 17 rotas legadas: `oportunidades/` (+ CRUD, autocomplete, etapa, hard delete, atividades) e `configuracoes/` (origens, etapas, motivos de perda). Desde 14/09/2026, +9 rotas de Produtos e Serviços, todas aninhadas sob `oportunidades/<int:pk>/`: `produtos-servicos/itens/adicionar/`, `produtos-servicos/itens/<int:item_pk>/editar/`, `produtos-servicos/itens/<int:item_pk>/remover/`, `produtos-servicos/condicoes/`, `produtos-servicos/nova-versao/`, `produtos-servicos/gerar-documento/`, `produtos-servicos/aceitar/`, `produtos-servicos/disponibilidade/` e `anexos/<int:attachment_pk>/download/`.

## Permissions

9 `PermissionSpec` com `app_label="crm"` — **as únicas do catálogo sem equivalente legado** (`legacy_constant=None`): as 7 originais (`view_opportunities`, `add_opportunities`, `change_opportunities`, `change_opportunity_stage`, `view_commercial_activities`, `add_commercial_activities`, `manage_commercial_settings`) mais 2 novas de 14/09/2026: `issue_proposal_documents` (emitir Proposta Comercial em PDF) e `generate_contract` (gerar Contrato em PDF). `OpportunityHardDeleteView` fica fora do catálogo (`SuperuserRequiredMixin`/`is_superuser` puro — "Nível C").

**Por que só 2 permissions novas, e não uma por ação** (spec seção 83, "evitar excesso de permissions"): toda a composição da proposta (adicionar/editar/remover item, salvar condições, criar nova versão) reaproveita `crm.change_opportunities` — é conceitualmente "editar dados da oportunidade", a mesma permissão que já protegia a ficha. Aceitar reaproveita `crm.change_opportunity_stage` — aceitar É uma mudança de etapa (para uma etapa ganha), não uma ação nova. Só emitir Proposta (produz um documento comercial formal, número definitivo, snapshot congelado) e gerar Contrato (produto jurídico) ganharam permissão própria, porque são ações qualitativamente diferentes de "editar um rascunho" — o resto seria duplicação.

## Templates

`templates/crm/`: `opportunity_list.html` (Kanban + drawer de criação rápida + toolbar de filtros), `_opportunity_kanban_card.html` (fonte única do card, reusada via `render_to_string` na resposta JSON), `_opportunity_quick_create_fields.html` (parcial reenviado como fragmento AJAX em erro), `opportunity_form.html`, `opportunity_detail.html` (abas Visão geral/Atividades/**Produtos e Serviços**/Equipamentos/Histórico/**Anexos** — as duas últimas abas novas de 14/09/2026), `_proposal_composition.html` (parcial incluído na aba Produtos e Serviços — cabeçalho de status/versão, bloco de geração de documentos, formulário de condições comerciais, tabela de itens + formulário de adicionar item, resumo financeiro, bloco de aceite), `opportunity_hard_delete_confirm.html`, e os CRUDs simples de configuração. `templates/crm/pdf/proposal.html` e `templates/crm/pdf/contract.html` — templates A4 renderizados por WeasyPrint (não servidos como HTML normal), mesmo padrão de `apps.qrcodes` (`render_to_string()` + `HTML(string=...).write_pdf()`); o `contract.html` exibe um aviso visível de texto placeholder enquanto `Contract.legal_text_is_placeholder=True`.

A aba "Histórico" passou a iterar `TimelineEntry` (via `build_opportunity_timeline()`) em vez de `OpportunityStageChange` diretamente, para incluir também eventos de proposta/versão/contrato na mesma linha do tempo.

## JavaScript

`static/crm/*.js`: **`client_autocomplete.js`** (debounce 275ms, `AbortController` para descartar respostas obsoletas), **`kanban.js`** (drag-and-drop nativo HTML5, POST via `fetch`, move o card no DOM só após confirmação do backend — nunca otimista), **`opportunity_detail.js`** (roteia submits de mudança de etapa para o modal de perda/ganho conforme `data-is-lost`/`data-is-won` na `<option>`), **`opportunity_quick_create.js`** (drawer com focus trap, estado "sujo" com confirmação de descarte), **`proposal_composition.js`** (14/09/2026 — `fetch()` debounced de 250ms para `AvailabilityCheckView` disparado por `change`/`input` nos campos modelo/quantidade do formulário de adicionar item; atualiza um `<span data-availability-result>` com "X solicitados — Y disponíveis[— Z em falta]"; puramente informativo, nunca bloqueia o submit do formulário — a checagem de disponibilidade é consultiva, não uma trava).

## Dependências

`apps.clients.models.Client`; `apps.core` (SoftDeleteModel, TimeStampedModel, hard_delete, `HardDeleteConfirmForm`, `format_brl`, `CompanyProfile`/`get_company_profile()`); `apps.accounts` (User, `SuperuserRequiredMixin`); `django.contrib.postgres.search.TrigramWordSimilarity`; `simple_history`. Desde 14/09/2026 também: `apps.catalog.models.EquipmentModel` (catálogo real de produtos — nunca `Equipment`/patrimônio), `apps.equipment.models.Equipment`/`Status` (só leitura, em `check_availability()`), `apps.operations.models.Location` (FK opcional de local de entrega), `apps.attachments` (`Attachment`, `create_attachment`, `attachments_for` — PDFs gerados), `weasyprint` (geração de PDF).

## Quem chama apps.crm

`config/urls.py`/`settings.py` (registro padrão); `templates/base.html` (menu condicionado a `perms.crm.*`). Nenhum outro app importa `apps.crm.views`/`forms` diretamente — o acoplamento externo é só leitura unidirecional de `Client`, `EquipmentModel`, `Equipment` (status), `Location` e `CompanyProfile`; nenhum desses apps sabe que `apps.crm` existe.

## Testes

11 arquivos em `apps/crm/tests/`: os 9 originais (`test_client_autocomplete.py` — 23 testes, `test_kanban_view.py`, `test_opportunity_detail_redesign.py`, `test_opportunity_hard_delete.py`, `test_permission_matrix.py`, `test_quick_create_drawer.py`, `test_security.py`, `test_services.py`, `test_stage_change_concurrency.py`) mais 2 novos de 14/09/2026: **`test_proposal_services.py`** (44 testes — criação de proposta, composição de itens, ordem de cálculo financeiro, edição só em DRAFT, emissão + snapshot, versionamento, contrato, aceite, disponibilidade) e **`test_proposal_views.py`** (17 testes — permissão de cada endpoint POST-only, geração de documento, aceite com validação IDOR, checagem de disponibilidade, renderização das novas abas). `test_opportunity_detail_redesign.py` ganhou `test_proposal_version_has_no_parallel_won_lost_mechanism` (substitui o antigo `test_no_proposal_model_exists_in_crm_app`, obsoleto pela própria existência do model agora — o novo teste verifica, via `inspect.getsource`, que `accept_proposal_version()` chama literalmente `change_opportunity_stage(` e que `ProposalVersion` não tem nenhum campo `is_won`/`won`/`won_at`/`accepted_budget` próprio).

## Migrations

`0001_initial.py` (10/09/2026) + **`0002_numberingcounter_proposal_proposalversion_and_more.py`** (14/09/2026 — `NumberingCounter`, `Proposal`, `ProposalVersion`, `ProposalItem`, `Contract` e as 2 novas `Permission`s do Meta). A extensão `pg_trgm` está em `apps.clients` (`0006_pg_trgm_extension.py`), **não** em `apps.crm`.

## Pontos importantes

- **Único app nascido 100% na arquitetura de Cargo** — as 9 permissions `crm.*` são as únicas do catálogo sem `legacy_constant`. CRM foi construído depois da aprovação da nova arquitetura, então nunca passou pelo sistema legado.
- **Botão escondido ≠ bloqueio no backend** — a autorização real é sempre `PermissionRequiredMixin`; POST manual de campos de perda/ganho (ou de qualquer ação de Produtos e Serviços) sem permissão é bloqueado mesmo que o botão nunca tivesse aparecido (testado explicitamente).
- **`get_object_or_404` sem filtro por usuário/dono é deliberado** — a proteção contra IDOR é a permissão (`view_opportunities`), não esconder o PK. Para o aceite de proposta especificamente, há uma segunda camada: o `proposal_version` submetido precisa estar em `acceptable_proposal_versions(opportunity)`.
- **Dupla camada de validação**: toda regra crítica (ganho/perda mutuamente exclusivos, valores não-negativos, total nunca negativo) tem `CheckConstraint` no banco E validação explícita em `clean()`/services.
- **`TrigramWordSimilarity` vs `TrigramSimilarity`**: escolha documentada por medição manual — `word_similarity` mede o melhor trecho contínuo do nome, mais adequado para buscas curtas contra nomes longos.
- **Aba "Equipamentos" na ficha continua estado vazio estático** — não existe vínculo Oportunidade↔Equipamento implementado (a composição da proposta é por `EquipmentModel`, não por `Equipment` individual — ver `ProposalItem`). Aba "Anexos" deixou de ser omitida: `apps.attachments` agora tem implementação real (ver `docs/apps/attachments.md`).
- **"Criar/salvar" ≠ "emitir" ≠ "aceitar"** — três verbos, três funções de `services.py` distintas (`create_proposal`/`update_draft_conditions`, `issue_proposal`, `accept_proposal_version`), nunca fundidos numa única ação. Emitir não implica aceitar; gerar contrato não implica aceitar.
- **`Proposal` não guarda `status` próprio** — sempre derivado de `latest_version.status` (`display_status`), para nunca ter duas fontes de verdade divergentes.
- **Limitação conhecida de UI**: `update_proposal_item()`/`ProposalItemUpdateView` existem e têm cobertura de teste, mas `_proposal_composition.html` só oferece botões de adicionar/remover item — não há um controle de "editar" inline na tela; para mudar quantidade/preço de um item já adicionado, hoje é preciso remover e adicionar de novo. Disclosed no relatório final.
=======
`app_name="crm"`, montado como `path("crm/", ...)`. 17 rotas: `oportunidades/` (+ CRUD, autocomplete, etapa, hard delete, atividades) e `configuracoes/` (origens, etapas, motivos de perda).

## Permissions

7 `PermissionSpec` com `app_label="crm"` — **as únicas do catálogo sem equivalente legado** (`legacy_constant=None`): `view_opportunities`, `add_opportunities`, `change_opportunities`, `change_opportunity_stage`, `view_commercial_activities`, `add_commercial_activities`, `manage_commercial_settings`. `OpportunityHardDeleteView` fica fora do catálogo (`SuperuserRequiredMixin`/`is_superuser` puro — "Nível C").

## Templates

`templates/crm/`: `opportunity_list.html` (Kanban + drawer de criação rápida + toolbar de filtros), `_opportunity_kanban_card.html` (fonte única do card, reusada via `render_to_string` na resposta JSON), `_opportunity_quick_create_fields.html` (parcial reenviado como fragmento AJAX em erro), `opportunity_form.html`, `opportunity_detail.html` (abas Visão geral/Atividades/Equipamentos/Histórico), `opportunity_hard_delete_confirm.html`, e os CRUDs simples de configuração.

## JavaScript

`static/crm/*.js`: **`client_autocomplete.js`** (debounce 275ms, `AbortController` para descartar respostas obsoletas), **`kanban.js`** (drag-and-drop nativo HTML5, POST via `fetch`, move o card no DOM só após confirmação do backend — nunca otimista), **`opportunity_detail.js`** (roteia submits de mudança de etapa para o modal de perda/ganho conforme `data-is-lost`/`data-is-won` na `<option>`), **`opportunity_quick_create.js`** (drawer com focus trap, estado "sujo" com confirmação de descarte).

## Dependências

`apps.clients.models.Client`; `apps.core` (SoftDeleteModel, TimeStampedModel, hard_delete, `HardDeleteConfirmForm`, `format_brl`); `apps.accounts` (User, `SuperuserRequiredMixin`); `django.contrib.postgres.search.TrigramWordSimilarity`; `simple_history`.

## Quem chama apps.crm

`config/urls.py`/`settings.py` (registro padrão); `templates/base.html` (menu condicionado a `perms.crm.*`). Nenhum outro app importa `apps.crm.views`/`forms` diretamente — o acoplamento externo é só leitura unidirecional de `Client`.

## Testes

9 arquivos em `apps/crm/tests/`: `test_client_autocomplete.py` (23 testes), `test_kanban_view.py`, `test_opportunity_detail_redesign.py`, `test_opportunity_hard_delete.py`, `test_permission_matrix.py`, `test_quick_create_drawer.py`, `test_security.py` (IDOR, CSRF, integridade won/lost a nível de banco), `test_services.py`, `test_stage_change_concurrency.py` (`TransactionTestCase`).

## Migrations

Apenas `0001_initial.py` (10/09/2026). A extensão `pg_trgm` está em `apps.clients` (`0006_pg_trgm_extension.py`), **não** em `apps.crm`.

## Pontos importantes

- **Único app nascido 100% na arquitetura de Cargo** — as 7 permissions `crm.*` são as únicas do catálogo sem `legacy_constant`. CRM foi construído depois da aprovação da nova arquitetura, então nunca passou pelo sistema legado.
- **Botão escondido ≠ bloqueio no backend** — a autorização real é sempre `PermissionRequiredMixin`; POST manual de campos de perda/ganho sem permissão é bloqueado mesmo que o botão nunca tivesse aparecido (testado explicitamente).
- **`get_object_or_404` sem filtro por usuário/dono é deliberado** — a proteção contra IDOR é a permissão (`view_opportunities`), não esconder o PK.
- **Dupla camada de validação**: toda regra crítica (ganho/perda mutuamente exclusivos, valores não-negativos) tem `CheckConstraint` no banco E validação explícita em `clean()`/services.
- **`TrigramWordSimilarity` vs `TrigramSimilarity`**: escolha documentada por medição manual — `word_similarity` mede o melhor trecho contínuo do nome, mais adequado para buscas curtas contra nomes longos.
- **Aba "Equipamentos" na ficha é estado vazio estático** — não existe vínculo Oportunidade↔Equipamento implementado. Aba "Arquivos" omitida (app `attachments` vazio).
>>>>>>> 91fdd0e616b042df380c39e660beb2c204e822b7
- Sem TODOs/FIXMEs literais — decisões pendentes são documentadas em prosa nas docstrings.
