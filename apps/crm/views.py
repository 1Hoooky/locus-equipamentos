"""
Views do CRM (LocusHub, Etapa 1) — PRIMEIRO módulo do projeto a usar a
arquitetura NOVA de autorização (`User` → Cargo/`Group` → `Permission`,
via `PermissionRequiredMixin`/`perms.crm.*`) em vez do `RoleRequiredMixin`
legado. Nenhuma view aqui checa `role`/`CAN_*`/`RoleRequiredMixin` — só
`login_required` + `permission_required`, exatamente uma Permission do
catálogo por ação (ver `apps/accounts/permission_catalog.py`).

`LoginRequiredMixin` + `PermissionRequiredMixin` (ambos de
`django.contrib.auth.mixins`, nativos do Django) reproduzem EXATAMENTE o
comportamento de `RoleRequiredMixin` sem nenhum código novo:
`AccessMixin.handle_no_permission()` já redireciona anônimo para o login
e levanta `PermissionDenied` (403) para autenticado-sem-permissão, e
`ModelBackend.has_perm()` já dá bypass automático a `is_superuser=True`
(Administrador/superusuário continuam com acesso irrestrito, sem
precisar de nenhuma Permission concedida — mesma "válvula de segurança
operacional" do resto do sistema).

Toda escrita (POST) chama exclusivamente `apps/crm/services.py` — nunca
`Opportunity.objects.create()`/`.save()` direto numa view para os campos
de etapa/ganho/perda. `get_object_or_404(Opportunity, pk=pk)` (sem
filtro adicional por usuário/dono) é deliberado: a oportunidade PK 11
não existe "escondida" para quem tem `view_opportunities` só porque
pertence a outro `owner` — a permissão é a fronteira, não a posse. Um
usuário SEM `view_opportunities` nunca alcança nenhuma destas views
(bloqueado por `PermissionRequiredMixin` antes de qualquer query rodar),
então PK sequencial não vaza nada para quem não tem a permissão de ver
oportunidades (proteção IDOR real é "a permissão", não "esconder o PK").
"""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.postgres.search import TrigramWordSimilarity
from django.core.exceptions import PermissionDenied
from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Greatest
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import SuperuserRequiredMixin
from apps.attachments.models import Attachment
from apps.attachments.services import attachments_for
from apps.catalog.models import EquipmentModel
from apps.clients.models import Client
from apps.core.forms import HardDeleteConfirmForm
from apps.core.hard_delete import HardDeleteBlocked
from apps.core.templatetags.currency import format_brl
from apps.crm.forms import (
    AcceptProposalVersionForm,
    ActivityTypeForm,
    CommercialActivityForm,
    CommercialSourceForm,
    DocumentGenerationForm,
    EquipmentLinkForm,
    EquipmentUnlinkForm,
    LossReasonForm,
    OpportunityCreateForm,
    OpportunityStageChangeForm,
    OpportunityStageForm,
    OpportunityUpdateForm,
    PriceTableItemForm,
    PriceTableRateForm,
    ProposalConditionsForm,
    ProposalInstallmentForm,
    ProposalItemForm,
    ServiceCatalogItemForm,
)
from apps.crm.models import (
    ActivityType,
    BillingMode,
    BusinessType,
    CommercialPlan,
    CommercialSource,
    CommercialTerm,
    LossReason,
    Opportunity,
    OpportunityEquipment,
    OpportunityStage,
    PriceTableItem,
    PriceTableRate,
    ProposalItem,
    ProposalVersionInstallment,
    ServiceCatalogItem,
)
from apps.crm.services import (
    DocumentType,
    LinkEquipmentData,
    NewActivityData,
    NewOpportunityData,
    OpportunityUpdateData,
    PriceTableItemData,
    PriceTableRateData,
    ProposalConditionsData,
    ProposalInstallmentData,
    ProposalItemData,
    UnlinkEquipmentData,
    acceptable_proposal_versions,
    accept_proposal_version,
    add_installment,
    add_proposal_item,
    build_opportunity_timeline,
    change_opportunity_stage,
    check_availability,
    check_payment_reconciliation,
    OBSERVATION_ACTIVITY_TYPE_CODE,
    create_activity,
    create_opportunity,
    ensure_editable_installment,
    ensure_editable_item,
    ensure_editable_version,
    generate_documents,
    get_observation_activity_type,
    get_or_create_active_proposal,
    get_suggested_price,
    hard_delete_opportunity,
    link_equipment_to_opportunity,
    linked_equipment_for,
    list_commercial_plans,
    list_price_table_matrix,
    list_price_table_rows,
    next_installment_suggestion,
    preview_opportunity_hard_delete,
    remove_installment,
    remove_proposal_item,
    set_price_table_item,
    set_price_table_rate,
    unlink_equipment_from_opportunity,
    update_draft_conditions,
    update_installment,
    update_opportunity,
    update_proposal_item,
)
from apps.equipment.filters import filter_equipment_queryset
from apps.equipment.models import Equipment, Status as EquipmentStatus
from apps.operations.models import Location, LocationType

# ---------------------------------------------------------------------------
# Oportunidades
# ---------------------------------------------------------------------------


def _filtered_opportunities_queryset(params):
    """
    Filtro compartilhado de Oportunidades — fonte ÚNICA de "quais
    oportunidades entram na conta", usada tanto pelo Kanban
    (`OpportunityListView`, agrupamento por etapa) quanto pelo endpoint
    AJAX de mudança de etapa (`OpportunityStageChangeView`, para
    recalcular os totais de origem/destino respeitando os MESMOS filtros
    ativos na tela no momento do arraste — sem isso, o total da coluna
    "piscaria" fora de sincronia com o que o usuário está vendo filtrado).

    `params` é qualquer `QueryDict`-like com `.get()` (`request.GET` nas
    duas chamadoras — o endpoint AJAX recebe os filtros ativos na própria
    querystring da URL de POST, ver `static/crm/kanban.js`).

    Sem filtro por `stage` aqui (diferente da antiga listagem em tabela):
    no Kanban a própria COLUNA já é a etapa — filtrar por etapa além
    disso não faria sentido estrutural nenhum, e por isso o seletor de
    "Etapa" foi removido da tela (decisão de produto, 11/09/2026).
    """
    qs = Opportunity.objects.select_related("client", "owner", "source", "stage")

    owner = params.get("owner", "")
    source = params.get("source", "")
    business_type = params.get("business_type", "")
    client = params.get("client", "")
    q = params.get("q", "").strip()

    # owner/source/client filtram por PK (FK) — um valor não numérico
    # (ex.: "?owner=abc", URL adulterada à mão) faria o ORM levantar
    # ValueError ao preparar o lookup (500 em vez de simplesmente ignorar
    # um filtro inválido). Mesmo cuidado já aplicado em
    # apps.equipment.filters.filter_equipment_queryset para
    # category/model — ignora silenciosamente, não propaga erro.
    if owner and owner.isdigit():
        qs = qs.filter(owner_id=owner)
    if source and source.isdigit():
        qs = qs.filter(source_id=source)
    if business_type:
        qs = qs.filter(business_type=business_type)
    if client and client.isdigit():
        qs = qs.filter(client_id=client)
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(client__company_name__icontains=q) | Q(client__trade_name__icontains=q)
        )
    return qs


def _default_new_opportunity_stage():
    """
    Etapa inicial sugerida ao ABRIR "Nova oportunidade" (drawer OU rota
    tradicional) — UX pedida na rodada de 11/09/2026 ("criação rápida em
    drawer"): a primeira etapa ATIVA pela ordem configurada que não seja
    de ganho nem de perda. Puramente uma SUGESTÃO de `initial=` no form —
    nunca hardcoded ("ORÇAMENTO" ou qualquer nome fixo), nunca contorna a
    validação real: `OpportunityCreateForm.stage` continua restrito ao
    MESMO queryset (`is_active=True, is_won=False, is_lost=False`) e
    `apps.crm.services.create_opportunity()` continua sendo quem de fato
    rejeita qualquer etapa de ganho/perda/inativa — esta função só decide
    QUAL etapa desse conjunto já vem pré-marcada no `<select>`, o usuário
    pode sempre trocar por outra etapa elegível antes de criar. Se não
    houver nenhuma etapa elegível configurada, retorna `None` e o campo
    nasce sem seleção (mesmo comportamento de hoje).
    """
    return (
        OpportunityStage.objects.filter(is_active=True, is_won=False, is_lost=False)
        .order_by("order", "name")
        .first()
    )


def _new_opportunity_create_form(data=None):
    """
    Fábrica única do `OpportunityCreateForm` "em branco" (GET) — usada
    tanto pela rota tradicional (`OpportunityCreateView.get`) quanto pelo
    Kanban (`OpportunityListView.get`, para o drawer) — para as duas
    nascerem com a MESMA etapa inicial sugerida (`_default_new_opportunity_
    stage`), nunca divergindo entre os dois pontos de entrada. `data`
    (POST) nunca passa por aqui — um form BOUND nunca deve ter `initial`
    reaplicado por cima do que o usuário enviou.
    """
    initial = {}
    default_stage = _default_new_opportunity_stage()
    if default_stage is not None:
        initial["stage"] = default_stage.pk
    return OpportunityCreateForm(initial=initial)


def _stage_summary(stage, params):
    """
    Contagem + valor total consolidado de uma etapa, respeitando os
    filtros ativos (`params`) — usado pelo endpoint AJAX para devolver os
    totais atualizados de origem/destino depois de um arraste, sem o
    front precisar duplicar nenhuma lógica de soma/formatação (mesma
    função `format_brl` usada em todo o resto do sistema).

    Mesma regra de `display_value` do Kanban: valor de fechamento se a
    oportunidade já está fechada (ganha), senão o valor estimado (ou zero
    se nenhum dos dois foi informado) — nunca os dois somados.
    """
    stage_opportunities = _filtered_opportunities_queryset(params).filter(stage_id=stage.pk)
    total = Decimal(0)
    count = 0
    for opportunity in stage_opportunities:
        count += 1
        total += opportunity.closed_value if opportunity.closed_value is not None else (opportunity.estimated_value or Decimal(0))
    return {"id": stage.pk, "count": count, "total_value_display": format_brl(total)}


