# Fluxos principais

Fluxos reais do sistema, extraídos do código (views → forms → services → models). Notação: `A → B` significa "A aciona/chama B, nessa ordem".

## 1. Cadastro de equipamento (geração de patrimônio)

```
EquipmentCreateView (POST)
  → EquipmentCreateForm.is_valid()
  → apps.equipment.services.create_equipment(NewEquipmentData)
      → @transaction.atomic:
          EquipmentModel.objects.select_for_update().get(pk=model_id)   # lock pessimista
          → last_sequence += 1; model.save(update_fields=["last_sequence", ...])
          → patrimonio = build_patrimonio(model.code, last_sequence)     # "LOC-{CODE}-{SEQ:04d}"
          → Equipment.objects.create(patrimonio=..., model_sequence=..., ...)
  → redirect para a ficha do equipamento criado
```

Cadastro em lote (`EquipmentBatchCreateView` → `Confirm` → `Result`, 3 telas) chama `create_equipment_batch()`, que repete o passo acima N vezes **na mesma transação** — se qualquer unidade falhar, o lote inteiro é desfeito. Proteção de banco: `UniqueConstraint(model, model_sequence)` como rede de segurança final.

## 2. Cadastro de cliente (com unidade operacional automática)

```
ClientCreateView (POST, action=save)
  → ClientForm.is_valid()
  → apps.clients.services.create_client(NewClientData)
      → @transaction.atomic:
          validate_document_for_type(document, client_type)
          → checa duplicidade de document/auvo_code
          → apps.core.services.create_address(fiscal_address_data)      # fiscal_address
          → Client.objects.create(...)
          → import local: apps.operations.services.create_location(
                NewLocationData(type=CLIENTE, client=client,
                                name="Unidade principal" ou nome informado))
  → redirect para a ficha do cliente
```

Ação "Consultar CNPJ" (mesma tela, `action=lookup`) é um caminho **separado** que nunca chama `create_client()` — só popula o form via `CompanyLookupService`/BrasilAPI, sem salvar nada.

## 3. Movimentação de equipamento (instalar / retirar / transferir / retornar)

```
MovementCreateView (POST, para um equipamento por patrimônio)
  → MovementForm.is_valid()                        # já filtra destino por tipo no cliente
  → apps.operations.services.create_movement(NewMovementData)
      → @transaction.atomic:
          equipment = Equipment.objects.select_for_update().get(...)     # lock pessimista
          → origin = equipment.current_location                         # nunca vem do chamador
          → _validate_transition(equipment, movement_type, destination)
              → import local: apps.maintenance.services.has_open_maintenance(equipment)
                  → se True e o tipo está em _BLOCKED_BY_OPEN_MAINTENANCE: rejeita
              → checa status atual exigido, tipo de destino compatível,
                TRANSFERENCIA para o mesmo local é rejeitada
          → Movement.objects.create(... 4 snapshots de nome ...)
          → se a regra prevê novo status: apps.equipment.services.change_status(...)
          → equipment.current_location, equipment.current_client = destino  # sempre juntos, 1 save()
  → redirect para a ficha do equipamento
```

## 4. Abrir → concluir/cancelar manutenção

```
MaintenanceOpenView (POST)
  → MaintenanceOpenForm.is_valid()
  → apps.maintenance.services.open_maintenance(NewMaintenanceData)
      → @transaction.atomic:
          equipment = Equipment.objects.select_for_update().get(...)
          → rejeita se has_open_maintenance(equipment) já True
          → SEM departure_movement: exige status DISPONIVEL/EM_OPERACAO
              → apps.equipment.services.change_status(equipment, MANUTENCAO, reason, changed_by)
          → COM departure_movement: valida vínculo com um Movement(ENVIO_MANUTENCAO)
              já existente e ainda não reclamado; não altera status (já é MANUTENCAO)
          → Maintenance.objects.create(status=ABERTA, status_before=..., ...)

MaintenanceCloseView (POST)                                    MaintenanceCancelView (POST)
  → apps.maintenance.services.close_maintenance(...)             → apps.maintenance.services.cancel_maintenance(...)
      → exige status ABERTA + service_performed                      → exige status ABERTA
      → valida return_movement opcional (7 checagens)                → _restore_status_if_owned()
      → change_condition() se condition_after mudou                  → status = CANCELADA
      → _restore_status_if_owned()
          → só restaura Equipment.status se departure_movement
            for None E equipment.status ainda for MANUTENCAO
            (idempotente — Movement externo pode já ter mudado)
      → status = CONCLUIDA
```

