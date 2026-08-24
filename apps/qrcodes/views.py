"""
Views de download de QR/etiqueta — telas da seção 12 ("Geração/download
de QR e etiqueta"), restritas a Administrador/Administrativo (matriz da
seção 11).
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View

from apps.accounts.permissions import CAN_MANAGE_EQUIPMENT, RoleRequiredMixin
from apps.equipment.models import Equipment
from apps.qrcodes.services import (
    generate_label_pdf,
    generate_labels_pdf,
    generate_labels_zip,
    generate_qr_png,
    generate_qr_zip,
)


class QRCodeDownloadView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, patrimonio: str):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        png_bytes = generate_qr_png(equipment)
        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = f'inline; filename="{equipment.patrimonio}-qr.png"'
        return response


class LabelDownloadView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, patrimonio: str):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        pdf_bytes = generate_label_pdf(equipment)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{equipment.patrimonio}-etiqueta.pdf"'
        return response


class LabelBatchDownloadView(RoleRequiredMixin, View):
    """
    Impressão em lote — usada pela action do admin
    (`apps/equipment/admin.py`, "Baixar etiquetas em PDF") e reutilizável
    por qualquer outra tela que precise gerar várias etiquetas de uma vez.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        patrimonios = request.GET.getlist("patrimonio")
        equipment_list = list(Equipment.objects.filter(patrimonio__in=patrimonios).select_related("model", "category"))
        pdf_bytes = generate_labels_pdf(equipment_list)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="etiquetas-locus.pdf"'
        return response


def _active_equipment_for_export():
    """
    Base comum das duas exportações em lote abaixo: todos os equipamentos
    ativos (nunca os inativos/"excluídos" via soft delete — seção 3 do
    pedido), na mesma ordenação (categoria, código do modelo, patrimônio)
    para o resultado ser determinístico e fácil de conferir.
    """
    return Equipment.objects.filter(is_active=True).select_related("model", "category").order_by(
        "category__name", "model__code", "model_sequence"
    )


class QRCodeZipExportView(RoleRequiredMixin, View):
    """
    Exportação em lote dos QR Codes de todos os equipamentos ativos —
    .zip organizado em Categoria/Código-do-modelo/Patrimônio.png (seção 3
    do pedido). Botão "Exportar QR Codes" na listagem de equipamentos.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        zip_bytes = generate_qr_zip(_active_equipment_for_export())
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="qrcodes-locus.zip"'
        return response


class LabelZipExportView(RoleRequiredMixin, View):
    """
    Exportação em lote das etiquetas (uma PDF por equipamento, página
    única no tamanho físico exato) de todos os equipamentos ativos —
    mesma organização Categoria/Código-do-modelo/Patrimônio.pdf da
    exportação de QR Codes acima (seção 4 do pedido). Botão "Exportar
    Etiquetas" na listagem de equipamentos.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        zip_bytes = generate_labels_zip(_active_equipment_for_export())
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="etiquetas-locus.zip"'
        return response