class OpportunityListView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Funil Kanban de oportunidades — SUBSTITUI por completo a antiga
    listagem em tabela paginada (decisão de produto, 11/09/2026: "Kanban
    substitui a listagem por completo"). Continua no MESMO nome de
    view/URL/endpoint (`crm:opportunity_list`, `/crm/oportunidades/`) —
    nenhum link/teste existente para a listagem precisa mudar de destino.

    Sem paginação: um funil mostra TODAS as oportunidades do filtro
    corrente, agrupadas por etapa — "próxima página" não é um conceito
    que existe num Kanban. Em volume muito grande isso pode significar
    uma coluna com scroll interno longo; nenhum "carregar mais" por
    coluna foi pedido nesta rodada.
    """

    permission_required = "crm.view_opportunities"

    def get(self, request):
        opportunities = list(_filtered_opportunities_queryset(request.GET).order_by("-created_at"))

        # `display_value`: MESMA regra usada em `_stage_summary` acima —
        # atributo calculado em memória (nunca gravado no banco), só para
        # o template não repetir a mesma expressão condicional em cada
        # card.
        for opportunity in opportunities:
            opportunity.display_value = (
                opportunity.closed_value if opportunity.closed_value is not None else (opportunity.estimated_value or Decimal(0))
            )

        opportunities_by_stage = {}
        for opportunity in opportunities:
            opportunities_by_stage.setdefault(opportunity.stage_id, []).append(opportunity)

        columns = []
        for stage in OpportunityStage.objects.filter(is_active=True).order_by("order", "name"):
            stage_opportunities = opportunities_by_stage.get(stage.pk, [])
            total = sum((o.display_value for o in stage_opportunities), Decimal(0))
            columns.append(
                {
                    "stage": stage,
                    "opportunities": stage_opportunities,
                    "count": len(stage_opportunities),
                    "total_value_display": format_brl(total),
                }
            )

        can_add_opportunity = request.user.has_perm("crm.add_opportunities")
        context = {
            "columns": columns,
            "sources": CommercialSource.objects.filter(is_active=True).order_by("order", "name"),
            "business_type_choices": Opportunity._meta.get_field("business_type").choices,
            "selected_source": request.GET.get("source", ""),
            "selected_business_type": request.GET.get("business_type", ""),
            "q": request.GET.get("q", ""),
            "can_change_stage": request.user.has_perm("crm.change_opportunity_stage"),
            "can_add_opportunity": can_add_opportunity,
            # Form de criação rápida embutido no drawer lateral do Kanban
            # (rodada "CRIAÇÃO RÁPIDA SEM SAIR DO FUNIL", 11/09/2026) — só
            # instanciado (e só as queries de `client`/`owner`/`source`/
            # `stage` elegíveis disparadas) para quem TEM a permissão;
            # sem permissão nenhuma nem o botão "+ Nova oportunidade"
            # aparece no template. Mesmo form/mesma fábrica usados pela
            # rota tradicional (`OpportunityCreateView.get`) — nunca uma
            # segunda definição de campos.
            "create_form": _new_opportunity_create_form() if can_add_opportunity else None,
            "can_manage_settings": request.user.has_perm("crm.manage_commercial_settings"),
            # Embutido via `json_script` no template para o JS de
            # drag-and-drop montar o <select> de motivo de perda do modal
            # exigido ao soltar um card numa etapa `is_lost` — nunca
            # interpolado cru (XSS-safe, mesmo padrão de `json_script` do
            # próprio Django).
            "loss_reasons": list(LossReason.objects.filter(is_active=True).order_by("order", "name").values("id", "name")),
        }
        return render(request, "crm/opportunity_list.html", context)


class OpportunityDetailView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.view_opportunities"

    def get(self, request, pk):
        opportunity = get_object_or_404(
            Opportunity.objects.select_related("client", "owner", "source", "stage", "loss_reason", "created_by"),
            pk=pk,
        )
        stage_changes = opportunity.stage_changes.select_related("from_stage", "to_stage", "changed_by")

        # `view_commercial_activities` é uma Permission PRÓPRIA — mesmo
        # tendo `view_opportunities` (chegou até aqui), um usuário sem
        # `view_commercial_activities` nunca recebe as atividades no
        # contexto: a checagem é no BACKEND (aqui), não só escondida no
        # template — evita vazar descrição/observação de atividade
        # comercial por qualquer variável de contexto acessível.
        can_view_activities = request.user.has_perm("crm.view_commercial_activities")
        activities = (
            # `select_related("activity_type")` desde a RODADA 3
            # (14/09/2026): `activity_type` virou FK (antes era um
            # `TextChoices` sem join nenhum) — sem isso, `{{
            # activity.activity_type.name }}` no template dispararia uma
            # query por linha (N+1).
            opportunity.activities.select_related("created_by", "activity_type").order_by("-created_at")
            if can_view_activities
            else opportunity.activities.none()
        )
        # Já vem ordenada `-created_at` acima — o primeiro item é sempre o
        # mais recente. `None` (nunca uma string vazia) quando não há
        # nenhuma atividade OU quando o usuário não tem
        # `view_commercial_activities`, para o template distinguir
        # "sem atividade" de "sem permissão para ver".
        last_activity = activities.first() if can_view_activities else None

        # Observações (Visão Geral) — RODADA 3 DE REFINAMENTOS (14/09/2026).
        # REAPROVEITA `CommercialActivity` (nenhum model novo de notas):
        # é o mesmo `activities` já filtrado por permissão acima, só
        # restrito ao tipo "Observação". `observation_activity_type` pode
        # ser `None` se a migration de seed (`0004_seed_activitytype`)
        # ainda não rodou no ambiente — nesse caso o botão "+" fica
        # oculto em vez de quebrar a página (`can_add_observation` exige
        # o tipo existir).
        try:
            observation_activity_type = get_observation_activity_type()
        except ActivityType.DoesNotExist:
            observation_activity_type = None
        observations = activities.filter(activity_type=observation_activity_type) if observation_activity_type else activities.none()
        can_add_observation = bool(observation_activity_type) and request.user.has_perm("crm.add_commercial_activities")

        can_change_stage = request.user.has_perm("crm.change_opportunity_stage")

        # REDESIGN COMPLETO DA TELA INTERNA DA OPORTUNIDADE (12/09/2026):
        # "Registrar perda"/"Orçamento aceito" nunca hardcodeiam qual
        # etapa é ganho/perda — sempre a CONFIGURAÇÃO real (`is_won`/
        # `is_lost`, só entre etapas ATIVAS). Zero, uma ou várias etapas
        # podem estar marcadas (ver docstring de `OpportunityStage`) — os
        # botões só aparecem quando existe pelo menos uma candidata, e a
        # tela apresenta um `<select>` dentro do modal quando há mais de
        # uma (nunca escolhe sozinha por nome/heurística).
        # Materializadas em lista (não querysets "vivos") de propósito:
        # o template reusa cada uma mais de uma vez (contagem para
        # decidir select-com-múltiplas-opções vs. campo único, iteração
        # das opções, valor da única candidata) — uma lista evita repetir
        # a mesma consulta a cada uso, ao contrário de um QuerySet.
        won_stages = list(OpportunityStage.objects.filter(is_active=True, is_won=True).order_by("order", "name"))
        lost_stages = list(OpportunityStage.objects.filter(is_active=True, is_lost=True).order_by("order", "name"))
        all_active_stages = list(OpportunityStage.objects.filter(is_active=True).order_by("order", "name"))

        # A interface precisa refletir o estado JÁ alcançado: uma
        # oportunidade já perdida não mostra "Registrar perda" como se
        # ainda estivesse aberta, e vice-versa para "Orçamento aceito"
        # (pedido explícito). A ação OPOSTA continua disponível — reabrir
        # por engano é uma mudança de etapa normal, já suportada pelo
        # `change_opportunity_stage()` (semântica de "reabertura").
        can_show_registrar_perda = can_change_stage and bool(lost_stages) and not opportunity.stage.is_lost
        can_show_orcamento_aceito = can_change_stage and bool(won_stages) and not opportunity.stage.is_won

        # "Retomar negociação" (seção 52-59, RODADA 3, 14/09/2026) — nova
        # ação visível SOMENTE quando a oportunidade já está ganha. Etapa
        # de destino: NUNCA hardcoda um nome — usa `open_stages` (ativas,
        # nem ganho nem perda), calculado no view do MESMO jeito que
        # `won_stages`/`lost_stages` (zero/uma/várias candidatas — mesma
        # lógica de exibição do `<select>` vs. campo único). Reabrir usa o
        # MESMO `change_opportunity_stage()`/endpoint de sempre — já limpa
        # won_at/lost_at/loss_reason/loss_notes/closed_value ao mover para
        # uma etapa intermediária, então nenhum serviço novo é necessário.
        open_stages = [s for s in all_active_stages if not s.is_won and not s.is_lost]
        can_show_retomar_negociacao = can_change_stage and bool(open_stages) and opportunity.stage.is_won

        # ------------------------------------------------------------
        # Produtos e Serviços (14/09/2026) — a composição comercial é
        # sempre a Proposal mais recente da Opportunity (ver docstring
        # de `get_or_create_active_proposal`). GET nunca cria nada por
        # conta própria: só quem já tem `crm.change_opportunities`
        # (poder de editar) dispara a criação lazy; quem só tem
        # `crm.view_opportunities` vê a composição já existente, ou um
        # estado vazio se ainda não existe nenhuma.
        # ------------------------------------------------------------
        can_change_opportunity = request.user.has_perm("crm.change_opportunities")
        can_issue_proposal = request.user.has_perm("crm.issue_proposal_documents")
        can_generate_contract = request.user.has_perm("crm.generate_contract")

        proposal = None
        current_version = None
        if can_change_opportunity:
            proposal = get_or_create_active_proposal(opportunity=opportunity, created_by=request.user)
        else:
            proposal = opportunity.proposals.order_by("-created_at").first()
        if proposal is not None:
            current_version = proposal.latest_version

        # RODADA 4 (REFINAMENTO DA COMPOSIÇÃO COMERCIAL, 15/09/2026,
        # seção 9-14): `item_form`/`conditions_form` deixaram de exigir
        # `current_version.is_editable` — o usuário precisa conseguir
        # continuar adicionando/removendo item e alterando condições
        # mesmo quando a versão mais recente já foi emitida; a PRIMEIRA
        # mutação de fato (POST) é quem decide clonar automaticamente uma
        # nova versão DRAFT (`ensure_editable_version()`/
        # `ensure_editable_item()`, ver services.py) — abrir/recarregar
        # esta página (GET) nunca cria uma versão nova por si só (seção
        # 11/12, "lazy": "não criar versão apenas porque o usuário abriu
        # a tela").
        item_form = ProposalItemForm() if (can_change_opportunity and current_version) else None
        # RODADA 4 (CORREÇÃO — "Local de entrega/operação", 15/09/2026,
        # seção 6): se a versão AINDA não tem `delivery_location` salvo e
        # o cliente da Oportunidade tem exatamente UMA unidade ativa,
        # pré-seleciona essa unidade no `initial` — o campo continua
        # sendo um `<select>` normal mostrando claramente qual local será
        # usado (nunca escondido/automático demais); se a versão já tem
        # um valor salvo (mesmo de uma unidade que não é mais a única),
        # esse valor sempre prevalece.
        initial_delivery_location = None
        if current_version is not None:
            if current_version.delivery_location_id:
                initial_delivery_location = current_version.delivery_location_id
            else:
                client_locations = list(
                    Location.objects.filter(is_active=True, type=LocationType.CLIENTE, client=opportunity.client).values_list(
                        "pk", flat=True
                    )[:2]
                )
                if len(client_locations) == 1:
                    initial_delivery_location = client_locations[0]
        conditions_form = (
            ProposalConditionsForm(
                initial={
                    # "Tabela de preço"/"Outra forma"/"Condição" não são
                    # mais campos deste form (REFINAMENTO VISUAL,
                    # 14/09/2026) — omitidos aqui de propósito; os valores
                    # persistidos continuam intactos no banco (ver
                    # `ProposalConditionsSaveView.post()`), só não fazem
                    # mais parte do `initial` de exibição.
                    "payment_method": current_version.payment_method,
                    "commercial_plan": current_version.commercial_plan_id,
                    "event_name": current_version.event_name,
                    "onsite_responsible_name": current_version.onsite_responsible_name,
                    "onsite_responsible_phone": current_version.onsite_responsible_phone,
                    "contracted_start_date": current_version.contracted_start_date,
                    "contracted_end_date": current_version.contracted_end_date,
                    "expected_delivery_date": current_version.expected_delivery_date,
                    "expected_delivery_time": current_version.expected_delivery_time,
                    "expected_pickup_date": current_version.expected_pickup_date,
                    "expected_pickup_time": current_version.expected_pickup_time,
                    "delivery_location": initial_delivery_location,
                    "general_discount": current_version.general_discount,
                    "interest_amount": current_version.interest_amount,
                    "freight_amount": current_version.freight_amount,
                    "special_clauses": current_version.special_clauses,
                    "payment_info_notes": current_version.payment_info_notes,
                    "general_notes": current_version.general_notes,
                },
                opportunity=opportunity,
            )
            if (can_change_opportunity and current_version)
            else None
        )
        # `document_form` aparece quando existe uma versão com pelo menos
        # um item — mesmo em rascunho, já que "Gerar documento" emite
        # automaticamente se ainda estiver em rascunho (ver
        # `generate_documents()`).
        document_form = (
            DocumentGenerationForm()
            if (current_version is not None and current_version.items.exists() and (can_issue_proposal or can_generate_contract))
            else None
        )

        # RODADA 4 (15/09/2026, seção 1-4/34): o bloco "Aceite" (aceitar
        # uma `ProposalVersion` específica) SAIU da interface — o único
        # CTA de aceite comercial visível continua sendo "Orçamento
        # aceito" no topo da página (`can_show_orcamento_aceito` acima,
        # via `change_opportunity_stage()`). O backend de
        # `accept_proposal_version()`/`ProposalAcceptVersionView`/
        # `AcceptProposalVersionForm` NÃO foi removido (seção 2: "não
        # remover o aceite real do sistema") — só não tem mais nenhum
        # gatilho de UI nesta tela; por isso `candidate_versions`/
        # `accept_form` deixaram de ser calculados aqui (nada mais os
        # consome).

        # ------------------------------------------------------------
        # Equipamentos (RODADA 3, 14/09/2026, seção 60-68) — vincular
        # patrimônio real via `create_movement()` (ver `apps.crm.services.
        # link_equipment_to_opportunity()`/`unlink_equipment_from_
        # opportunity()`). "CRM/comercial pode VER, Operação pode
        # vincular/devolver": ver (esta aba) já está coberto por
        # `crm.view_opportunities` (exigido para alcançar esta view
        # inteira); a ESCRITA (vincular/desvincular) reaproveita
        # `operations.register_operations` — a MESMA Permission que já
        # existe desde a Fase 1 (mirror de `CAN_REGISTER_OPERATIONS`) para
        # "manutenção/higienização/movimentação" — nenhuma Permission nova
        # criada para esta aba.
        #
        # O botão "+ Vincular equipamento" só aparece quando existe pelo
        # menos uma Location do tipo Cliente cadastrada para O CLIENTE
        # desta Oportunidade (senão não haveria nenhum destino válido para
        # a instalação) — mesmo raciocínio "zero/uma/várias candidatas" já
        # usado para won_stages/lost_stages/open_stages acima.
        can_link_equipment = request.user.has_perm("operations.register_operations")
        equipment_links = list(linked_equipment_for(opportunity))
        client_install_locations = (
            list(
                Location.objects.filter(is_active=True, type=LocationType.CLIENTE, client_id=opportunity.client_id).order_by(
                    "name"
                )
            )
            if can_link_equipment
            else []
        )
        can_show_link_equipment = can_link_equipment and bool(client_install_locations)
        link_equipment_form = EquipmentLinkForm(opportunity=opportunity) if can_show_link_equipment else None
        unlink_equipment_form = EquipmentUnlinkForm() if can_link_equipment else None

        # `OpportunityDetailView.permission_required` já exige
        # `crm.view_opportunities` para chegar até aqui — nenhuma
        # checagem extra necessária para listar os anexos (Anexos ainda
        # não tem sua própria Permission de leitura nesta rodada, ver
        # docstring de `apps.attachments.models.Attachment`).
        attachments = list(attachments_for(opportunity))
        timeline = build_opportunity_timeline(opportunity)

        # Download automático do PDF logo após "Gerar orçamento"/"Gerar
        # contrato" (seção 30-51, RODADA 3, 14/09/2026):
        # `ProposalGenerateDocumentView` redireciona para cá com
        # `?baixar_pdf=<attachment_pk>` — nunca um id "confiado" cru: só
        # vira `auto_download_url` se o Anexo existir E pertencer a ESTA
        # Opportunity (mesma checagem de posse de `AttachmentDownloadView`).
        # O disparo em si é só JS de conveniência no template (um
        # download real via `Content-Disposition: attachment`, nunca
        # `fetch`/AJAX) — a AUTORIDADE de acesso continua 100% em
        # `AttachmentDownloadView`.
        auto_download_url = None
        download_attachment_id = request.GET.get("baixar_pdf")
        if download_attachment_id:
            candidate = next((a for a in attachments if str(a.pk) == download_attachment_id), None)
            if candidate is not None:
                auto_download_url = reverse("crm:attachment_download", args=[opportunity.pk, candidate.pk])

        context = {
            "opportunity": opportunity,
            "stage_changes": stage_changes,
            "timeline": timeline,
            "auto_download_url": auto_download_url,
            "activities": activities,
            "last_activity": last_activity,
            "observations": observations,
            "can_add_observation": can_add_observation,
            "observation_activity_type": observation_activity_type,
            "can_view_activities": can_view_activities,
            "can_change_opportunity": can_change_opportunity,
            "can_change_stage": can_change_stage,
            "can_add_activity": request.user.has_perm("crm.add_commercial_activities"),
            "stage_change_form": OpportunityStageChangeForm() if can_change_stage else None,
            "activity_form": CommercialActivityForm() if can_view_activities and request.user.has_perm("crm.add_commercial_activities") else None,
            "won_stages": won_stages,
            "lost_stages": lost_stages,
            "all_active_stages": all_active_stages,
            "can_show_registrar_perda": can_show_registrar_perda,
            "can_show_orcamento_aceito": can_show_orcamento_aceito,
            "open_stages": open_stages,
            "can_show_retomar_negociacao": can_show_retomar_negociacao,
            # Produtos e Serviços
            "proposal": proposal,
            "current_version": current_version,
            "proposal_items": (
                current_version.items.select_related("equipment_model", "service") if current_version else []
            ),
            "item_form": item_form,
            "conditions_form": conditions_form,
            "document_form": document_form,
            "can_issue_proposal": can_issue_proposal,
            "can_generate_contract": can_generate_contract,
            # Condições de pagamento / parcelas (FECHAMENTO DA PROPOSTA
            # COMERCIAL, 23/09/2026, seção 18/23) — mesmo `current_version`
            # de Produtos e Serviços; `installment_form` só aparece quando
            # existe uma versão editável para não oferecer "Adicionar
            # parcela" sem ter onde salvar (mesmo raciocínio de `item_form`).
            "installments": current_version.installments.all() if current_version else [],
            # `prefix="parcela"` (seção 18): `ProposalInstallmentForm.
            # payment_method_other` tem o MESMO nome de campo que existia
            # em `ProposalConditionsForm` (removido da UI, mas o `id`
            # HTML default de um `Form` é só `id_<nome do campo>` — sem
            # prefixo, duas instâncias de formulário na MESMA página com
            # um campo de mesmo nome colidiriam no MESMO `id`, HTML
            # inválido/acessibilidade quebrada, mesmo sem relação nenhuma
            # com a Proposta em si).
            "installment_form": ProposalInstallmentForm(prefix="parcela") if (can_change_opportunity and current_version) else None,
            "installment_suggestion": (
                next_installment_suggestion(proposal_version=current_version) if current_version else None
            ),
            "payment_reconciliation": (
                check_payment_reconciliation(current_version) if current_version else None
            ),
            # Equipamentos
            "equipment_links": equipment_links,
            "can_link_equipment": can_link_equipment,
            "can_show_link_equipment": can_show_link_equipment,
            "link_equipment_form": link_equipment_form,
            "unlink_equipment_form": unlink_equipment_form,
            # Anexos
            "attachments": attachments,
        }
        return render(request, "crm/opportunity_detail.html", context)


class OpportunityCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Rota tradicional de criação — MANTIDA de propósito (rodada "CRIAÇÃO
    RÁPIDA EM DRAWER", 11/09/2026: "NÃO remover automaticamente a rota
    tradicional... pode continuar existindo como fallback/compatibilidade/
    acesso direto"). Serve três papéis agora: (1) acesso direto por URL/
    bookmark; (2) fallback sem JavaScript — o botão "+ Nova oportunidade"
    do Kanban continua sendo um `<a href>` de verdade para esta MESMA URL,
    só interceptado por JS quando disponível (ver templates/crm/
    opportunity_list.html + static/crm/opportunity_quick_create.js); (3)
    resposta ao POST do PRÓPRIO drawer, via `fetch()` para esta mesma URL
    — o drawer não é uma arquitetura paralela, é o MESMO endpoint, só
    detectado pelo cabeçalho `X-Requested-With: XMLHttpRequest` (idêntico
    ao padrão já usado em `OpportunityStageChangeView`) para decidir a
    FORMA da resposta:
      - GET sempre continua devolvendo a página cheia (o drawer nunca
        busca este form via AJAX — nasce já embutido no HTML do Kanban,
        ver `OpportunityListView.get`, para abrir instantaneamente sem
        round-trip extra);
      - POST inválido: AJAX recebe só o FRAGMENTO de campos (com erros
        bound, re-injetado no drawer sem fechar/perder o que já foi
        digitado); não-AJAX continua recebendo a página cheia de sempre;
      - POST válido: AJAX recebe JSON (card pronto + resumo da coluna,
        para o Kanban se atualizar sem recarregar); não-AJAX continua
        com o redirect + mensagem de sempre.
    Em NENHUM dos dois caminhos a validação ou a regra de negócio muda —
    os dois chamam exatamente o mesmo `OpportunityCreateForm` e o mesmo
    `apps.crm.services.create_opportunity()`.
    """

    permission_required = "crm.add_opportunities"

    def get(self, request):
        return render(request, "crm/opportunity_form.html", {"form": _new_opportunity_create_form(), "is_new": True})

    def post(self, request):
        form = OpportunityCreateForm(request.POST)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if not form.is_valid():
            if is_ajax:
                return render(request, "crm/_opportunity_quick_create_fields.html", {"form": form}, status=400)
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": True})

        cleaned = form.cleaned_data
        try:
            opportunity = create_opportunity(
                NewOpportunityData(
                    client=cleaned["client"],
                    title=cleaned["title"],
                    owner=cleaned["owner"],
                    source=cleaned["source"],
                    business_type=cleaned["business_type"],
                    stage=cleaned["stage"],
                    created_by=request.user,
                    # "Valor estimado"/"Previsão de fechamento" REMOVIDOS da
                    # criação (pedido de 12/09/2026: "quando colocarmos os
                    # equipamentos os valores vão puxar automático" — não
                    # tem necessidade de pedir na criação). `NewOpportunityData`
                    # já tem os dois como `None` por padrão — continuam
                    # editáveis depois via `OpportunityUpdateForm`, que NÃO
                    # foi tocado; só a criação ficou mais enxuta.
                    notes=cleaned["notes"],
                )
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            if is_ajax:
                return render(request, "crm/_opportunity_quick_create_fields.html", {"form": form}, status=400)
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": True})

        if is_ajax:
            # Mesma regra de `display_value` de `OpportunityListView`/
            # `_stage_summary` — uma oportunidade recém-criada nunca tem
            # `closed_value` (não pode nascer ganha/perdida, ver
            # `create_opportunity`), mas a expressão completa é repetida
            # aqui por clareza/defesa em profundidade, não só `estimated_
            # value`.
            opportunity.display_value = (
                opportunity.closed_value if opportunity.closed_value is not None else (opportunity.estimated_value or Decimal(0))
            )
            card_html = render_to_string(
                "crm/_opportunity_kanban_card.html",
                {
                    "opportunity": opportunity,
                    "stage": opportunity.stage,
                    "can_change_stage": request.user.has_perm("crm.change_opportunity_stage"),
                },
                request=request,
            )
            # A oportunidade recém-criada só é inserida visualmente no
            # Kanban se ela também passaria pelos FILTROS ativos no
            # momento (busca/origem/tipo de negócio, os mesmos 3 campos
            # da toolbar) — mesma fonte única de verdade do resto da
            # tela (`_filtered_opportunities_queryset`), nunca uma cópia
            # da lógica de filtro reimplementada em JS. Criada no banco
            # de qualquer forma; só a apresentação imediata respeita o
            # filtro corrente (ver static/crm/opportunity_quick_create.js).
            matches_current_filters = _filtered_opportunities_queryset(request.GET).filter(pk=opportunity.pk).exists()
            return JsonResponse(
                {
                    "ok": True,
                    "message": f"Oportunidade \"{opportunity.title}\" criada.",
                    "stage_id": opportunity.stage_id,
                    "matches_current_filters": matches_current_filters,
                    "destination_stage": _stage_summary(opportunity.stage, request.GET),
                    "card_html": card_html,
                }
            )

        messages.success(request, f"Oportunidade \"{opportunity.title}\" criada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class OpportunityClientAutocompleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Endpoint pequeno e específico de busca de `Client` para o campo
    "Cliente" da criação de oportunidade (CORRIGIR DEFINITIVAMENTE O
    CAMPO CLIENTE — AUTOCOMPLETE PESQUISÁVEL, 12/09/2026). Substitui o
    `<select>` nativo que carregava TODOS os clientes ativos de uma vez
    por uma busca sob demanda: no máximo `RESULT_LIMIT` resultados por
    requisição, nunca a listagem completa — continua rápido com 700,
    2.000 ou 10.000 clientes porque a página NUNCA recebe a lista
    inteira, só o que o usuário efetivamente digitou.

    Só GET, exigindo `crm.add_opportunities` — a MESMA permissão já
    exigida para alcançar as duas telas onde o campo "Cliente" aparece
    (`/crm/oportunidades/nova/` e o drawer do Kanban). `client` não
    existe em `OpportunityUpdateForm` (é imutável depois de criada a
    oportunidade — ver docstring de `OpportunityCreateForm`), então
    nenhuma outra permissão precisa ser considerada aqui.

    Query com menos de `MIN_QUERY_LENGTH` caracteres devolve uma lista
    vazia SEM consultar o banco — não é um erro, é o estado normal
    enquanto o usuário ainda está digitando (o front-end já nem chega a
    disparar a requisição antes de 3 caracteres; esta checagem aqui é
    defesa em profundidade, nunca a única camada). Resposta
    deliberadamente mínima ("Não retornar dados fiscais completos"): só
    `id` e `name` (nome de exibição via `Client.display_name()` — nome
    fantasia, senão razão social, senão o próprio CNPJ), nunca
    documento/telefone/e-mail/endereço.

    Ordenação em 3 níveis, pedido explícito ("não resultados
    aleatórios"): (0) prefixo exato — nome ou CNPJ começam com o texto
    digitado; (1) contém — o texto aparece em qualquer posição; (2)
    similaridade aproximada real via `pg_trgm`/`TrigramWordSimilarity`
    (extensão ativada em `apps/clients/migrations/0006_pg_trgm_
    extension.py`, recurso NATIVO do Postgres, zero infraestrutura
    nova) — cobre erro de digitação/abreviação sem cair em substring
    puro nem em resultado aleatório. Dentro de cada nível, desempate por
    nome (ordem alfabética estável).

    `TrigramWordSimilarity` (Postgres `word_similarity()`), NÃO
    `TrigramSimilarity` (Postgres `similarity()`) — deliberado, medido
    manualmente contra o próprio exemplo da especificação ("KAU" deve
    achar também "Komodoro Ind"/"Kurizaki", que não contêm "kau"):
    `similarity('kau', 'komodoro ind')` ≈ 0.06 e `similarity('kau',
    'kurizaki')` ≈ 0.08 — abaixo de qualquer limiar útil sem também
    deixar passar ruído (`similarity()` penaliza demais a diferença de
    tamanho entre uma busca curta e um nome de cliente longo).
    `word_similarity('kau', 'komodoro ind')`/`word_similarity('kau',
    'kurizaki')` ≈ 0.25 (mede o melhor trecho contínuo do nome que se
    parece com a busca, em vez do nome inteiro) — já `word_similarity('kau',
    'construtora abc ltda')` = 0.0, então o limiar abaixo continua sem
    devolver nomes sem nenhuma relação real com o texto digitado.
    """

    permission_required = "crm.add_opportunities"

    RESULT_LIMIT = 20
    MIN_QUERY_LENGTH = 3
    SIMILARITY_THRESHOLD = 0.2

    def get(self, request):
        q = request.GET.get("q", "").strip()
        if len(q) < self.MIN_QUERY_LENGTH:
            return JsonResponse({"results": []})

        contains_q = Q(trade_name__icontains=q) | Q(company_name__icontains=q) | Q(document__icontains=q)
        starts_q = Q(trade_name__istartswith=q) | Q(company_name__istartswith=q) | Q(document__istartswith=q)

        clients = (
            Client.objects.filter(is_active=True)
            .annotate(
                similarity=Greatest(
                    TrigramWordSimilarity(q, "trade_name"),
                    TrigramWordSimilarity(q, "company_name"),
                    TrigramWordSimilarity(q, "document"),
                )
            )
            .filter(contains_q | Q(similarity__gte=self.SIMILARITY_THRESHOLD))
            .annotate(
                priority=Case(
                    When(starts_q, then=Value(0)),
                    When(contains_q, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            )
            .order_by("priority", "-similarity", "trade_name", "company_name")[: self.RESULT_LIMIT]
        )

        results = [{"id": client.pk, "name": client.display_name()} for client in clients]
        return JsonResponse({"results": results})


class OpportunityUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.change_opportunities"

    def get(self, request, pk):
        opportunity = get_object_or_404(Opportunity.objects.select_related("client", "owner", "source"), pk=pk)
        form = OpportunityUpdateForm(
            initial={
                "title": opportunity.title,
                "owner": opportunity.owner_id,
                "source": opportunity.source_id,
                "business_type": opportunity.business_type,
                "expected_close_date": opportunity.expected_close_date,
                "estimated_value": opportunity.estimated_value,
                "notes": opportunity.notes,
            },
            owner_instance=opportunity.owner,
            source_instance=opportunity.source,
        )
        return render(request, "crm/opportunity_form.html", {"form": form, "is_new": False, "opportunity": opportunity})

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity.objects.select_related("client", "owner", "source"), pk=pk)
        form = OpportunityUpdateForm(request.POST, owner_instance=opportunity.owner, source_instance=opportunity.source)
        if not form.is_valid():
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": False, "opportunity": opportunity})

        cleaned = form.cleaned_data
        try:
            update_opportunity(
                opportunity=opportunity,
                changed_by=request.user,
                data=OpportunityUpdateData(
                    title=cleaned["title"],
                    owner=cleaned["owner"],
                    source=cleaned["source"],
                    business_type=cleaned["business_type"],
                    expected_close_date=cleaned["expected_close_date"],
                    estimated_value=cleaned["estimated_value"],
                    notes=cleaned["notes"],
                ),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": False, "opportunity": opportunity})

        messages.success(request, f"Oportunidade \"{opportunity.title}\" atualizada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class OpportunityHardDeleteView(SuperuserRequiredMixin, View):
    """
    Exclusão DEFINITIVA (hard delete) — restrita à "autoridade máxima"
    (`is_superuser` puro, nunca `crm.change_opportunities`/nenhuma outra
    Permission do catálogo; ver `apps.core.hard_delete` e
    `apps.crm.services.hard_delete_opportunity`). Único caminho de
    exclusão real de `Opportunity` no sistema — o model nem é
    `SoftDeleteModel` (ver docstring de `apps.crm.models.Opportunity`),
    então antes desta rodada não havia NENHUMA forma de remover uma
    oportunidade, nem de teste.
    """

    def get(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        impact = preview_opportunity_hard_delete(opportunity)
        return render(
            request,
            "crm/opportunity_hard_delete_confirm.html",
            {"opportunity": opportunity, "impact": impact, "form": HardDeleteConfirmForm()},
        )

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        impact = preview_opportunity_hard_delete(opportunity)
        form = HardDeleteConfirmForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "crm/opportunity_hard_delete_confirm.html",
                {"opportunity": opportunity, "impact": impact, "form": form},
            )

        try:
            result = hard_delete_opportunity(opportunity_id=opportunity.pk, actor=request.user)
        except HardDeleteBlocked as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        extra = f" ({result.total_dependents} registro(s) dependente(s) removido(s) junto.)" if result.total_dependents else ""
        messages.success(request, f"{result.target_label.capitalize()} foi excluída definitivamente.{extra}")
        return redirect("crm:opportunity_list")


class OpportunityStageChangeView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Só POST (deliberado — sem `get()`, então `GET` recebe 405 do próprio
    `django.views.View`): mudar etapa/ganhar/perder é sempre uma escrita,
    nunca uma navegação. Exige as DUAS permissões — ver a oportunidade E
    poder mudar sua etapa — para nunca alterar o estado de algo que o
    próprio usuário não teria como ver antes.

    MESMO endpoint para os dois fluxos da tela — o form inline da ficha
    da oportunidade (`opportunity_detail.html`, POST normal) E o
    arraste de card do Kanban (`static/crm/kanban.js`, POST via
    `fetch()`): a distinção é só a RESPOSTA (redirect+messages vs. JSON),
    nunca a validação nem a regra de negócio — as duas chamam exatamente
    o mesmo `OpportunityStageChangeForm` e o mesmo
    `apps.crm.services.change_opportunity_stage()`, então não existe
    nenhum caminho de escrita "mais permissivo" pelo Kanban. A detecção é
    pelo cabeçalho `X-Requested-With: XMLHttpRequest`, que
    `static/crm/kanban.js` sempre envia e o form HTML normal nunca envia
    (nenhum `fetch()`/`XMLHttpRequest` por trás de um `<form>` comum).
    """

    permission_required = ("crm.view_opportunities", "crm.change_opportunity_stage")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = OpportunityStageChangeForm(request.POST)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if not form.is_valid():
            errors = [error for field_errors in form.errors.values() for error in field_errors]
            if is_ajax:
                return JsonResponse(
                    {"ok": False, "error": " ".join(errors) or "Não foi possível mudar a etapa."}, status=400
                )
            messages.error(request, "Não foi possível mudar a etapa — corrija os erros abaixo.")
            for error in errors:
                messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        origin_stage = opportunity.stage
        try:
            change_opportunity_stage(
                opportunity_id=opportunity.pk,
                new_stage=cleaned["stage"],
                changed_by=request.user,
                reason=cleaned["reason"],
                loss_reason=cleaned["loss_reason"],
                loss_notes=cleaned["loss_notes"],
                closed_value=cleaned["closed_value"],
            )
        except ValueError as exc:
            if is_ajax:
                return JsonResponse({"ok": False, "error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        if is_ajax:
            # Os filtros ativos no Kanban no momento do arraste chegam na
            # própria querystring desta URL de POST (ver
            # `static/crm/kanban.js`) — `request.GET` os enxerga
            # normalmente mesmo numa requisição POST (Django sempre
            # analisa a querystring da URL, independente do método).
            return JsonResponse(
                {
                    "ok": True,
                    "message": f"Etapa alterada para \"{cleaned['stage'].name}\".",
                    "origin_stage": _stage_summary(origin_stage, request.GET),
                    "destination_stage": _stage_summary(cleaned["stage"], request.GET),
                }
            )

        messages.success(request, f"Etapa alterada para \"{cleaned['stage'].name}\".")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class CommercialActivityCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Só POST — registrar atividade é sempre uma escrita (ver `OpportunityStageChangeView`)."""

    permission_required = ("crm.view_opportunities", "crm.add_commercial_activities")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = CommercialActivityForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível registrar a atividade — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            create_activity(
                NewActivityData(
                    opportunity=opportunity,
                    activity_type=cleaned["activity_type"],
                    created_by=request.user,
                    description=cleaned["description"],
                    occurred_at=cleaned["occurred_at"],
                    scheduled_for=cleaned["scheduled_for"],
                )
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        is_observation = cleaned["activity_type"].code == OBSERVATION_ACTIVITY_TYPE_CODE
        messages.success(request, "Observação registrada." if is_observation else "Atividade registrada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


# ---------------------------------------------------------------------------
# Configurações comerciais — Origem, Etapa, Motivo de perda.
#
# Mesmo padrão simples de `apps.catalog.views.CategoryListView/
# CreateView/UpdateView` — `ModelForm` direto, sem service dedicado
# (nenhuma regra de negócio além do que já está em `Meta.permissions`/
# `clean()` do próprio modelo). "Excluir" nunca existe aqui, de propósito
# — só editar `is_active` pelo mesmo form de edição (mesma convenção de
# `Category`), nunca DELETE de verdade (requisito: nunca apagar
# fisicamente origem/etapa/motivo já utilizado).
# ---------------------------------------------------------------------------


class CommercialSourceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = CommercialSource
    template_name = "crm/commercial_source_list.html"
    context_object_name = "sources"

    def get_queryset(self):
        return CommercialSource.objects.all().order_by("order", "name")


class CommercialSourceCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/commercial_source_form.html", {"form": CommercialSourceForm(), "is_new": True})

    def post(self, request):
        form = CommercialSourceForm(request.POST)
        if form.is_valid():
            source = form.save()
            messages.success(request, f"Origem comercial \"{source.name}\" criada.")
            return redirect("crm:commercial_source_list")
        return render(request, "crm/commercial_source_form.html", {"form": form, "is_new": True})


class CommercialSourceUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        source = get_object_or_404(CommercialSource, pk=pk)
        return render(
            request, "crm/commercial_source_form.html", {"form": CommercialSourceForm(instance=source), "is_new": False, "source": source}
        )

    def post(self, request, pk):
        source = get_object_or_404(CommercialSource, pk=pk)
        form = CommercialSourceForm(request.POST, instance=source)
        if form.is_valid():
            form.save()
            messages.success(request, f"Origem comercial \"{source.name}\" atualizada.")
            return redirect("crm:commercial_source_list")
        return render(request, "crm/commercial_source_form.html", {"form": form, "is_new": False, "source": source})


class OpportunityStageListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = OpportunityStage
    template_name = "crm/opportunity_stage_list.html"
    context_object_name = "stages"

    def get_queryset(self):
        return OpportunityStage.objects.all().order_by("order", "name")


class OpportunityStageCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/opportunity_stage_form.html", {"form": OpportunityStageForm(), "is_new": True})

    def post(self, request):
        form = OpportunityStageForm(request.POST)
        if form.is_valid():
            stage = form.save()
            messages.success(request, f"Etapa \"{stage.name}\" criada.")
            return redirect("crm:opportunity_stage_list")
        return render(request, "crm/opportunity_stage_form.html", {"form": form, "is_new": True})


class OpportunityStageUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        stage = get_object_or_404(OpportunityStage, pk=pk)
        return render(
            request, "crm/opportunity_stage_form.html", {"form": OpportunityStageForm(instance=stage), "is_new": False, "stage": stage}
        )

    def post(self, request, pk):
        stage = get_object_or_404(OpportunityStage, pk=pk)
        form = OpportunityStageForm(request.POST, instance=stage)
        if form.is_valid():
            form.save()
            messages.success(request, f"Etapa \"{stage.name}\" atualizada.")
            return redirect("crm:opportunity_stage_list")
        return render(request, "crm/opportunity_stage_form.html", {"form": form, "is_new": False, "stage": stage})


class LossReasonListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = LossReason
    template_name = "crm/loss_reason_list.html"
    context_object_name = "reasons"

    def get_queryset(self):
        return LossReason.objects.all().order_by("order", "name")


class LossReasonCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/loss_reason_form.html", {"form": LossReasonForm(), "is_new": True})

    def post(self, request):
        form = LossReasonForm(request.POST)
        if form.is_valid():
            reason = form.save()
            messages.success(request, f"Motivo de perda \"{reason.name}\" criado.")
            return redirect("crm:loss_reason_list")
        return render(request, "crm/loss_reason_form.html", {"form": form, "is_new": True})


class LossReasonUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        reason = get_object_or_404(LossReason, pk=pk)
        return render(
            request, "crm/loss_reason_form.html", {"form": LossReasonForm(instance=reason), "is_new": False, "reason": reason}
        )

    def post(self, request, pk):
        reason = get_object_or_404(LossReason, pk=pk)
        form = LossReasonForm(request.POST, instance=reason)
        if form.is_valid():
            form.save()
            messages.success(request, f"Motivo de perda \"{reason.name}\" atualizado.")
            return redirect("crm:loss_reason_list")
        return render(request, "crm/loss_reason_form.html", {"form": form, "is_new": False, "reason": reason})


# RODADA 3 DE REFINAMENTOS (14/09/2026): `ActivityType` migrou de
# `TextChoices` fixo para entidade configurável — mesmo padrão exato das
# 3 views acima, "excluir" nunca existe aqui também (só editar
# `is_active`), mesma permissão `crm.manage_commercial_settings`
# (nenhuma permissão nova criada).
class ActivityTypeListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = ActivityType
    template_name = "crm/activity_type_list.html"
    context_object_name = "activity_types"

    def get_queryset(self):
        return ActivityType.objects.all().order_by("order", "name")


class ActivityTypeCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/activity_type_form.html", {"form": ActivityTypeForm(), "is_new": True})

    def post(self, request):
        form = ActivityTypeForm(request.POST)
        if form.is_valid():
            activity_type = form.save()
            messages.success(request, f"Tipo de atividade \"{activity_type.name}\" criado.")
            return redirect("crm:activity_type_list")
        return render(request, "crm/activity_type_form.html", {"form": form, "is_new": True})


class ActivityTypeUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        activity_type = get_object_or_404(ActivityType, pk=pk)
        return render(
            request,
            "crm/activity_type_form.html",
            {"form": ActivityTypeForm(instance=activity_type), "is_new": False, "activity_type": activity_type},
        )

    def post(self, request, pk):
        activity_type = get_object_or_404(ActivityType, pk=pk)
        form = ActivityTypeForm(request.POST, instance=activity_type)
        if form.is_valid():
            form.save()
            messages.success(request, f"Tipo de atividade \"{activity_type.name}\" atualizado.")
            return redirect("crm:activity_type_list")
        return render(
            request, "crm/activity_type_form.html", {"form": form, "is_new": False, "activity_type": activity_type}
        )


# RODADA 4 (REFINAMENTO DA COMPOSIÇÃO COMERCIAL, 15/09/2026, seção 21):
# catálogo de serviços comerciais — mesmo padrão exato das 4 telas de
# configuração acima ("excluir" nunca existe aqui também, só editar
# `is_active`), mesma permissão `crm.manage_commercial_settings`
# (nenhuma permissão nova criada).
class ServiceCatalogItemListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = ServiceCatalogItem
    template_name = "crm/service_catalog_item_list.html"
    context_object_name = "service_catalog_items"

    def get_queryset(self):
        return ServiceCatalogItem.objects.all().order_by("order", "name")


class ServiceCatalogItemCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/service_catalog_item_form.html", {"form": ServiceCatalogItemForm(), "is_new": True})

    def post(self, request):
        form = ServiceCatalogItemForm(request.POST)
        if form.is_valid():
            item = form.save()
            messages.success(request, f"Serviço \"{item.name}\" criado.")
            return redirect("crm:service_catalog_item_list")
        return render(request, "crm/service_catalog_item_form.html", {"form": form, "is_new": True})


class ServiceCatalogItemUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        item = get_object_or_404(ServiceCatalogItem, pk=pk)
        return render(
            request,
            "crm/service_catalog_item_form.html",
            {"form": ServiceCatalogItemForm(instance=item), "is_new": False, "service_catalog_item": item},
        )

    def post(self, request, pk):
        item = get_object_or_404(ServiceCatalogItem, pk=pk)
        form = ServiceCatalogItemForm(request.POST, instance=item)
        if form.is_valid():
            form.save()
            messages.success(request, f"Serviço \"{item.name}\" atualizado.")
            return redirect("crm:service_catalog_item_list")
        return render(
            request, "crm/service_catalog_item_form.html", {"form": form, "is_new": False, "service_catalog_item": item}
        )


# ---------------------------------------------------------------------------
# Tabela de Preços V1 (16/09/2026). Tela de configuração comercial —
# mesma família de Origens/Etapas/Motivos/Tipos de atividade/Serviços
# comerciais acima, mas com DUAS permissões PRÓPRIAS
# (`crm.view_price_table`/`crm.change_price_table`, seção 18: "preço é
# informação comercial sensível... separar ver tabela / editar valores")
# em vez de reaproveitar `crm.manage_commercial_settings`.
#
# `PriceTableItemRowView` é GET (visualizar/entrar em modo de edição de
# UMA linha) + POST (salvar) — o `permission_required` da classe só exige
# `crm.view_price_table` (visualizar a linha); a checagem de
# `crm.change_price_table` (entrar em modo de edição OU salvar) é manual,
# DENTRO da view (mesmo padrão de checagem manual já documentado em
# `docs/permissions.md`, seção "Nota sobre apps.crm") — "Botão escondido
# ≠ bloqueio no backend" (seção 33 dos testes: acesso direto por URL sem
# `change_price_table` precisa ser bloqueado mesmo com o lápis escondido
# na tela).
# ---------------------------------------------------------------------------


class PriceTableView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.view_price_table"

    def get(self, request):
        business_type = request.GET.get("tipo") or BusinessType.LOCACAO
        if business_type not in BusinessType.values:
            business_type = BusinessType.LOCACAO
        search = request.GET.get("q", "").strip()
        only_missing = request.GET.get("sem_valor") == "1"

        # Serviços continuam SEMPRE em lista simples (flat), em qualquer
        # aba — inclusive Locação (RODADA 1, 16/09/2026): a matriz
        # plano×prazo é só para equipamentos, nunca pedida para o
        # catálogo de serviços comerciais. `list_price_table_rows()`
        # segue sendo a ÚNICA fonte dessa lista — reaproveitada aqui
        # mesmo quando `business_type=LOCACAO`, sem duplicar a consulta.
        rows = list_price_table_rows(business_type=business_type, search=search, only_missing=only_missing)
        context = {
            "business_type": business_type,
            "business_type_choices": BusinessType.choices,
            "search": search,
            "only_missing": only_missing,
            "service_rows": rows.service_rows,
            "can_change": request.user.has_perm("crm.change_price_table"),
        }

        if business_type == BusinessType.LOCACAO:
            # RODADA 1: aba Locação troca a listagem simples de
            # equipamentos (V1) pela matriz plano×prazo — "Venda"/
            # "Serviço" continuam com `rows.equipment_rows` inalterado
            # (seção: "preservar o comportamento atual da aba Venda").
            #
            # `rows.equipment_rows` NUNCA entra nos contadores aqui
            # (`list_price_table_rows()` foi chamada só para obter
            # `service_rows` — contar `rows.total_count`/etc. junto com os
            # da matriz DUPLICARIA cada equipamento: uma vez pela matriz,
            # outra pela lista flat descartada).
            service_total = len(rows.service_rows)
            service_configured = sum(1 for row in rows.service_rows if row.has_price)
            service_missing = service_total - service_configured

            plans = list_commercial_plans()
            plan_id = request.GET.get("plano")
            plan = None
            if plan_id and plan_id.isdigit():
                plan = next((p for p in plans if p.pk == int(plan_id)), None)
            if plan is None:
                plan = plans[0] if plans else None

            context["commercial_plans"] = plans
            context["commercial_plan"] = plan
            if plan is not None:
                matrix = list_price_table_matrix(commercial_plan=plan, search=search, only_missing=only_missing)
                context["matrix_terms"] = matrix.terms
                context["matrix_rows"] = matrix.rows
                context["total_count"] = matrix.total_count + service_total
                context["configured_count"] = matrix.configured_count + service_configured
                context["missing_count"] = matrix.missing_count + service_missing
            else:
                # Nenhum plano ativo cadastrado — estado vazio (nunca um
                # erro): mesma tela, só sem matriz para renderizar.
                context["matrix_terms"] = []
                context["matrix_rows"] = []
                context["total_count"] = service_total
                context["configured_count"] = service_configured
                context["missing_count"] = service_missing
        else:
            context["equipment_rows"] = rows.equipment_rows
            context["total_count"] = rows.total_count
            context["configured_count"] = rows.configured_count
            context["missing_count"] = rows.missing_count

        return render(request, "crm/price_table.html", context)


class PriceTableItemRowView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.view_price_table"

    def _resolve_target(self, request, kind, target_id):
        business_type = request.GET.get("tipo") or request.POST.get("tipo")
        if business_type not in BusinessType.values:
            raise Http404("Tipo de negócio inválido.")
        if kind == "equipamento":
            target = get_object_or_404(EquipmentModel, pk=target_id, is_active=True)
            label = f"{target.name} ({target.code})"
            filter_kwargs = {"equipment_model": target, "service": None}
        elif kind == "servico":
            target = get_object_or_404(ServiceCatalogItem, pk=target_id, is_active=True)
            label = target.name
            filter_kwargs = {"equipment_model": None, "service": target}
        else:
            raise Http404("Tipo de item inválido.")
        return business_type, target, label, filter_kwargs

    def _current_item(self, business_type, filter_kwargs):
        return PriceTableItem.objects.select_related("updated_by").filter(
            price_table__business_type=business_type, **filter_kwargs
        ).first()

    @staticmethod
    def _updated_by_label(item):
        if item is None:
            return ""
        return item.updated_by.get_full_name() or item.updated_by.username

    def get(self, request, kind, target_id):
        business_type, target, label, filter_kwargs = self._resolve_target(request, kind, target_id)
        can_change = request.user.has_perm("crm.change_price_table")
        edit_mode = request.GET.get("modo") == "editar"
        if edit_mode and not can_change:
            raise PermissionDenied("Você não tem permissão para editar valores da Tabela de Preços.")

        item = self._current_item(business_type, filter_kwargs)
        # Contexto SEMPRE em campos "achatados" (`unit_price`/
        # `updated_by_label`, nunca o `PriceTableItem` bruto) — o mesmo
        # parcial `_price_table_row.html` também é `{% include %}`'d por
        # `price_table.html` a partir de `PriceTableRow` (dataclass de
        # `services.list_price_table_rows()`), que tem exatamente este
        # formato; um único parcial funciona para os dois chamadores.
        context = {
            "kind": kind,
            "target_id": target.pk,
            "label": label,
            "business_type": business_type,
            "unit_price": item.unit_price if item else None,
            "updated_by_label": self._updated_by_label(item),
            "can_change": can_change,
        }
        if edit_mode:
            context["form"] = PriceTableItemForm(initial={"unit_price": item.unit_price if item else None})
            return render(request, "crm/_price_table_row_edit.html", context)
        return render(request, "crm/_price_table_row.html", context)

    def post(self, request, kind, target_id):
        if not request.user.has_perm("crm.change_price_table"):
            raise PermissionDenied("Você não tem permissão para editar valores da Tabela de Preços.")

        business_type, target, label, filter_kwargs = self._resolve_target(request, kind, target_id)
        form = PriceTableItemForm(request.POST)
        base_context = {
            "kind": kind,
            "target_id": target.pk,
            "label": label,
            "business_type": business_type,
            "can_change": True,
        }
        if not form.is_valid():
            base_context["form"] = form
            return render(request, "crm/_price_table_row_edit.html", base_context, status=400)

        try:
            item = set_price_table_item(
                data=PriceTableItemData(
                    business_type=business_type,
                    equipment_model=filter_kwargs["equipment_model"],
                    service=filter_kwargs["service"],
                    unit_price=form.cleaned_data["unit_price"],
                ),
                user=request.user,
            )
        except ValueError as exc:
            form.add_error("unit_price", str(exc))
            base_context["form"] = form
            return render(request, "crm/_price_table_row_edit.html", base_context, status=400)

        # Sem `messages.success()` aqui de propósito: esta view devolve só
        # o `<tr>` (fragmento HTML via htmx, nunca um redirect/reload de
        # página inteira) — uma mensagem da framework `django.contrib.
        # messages` ficaria "pendurada" na sessão e apareceria fora de
        # contexto na PRÓXIMA navegação normal do usuário. A confirmação
        # visual já é o próprio valor atualizado aparecendo na linha.
        context = {
            **base_context,
            "unit_price": item.unit_price,
            "updated_by_label": self._updated_by_label(item),
        }
        return render(request, "crm/_price_table_row.html", context)


class PriceTableRateCellView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Edição inline de UMA célula da matriz de Preços de Locação
    (equipamento × plano × prazo) — RODADA 1 (16/09/2026). MESMO padrão de
    permissão/checagem manual de `PriceTableItemRowView`: `permission_required`
    da classe só exige `crm.view_price_table` (ver a célula); entrar em
    modo de edição OU salvar exige `crm.change_price_table`, checado
    manualmente dentro da view (mesmo raciocínio documentado em
    `docs/permissions.md`).
    """

    permission_required = "crm.view_price_table"

    def _resolve_target(self, request, equipment_model_id, commercial_term_id):
        plan_id = request.GET.get("plano") or request.POST.get("plano")
        if not (plan_id and plan_id.isdigit()):
            raise Http404("Plano comercial inválido.")
        commercial_plan = get_object_or_404(CommercialPlan, pk=plan_id, is_active=True)
        equipment_model = get_object_or_404(EquipmentModel, pk=equipment_model_id, is_active=True)
        commercial_term = get_object_or_404(
            CommercialTerm, pk=commercial_term_id, commercial_plan=commercial_plan, is_active=True
        )
        return commercial_plan, equipment_model, commercial_term

    @staticmethod
    def _updated_by_label(rate):
        if rate is None:
            return ""
        return rate.updated_by.get_full_name() or rate.updated_by.username

    def _current_rate(self, commercial_plan, equipment_model, commercial_term):
        return (
            PriceTableRate.objects.select_related("updated_by")
            .filter(
                commercial_plan=commercial_plan,
                commercial_term=commercial_term,
                price_table_item__equipment_model=equipment_model,
            )
            .first()
        )

    def get(self, request, equipment_model_id, commercial_term_id):
        commercial_plan, equipment_model, commercial_term = self._resolve_target(
            request, equipment_model_id, commercial_term_id
        )
        can_change = request.user.has_perm("crm.change_price_table")
        edit_mode = request.GET.get("modo") == "editar"
        if edit_mode and not can_change:
            raise PermissionDenied("Você não tem permissão para editar valores da Tabela de Preços.")

        rate = self._current_rate(commercial_plan, equipment_model, commercial_term)
        context = {
            "equipment_model_id": equipment_model.pk,
            "commercial_term_id": commercial_term.pk,
            "commercial_plan_id": commercial_plan.pk,
            "amount": rate.amount if rate else None,
            "billing_mode": rate.billing_mode if rate else None,
            "updated_by_label": self._updated_by_label(rate),
            "can_change": can_change,
        }
        if edit_mode:
            context["form"] = PriceTableRateForm(
                initial={
                    "amount": rate.amount if rate else None,
                    "billing_mode": rate.billing_mode if rate else BillingMode.TERM_TOTAL,
                }
            )
            return render(request, "crm/_price_table_matrix_cell_edit.html", context)
        return render(request, "crm/_price_table_matrix_cell.html", context)

    def post(self, request, equipment_model_id, commercial_term_id):
        if not request.user.has_perm("crm.change_price_table"):
            raise PermissionDenied("Você não tem permissão para editar valores da Tabela de Preços.")

        commercial_plan, equipment_model, commercial_term = self._resolve_target(
            request, equipment_model_id, commercial_term_id
        )
        form = PriceTableRateForm(request.POST)
        base_context = {
            "equipment_model_id": equipment_model.pk,
            "commercial_term_id": commercial_term.pk,
            "commercial_plan_id": commercial_plan.pk,
            "can_change": True,
        }
        if not form.is_valid():
            base_context["form"] = form
            return render(request, "crm/_price_table_matrix_cell_edit.html", base_context, status=400)

        try:
            rate = set_price_table_rate(
                data=PriceTableRateData(
                    equipment_model=equipment_model,
                    commercial_plan=commercial_plan,
                    commercial_term=commercial_term,
                    amount=form.cleaned_data["amount"],
                    billing_mode=form.cleaned_data["billing_mode"],
                ),
                user=request.user,
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            base_context["form"] = form
            return render(request, "crm/_price_table_matrix_cell_edit.html", base_context, status=400)

        # Sem `messages.success()` (mesmo raciocínio de `PriceTableItemRowView`
        # — fragmento htmx, não redirect).
        context = {
            **base_context,
            "amount": rate.amount,
            "billing_mode": rate.billing_mode,
            "updated_by_label": self._updated_by_label(rate),
        }
        return render(request, "crm/_price_table_matrix_cell.html", context)


# ---------------------------------------------------------------------------
# Produtos e Serviços / Proposta Comercial + Contrato (14/09/2026).
#
# Toda escrita aqui é SÓ POST (seção 85, "Nunca GET para: emitir/aceitar/
# cancelar/gerar contrato/criar versão/remover item") — nenhuma destas
# views define `get()`, então um `GET` acidental recebe 405 do próprio
# `django.views.View` (mesmo raciocínio de `OpportunityStageChangeView`).
# Todas exigem `crm.view_opportunities` + a permissão específica da ação
# (seção 84: "Não confiar em botão escondido — toda ação protegida no
# backend").
# ---------------------------------------------------------------------------


def _get_or_create_editable_version(request, opportunity):
    """
    Versão EDITÁVEL da proposta ATIVA da Opportunity — mesma fonte única
    de verdade usada por `OpportunityDetailView.get` (nunca aceita um
    `proposal_version` vindo do POST/URL para "qual versão editar":
    eliminaria por construção qualquer risco de um POST tentar editar a
    versão de OUTRA Opportunity só adivinhando um pk).
    `get_or_create_active_proposal()` garante que um POST de "adicionar
    item"/"salvar rascunho" nunca depende de o usuário ter visitado a
    tela antes — cria a Proposal/v1 na hora se ainda não existir.

    RODADA 4 (REFINAMENTO DA COMPOSIÇÃO COMERCIAL, 15/09/2026, seção
    9-13): deixou de levantar 404 quando a versão mais recente já foi
    emitida — em vez disso, `ensure_editable_version()` clona
    automaticamente uma nova versão DRAFT na hora (auto-versionamento
    preguiçoso). O usuário nunca mais vê "crie uma nova versão primeiro".
    """
    proposal = get_or_create_active_proposal(opportunity=opportunity, created_by=request.user)
    return ensure_editable_version(proposal=proposal, created_by=request.user)


class ProposalItemAddView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        version = _get_or_create_editable_version(request, opportunity)
        form = ProposalItemForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível adicionar o produto/serviço — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            add_proposal_item(
                proposal_version=version,
                data=ProposalItemData(
                    item_type=cleaned["item_type"],
                    equipment_model=cleaned["equipment_model"],
                    service=cleaned["service"],
                    quantity=cleaned["quantity"],
                    unit_price=cleaned["unit_price"],
                    item_discount_amount=cleaned["item_discount_amount"] or Decimal("0"),
                    notes=cleaned["notes"],
                ),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Produto/serviço adicionado.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalItemUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk, item_pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        item = get_object_or_404(ProposalItem, pk=item_pk)
        if item.proposal_version.proposal.opportunity_id != opportunity.pk:
            raise Http404("Item não pertence a esta oportunidade.")

        form = ProposalItemForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível atualizar o produto/serviço — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        # RODADA 4 (15/09/2026, seção 9-13): o item clicado pode pertencer
        # a uma versão já emitida (é sempre a versão mais recente exibida
        # na tela, emitida ou não) — `ensure_editable_item()` resolve o
        # item CORRESPONDENTE numa versão editável, clonando
        # automaticamente quando necessário, sem que o usuário precise
        # saber disso.
        item = ensure_editable_item(item=item, created_by=request.user)

        cleaned = form.cleaned_data
        try:
            update_proposal_item(
                item=item,
                data=ProposalItemData(
                    item_type=cleaned["item_type"],
                    equipment_model=cleaned["equipment_model"],
                    service=cleaned["service"],
                    quantity=cleaned["quantity"],
                    unit_price=cleaned["unit_price"],
                    item_discount_amount=cleaned["item_discount_amount"] or Decimal("0"),
                    notes=cleaned["notes"],
                ),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Produto/serviço atualizado.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalItemRemoveView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk, item_pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        item = get_object_or_404(ProposalItem, pk=item_pk)
        if item.proposal_version.proposal.opportunity_id != opportunity.pk:
            raise Http404("Item não pertence a esta oportunidade.")

        # RODADA 4 (15/09/2026, seção 15): remover um item de uma versão
        # já emitida nunca apaga da versão antiga — `ensure_editable_item()`
        # clona automaticamente (se ainda não existir rascunho) e resolve
        # a linha correspondente NA NOVA versão antes de remover.
        item = ensure_editable_item(item=item, created_by=request.user)

        try:
            remove_proposal_item(item=item)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Produto/serviço removido.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalConditionsSaveView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    "Salvar rascunho" (seção 5/57) — condições/período/logística/financeiro/textos.
    RODADA 4 (15/09/2026, seção 9): alterar qualquer uma dessas condições
    também conta como "primeira alteração após emissão" — `_get_or_create_editable_version()`
    clona automaticamente quando a versão mais recente já não é DRAFT.
    """

    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        version = _get_or_create_editable_version(request, opportunity)
        form = ProposalConditionsForm(request.POST, opportunity=opportunity)
        if not form.is_valid():
            messages.error(request, "Não foi possível salvar — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            update_draft_conditions(
                proposal_version=version,
                data=ProposalConditionsData(
                    # "Tabela de preço"/"Outra forma"/"Condição" saíram da
                    # UI (REFINAMENTO VISUAL, 14/09/2026 — correção da
                    # especificação original), mas os 3 campos continuam
                    # existindo em `ProposalVersion` (nenhuma migration
                    # destrutiva). `update_draft_conditions()` GRAVA O
                    # OBJETO INTEIRO a cada "Salvar rascunho" — se
                    # passássemos "" aqui (o default do dataclass), um
                    # valor já persistido (ex.: gravado antes desta
                    # mudança, ou via admin) seria silenciosamente
                    # apagado só porque o campo não está mais neste
                    # formulário. Para preservar compatibilidade sem
                    # reexpor os campos, repassamos o valor JÁ GRAVADO na
                    # própria versão (sem alteração nenhuma).
                    price_table_label=version.price_table_label,
                    payment_method=cleaned["payment_method"],
                    payment_method_other=version.payment_method_other,
                    payment_condition=version.payment_condition,
                    commercial_plan=cleaned["commercial_plan"],
                    event_name=cleaned["event_name"],
                    onsite_responsible_name=cleaned["onsite_responsible_name"],
                    onsite_responsible_phone=cleaned["onsite_responsible_phone"],
                    contracted_start_date=cleaned["contracted_start_date"],
                    contracted_end_date=cleaned["contracted_end_date"],
                    expected_delivery_date=cleaned["expected_delivery_date"],
                    expected_delivery_time=cleaned["expected_delivery_time"],
                    expected_pickup_date=cleaned["expected_pickup_date"],
                    expected_pickup_time=cleaned["expected_pickup_time"],
                    delivery_location=cleaned["delivery_location"],
                    general_discount=cleaned["general_discount"] or Decimal("0"),
                    interest_amount=cleaned["interest_amount"] or Decimal("0"),
                    freight_amount=cleaned["freight_amount"] or Decimal("0"),
                    special_clauses=cleaned["special_clauses"],
                    payment_info_notes=cleaned["payment_info_notes"],
                    general_notes=cleaned["general_notes"],
                ),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Rascunho salvo.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalInstallmentAddView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """"[+ Adicionar parcela]" (FECHAMENTO DA PROPOSTA COMERCIAL, 23/09/2026, seção 18-20) — mesmo padrão de `ProposalItemAddView`."""

    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        version = _get_or_create_editable_version(request, opportunity)
        form = ProposalInstallmentForm(request.POST, prefix="parcela")
        if not form.is_valid():
            messages.error(request, "Não foi possível adicionar a parcela — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            add_installment(
                proposal_version=version,
                data=ProposalInstallmentData(
                    payment_method=cleaned["payment_method"],
                    payment_method_other=cleaned["payment_method_other"],
                    amount=cleaned["amount"],
                    due_date=cleaned["due_date"],
                ),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Parcela adicionada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalInstallmentUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Mesmo padrão de `ProposalItemUpdateView` — resolve a parcela correspondente numa versão editável antes de gravar."""

    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk, installment_pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        installment = get_object_or_404(ProposalVersionInstallment, pk=installment_pk)
        if installment.proposal_version.proposal.opportunity_id != opportunity.pk:
            raise Http404("Parcela não pertence a esta oportunidade.")

        form = ProposalInstallmentForm(request.POST, prefix="parcela")
        if not form.is_valid():
            messages.error(request, "Não foi possível atualizar a parcela — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        installment = ensure_editable_installment(installment=installment, created_by=request.user)

        cleaned = form.cleaned_data
        try:
            update_installment(
                installment=installment,
                data=ProposalInstallmentData(
                    payment_method=cleaned["payment_method"],
                    payment_method_other=cleaned["payment_method_other"],
                    amount=cleaned["amount"],
                    due_date=cleaned["due_date"],
                ),
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Parcela atualizada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalInstallmentRemoveView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Mesmo padrão de `ProposalItemRemoveView`."""

    permission_required = ("crm.view_opportunities", "crm.change_opportunities")

    def post(self, request, pk, installment_pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        installment = get_object_or_404(ProposalVersionInstallment, pk=installment_pk)
        if installment.proposal_version.proposal.opportunity_id != opportunity.pk:
            raise Http404("Parcela não pertence a esta oportunidade.")

        installment = ensure_editable_installment(installment=installment, created_by=request.user)

        try:
            remove_installment(installment=installment)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Parcela removida.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class ProposalGenerateDocumentView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Dropdown "Gerar documento" (seção 6/64/65). Permissão varia por tipo
    de documento — checada manualmente no corpo (não dá para expressar
    "OR condicional ao dado do POST" em `permission_required` estático):
    Proposta Comercial exige `crm.issue_proposal_documents`; Contrato e
    Proposta+Contrato exigem `crm.generate_contract` (gerar contrato é
    sempre o poder mais sensível das três opções).
    """

    permission_required = "crm.view_opportunities"

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        # A versão a documentar é a mais recente da proposta ativa,
        # emitida OU em rascunho (gerar documento pode emitir na hora) —
        # por isso não reaproveita `_get_or_create_editable_version()`
        # (que sempre devolve uma DRAFT, clonando se preciso — geração de
        # documento é o único fluxo que precisa da versão como ela
        # ESTÁ, não de uma editável).
        proposal = opportunity.proposals.order_by("-created_at").first()
        if proposal is None:
            raise Http404("Esta oportunidade ainda não tem nenhuma proposta.")
        version = proposal.latest_version
        if version is None or not version.items.exists():
            messages.error(request, "Não é possível gerar documento sem nenhum produto/serviço na composição.")
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        form = DocumentGenerationForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Selecione um tipo de documento válido.")
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        document_type = form.cleaned_data["document_type"]
        if document_type == DocumentType.PROPOSTA and not request.user.has_perm("crm.issue_proposal_documents"):
            raise PermissionDenied("Você não tem permissão para emitir Proposta Comercial.")
        if document_type in (DocumentType.CONTRATO, DocumentType.PROPOSTA_E_CONTRATO) and not request.user.has_perm(
            "crm.generate_contract"
        ):
            raise PermissionDenied("Você não tem permissão para gerar Contrato.")

        try:
            result = generate_documents(proposal_version=version, document_type=document_type, actor=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        # RODADA 3 DE REFINAMENTOS (14/09/2026), seção 30-51: gerar NUNCA
        # é aceitar — a mensagem/o download automático não têm nenhum
        # efeito sobre `Opportunity.stage`/`won_at` (isso continua
        # exclusivo de `ProposalAcceptVersionView`/"ORÇAMENTO ACEITO").
        # O PDF gerado já está em Anexos (repositório permanente); o
        # download automático abaixo é só conveniência — nunca cria um
        # segundo arquivo.
        messages.success(request, "Orçamento gerado e salvo em Anexos — o download do PDF começou automaticamente.")
        redirect_url = reverse("crm:opportunity_detail", args=[opportunity.pk])
        download_attachment = result.get("download_attachment")
        if download_attachment is not None:
            redirect_url = f"{redirect_url}?baixar_pdf={download_attachment.pk}"
        return redirect(redirect_url)


class ProposalAcceptVersionView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Aceite (seção 71-74) — exige `crm.change_opportunity_stage` (é
    literalmente o mesmo poder: aceitar chama `change_opportunity_stage()`,
    ver `apps.crm.services.accept_proposal_version`).
    """

    permission_required = ("crm.view_opportunities", "crm.change_opportunity_stage")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = AcceptProposalVersionForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível aceitar — corrija os erros abaixo.")
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        candidates = acceptable_proposal_versions(opportunity)
        version = candidates.filter(pk=form.cleaned_data["proposal_version"]).first()
        if version is None:
            messages.error(request, "Versão inválida ou não está mais disponível para aceite.")
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        try:
            accept_proposal_version(proposal_version=version, accepted_by=request.user, won_stage=form.cleaned_data["stage"])
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, f"Proposta {version.display_label} aceita — negócio ganho.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


# ---------------------------------------------------------------------------
# Equipamentos — vínculo Oportunidade↔patrimônio real (RODADA 3 DE
# REFINAMENTOS, 14/09/2026, seção 60-68).
# ---------------------------------------------------------------------------


class OpportunityEquipmentSearchView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Busca de patrimônio DISPONÍVEL para vincular — SÓ LEITURA, AJAX, GET
    (mesmo padrão de `OpportunityClientAutocompleteView`/
    `AvailabilityCheckView`). Restrito a quem pode efetivamente vincular
    (`operations.register_operations`, a MESMA Permission reaproveitada
    pelas duas views de escrita abaixo) — não faz sentido expor a busca
    de patrimônio a quem não pode usá-la.

    Reaproveita `apps.equipment.filters.filter_equipment_queryset()`
    (busca por patrimônio/número de série via `q`) — nunca uma cópia
    divergente da lógica de busca já usada pela listagem de Equipamentos.
    A queryset em si não depende de QUAL Oportunidade (`pk` na URL só
    mantém a mesma estrutura aninhada do resto do CRM e serve de âncora
    de permissão) — qualquer patrimônio `DISPONÍVEL` pode ser vinculado a
    qualquer Oportunidade; não existe reserva de estoque por cliente
    neste projeto.
    """

    permission_required = ("crm.view_opportunities", "operations.register_operations")
    RESULT_LIMIT = 20

    def get(self, request, pk):
        get_object_or_404(Opportunity, pk=pk)
        queryset = Equipment.objects.filter(is_active=True, status=EquipmentStatus.DISPONIVEL).select_related(
            "model", "current_location"
        )
        queryset = filter_equipment_queryset(queryset, request.GET)
        equipment_list = queryset.order_by("patrimonio")[: self.RESULT_LIMIT]
        results = [
            {
                "id": equipment.pk,
                "patrimonio": equipment.patrimonio,
                "model": equipment.model.name,
                "location": equipment.current_location.name if equipment.current_location else "—",
            }
            for equipment in equipment_list
        ]
        return JsonResponse({"results": results})


class OpportunityEquipmentLinkView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """"Vincular equipamento" — único caminho de POST, sempre via `link_equipment_to_opportunity()`."""

    permission_required = ("crm.view_opportunities", "operations.register_operations")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = EquipmentLinkForm(request.POST, opportunity=opportunity)
        if not form.is_valid():
            messages.error(request, "Não foi possível vincular o equipamento — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            link_equipment_to_opportunity(
                LinkEquipmentData(
                    opportunity=opportunity,
                    equipment=cleaned["equipment"],
                    destination_location=cleaned["destination_location"],
                    actor=request.user,
                    reason=cleaned["reason"],
                )
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, f'Equipamento {cleaned["equipment"].patrimonio} vinculado.')
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class OpportunityEquipmentUnlinkView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """"Desvincular" — único caminho de POST, sempre via `unlink_equipment_from_opportunity()` (nunca DELETE)."""

    permission_required = ("crm.view_opportunities", "operations.register_operations")

    def post(self, request, pk, link_pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        link = get_object_or_404(OpportunityEquipment, pk=link_pk, opportunity=opportunity)
        form = EquipmentUnlinkForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível desvincular o equipamento — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            unlink_equipment_from_opportunity(
                UnlinkEquipmentData(
                    link=link,
                    destination_location=cleaned["destination_location"],
                    actor=request.user,
                    reason=cleaned["reason"],
                )
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, f"Equipamento {link.equipment.patrimonio} desvinculado.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class AvailabilityCheckView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    "Consulta de disponibilidade" (seção 11/12/76/77) — SÓ LEITURA, AJAX,
    GET (não é uma mudança de estado — seção 85 só exige POST para
    escrita). Nunca cria reserva/movimento/seleção de patrimônio.
    """

    permission_required = "crm.view_opportunities"

    def get(self, request, pk):
        equipment_model_id = request.GET.get("equipment_model", "")
        quantity_raw = request.GET.get("quantity", "1")
        if not equipment_model_id.isdigit():
            return JsonResponse({"ok": False, "error": "Modelo inválido."}, status=400)
        try:
            quantity = int(quantity_raw)
        except (TypeError, ValueError):
            quantity = 1
        equipment_model = get_object_or_404(EquipmentModel, pk=equipment_model_id)
        result = check_availability(equipment_model=equipment_model, requested_quantity=max(quantity, 1))
        return JsonResponse(
            {
                "ok": True,
                "requested": result.requested,
                "available": result.available,
                "missing": result.missing,
            }
        )


class SuggestedPriceView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    "Preço sugerido" (Tabela de Preços V1, seção 23) — SÓ LEITURA, AJAX,
    GET (mesmo raciocínio de `AvailabilityCheckView`: não é mudança de
    estado). Ao escolher um Produto/Modelo OU Serviço no form de
    adicionar item, `static/crm/proposal_composition.js` consulta este
    endpoint e PREENCHE (nunca trava — seção 24) o campo "Valor unitário"
    se ele ainda estiver vazio; o vendedor continua livre para digitar
    outro valor por cima. Resolve o `BusinessType` da própria Opportunity
    da URL (nunca aceita um `business_type` vindo do GET — eliminaria por
    construção qualquer tentativa de consultar o preço de um tipo de
    negócio diferente do desta oportunidade).
    """

    permission_required = "crm.view_opportunities"

    def get(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        equipment_model_id = request.GET.get("equipment_model", "")
        service_id = request.GET.get("service", "")

        equipment_model = None
        service = None
        if equipment_model_id.isdigit():
            equipment_model = EquipmentModel.objects.filter(pk=equipment_model_id, is_active=True).first()
        elif service_id.isdigit():
            service = ServiceCatalogItem.objects.filter(pk=service_id, is_active=True).first()

        if equipment_model is None and service is None:
            return JsonResponse({"ok": False, "error": "Selecione um produto/modelo ou um serviço."}, status=400)

        suggestion = get_suggested_price(
            business_type=opportunity.business_type, equipment_model=equipment_model, service=service
        )
        return JsonResponse(
            {
                "ok": True,
                "found": suggestion is not None,
                "unit_price": str(suggestion.amount) if suggestion is not None else None,
                "business_type_display": opportunity.get_business_type_display(),
            }
        )


class AttachmentDownloadView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Download autenticado de um Anexo — nunca um link `/media/` direto (evitaria a checagem de permissão)."""

    permission_required = "crm.view_opportunities"

    def get(self, request, pk, attachment_pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        attachment = get_object_or_404(Attachment, pk=attachment_pk)
        from django.contrib.contenttypes.models import ContentType

        opportunity_ct = ContentType.objects.get_for_model(Opportunity)
        if attachment.content_type_id != opportunity_ct.pk or attachment.object_id != opportunity.pk:
            raise Http404("Anexo não pertence a esta oportunidade.")
        return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.original_filename or attachment.file.name)
