"""
Views mínimas da Fase 1: listagem (autenticada) e ficha do equipamento
com as duas camadas de visualização (seção 12/13 da especificação — a
ficha pública nunca inclui cliente, valor de aquisição ou manutenção).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import ListView

from apps.equipment.models import Equipment


class EquipmentListView(LoginRequiredMixin, ListView):
    """Todos os 4 perfis podem consultar (matriz da seção 11)."""

    model = Equipment
    template_name = "equipment/list.html"
    context_object_name = "equipment_list"
    paginate_by = 50

    def get_queryset(self):
        qs = Equipment.objects.select_related("model", "category").filter(is_active=True)

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(patrimonio__icontains=q) | qs.filter(serial_number__icontains=q)

        for field in ("status", "condition", "category"):
            value = self.request.GET.get(field)
            if value:
                qs = qs.filter(**{field: value})

        return qs.order_by("-created_at")


class EquipmentDetailView(View):
    """
    Rota pública do QR Code (especificação, seção 12/14).

    Não autenticado: só empresa + categoria + modelo + patrimônio.
    Autenticado: ficha completa (a Fase 1 ainda não tem ações de
    manutenção/movimentação — essas chegam na Fase 2, seção 21).
    """

    def get(self, request, patrimonio: str):
        equipment = get_object_or_404(
            Equipment.objects.select_related("model", "category", "current_client", "current_location"),
            patrimonio=patrimonio,
        )

        if not request.user.is_authenticated:
            return render(
                request,
                "equipment/detail_public.html",
                {"equipment": equipment},
            )

        return render(request, "equipment/detail_private.html", {"equipment": equipment})
