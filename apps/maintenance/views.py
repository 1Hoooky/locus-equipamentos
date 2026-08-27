"""
Views de `Maintenance`/`Cleaning` — UI operacional (Fase 2). Toda escrita
passa exclusivamente pelos services já existentes (`open_maintenance()`,
`close_maintenance()`, `cancel_maintenance()`, `create_cleaning()`,
`cancel_cleaning()`) — nunca `Maintenance.objects.create()`/`.save()`/
`Cleaning.objects.create()` direto aqui, mesma disciplina de
`apps.operations.views`. Nenhuma regra de domínio é reescrita nesta
camada: erros de domínio (`ValueError`) viram mensagem de formulário,
nunca HTTP 500.

Permissões (seção 9 da revisão): leitura via `CAN_VIEW_MAINTENANCE`
(4 perfis), escrita via `CAN_REGISTER_OPERATIONS` (Admin/Administrativo/
Operacional) — Consulta nunca alcança nenhuma view de escrita abaixo,
mesmo manipulando a URL/POST diretamente (RoleRequiredMixin, backend).
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import CAN_REGISTER_OPERATIONS, CAN_VIEW_MAINTENANCE, RoleRequiredMixin
from apps.core.submission import SubmissionGuard
from apps.equipment.models import Equipment
from apps.maintenance.filters import filter_cleaning_queryset, filter_maintenance_queryset
from apps.maintenance.forms import (
    CleaningCancelForm,
    CleaningForm,
    MaintenanceCancelForm,
    MaintenanceCloseForm,
    MaintenanceOpenForm,
    departure_movement_queryset,
)
from apps.maintenance.models import Cleaning, Maintenance, MaintenanceStatus, MaintenanceType
from apps.maintenance.services import (
    CloseMaintenanceData,
    NewCleaningData,
    NewMaintenanceData,
    cancel_cleaning,
    cancel_maintenance,
    close_maintenance,
    create_cleaning,
    open_maintenance,
)

# Escopos "planos" (não por objeto) para os dois fluxos de CRIAÇÃO — o
# equipamento é escolhido DENTRO do formulário (não vem na URL, diferente
# de MovementCreateView), então não há identificador conhecido no GET
# inicial para compor um scope por objeto; mesmo padrão já usado por
# `LocationCreateView` (`SubmissionGuard("location_create")`).
_maintenance_open_guard = SubmissionGuard("maintenance_open")
_cleaning_create_guard = SubmissionGuard("cleaning_create")


def _maintenance_close_guard(pk: int) -> SubmissionGuard:
    return SubmissionGuard(f"maintenance_close:{pk}")


def _maintenance_cancel_guard(pk: int) -> SubmissionGuard:
    return SubmissionGuard(f"maintenance_cancel:{pk}")


def _cleaning_cancel_guard(pk: int) -> SubmissionGuard:
    return SubmissionGuard(f"cleaning_cancel:{pk}")


class MaintenanceListView(RoleRequiredMixin, ListView):
    allowed_roles = CAN_VIEW_MAINTENANCE
    model = Maintenance
    template_name = "maintenance/maintenance_list.html"
    context_object_name = "maintenances"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Maintenance.objects.filter(is_active=True)
            .select_related("equipment", "equipment__model", "responsible")
            .order_by("-created_at")
        )
        return filter_maintenance_queryset(qs, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["status_choices"] = MaintenanceStatus.choices
        context["type_choices"] = MaintenanceType.choices
        context["selected_status"] = self.request.GET.get("status", "")
        context["selected_type"] = self.request.GET.get("maintenance_type", "")
        context["selected_q"] = self.request.GET.get("q", "")
        return context


class MaintenanceDetailView(RoleRequiredMixin, View):
    allowed_roles = CAN_VIEW_MAINTENANCE

    def get(self, request, pk):
        maintenance = get_object_or_404(
            Maintenance.objects.select_related(
                "equipment",
                "equipment__model",
                "equipment__category",
                "responsible",
                "created_by",
                "departure_movement",
                "return_movement",
            ),
            pk=pk,
        )
        return render(request, "maintenance/maintenance_detail.html", {"maintenance": maintenance})


class MaintenanceOpenView(RoleRequiredMixin, View):
    """
    Abertura de `Maintenance` — sempre via `open_maintenance()`. Acessível
    de forma genérica (equipamento escolhido no próprio formulário) e a
    partir da ficha do equipamento (`?equipment=<pk>`, pré-seleciona sem
    travar o campo — o service revalida tudo de qualquer forma).
    """

    allowed_roles = CAN_REGISTER_OPERATIONS

    def _initial_equipment(self, request):
        equipment_id = request.GET.get("equipment") or request.POST.get("equipment")
        if not equipment_id:
            return None
        return Equipment.objects.filter(pk=equipment_id, is_active=True).first()

    def get(self, request):
        initial_equipment = self._initial_equipment(request)
        initial = {"equipment": initial_equipment.pk} if initial_equipment else {}
        form = MaintenanceOpenForm(initial=initial, initial_equipment=initial_equipment)
        token = _maintenance_open_guard.issue(request)
        return render(
            request,
            "maintenance/maintenance_open_form.html",
            {"form": form, "submission_token": token, "initial_equipment": initial_equipment},
        )

    def post(self, request):
        form = MaintenanceOpenForm(request.POST)
        if not form.is_valid():
            token = _maintenance_open_guard.issue(request)
            return render(
                request, "maintenance/maintenance_open_form.html", {"form": form, "submission_token": token}
            )

        if not _maintenance_open_guard.consume_if_valid(request):
            # Reenvio (Enter repetido, duplo clique) — mesma proteção de
            # `LocationCreateView`/`MovementCreateView`. Nada é criado.
            messages.info(
                request,
                "Este formulário já havia sido enviado. Se a manutenção não aparece na lista, tente novamente.",
            )
            return redirect("maintenance:maintenance_list")

        try:
            maintenance = open_maintenance(
                NewMaintenanceData(
                    equipment_id=form.cleaned_data["equipment"].pk,
                    maintenance_type=form.cleaned_data["maintenance_type"],
                    responsible=form.cleaned_data["responsible"],
                    created_by=request.user,
                    diagnosis=form.cleaned_data["diagnosis"],
                    notes=form.cleaned_data["notes"],
                    departure_movement=form.cleaned_data["departure_movement"],
                )
            )
        except ValueError as exc:
            # Erro de domínio — mensagem compreensível na própria tela,
            # nunca HTTP 500 (ex.: POST manipulado escolhendo um
            # departure_movement de outro equipamento/tipo incompatível —
            # o form já filtra a queryset, mas o service é a autoridade
            # final contra um valor forjado direto no POST).
            form.add_error(None, str(exc))
            token = _maintenance_open_guard.issue(request)
            return render(
                request, "maintenance/maintenance_open_form.html", {"form": form, "submission_token": token}
            )

        messages.success(request, f"Manutenção aberta para {maintenance.equipment.patrimonio}.")
        return redirect("maintenance:maintenance_detail", pk=maintenance.pk)


class DepartureMovementOptionsView(RoleRequiredMixin, View):
    """
    Fragmento HTML (htmx) — opções de `departure_movement` para o
    equipamento escolhido no formulário de abertura, atualizado ao trocar
    o equipamento sem recarregar a página. Puramente UX: o form/service
    continuam sendo quem decide o que é aceito no POST final, mesmo com
    JS desabilitado (campo fica vazio até a próxima navegação).
    """

    allowed_roles = CAN_REGISTER_OPERATIONS

    def get(self, request):
        equipment = Equipment.objects.filter(pk=request.GET.get("equipment"), is_active=True).first()
        movements = departure_movement_queryset(equipment)
        return render(request, "maintenance/_departure_movement_options.html", {"movements": movements})


class MaintenanceCloseView(RoleRequiredMixin, View):
    allowed_roles = CAN_REGISTER_OPERATIONS

    def get(self, request, pk):
        maintenance = get_object_or_404(Maintenance.objects.select_related("equipment"), pk=pk)
        if maintenance.status != MaintenanceStatus.ABERTA:
            messages.error(request, "Esta manutenção não está mais aberta.")
            return redirect("maintenance:maintenance_detail", pk=maintenance.pk)

        form = MaintenanceCloseForm(equipment=maintenance.equipment)
        token = _maintenance_close_guard(pk).issue(request)
        return render(
            request,
            "maintenance/maintenance_close_form.html",
            {"form": form, "maintenance": maintenance, "submission_token": token},
        )

    def post(self, request, pk):
        maintenance = get_object_or_404(Maintenance.objects.select_related("equipment"), pk=pk)
        if maintenance.status != MaintenanceStatus.ABERTA:
            messages.error(request, "Esta manutenção não está mais aberta.")
            return redirect("maintenance:maintenance_detail", pk=maintenance.pk)

        guard = _maintenance_close_guard(pk)
        form = MaintenanceCloseForm(request.POST, equipment=maintenance.equipment)
        if not form.is_valid():
            token = guard.issue(request)
            return render(
                request,
                "maintenance/maintenance_close_form.html",
                {"form": form, "maintenance": maintenance, "submission_token": token},
            )

        if not guard.consume_if_valid(request):
            messages.info(request, "Esta conclusão já havia sido enviada.")
            return redirect("maintenance:maintenance_detail", pk=maintenance.pk)

        try:
            close_maintenance(
                maintenance=maintenance,
                data=CloseMaintenanceData(
                    service_performed=form.cleaned_data["service_performed"],
                    closed_by=request.user,
                    condition_after=form.cleaned_data["condition_after"],
                    return_movement=form.cleaned_data["return_movement"],
                ),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            token = guard.issue(request)
            return render(
                request,
                "maintenance/maintenance_close_form.html",
                {"form": form, "maintenance": maintenance, "submission_token": token},
            )

        messages.success(request, f"Manutenção concluída — {maintenance.equipment.patrimonio}.")
        return redirect("maintenance:maintenance_detail", pk=maintenance.pk)


class MaintenanceCancelView(RoleRequiredMixin, View):
    allowed_roles = CAN_REGISTER_OPERATIONS

    def get(self, request, pk):
        maintenance = get_object_or_404(Maintenance.objects.select_related("equipment"), pk=pk)
        if maintenance.status != MaintenanceStatus.ABERTA:
            messages.error(request, "Esta manutenção não está mais aberta.")
            return redirect("maintenance:maintenance_detail", pk=maintenance.pk)

        form = MaintenanceCancelForm()
        token = _maintenance_cancel_guard(pk).issue(request)
        return render(
            request,
            "maintenance/maintenance_cancel_confirm.html",
            {"form": form, "maintenance": maintenance, "submission_token": token},
        )

    def post(self, request, pk):
        maintenance = get_object_or_404(Maintenance.objects.select_related("equipment"), pk=pk)
        if maintenance.status != MaintenanceStatus.ABERTA:
            messages.error(request, "Esta manutenção não está mais aberta.")
            return redirect("maintenance:maintenance_detail", pk=maintenance.pk)

        guard = _maintenance_cancel_guard(pk)
        form = MaintenanceCancelForm(request.POST)
        if not form.is_valid():
            token = guard.issue(request)
            return render(
                request,
                "maintenance/maintenance_cancel_confirm.html",
                {"form": form, "maintenance": maintenance, "submission_token": token},
            )

        if not guard.consume_if_valid(request):
            messages.info(request, "Este cancelamento já havia sido enviado.")
            return redirect("maintenance:maintenance_detail", pk=maintenance.pk)

        try:
            cancel_maintenance(maintenance=maintenance, cancelled_by=request.user, reason=form.cleaned_data["reason"])
        except ValueError as exc:
            form.add_error(None, str(exc))
            token = guard.issue(request)
            return render(
                request,
                "maintenance/maintenance_cancel_confirm.html",
                {"form": form, "maintenance": maintenance, "submission_token": token},
            )

        messages.success(request, f"Manutenção cancelada — {maintenance.equipment.patrimonio}.")
        return redirect("maintenance:maintenance_detail", pk=maintenance.pk)


class CleaningListView(RoleRequiredMixin, ListView):
    allowed_roles = CAN_VIEW_MAINTENANCE
    model = Cleaning
    template_name = "maintenance/cleaning_list.html"
    context_object_name = "cleanings"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Cleaning.objects.filter(is_active=True)
            .select_related("equipment", "equipment__model", "responsible")
            .order_by("-performed_at")
        )
        return filter_cleaning_queryset(qs, self.request.GET)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_q"] = self.request.GET.get("q", "")
        return context


class CleaningDetailView(RoleRequiredMixin, View):
    allowed_roles = CAN_VIEW_MAINTENANCE

    def get(self, request, pk):
        cleaning = get_object_or_404(
            Cleaning.objects.select_related(
                "equipment", "equipment__model", "equipment__category", "responsible", "created_by", "movement"
            ),
            pk=pk,
        )
        return render(request, "maintenance/cleaning_detail.html", {"cleaning": cleaning})


class CleaningCreateView(RoleRequiredMixin, View):
    allowed_roles = CAN_REGISTER_OPERATIONS

    def _initial_equipment(self, request):
        equipment_id = request.GET.get("equipment") or request.POST.get("equipment")
        if not equipment_id:
            return None
        return Equipment.objects.filter(pk=equipment_id, is_active=True).first()

    def get(self, request):
        initial_equipment = self._initial_equipment(request)
        initial = {"equipment": initial_equipment.pk} if initial_equipment else {}
        form = CleaningForm(initial=initial, initial_equipment=initial_equipment)
        token = _cleaning_create_guard.issue(request)
        return render(
            request,
            "maintenance/cleaning_form.html",
            {"form": form, "submission_token": token, "initial_equipment": initial_equipment},
        )

    def post(self, request):
        form = CleaningForm(request.POST)
        if not form.is_valid():
            token = _cleaning_create_guard.issue(request)
            return render(request, "maintenance/cleaning_form.html", {"form": form, "submission_token": token})

        if not _cleaning_create_guard.consume_if_valid(request):
            messages.info(
                request, "Este formulário já havia sido enviado. Se o registro não aparece na lista, tente novamente."
            )
            return redirect("maintenance:cleaning_list")

        try:
            cleaning = create_cleaning(
                NewCleaningData(
                    equipment_id=form.cleaned_data["equipment"].pk,
                    responsible=form.cleaned_data["responsible"],
                    created_by=request.user,
                    performed_at=form.cleaned_data["performed_at"],
                    notes=form.cleaned_data["notes"],
                    next_due_at=form.cleaned_data["next_due_at"],
                    movement=form.cleaned_data["movement"],
                )
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            token = _cleaning_create_guard.issue(request)
            return render(request, "maintenance/cleaning_form.html", {"form": form, "submission_token": token})

        messages.success(request, f"Higienização registrada — {cleaning.equipment.patrimonio}.")
        return redirect("maintenance:cleaning_detail", pk=cleaning.pk)


class CleaningCancelView(RoleRequiredMixin, View):
    allowed_roles = CAN_REGISTER_OPERATIONS

    def get(self, request, pk):
        cleaning = get_object_or_404(Cleaning.objects.select_related("equipment"), pk=pk)
        if not cleaning.is_active:
            messages.error(request, "Este registro já está cancelado.")
            return redirect("maintenance:cleaning_detail", pk=cleaning.pk)

        form = CleaningCancelForm()
        token = _cleaning_cancel_guard(pk).issue(request)
        return render(
            request,
            "maintenance/cleaning_cancel_confirm.html",
            {"form": form, "cleaning": cleaning, "submission_token": token},
        )

    def post(self, request, pk):
        cleaning = get_object_or_404(Cleaning.objects.select_related("equipment"), pk=pk)
        if not cleaning.is_active:
            messages.error(request, "Este registro já está cancelado.")
            return redirect("maintenance:cleaning_detail", pk=cleaning.pk)

        guard = _cleaning_cancel_guard(pk)
        form = CleaningCancelForm(request.POST)
        if not form.is_valid():
            token = guard.issue(request)
            return render(
                request,
                "maintenance/cleaning_cancel_confirm.html",
                {"form": form, "cleaning": cleaning, "submission_token": token},
            )

        if not guard.consume_if_valid(request):
            messages.info(request, "Este cancelamento já havia sido enviado.")
            return redirect("maintenance:cleaning_detail", pk=cleaning.pk)

        try:
            cancel_cleaning(cleaning=cleaning)
        except ValueError as exc:
            form.add_error(None, str(exc))
            token = guard.issue(request)
            return render(
                request,
                "maintenance/cleaning_cancel_confirm.html",
                {"form": form, "cleaning": cleaning, "submission_token": token},
            )

        messages.success(request, f"Higienização cancelada — {cleaning.equipment.patrimonio}.")
        return redirect("maintenance:cleaning_detail", pk=cleaning.pk)