## 5. Criação de oportunidade (CRM) com autocomplete de cliente

```
[usuário digita ≥3 caracteres no campo Cliente do drawer/form]
  → GET crm:opportunity_client_autocomplete?q=...
      → OpportunityClientAutocompleteView (permission crm.add_opportunities)
          → filtra Client ativos por trade_name/company_name/document
            (icontains/istartswith + TrigramWordSimilarity, pg_trgm)
          → retorna [{"id": ..., "name": display_name()}, ...] (máx. 20)
  → JS preenche o <input type="hidden"> com o id escolhido

OpportunityCreateView (POST, AJAX via drawer OU rota tradicional)
  → OpportunityCreateForm.is_valid()                # client é ModelChoiceField normal
  → apps.crm.services.create_opportunity(NewOpportunityData)
      → @transaction.atomic:
          rejeita etapa ganha/perdida/inativa
          → Opportunity.objects.create(stage=etapa_inicial, ...)
          → OpportunityStageChange.objects.create(from_stage=None, to_stage=etapa_inicial, ...)
  → AJAX: JSON com card_html (render_to_string do card do Kanban)
    tradicional: redirect para a ficha da oportunidade
```

## 6. Mudança de etapa da oportunidade (Kanban / ficha)

```
[drag-and-drop no Kanban OU form da ficha OU modal de perda/ganho]
  → POST crm:opportunity_change_stage
      → OpportunityStageChangeView (permissions: view_opportunities + change_opportunity_stage)
          → OpportunityStageChangeForm.is_valid()   # loss_reason obrigatório se stage.is_lost
          → apps.crm.services.change_opportunity_stage(...)
              → @transaction.atomic:
                  opportunity = Opportunity.objects.select_for_update().get(...)
                  → rejeita mesma etapa / etapa inativa
                  → nova etapa is_won:  won_at=now(), limpa estado de perda
                  → nova etapa is_lost: exige loss_reason, lost_at=now(), limpa estado de ganho
                  → etapa intermediária: limpa TODO estado de fechamento (reabertura)
                  → OpportunityStageChange.objects.create(from_stage=antiga, to_stage=nova, ...)
      → AJAX: move o card no Kanban só após confirmação do backend (nunca otimista)
```

## 7. Login com `next` — fluxo do QR Code

```
[visitante anônimo escaneia o QR de um equipamento]
  → GET /equipamentos/<patrimonio>/           # EquipmentDetailView, sem login
      → anônimo: renderiza detail_public.html (.only() — nunca busca campos privados)
      → [visitante clica "Entrar" para ver detalhes completos]
          → GET accounts:login?next=/equipamentos/<patrimonio>/
              → LoginView (Django genérico) — campo hidden `next` preservado
              → POST credenciais válidas
                  → RedirectURLMixin.get_success_url(): `next` tem prioridade
                    sobre LOGIN_REDIRECT_URL sempre que presente e seguro (mesmo host)
              → redirect de volta para /equipamentos/<patrimonio>/
                  → agora autenticado: EquipmentDetailView renderiza detail_private.html completo
```

Sem `next` (login direto pela tela de login), o destino é `LOGIN_REDIRECT_URL = "dashboard:home"`.

## 8. Hard delete (Cliente / Equipamento / Oportunidade)

