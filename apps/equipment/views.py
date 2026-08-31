"""
Views da Fase 1: listagem (autenticada), ficha do equipamento com as duas
camadas de visualização (seção 12/13 da especificação — a ficha pública
nunca inclui cliente, valor de aquisição ou manutenção), e as telas
próprias de cadastro/edição/reclassificação/reemissão que substituem o
Django admin como interface operacional (fechamento da Fase 1).
"""

import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import (
    CAN_CHANGE_STATUS_CONDITION,
    CAN_EXPORT_DATA,
    CAN_MANAGE_EQUIPMENT,
    CAN_RECLASSIFY_EQUIPMENT_MODEL,
    CAN_SUPERSEDE_EQUIPMENT,
    CAN_VIEW_ACQUISITION_VALUE,
    RoleRequiredMixin,
)
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.filters import filter_equipment_queryset
from apps.equipment.grouping import build_model_groups
from apps.equipment.forms import (
    ChangeConditionForm,
    ChangeStatusForm,
    EquipmentBatchCreateForm,
    EquipmentCreateForm,
    EquipmentUpdateForm,
    ReclassifyModelForm,
    SupersedeEquipmentForm,
)
from apps.equipment.models import Condition, Equipment, EquipmentBatch, Status
from apps.equipment.services import (
    NewEquipmentBatchData,
    NewEquipmentData,
    change_condition,
    change_status,
    create_equipment,
    create_equipment_batch,
    get_equipment_history_timeline,
    reclassify_model,
    supersede_equipment,
)


