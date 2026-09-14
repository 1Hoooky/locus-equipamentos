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

## Nota sobre "efeitos colaterais entre apps"

Dois pontos do sistema mudam `Equipment.status` fora de `apps.equipment`, sempre através de `apps.equipment.services.change_status()` (nunca atribuição direta):

- `apps.operations.services.create_movement()` — quando a regra de transição prevê mudança de status (ex.: instalar → `EM_OPERACAO`).
- `apps.maintenance.services.open_maintenance()`/`close_maintenance()`/`cancel_maintenance()` — abre/restaura o status conforme o ciclo de vida da manutenção.

Nenhum dos dois grava `current_location`/`current_client` (isso é exclusivo de `create_movement()`), e nenhum dos dois duplica a criação de `StatusHistory` — sempre reaproveitam `change_status()`.