```
*HardDeleteView (GET)
  → SuperuserRequiredMixin.test_func()             # só is_superuser, nunca Role/Permission
  → preview_*_hard_delete(obj) → HardDeleteImpact(target_label, dependents={...})
  → renderiza confirmação com o impacto visível (HardDeleteConfirmForm)

*HardDeleteView (POST, confirm=True)
  → hard_delete_*(id=..., actor=request.user)
      → @transaction.atomic:
          assert actor.is_superuser                 # checado de novo dentro do service
          → obj = Model.objects.select_for_update().get(...)
          → (equipment/opportunity: apaga dependentes PROTECT numa ordem específica primeiro)
          → obj.delete()
          → except ProtectedError: raise HardDeleteBlocked(describe_protected_error(...))
          → purga as linhas de HistoricalRecords do objeto (django-simple-history não
            segura FK viva depois que o objeto sumiu)
  → sucesso: redirect com mensagem / bloqueado: mensagem de erro com o que está protegendo
```

## 9. Reclassificação vs. reemissão de equipamento

```
[erro de classificação identificado — modelo errado atribuído a um equipamento]

reclassify_model()                              supersede_equipment()
  # correção PADRÃO, sem custo físico             # procedimento EXCEPCIONAL
  → @transaction.atomic:                          → @transaction.atomic:
      equipment.model = novo_model                    novo_equip = create_equipment(...)  # patrimônio NOVO
      equipment.category = novo_model.category         # copia serial/fornecedor/aquisição/condição
      equipment.save(...)                             → equipment_antigo.is_active = False
      # patrimonio/model_sequence NUNCA mudam            equipment_antigo.status = INATIVO
                                                         equipment_antigo.superseded_by = novo_equip
                                                     # exige confirm_reprint=True no form
                                                     # (etiqueta física precisa ser trocada)
```

`CAN_RECLASSIFY_EQUIPMENT_MODEL`/`CAN_SUPERSEDE_EQUIPMENT` = só `Role.ADMIN` nos dois casos.

## 10. Importação assistida (padrão comum a Clientes/Auvo e Equipamentos/planilha legada)

```
Upload (POST, .xlsx)
  → parse_*_workbook(arquivo)                     # só leitura, nunca grava
      → valida cabeçalhos obrigatórios (senão levanta *ImportError antes de processar)
      → para cada linha: classifica (NOVO / JA_EXISTENTE / POSSIVEL_DUPLICADO|SEM_CORRESPONDENCIA / INVALIDO)
  → linhas serializadas ficam em SESSÃO (sem tabela de auditoria de importação)
  → redirect para Revisão

Revisão (GET mostra prévia agrupada por categoria; POST confirma)
  → para cada linha aceita: revalida no servidor e chama o service real
    (create_client(..., require_document=False) OU create_equipment(...))
  → captura ValueError/ValidationError por linha (uma linha ruim não derruba as outras)
  → limpa a sessão, monta resumo

Resumo (GET, lê o resumo da sessão — se ausente, redireciona para Upload)
```

## 11. Composição, emissão, versionamento, contrato e aceite de Proposta (CRM — Produtos e Serviços, 14/09/2026)