class EquipmentListView(LoginRequiredMixin, ListView):
    """
    Todos os 4 perfis podem consultar (matriz da seção 11).

    Melhoria de UX/consulta (rodada corretiva pós-homologação): a área
    principal da tela passou a exibir os equipamentos AGRUPADOS POR
    MODELO (`context["model_groups"]`, via `apps.equipment.grouping`) em
    vez de uma tabela única — com a frota crescendo, uma tabela plana de
    centenas/milhares de patrimônios deixou de ser utilizável. Os
    equipamentos individuais de cada grupo são carregados sob demanda,
    via HTMX, por `EquipmentModelItemsView` abaixo — nunca todos de uma
    vez no HTML desta página.

    `get_queryset`/`context_object_name`/`paginate_by` (a listagem PLANA,
    paginada, de `Equipment`) foram deliberadamente MANTIDOS intactos:
    nenhum código novo depende mais deles para renderizar a tela, mas
    `response.context["equipment_list"]` continua correto e disponível —
    é o que `EquipmentExportView` já usa via `filter_equipment_queryset`
    (lógica compartilhada, não duplicada aqui) e o que os testes de
    filtro pré-existentes (`test_equipment_crud_views.py`,
    `test_batch_views.py`) verificam. Manter esse contrato evita quebrar
    silenciosamente uma garantia que já existia.
    """

    model = Equipment
    template_name = "equipment/list.html"
    context_object_name = "equipment_list"
    paginate_by = 50

    def get_queryset(self):
        qs = Equipment.objects.select_related("model", "category").filter(is_active=True)
        qs = filter_equipment_queryset(qs, self.request.GET)
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Alimenta os dropdowns de filtro combinado (seção 12 — "Filtros
        # combinados: patrimônio, modelo, categoria, serial, status,
        # condição"). O backend (filter_equipment_queryset) já suportava
        # esses parâmetros; isto só completa a UI que faltava.
        context["status_choices"] = Status.choices
        context["condition_choices"] = Condition.choices
        context["categories"] = Category.objects.filter(is_active=True).order_by("name")
        context["models"] = EquipmentModel.objects.filter(is_active=True).select_related("category").order_by(
            "category__name", "name"
        )
        context["selected_status"] = self.request.GET.get("status", "")
        context["selected_condition"] = self.request.GET.get("condition", "")
        context["selected_category"] = self.request.GET.get("category", "")
        context["selected_model"] = self.request.GET.get("model", "")

        # Grupos por modelo — mesma queryset filtrada (`self.get_queryset()`
        # reconstrói a expressão, não reexecuta a página inteira; a
        # agregação em si é 1 única query, ver apps/equipment/grouping.py).
        # Não usa `context["equipment_list"]` (que já veio FATIADA pela
        # paginação do ListView) porque os contadores precisam refletir o
        # resultado FILTRADO inteiro, não só os 50 primeiros registros.
        context["model_groups"] = build_model_groups(self.get_queryset())

        # Busca textual (seção 6 do pedido de correção): "facilitar chegar
        # diretamente ao equipamento" sem obrigar a pessoa a descobrir em
        # qual grupo ele está. Quando há busca ativa, os grupos com
        # resultado se auto-expandem no carregamento da página (JS no fim
        # de list.html simula um clique) — cada auto-expansão dispara UMA
        # requisição HTMX própria para `EquipmentModelItemsView` (mesmo
        # endpoint de um clique manual), então isto NÃO reintroduz N+1 na
        # resposta desta página: o número de queries AQUI continua fixo,
        # independente de quantos grupos tiverem resultado.
        context["auto_expand_groups"] = bool(self.request.GET.get("q", "").strip())
        return context


class EquipmentModelItemsView(LoginRequiredMixin, View):
    """
    Fragmento HTMX com os equipamentos de UM `EquipmentModel` — carregado
    sob demanda ao expandir um grupo na listagem agrupada
    (`EquipmentListView`/`templates/equipment/list.html`).

    Mesma visibilidade de `EquipmentListView` (`LoginRequiredMixin`, os 4
    perfis) — este endpoint não expõe nenhum dado que a listagem completa
    já não mostrasse ao mesmo usuário; a única diferença é carregar sob
    demanda em vez de tudo de uma vez. As ações de QR/etiqueta dentro do
    fragmento continuam checando `user.is_administrativo_ou_superior` no
    TEMPLATE (mesma condição já usada em list.html) — a proteção de
    verdade dessas rotas já é feita nas próprias views de QR/etiqueta
    (`apps.qrcodes`), este template não concede nem retira permissão
    nenhuma, só decide o que desenhar.

    Reaproveita `filter_equipment_queryset` (mesma função da listagem e da
    exportação) para que os filtros ativos (status/condição/busca/etc.)
    continuem valendo também dentro do grupo expandido — sem isso, expandir
    um grupo com o filtro "Status = Manutenção" ativo mostraria TODOS os
    equipamentos daquele modelo, não só os em manutenção.
    """

    GROUP_PAGE_SIZE = 20

    def get(self, request, model_id):
        model = get_object_or_404(EquipmentModel, pk=model_id)

        qs = Equipment.objects.select_related("model", "category").filter(is_active=True, model_id=model_id)
        qs = filter_equipment_queryset(qs, request.GET)
        qs = qs.order_by("-created_at")

        paginator = Paginator(qs, self.GROUP_PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get("page") or 1)

        return render(
            request,
            "equipment/_model_group_items.html",
            {
                "model": model,
                "page_obj": page_obj,
                "paginator": paginator,
                "is_paginated": paginator.num_pages > 1,
            },
        )


class EquipmentCreateView(RoleRequiredMixin, View):
    """
    Cadastro de equipamento — especificação, seção 12 ("Cadastro/edição de
    equipamento"). Sempre passa por `create_equipment()` (geração atômica
    do patrimônio, seção 8) — nunca instancia `Equipment(...)` direto.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        return render(request, "equipment/equipment_form.html", {"form": EquipmentCreateForm(), "is_new": True})

    def post(self, request):
        form = EquipmentCreateForm(request.POST)
        if form.is_valid():
            equipment = create_equipment(
                NewEquipmentData(
                    model_id=form.cleaned_data["model"].pk,
                    created_by=request.user,
                    serial_number=form.cleaned_data["serial_number"],
                    legacy_code=form.cleaned_data["legacy_code"],
                    supplier=form.cleaned_data["supplier"],
                    acquisition_date=form.cleaned_data["acquisition_date"],
                    acquisition_value=form.cleaned_data["acquisition_value"],
                    condition=form.cleaned_data["condition"],
                    notes=form.cleaned_data["notes"],
                )
            )
            messages.success(request, f"Equipamento {equipment.patrimonio} cadastrado com sucesso.")
            return redirect("equipment:detail", patrimonio=equipment.patrimonio)
        return render(request, "equipment/equipment_form.html", {"form": form, "is_new": True})


SESSION_KEY_BATCH_PENDING = "equipment_batch_pending"


class EquipmentBatchCreateView(RoleRequiredMixin, View):
    """
    Passo 1/3 do cadastro em lote (melhoria operacional da Fase 1, pedida
    em 25/08/2026) — mesmo padrão de fluxo em múltiplas telas já usado na
    importação legada (upload → revisão → resumo,
    `apps/equipment/views_import.py`): aqui, formulário → confirmação
    (`EquipmentBatchConfirmView`) → resultado (`EquipmentBatchResultView`).

    Mesma permissão de `EquipmentCreateView` (`CAN_MANAGE_EQUIPMENT`) — os
    perfis que já podem cadastrar equipamento individualmente são os
    mesmos que podem cadastrar em lote; nenhum privilégio novo é
    concedido.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        return render(request, "equipment/batch_create.html", {"form": EquipmentBatchCreateForm()})

    def post(self, request):
        form = EquipmentBatchCreateForm(request.POST)
        if not form.is_valid():
            return render(request, "equipment/batch_create.html", {"form": form})

        cleaned = form.cleaned_data
        # Guardado na sessão (não no banco ainda) — nada é persistido até a
        # confirmação explícita no próximo passo. Mesma técnica já usada em
        # LegacyImportUploadView/LegacyImportReviewView.
        request.session[SESSION_KEY_BATCH_PENDING] = {
            "model_id": cleaned["model"].pk,
            "quantity": cleaned["quantity"],
            "condition": cleaned["condition"],
            "supplier": cleaned["supplier"],
            "acquisition_date": cleaned["acquisition_date"].isoformat() if cleaned["acquisition_date"] else None,
            "acquisition_value": str(cleaned["acquisition_value"]) if cleaned["acquisition_value"] is not None else None,
            "notes": cleaned["notes"],
        }
        return redirect("equipment:batch_confirm")


class EquipmentBatchConfirmView(RoleRequiredMixin, View):
    """
    Passo 2/3: confirmação explícita antes de criar de fato — pedido do
    usuário para evitar criação acidental em lotes grandes.

    A proteção contra clique duplo/reenvio do formulário está em
    `del request.session[SESSION_KEY_BATCH_PENDING]` logo no início do
    POST: a chave é consumida (uso único) antes mesmo de chamar o serviço,
    então uma segunda tentativa (F5 na página de confirmação, "voltar" +
    reenviar) não encontra mais dado pendente e é mandada de volta para o
    formulário, em vez de criar um segundo lote.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        pending = request.session.get(SESSION_KEY_BATCH_PENDING)
        if not pending:
            messages.info(
                request, "Nenhum cadastro em lote pendente de confirmação — preencha o formulário primeiro."
            )
            return redirect("equipment:batch_create")

        model = get_object_or_404(EquipmentModel, pk=pending["model_id"])
        return render(
            request,
            "equipment/batch_confirm.html",
            {
                "model": model,
                "quantity": pending["quantity"],
                "condition_display": dict(Condition.choices).get(pending["condition"], pending["condition"]),
            },
        )

    def post(self, request):
        pending = request.session.get(SESSION_KEY_BATCH_PENDING)
        if not pending:
            messages.error(request, "A confirmação expirou ou já foi usada. Preencha o formulário novamente.")
            return redirect("equipment:batch_create")

        del request.session[SESSION_KEY_BATCH_PENDING]

        try:
            batch = create_equipment_batch(
                NewEquipmentBatchData(
                    model_id=pending["model_id"],
                    quantity=pending["quantity"],
                    created_by=request.user,
                    condition=pending["condition"],
                    supplier=pending["supplier"],
                    acquisition_date=(
                        datetime.date.fromisoformat(pending["acquisition_date"])
                        if pending["acquisition_date"]
                        else None
                    ),
                    acquisition_value=(
                        Decimal(pending["acquisition_value"]) if pending["acquisition_value"] is not None else None
                    ),
                    notes=pending["notes"],
                )
            )
        except (ValueError, EquipmentModel.DoesNotExist) as exc:
            messages.error(request, str(exc) or "Não foi possível criar o lote de equipamentos.")
            return redirect("equipment:batch_create")

        messages.success(
            request, f"{batch.quantity} equipamentos criados: {batch.first_patrimonio} → {batch.last_patrimonio}."
        )
        return redirect("equipment:batch_result", batch_id=batch.pk)


class EquipmentBatchResultView(RoleRequiredMixin, View):
    """Passo 3/3: resumo do lote recém-criado, com atalhos para consultar/exportar só essas unidades."""

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, batch_id):
        batch = get_object_or_404(EquipmentBatch.objects.select_related("model", "created_by"), pk=batch_id)
        return render(request, "equipment/batch_result.html", {"batch": batch})


class EquipmentUpdateView(RoleRequiredMixin, View):
    """
    Edição de equipamento — nunca toca em `model`, `patrimonio`,
    `model_sequence`, `status` ou `condition` (essas têm fluxo próprio:
    reclassificação/reemissão e as telas de alterar status/condição).
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        return render(
            request,
            "equipment/equipment_form.html",
            {"form": EquipmentUpdateForm(instance=equipment), "is_new": False, "equipment": equipment},
        )

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = EquipmentUpdateForm(request.POST, instance=equipment)
        if form.is_valid():
            form.save()
            messages.success(request, f"Equipamento {equipment.patrimonio} atualizado.")
            return redirect("equipment:detail", patrimonio=equipment.patrimonio)
        return render(
            request, "equipment/equipment_form.html", {"form": form, "is_new": False, "equipment": equipment}
        )


class EquipmentChangeStatusView(RoleRequiredMixin, View):
    """
    Alterar status — matriz da seção 11 concede isto também a
    Operacional/Técnico, por isso é uma tela separada do cadastro/edição
    completo (que é só Administrador/Administrativo). Sempre gera
    `StatusHistory` (services.change_status()), nunca edição direta.
    """

    allowed_roles = CAN_CHANGE_STATUS_CONDITION

    def get(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = ChangeStatusForm(current_status=equipment.status)
        return render(request, "equipment/change_status.html", {"form": form, "equipment": equipment})

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = ChangeStatusForm(request.POST, current_status=equipment.status)
        if form.is_valid():
            try:
                change_status(
                    equipment=equipment,
                    new_status=form.cleaned_data["new_status"],
                    reason=form.cleaned_data["reason"],
                    changed_by=request.user,
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(request, "equipment/change_status.html", {"form": form, "equipment": equipment})
            messages.success(request, f"Status de {equipment.patrimonio} atualizado.")
            return redirect("equipment:detail", patrimonio=equipment.patrimonio)
        return render(request, "equipment/change_status.html", {"form": form, "equipment": equipment})


class EquipmentChangeConditionView(RoleRequiredMixin, View):
    """Alterar condição — mesmo raciocínio de `EquipmentChangeStatusView`."""

    allowed_roles = CAN_CHANGE_STATUS_CONDITION

    def get(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = ChangeConditionForm(current_condition=equipment.condition)
        return render(request, "equipment/change_condition.html", {"form": form, "equipment": equipment})

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = ChangeConditionForm(request.POST, current_condition=equipment.condition)
        if form.is_valid():
            try:
                change_condition(
                    equipment=equipment,
                    new_condition=form.cleaned_data["new_condition"],
                    reason=form.cleaned_data["reason"],
                    changed_by=request.user,
                )
            except ValueError as exc:
                form.add_error(None, str(exc))
                return render(request, "equipment/change_condition.html", {"form": form, "equipment": equipment})
            messages.success(request, f"Condição de {equipment.patrimonio} atualizada.")
            return redirect("equipment:detail", patrimonio=equipment.patrimonio)
        return render(request, "equipment/change_condition.html", {"form": form, "equipment": equipment})


class EquipmentReclassifyView(RoleRequiredMixin, View):
    """
    Reclassificação de modelo (ação restrita, Administrador) — especificação,
    seção 8/12/13 (fluxo C). Preserva patrimônio e model_sequence; só
    corrige `model`. Motivo obrigatório, evento auditado via
    django-simple-history.
    """

    allowed_roles = CAN_RECLASSIFY_EQUIPMENT_MODEL

    def get(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = ReclassifyModelForm(current_model=equipment.model)
        return render(request, "equipment/reclassify.html", {"form": form, "equipment": equipment})

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = ReclassifyModelForm(request.POST, current_model=equipment.model)
        if form.is_valid():
            reclassify_model(
                equipment=equipment,
                new_model=form.cleaned_data["new_model"],
                reason=form.cleaned_data["reason"],
                changed_by=request.user,
            )
            messages.success(
                request, f"Modelo de {equipment.patrimonio} reclassificado. O patrimônio não foi alterado."
            )
            return redirect("equipment:detail", patrimonio=equipment.patrimonio)
        return render(request, "equipment/reclassify.html", {"form": form, "equipment": equipment})


class EquipmentSupersedeView(RoleRequiredMixin, View):
    """
    Reemissão excepcional de patrimônio (Administrador) — especificação,
    seção 8/12/13 (fluxo C, passo 4). Usar só quando a divergência for
    grande demais para conviver com a reclassificação simples; exige
    confirmação explícita de que a etiqueta física será reimpressa.
    """

    allowed_roles = CAN_SUPERSEDE_EQUIPMENT

    def get(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = SupersedeEquipmentForm()
        return render(request, "equipment/supersede.html", {"form": form, "equipment": equipment})

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = SupersedeEquipmentForm(request.POST)
        if form.is_valid():
            new_equipment = supersede_equipment(
                equipment=equipment,
                new_model=form.cleaned_data["new_model"],
                reason=form.cleaned_data["reason"],
                changed_by=request.user,
            )
            messages.success(
                request,
                f"Patrimônio reemitido: {equipment.patrimonio} foi inativado, "
                f"novo patrimônio {new_equipment.patrimonio}.",
            )
            return redirect("equipment:detail", patrimonio=new_equipment.patrimonio)
        return render(request, "equipment/supersede.html", {"form": form, "equipment": equipment})


class EquipmentExportView(RoleRequiredMixin, View):
    """
    Exportação CSV/Excel — tela da seção 12 ("Exportação de dados").
    Respeita exatamente os mesmos filtros da listagem (`?q=`, `?status=`,
    `?condition=`, `?category=`, `?model=`), passados como querystring.
    Uso: /equipamentos/exportar/?format=xlsx&status=DISPONIVEL
    """

    allowed_roles = CAN_EXPORT_DATA

    def get(self, request):
        from apps.equipment.export import export_to_csv, export_to_xlsx

        qs = Equipment.objects.select_related("model", "category").filter(is_active=True)
        qs = filter_equipment_queryset(qs, request.GET).order_by("model__code", "model_sequence")

        fmt = request.GET.get("format", "csv")
        if fmt == "xlsx":
            return export_to_xlsx(qs)
        return export_to_csv(qs)


class EquipmentDetailView(View):
    """
    Rota pública do QR Code (especificação, seção 12/14).

    Não autenticado: landing pública/comercial (etapa de UX/UI,
    28/08/2026) — só empresa + categoria + modelo + patrimônio.
    Autenticado: ficha completa (a Fase 1 ainda não tem ações de
    manutenção/movimentação — essas chegam na Fase 2, seção 21).

    Os dois ramos usam consultas DIFERENTES ao banco (defesa em
    profundidade, ver `_get_public_equipment`/`_get_private_equipment`
    abaixo) — a separação por `is_authenticated` já existia antes, mas até
    a auditoria de 28/08/2026 (ver AUDITORIA_UX_HOME_NAVEGACAO_QR.md, item
    [6]) as duas rotas compartilhavam o MESMO `select_related` (incluindo
    `current_client`/`current_location`), e só o TEMPLATE público
    decidia não renderizar esses campos. A proteção do valor de aquisição
    já usava `.defer()` (auditoria final da Fase 1); agora o mesmo
    raciocínio se estende a cliente/localização/notas/histórico técnico
    resumido/lote/reemissão para o visitante anônimo: esses campos nunca
    chegam a sair do banco na rota pública, não é só uma questão de o
    template "não usar" o que já veio na consulta.
    """

    # Campos que a landing pública (`equipment/detail_public.html`)
    # efetivamente usa hoje — qualquer campo fora desta lista fica
    # deferred pelo Django (nunca sai do banco) para o visitante anônimo.
    # Ver auditoria, itens [5]/[6]/[12] para a lista completa do que NUNCA
    # pode ser público (cliente, localização, financeiro, notas,
    # histórico operacional, IDs internos administrativos).
    _PUBLIC_ONLY_FIELDS = (
        "patrimonio",
        "model__name",
        "model__code",
        "model__manufacturer",
        "category__name",
    )

    def get(self, request, patrimonio: str):
        if not request.user.is_authenticated:
            equipment = self._get_public_equipment(patrimonio)
            return render(
                request,
                "equipment/detail_public.html",
                {"equipment": equipment},
            )

        return self._render_private(request, patrimonio)

    def _get_public_equipment(self, patrimonio: str) -> Equipment:
        queryset = (
            Equipment.objects.select_related("model", "category")
            .only(*self._PUBLIC_ONLY_FIELDS)
        )
        return get_object_or_404(queryset, patrimonio=patrimonio)

    def _render_private(self, request, patrimonio: str):
        # Fornecedor/data/valor de aquisição (seção 11: "Ver valor de
        # aquisição / dados financeiros" — Admin e Administrativo, não
        # Operacional nem Consulta) só devem sair do banco quando o
        # usuário tem CAN_VIEW_ACQUISITION_VALUE. Corrigido na auditoria
        # final da Fase 1 (25/08/2026): antes, esses três campos eram
        # sempre carregados no objeto `equipment` e a proteção dependia
        # só do template esconder o bloco (`{% if
        # user.is_administrativo_ou_superior %}`) — correto na tela, mas
        # sem nenhuma garantia de que o dado não estava disponível no
        # contexto/consulta para quem não deveria vê-lo. Usar
        # `.defer(...)` aqui garante que, para quem não tem a permissão, a
        # própria consulta ao banco nunca traz esses três campos — não é
        # só uma questão de o template não renderizar.
        can_view_acquisition_value = request.user.is_superuser or request.user.role in CAN_VIEW_ACQUISITION_VALUE

        queryset = Equipment.objects.select_related("model", "category", "current_client", "current_location")
        if not can_view_acquisition_value:
            queryset = queryset.defer("supplier", "acquisition_date", "acquisition_value")

        equipment = get_object_or_404(queryset, patrimonio=patrimonio)

        # Import local — mesmo padrão já usado no bloco de Movement dentro
        # de `get_equipment_history_timeline()`: evita subir uma
        # dependência de apps.maintenance para o topo deste módulo só por
        # causa de uma seção de leitura da ficha. Só quem tem
        # CAN_VIEW_MAINTENANCE vê a seção (checado no template, mesmo
        # padrão de `can_view_acquisition_value` acima — a ação de
        # ESCREVER (abrir/registrar) continua protegida de verdade no
        # backend por `CAN_REGISTER_OPERATIONS`, em
        # `apps.maintenance.views`, nunca só aqui).
        from apps.accounts.permissions import CAN_VIEW_MAINTENANCE
        from apps.maintenance.services import get_equipment_maintenance_summary

        can_view_maintenance = request.user.is_superuser or request.user.role in CAN_VIEW_MAINTENANCE
        maintenance_summary = get_equipment_maintenance_summary(equipment) if can_view_maintenance else None

        return render(
            request,
            "equipment/detail_private.html",
            {
                "equipment": equipment,
                # Só na ficha autenticada — a rota pública do QR Code
                # (acima) nunca recebe esta chave no contexto, então
                # `detail_public.html` não tem como exibir o histórico
                # mesmo por engano.
                "history_events": get_equipment_history_timeline(equipment),
                "can_view_acquisition_value": can_view_acquisition_value,
                "can_view_maintenance": can_view_maintenance,
                "maintenance_summary": maintenance_summary,
            },
        )
