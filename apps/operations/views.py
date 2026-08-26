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

from apps.accounts.permissions import (
    CAN_MANAGE_LOCATIONS,
    CAN_REGISTER_OPERATIONS,
    CAN_VIEW_CLIENTS,
    CAN_VIEW_DIAGNOSTICS,
    RoleRequiredMixin,
)
from apps.core.forms import AddressForm
from apps.core.services import AddressData
from apps.core.submission import SubmissionGuard
from apps.equipment.models import Equipment
from apps.operations.forms import LocationForm, LocationUpdateForm, MovementForm
from apps.operations.models import Location, LocationType
from apps.operations.services import (
    LocationUpdateData,
    NewLocationData,
    NewMovementData,
    create_location,
    create_movement,
    execute_duplicate_location_cleanup,
    find_duplicate_location_groups,
    plan_duplicate_location_cleanup,
    update_location,
    update_location_address,
)

# Proteção contra reenvio (2º reteste manual: Enter repetido em "Nova
# unidade" criava várias Locations idênticas) — mesmo SubmissionGuard já
# usado no cadastro de cliente. Server-side, nunca só JS: um mesmo submit
# válido produz no máximo um objeto/evento.
_location_create_guard = SubmissionGuard("location_create")


def _movement_guard(patrimonio: str) -> SubmissionGuard:
    # Scope por equipamento: registrar movimentação de DOIS equipamentos em
    # abas diferentes não pode fazer um formulário invalidar o token do
    # outro (mesma sessão, formulários independentes).
    return SubmissionGuard(f"movement_create:{patrimonio}")


# Mesmo mecanismo de proteção contra reenvio já usado em toda escrita
# deste app — aqui protege contra a AÇÃO em si (a limpeza só pode
# executar depois de uma tela de confirmação ter emitido o token; um POST
# direto, sem ter passado pelo GET de confirmação, nunca tem token válido
# e é bloqueado).
_duplicate_cleanup_guard = SubmissionGuard("duplicate_locations_cleanup")


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
        token = _location_create_guard.issue(request)
        return render(
            request,
            "operations/location_form.html",
            {"form": form, "is_new": True, "submission_token": token},
        )

    def post(self, request):
        form = LocationForm(request.POST)
        if not form.is_valid():
            # Nada foi criado — reemite o token para a correção seguinte.
            token = _location_create_guard.issue(request)
            return render(
                request,
                "operations/location_form.html",
                {"form": form, "is_new": True, "submission_token": token},
            )

        if not _location_create_guard.consume_if_valid(request):
            # Reenvio (Enter repetido, duplo clique, "voltar" + reenviar) —
            # 2º reteste manual: era possível criar várias unidades
            # idênticas. Nada é criado nesta tentativa. Deliberadamente SEM
            # UNIQUE(name): dois clientes diferentes podem legitimamente
            # ter unidades homônimas.
            messages.info(
                request,
                "Este formulário já havia sido enviado. Se a unidade não aparece na lista, tente novamente.",
            )
            return redirect("operations:location_list")

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
            # Token já consumido — emite um novo para a próxima tentativa.
            token = _location_create_guard.issue(request)
            return render(
                request,
                "operations/location_form.html",
                {"form": form, "is_new": True, "submission_token": token},
            )

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
        token = _movement_guard(patrimonio).issue(request)
        return render(
            request,
            "operations/movement_form.html",
            {"form": form, "equipment": equipment, "submission_token": token},
        )

    def post(self, request, patrimonio):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        guard = _movement_guard(patrimonio)
        form = MovementForm(request.POST, current_location=equipment.current_location)
        if not form.is_valid():
            token = guard.issue(request)
            return render(
                request,
                "operations/movement_form.html",
                {"form": form, "equipment": equipment, "submission_token": token},
            )

        if not guard.consume_if_valid(request):
            # Reenvio — as regras de transição do service já rejeitariam a
            # maioria dos duplicados (status incompatível na 2ª tentativa),
            # mas a proteção vale para TODAS as combinações, sem depender
            # de cada regra específica: um mesmo submit válido produz no
            # máximo um evento de movimentação.
            messages.info(
                request,
                "Esta movimentação já havia sido enviada. Confira a timeline do equipamento antes de tentar de novo.",
            )
            return redirect("equipment:detail", patrimonio=equipment.patrimonio)

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
            # Token já consumido — emite um novo para a próxima tentativa.
            token = guard.issue(request)
            return render(
                request,
                "operations/movement_form.html",
                {"form": form, "equipment": equipment, "submission_token": token},
            )

        messages.success(
            request, f"Movimentação registrada: {movement.get_movement_type_display()} — {equipment.patrimonio}."
        )
        return redirect("equipment:detail", patrimonio=equipment.patrimonio)