```
[usuário abre a aba "Produtos e Serviços" da ficha da Oportunidade]
  → OpportunityDetailView.get()
      → get_or_create_active_proposal(opportunity, created_by=request.user)   # se can_change_opportunity
      → renderiza item_form/conditions_form/document_form/accept_form conforme permissões e current_version.is_editable

ProposalItemAddView (POST)
  → _get_editable_version_or_404(request, opportunity)
      → get_or_create_active_proposal(...)                # nunca exige GET prévio
      → _require_draft(version)                            # ValueError se não for DRAFT
  → ProposalItemForm.is_valid()
  → apps.crm.services.add_proposal_item(proposal_version, ProposalItemData)
      → _validate_item_fields()                             # quantity>0, unit_price≥0, desconto 0-100
      → ProposalItem.objects.create(equipment_model=..., description_snapshot=modelo.description, ...)
      → calculate_proposal_version(version)                 # subtotal/total recalculados sempre

[JS: AvailabilityCheckView (GET), disparado por change/input no form de item]
  → apps.crm.services.check_availability(equipment_model, quantity)
      → só leitura: Equipment.objects.filter(model=..., is_active=True, status=DISPONIVEL).count()
      → nunca cria reserva/movimento, nunca seleciona patrimônio — puramente informativo

ProposalConditionsSaveView (POST)
  → _require_draft(version)
  → ProposalConditionsForm.is_valid()
  → apps.crm.services.update_draft_conditions(version, ProposalConditionsData)
      → grava condições/período/logística/financeiro/texto livre
      → calculate_proposal_version(version)

ProposalGenerateDocumentView (POST, document_type = PROPOSTA | CONTRATO | PROPOSTA_E_CONTRATO)
  → checagem manual de permissão conforme document_type (issue_proposal_documents / generate_contract)
  → apps.crm.services.generate_documents(version, document_type, actor)
      → @transaction.atomic:
          se PROPOSTA ou PROPOSTA_E_CONTRATO e ainda DRAFT:
              → issue_proposal(version, issued_by=actor)
                  → _require_draft() + exige ≥1 item + recalcula
                  → congela snapshots (cliente via opportunity.client, empresa via get_company_profile(), vendedor)
                  → status = ISSUED, issued_at, issued_by
                  → apps.crm.pdf.render_proposal_pdf(version) → apps.attachments.services.create_attachment(categoria=ORCAMENTO_PROPOSTA)
          se CONTRATO ou PROPOSTA_E_CONTRATO:
              → garante emitida (auto-emite se ainda DRAFT)
              → generate_contract(version, created_by=actor)
                  → rejeita se ainda DRAFT
                  → Contract.objects.create(number=..., legal_text_is_placeholder=True)
                  → apps.crm.pdf.render_contract_pdf(contract) → create_attachment(categoria=CONTRATO)
  # a partir daqui version.is_editable == False — qualquer alteração exige create_new_version()

[NÃO existe mais um botão/endpoint "Criar nova versão" desde a RODADA 4 (15/09/2026) —
 `ProposalNewVersionView` foi removida; create_new_version() só é chamada pelo
 auto-versionamento preguiçoso (ensure_editable_version()/ensure_editable_item()/
 ensure_editable_installment(), ver seção 11-A abaixo), nunca por um botão manual]
apps.crm.services.create_new_version(proposal, created_by)
  → exige última versão ISSUED/ACCEPTED (nunca DRAFT)
  → clona condições + itens + parcelas (FECHAMENTO DA PROPOSTA COMERCIAL, 23/09/2026)
    para nova ProposalVersion(version_number+1, DRAFT)
  → calculate_proposal_version(nova_versão)
  # a versão antiga permanece intocada/imutável para sempre — nunca editada in-place

ProposalAcceptVersionView (POST)
  → valida proposal_version ∈ acceptable_proposal_versions(opportunity)   # proteção IDOR
  → AcceptProposalVersionForm.is_valid()
  → apps.crm.services.accept_proposal_version(version, accepted_by, won_stage)
      → @transaction.atomic:
          exige status == ISSUED
          → status = ACCEPTED, accepted_at, accepted_by
          → apps.crm.services.change_opportunity_stage(opportunity_id=..., new_stage=won_stage,
                changed_by=accepted_by, closed_value=version.total)   # único efeito sobre Opportunity,
                                                                        # o mesmo service que já existia

AttachmentDownloadView (GET)
  → valida attachment.content_type/object_id == (Opportunity, pk da URL)
  → FileResponse(attachment.file, as_attachment=True)                   # nunca link /media/ direto
```

"Criar/salvar" (`add_proposal_item`/`update_draft_conditions`) ≠ "emitir" (`issue_proposal`, produz PDF + snapshot + número definitivo) ≠ "gerar contrato" (`generate_contract`) ≠ "aceitar" (`accept_proposal_version`, o único caminho que fecha a Oportunidade). Cada verbo é uma função de `services.py` distinta — nenhum deles implica o próximo automaticamente, exceto a auto-emissão embutida em `generate_documents()` quando o Contrato é pedido diretamente sobre uma versão ainda em rascunho (documentado ali mesmo, não é um atalho oculto).

