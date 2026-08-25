"""
Views de `Location` e `Movement` — Fase 2 (Operação). Toda escrita passa
por `apps.operations.services` (nunca `Location.objects.create()`/
`Movement.objects.create()` direto aqui) — mesma disciplina de
`apps.equipment.views` desde a Fase 1.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import CAN_MANAGE_LOCATIONS, CAN_REGISTER_OPERATIONS, CAN_VIEW_CLIENTS, RoleRequiredMixin
from apps.core.forms import AddressForm
from apps.core.services import AddressData
from apps.equipment.models import Equipment
from apps.operations.forms import LocationForm, LocationUpdateForm, MovementForm
from apps.operations.models import Location, LocationType
from apps.operations.services import (
    LocationUpdateData,
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
    update_location,
    update_location_address,
)


class LocationListView(RoleRequiredMixin, ListView):
    """
    Consulta de unidades/locais — a matriz da seção 11 (v1.0) não lista uma
    permissão dedicada de VISUALIZAÇÃO de `Location` (só cadastro/edição,
    via `CAN_MANAGE_LOCATIONS`); decisão tomada durante a implementação:
    reaproveitar `CAN_VIEW_CLIENTS` (todos os 4 perfis) aqui, mesmo padrão
    "todos consultam, perfil restrito edita" já usado para clientes e
    movimentações — não é uma permissão nova, só a escolha de qual
    constante já aprovada rege esta tela de leitura.
    """

    allowed_roles = CAN_VIEW_CLIENTS
    model = Location
    template_name = "operations/location_list.html"
    context_object_name = "locations"
    paginate_by = 50

    def get_queryset(self):
        qs = Location.objects.filter(is_active=True).select_related("client").order_by("type", "name")
        type_filter = self.request.GET.get("type", "")
        if type_filter:
            qs = qs.filter(type=type_filter)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["type_choices"] = LocationType.choices
        context["selected_type"] = self.request.GET.get("type", "")
        return context


class LocationDetailView(RoleRequiredMixin, View):
    allowed_roles = CAN_VIEW_CLIENTS

    def get(self, request, pk):
        location = get_object_or_404(Location.objects.select_related("client", "address"), pk=pk)
        equipment_here = Equipment.objects.filter(current_location=location, is_active=True).select_related(
            "model", "category"
        )
        return render(
            request,
            "operations/location_detail.html",
            {"location": location, "equipment_here": equipment_here},
        )


class LocationCreateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_LOCATIONS

    def get(self, request):
        initial = {}
        client_id = request.GET.get("client")
        if client_id:
            initial = {"type": LocationType.CLIENTE, "client": client_id}
        form = LocationForm(initial=initial)
        return render(request, "operations/location_form.html", {"form": form, "is_new": True})

    def post(self, request):
        form = LocationForm(request.POST)
        if not form.is_valid():
            return render(request, "operations/location_form.html", {"form": form, "is_new": True})

        cleaned = form.cleaned_data
        address = AddressData(
            cep=cleaned["cep"],
            logradouro=cleaned["logradouro"],
            numero=cleaned["numero"],
            complemento=cleaned["complemento"],
            bairro=cleaned["bairro"],
            cidade=cleaned["cidade"],
            uf=cleaned["uf"],
            reference_notes=cleaned["reference_notes"],
        )
        try:
            location = create_location(
                NewLocationData(name=cleaned["name"], type=cleaned["type"], client=cleaned["client"], address=address)
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "operations/location_form.html", {"form": form, "is_new": True})

        messages.success(request, f"Unidade {location.name} cadastrada com sucesso.")
        return redirect("operations:location_detail", pk=location.pk)


class LocationUpdateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_LOCATIONS

    def get(self, request, pk):
        location = get_object_or_404(Location, pk=pk)
        form = LocationUpdateForm(initial={"name": location.name, "type": location.type, "client": location.client_id})
        return render(request, "operations/location_update_form.html", {"form": form, "location": location})

    def post(self, request, pk):
        location = get_object_or_404(Location, pk=pk)
        form = LocationUpdateForm(request.POST)
        if not form.is_valid():
            return render(request, "operations/location_update_form.html", {"form": form, "location": location})

        try:
            update_location(
                location=location,
                data=LocationUpdateData(
                    name=form.cleaned_data["name"], type=form.cleaned_data["type"], client=form.cleaned_data["client"]
                ),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "operations/location_update_form.html", {"form": form, "location": location})

        messages.success(request, f"Unidade {location.name} atualizada.")
        return redirect("operations:location_detail", pk=location.pk)


class LocationAddressUpdateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_LOCATIONS

    def get(self, request, pk):
        location = get_object_or_404(Location, pk=pk)
        form = AddressForm(instance=location.address)
        return render(request, "operations/location_address_form.html", {"form": form, "location": location})

    def post(self, request, pk):
        location = get_object_or_404(Location, pk=pk)
        form = AddressForm(request.POST, instance=location.address)
        if not form.is_valid():
            return render(request, "operations/location_address_form.html", {"form": form, "location": location})

        data = AddressData(
            cep=form.cleaned_data["cep"],
            logradouro=form.cleaned_data["logradouro"],
            numero=form.cleaned_data["numero"],
            complemento=form.cleaned_data["complemento"],
            bairro=form.cleaned_data["bairro"],
            cidade=form.cleaned_data["cidade"],
            uf=form.cleaned_data["uf"],
            reference_notes=form.cleaned_data["reference_notes"],
        )
        update_location_address(location=location, data=data)
        messages.success(request, "Endereço operacional atualizado.")
        return redirect("operations:location_detail", pk=location.pk)


class MovementCreateView(RoleRequiredMixin, View):
    """
    Registro de movimentação (instalação/retirada/transferência/retorno ao
    estoque/envio-retorno de manutenção) para um equipamento específico —
    acessada a partir da ficha autenticada do equipamento
    (`equipment:detail`). Sempre via `create_movement()`.
    """

    allowed_roles = CAN_REGISTER_OPERATIONS

    def get(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = MovementForm(current_location=equipment.current_location)
        return render(request, "operations/movement_form.html", {"form": form, "equipment": equipment})

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        form = MovementForm(request.POST, current_location=equipment.current_location)
        if not form.is_valid():
            return render(request, "operations/movement_form.html", {"form": form, "equipment": equipment})

        try:
            movement = create_movement(
                NewMovementData(
                    equipment_id=equipment.pk,
                    movement_type=form.cleaned_data["movement_type"],
                    created_by=request.user,
                    destination_location=form.cleaned_data["destination_location"],
                    reason=form.cleaned_data["reason"],
                )
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "operations/movement_form.html", {"form": form, "equipment": equipment})

        messages.success(
            request, f"Movimentação registrada: {movement.get_movement_type_display()} — {equipment.patrimonio}."
        )
        return redirect("equipment:detail", patrimonio=equipment.patrimonio)