class DuplicateLocationsReportView(RoleRequiredMixin, View):
    """
    Ferramenta TEMPORÁRIA de diagnóstico (não faz parte da especificação de
    Fase 2) — criada porque o Render Free não dá acesso a Shell, e sem
    Shell não há como rodar `python manage.py report_duplicate_locations`
    em produção. Existe só para permitir localizar, sem apagar nada, as
    Locations duplicadas deixadas pelos testes manuais de double-submit.

    Esta view em si só aceita GET e reaproveita `find_duplicate_location_groups()`
    — a MESMA função usada pelo management command, nunca uma cópia
    divergente da regra. A única ação de escrita da ferramenta
    (`DuplicateLocationsCleanupView`, abaixo) vive numa view separada,
    sempre atrás de uma tela de confirmação própria — esta tela nunca
    apaga/edita/consolida nada sozinha, só mostra um link para lá quando
    há algo elegível para limpeza.

    Acesso restrito a Administrador (`CAN_VIEW_DIAGNOSTICS`, não
    `CAN_MANAGE_LOCATIONS`): é uma ferramenta de diagnóstico interno, não
    uma tela operacional do dia a dia da equipe administrativa.

    Remover esta view (+ a entrada em urls.py + o template) depois que os
    dados de teste forem limpos — não é infraestrutura permanente.
    """

    allowed_roles = CAN_VIEW_DIAGNOSTICS

    def get(self, request):
        groups = find_duplicate_location_groups()
        cleanup_plan = plan_duplicate_location_cleanup()
        return render(
            request,
            "operations/duplicate_locations_report.html",
            {"groups": groups, "cleanup_plan": cleanup_plan},
        )


class DuplicateLocationsCleanupView(RoleRequiredMixin, View):
    """
    Ação de escrita TEMPORÁRIA — "Limpar duplicatas sem referências", pedida
    explicitamente porque o Render Free não dá Shell (sem Shell não há
    como rodar uma limpeza manual em produção). Continuação direta de
    `DuplicateLocationsReportView`: só apaga (`is_active=False`, mesma
    convenção de SoftDeleteModel do resto do projeto — nunca DELETE
    físico) Locations dos grupos "TESTE"/"TESTE3"/"teste2" que NÃO têm
    nenhum Movement referenciando, revalidado individualmente e dentro de
    uma única transação (`execute_duplicate_location_cleanup`).

    Fluxo em duas etapas, obrigatório:
      1. GET — mostra a tela de confirmação com os IDs EXATOS que seriam
         removidos agora (`plan_duplicate_location_cleanup()`), sem apagar
         nada, e emite o token de confirmação.
      2. POST — só executa se o token bater (mesmo `SubmissionGuard` usado
         em toda escrita deste app); um POST direto, sem ter passado pela
         etapa 1, não tem token válido e é bloqueado sem apagar nada.

    Depois da execução, mostra o relatório: quantos foram removidos,
    quais foram preservados (tinham referência desde o início — nunca
    foram candidatos) e quais foram pulados por terem ganhado uma
    referência entre a confirmação e a execução (proteção contra corrida).

    Acesso: `CAN_VIEW_DIAGNOSTICS` — Administrador apenas, igual à tela de
    diagnóstico. Remover esta view (+ rota + botão no template) junto com
    o resto da ferramenta temporária, depois da limpeza.
    """

    allowed_roles = CAN_VIEW_DIAGNOSTICS

    def get(self, request):
        plan = plan_duplicate_location_cleanup()
        token = _duplicate_cleanup_guard.issue(request)
        return render(
            request,
            "operations/duplicate_locations_cleanup_confirm.html",
            {"plan": plan, "submission_token": token},
        )

    def post(self, request):
        if not _duplicate_cleanup_guard.consume_if_valid(request):
            # Sem token válido (POST direto, reenvio, ou token expirado/de
            # outra sessão) — bloqueado, nada é apagado. Reemite um token
            # novo para o Administrador confirmar de novo, se quiser.
            messages.error(
                request,
                "Confirmação inválida ou expirada — nada foi apagado. Revise a lista e confirme novamente.",
            )
            return redirect("operations:duplicate_locations_cleanup")

        report = execute_duplicate_location_cleanup(performed_by=request.user)
        return render(request, "operations/duplicate_locations_cleanup_result.html", {"report": report})