## 11-A. Condições de pagamento (parcelas) e validação na emissão (CRM, FECHAMENTO DA PROPOSTA COMERCIAL, 23/09/2026)

```
[usuário, na aba "Produtos e Serviços", abre o painel "+Adicionar parcela"]
  → ProposalInstallmentAddView (POST)
      → ensure_editable_version(proposal, created_by=request.user)   # auto-versionamento preguiçoso,
                                                                        # mesmo mecanismo da seção 11 acima
      → _require_draft(version)
      → ProposalInstallmentForm(prefix="parcela").is_valid()
      → apps.crm.services.add_installment(proposal_version, ProposalInstallmentData)
          → _validate_installment_fields()               # amount>0, due_date presente, payment_method válido
          → ProposalVersionInstallment.objects.create(sequence=..., ...)
  # nenhuma validação de "soma = total" acontece aqui — rascunho aceita estado incompleto (seção 22)

[edição/remoção de uma parcela já existente]
  → ProposalInstallmentUpdateView / ProposalInstallmentRemoveView (POST)
      → ensure_editable_installment(installment, created_by=request.user)
          → se a versão da parcela já não é DRAFT: ensure_editable_version() clona uma nova versão
            DRAFT (parcelas + itens + condições todos clonados) e localiza, nela, a parcela
            correspondente pelo mesmo `sequence` — só ENTÃO a edição/remoção pedida é aplicada
          → se já é DRAFT: nenhuma versão nova, edita/remove direto
      → update_installment(...) / remove_installment(...)

[UI, a qualquer momento — nunca só no submit]
  → apps.crm.services.check_payment_reconciliation(proposal_version)
      → soma installments.amount vs. proposal_version.total (Decimal)
      → devolve PaymentReconciliation(total, distributed, difference, is_reconciled)
  → template renderiza "Total da proposta / Total distribuído / Diferença" + badge
    "Pagamento conferido" (is_reconciled=True) ou estado de divergência — NUNCA corrige nada sozinho

ProposalGenerateDocumentView (POST, document_type inclui PROPOSTA)
  → generate_documents(...) → issue_proposal(version, issued_by=actor)
      → _require_draft() + exige ≥1 item + calculate_proposal_version()
      → apps.crm.services.validate_payment_before_issue(proposal_version)      # SEÇÃO 22, REGRA CENTRAL
          → ValueError se zero parcelas configuradas
          → ValueError se check_payment_reconciliation(...).is_reconciled é False
          → só passando os dois: emissão prossegue normalmente (congela snapshots, gera PDF)
  # se general_discount/item/frete mudar DEPOIS de já existir parcela configurada, e a próxima
  # tentativa de emitir não bater mais, o MESMO ValueError acima bloqueia de novo — nenhuma
  # parcela é jamais reescrita/redistribuída automaticamente por essa alteração (seção 24)
```

Mesma disciplina da seção 11: "salvar parcela" (`add_installment`/`update_installment`/`remove_installment`) ≠ "emitir" (`issue_proposal`, é o único ponto que EXIGE reconciliação completa). `ProposalVersionInstallment` nunca é lido/escrito por nenhum módulo financeiro — é um registro de negociação, não uma conta a receber (spec seção 15, fora de escopo — ver `docs/apps/crm.md`).

## 12. Tabela de Preços V1 → preço sugerido ao compor uma Proposta (CRM, 16/09/2026)

