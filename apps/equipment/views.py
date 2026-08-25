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
    """Todos os 4 perfis podem consultar (matriz da seção 11)."""

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
        return context


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

    Não autenticado: só empresa + categoria + modelo + patrimônio.
    Autenticado: ficha completa (a Fase 1 ainda não tem ações de
    manutenção/movimentação — essas chegam na Fase 2, seção 21).
    """

    def get(self, request, patrimonio: str):
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
        can_view_acquisition_value = request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in CAN_VIEW_ACQUISITION_VALUE
        )

        queryset = Equipment.objects.select_related("model", "category", "current_client", "current_location")
        if not can_view_acquisition_value:
            queryset = queryset.defer("supplier", "acquisition_date", "acquisition_value")

        equipment = get_object_or_404(queryset, patrimonio=patrimonio)

        if not request.user.is_authenticated:
            return render(
                request,
                "equipment/detail_public.html",
                {"equipment": equipment},
            )

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
            },
        )
