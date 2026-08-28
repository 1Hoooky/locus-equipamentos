"""
Home operacional — etapa de UX/UI, 28/08/2026 (ver
AUDITORIA_UX_HOME_NAVEGACAO_QR.md, itens [26]-[29]). Visível para
qualquer usuário autenticado (mesmo padrão de `EquipmentListView`: os 4
perfis já têm permissão de consulta sobre tudo que a Home mostra —
`CAN_VIEW_MOVEMENTS`/`CAN_VIEW_MAINTENANCE` já incluem os 4 perfis hoje,
ver apps/accounts/permissions.py — não há necessidade de um
`RoleRequiredMixin` dedicado aqui).
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from apps.dashboard.services import build_home_context


class DashboardHomeView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(build_home_context())
        return context