```
[usuário abre "Tabela de Preços" — configuracoes/tabela-de-precos/?tipo=LOCACAO]
  → PriceTableView.get()
      → list_price_table_rows(business_type, search, only_missing)   # 3 queries, nunca N+1
      → renderiza EQUIPAMENTOS + SERVIÇOS ativos, "Sem valor" para quem não tem PriceTableItem

[usuário clica no lápis de uma linha]
  → PriceTableItemRowView.get() com ?modo=editar          # exige crm.change_price_table (checagem manual)
      → devolve _price_table_row_edit.html (htmx, outerHTML no <tr>)

[usuário digita o valor e clica "Salvar"]
  → PriceTableItemRowView.post()                          # exige crm.change_price_table
      → PriceTableItemForm.is_valid()
      → apps.crm.services.set_price_table_item(PriceTableItemData, user=request.user)
          → @transaction.atomic:
              PriceTable.objects.get_or_create(business_type=...)      # nunca criada manualmente
              select_for_update() na linha existente, se houver
              PriceTableItem criado ou atualizado; item._history_user = user; item.save()
              # simple_history grava um HistoricalPriceTableItem (usuário + data/hora + valor)
      → devolve _price_table_row.html atualizado (htmx, outerHTML no <tr>)
  # NENHUM ProposalItem já existente é tocado por esta escrita — ver seção "Preço sugerido" abaixo.

---

[usuário, numa Oportunidade, abre "Adicionar produto/serviço" e escolhe um Modelo/Serviço]
  → JS (proposal_composition.js, initSuggestedPrice): fetch debounced 250ms
  → SuggestedPriceView.get(pk=opportunity.pk)              # só leitura, GET, exige crm.view_opportunities
      → apps.crm.services.get_suggested_price(
            business_type=opportunity.business_type,        # SEMPRE da própria Opportunity, nunca da querystring
            equipment_model=... ou service=...)
          → PriceTableItem.objects.filter(price_table__business_type=..., equipment_model=...).first()
          → devolve unit_price ou None (nunca 0.00 inventado)
      → JSON {"ok", "found", "unit_price", "business_type_display"}
  → JS preenche <input name="unit_price"> SÓ SE ainda vazio E o usuário não digitou nele antes
  → usuário pode sobrescrever livremente — o campo nunca é travado (readonly/disabled)

[usuário clica "Adicionar produto/serviço" — POST normal, sem relação com a Tabela de Preços]
  → ProposalItemAddView.post() → add_proposal_item(...)     # EXATAMENTE o mesmo fluxo da seção 11 acima
      → ProposalItem.unit_price = o que veio no POST (sugerido ou sobrescrito) — SNAPSHOT congelado

[dias depois, alguém muda o preço na Tabela de Preços para este mesmo Modelo/BusinessType]
  → set_price_table_item() atualiza SÓ o PriceTableItem
  → o ProposalItem já criado permanece com o unit_price antigo — ninguém o reescreve, em lugar nenhum
  → uma NOVA consulta a get_suggested_price()/SuggestedPriceView já devolve o valor novo
```

**PriceTable é sugestão, ProposalItem é snapshot** — os dois fluxos acima (edição da tabela vs. composição da proposta) nunca se cruzam depois do momento em que o formulário de adicionar item é preenchido. `get_suggested_price()` é consultada exatamente uma vez, no instante do preenchimento (via AJAX) — nunca em `calculate_proposal_version()`, nunca em `issue_proposal()`, nunca em nenhum recálculo posterior.

## 13. Matriz de Preços de Locação — plano × prazo (CRM, RODADA 1, 16/09/2026)

EVOLUI o fluxo #12 acima para Locação — Venda/Serviço continuam exatamente como estão (fluxo #12, sem nenhuma mudança).

```
[usuário abre "Tabela de Preços" — configuracoes/tabela-de-precos/?tipo=LOCACAO]
  → PriceTableView.get()
      → list_price_table_rows(business_type=LOCACAO, ...)   # só para SERVIÇOS (equipment_rows é descartado)
      → list_commercial_plans()                              # planos de Locação ativos
      → resolve o plano (?plano=, default o primeiro por order)
      → list_price_table_matrix(commercial_plan, search, only_missing)   # 3 queries, nunca N+1
      → renderiza sub-navegação de planos + matriz EquipmentModel × CommercialTerm (todas as categorias)
      → Serviços continuam na lista flat de sempre (fluxo #12), sempre visível

[usuário clica no lápis de UMA célula (equipamento × prazo)]
  → PriceTableRateCellView.get() com ?plano=<id>&modo=editar    # exige crm.change_price_table (checagem manual)
      → resolve/valida (commercial_plan, equipment_model, commercial_term) — 404 se o prazo não é do plano
      → devolve _price_table_matrix_cell_edit.html (htmx, outerHTML no <td>)

[usuário digita valor + modo de cobrança e clica "Salvar"]
  → PriceTableRateCellView.post()                             # exige crm.change_price_table
      → PriceTableRateForm.is_valid()
      → apps.crm.services.set_price_table_rate(PriceTableRateData, user=request.user)
          → @transaction.atomic:
              PriceTable.objects.get_or_create(business_type=LOCACAO)
              PriceTableItem existente? não → set_price_table_item(unit_price=None)  # linha "âncora", NUNCA 0.00
              select_for_update() na PriceTableRate existente, se houver
              PriceTableRate criada ou atualizada; rate._history_user = user; rate.save()
              # simple_history grava um HistoricalPriceTableRate (usuário + data/hora + valor)
      → devolve _price_table_matrix_cell.html atualizado (htmx, outerHTML no <td>)
  # NENHUM ProposalItem já existente é tocado — mesma regra crítica do fluxo #12.

---

[ATUALIZADO 23/09/2026 — FECHAMENTO DA PROPOSTA COMERCIAL adicionou ProposalVersion.commercial_plan
 (FK), mas SÓ para exibição no cabeçalho do PDF/UI ("LOCAÇÃO MENSAL") — ver docs/apps/crm.md.
 A integração de PREÇO por plano+prazo continua a mesma coisa registrada abaixo como RODADA 2,
 ainda NÃO implementada — só o vínculo estrutural passou a existir, nenhum cálculo/sugestão nova]
  → a composição da proposta ainda NÃO usa CommercialTerm nem consulta preço por plano/prazo
  → SuggestedPriceView continua chamando get_suggested_price() SEM plano/prazo para Locação
  → get_suggested_price(business_type=LOCACAO, equipment_model=..., commercial_plan=None, commercial_term=None)
      → cai no MESMO caminho flat do fluxo #12 (PriceTableItem.unit_price)
      → como equipamentos da matriz só têm a linha "âncora" (unit_price=None), a resposta é sempre None
      → "sem sugestão automática" — o campo continua 100% editável manualmente, nunca bloqueado
```

**Sem interpolação de prazo** — mesmo com "5 dias" preenchido para um equipamento, uma consulta a `get_suggested_price(commercial_plan=..., commercial_term=<7 dias>)` sem `PriceTableRate` própria devolve `None`, nunca o valor de "5 dias". **Sem cruzamento com Venda/Serviço** — a matriz só existe/é consultada para `business_type=LOCACAO` e só para `equipment_model` (nunca `service`); `get_suggested_price()` rejeita (`ValueError`) qualquer combinação de `commercial_plan`/`commercial_term` com outro `business_type` ou com `service`.

## Nota sobre "efeitos colaterais entre apps"

Dois pontos do sistema mudam `Equipment.status` fora de `apps.equipment`, sempre através de `apps.equipment.services.change_status()` (nunca atribuição direta):

- `apps.operations.services.create_movement()` — quando a regra de transição prevê mudança de status (ex.: instalar → `EM_OPERACAO`).
- `apps.maintenance.services.open_maintenance()`/`close_maintenance()`/`cancel_maintenance()` — abre/restaura o status conforme o ciclo de vida da manutenção.

Nenhum dos dois grava `current_location`/`current_client` (isso é exclusivo de `create_movement()`), e nenhum dos dois duplica a criação de `StatusHistory` — sempre reaproveitam `change_status()`.

Desde 14/09/2026, `apps.crm.services.check_availability()` é o único ponto do fluxo de Produtos e Serviços que lê `Equipment.status` — e só lê: nunca chama `change_status()`, nunca cria `Movement`, nunca associa um `ProposalItem` a um `Equipment` específico (a composição é sempre por `EquipmentModel`). Reservar estoque de verdade a partir de uma proposta aceita fica para uma etapa futura, deliberadamente fora desta implementação (spec seção 106).
