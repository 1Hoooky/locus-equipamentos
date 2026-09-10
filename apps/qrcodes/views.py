"""
Views de download de QR/etiqueta — telas da seção 12 ("Geração/download
de QR e etiqueta"), restritas a Administrador/Administrativo (matriz da
seção 11).
"""

import uuid

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.views import View

from apps.accounts.permissions import CAN_MANAGE_EQUIPMENT, RoleRequiredMixin
from apps.catalog.models import EquipmentModel
from apps.equipment.models import Equipment
from apps.qrcodes.services import (
    LABEL_THEME_LIGHT,
    VALID_LABEL_THEMES,
    generate_label_pdf,
    generate_labels_pdf,
    generate_labels_zip,
    generate_qr_png,
    generate_qr_zip,
    generate_square_label_pdf,
    generate_square_labels_pdf,
    generate_square_labels_zip,
)


def _validated_theme(request):
    """
    Lê `?tema=` da querystring e valida — só "light"/"dark" são aceitos,
    em qualquer rota que receba tema vindo de fora (nunca confiamos só
    no JS do modal). Ausente cai no padrão "light" (comportamento de
    sempre de qualquer rota que ainda não tinha tema nenhum). Retorna
    `(theme, error_response)`: quando `error_response` não é `None`, o
    chamador deve devolvê-lo imediatamente (tema inválido, HTTP 400) e
    nunca prosseguir para gerar nada.

    Compartilhado entre as rotas de etiqueta 6x6 (pedido de 08/09/2026)
    — mesmo raciocínio de validação já usado por `LabelBatchDownloadView`
    abaixo, só extraído para não repetir o mesmo bloco em cada view nova.
    """
    theme = request.GET.get("tema", LABEL_THEME_LIGHT)
    if theme not in VALID_LABEL_THEMES:
        return theme, HttpResponse(
            f"Tema de etiqueta inválido: {theme!r}. Use 'light' ou 'dark'.",
            content_type="text/plain",
            status=400,
        )
    return theme, None


class QRCodeDownloadView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, patrimonio: str):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        png_bytes = generate_qr_png(equipment)
        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = f'inline; filename="{equipment.patrimonio}-qr.png"'
        return response


class LabelDownloadView(RoleRequiredMixin, View):
    """
    Download individual — passou a gerar a etiqueta no padrão novo 6x6
    (`generate_square_label_pdf`, pedido de 08/09/2026: "downloads
    individuais continuam como estão, mas também devem sair no padrão
    6 por 6"). Interação inalterada: mesmo link direto de sempre, sem
    modal, sempre tema claro (mesmo padrão default de qualquer outra
    rota que não pede tema explicitamente).
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, patrimonio: str):
        equipment = get_object_or_404(Equipment, patrimonio=patrimonio)
        pdf_bytes = generate_square_label_pdf(equipment)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{equipment.patrimonio}-etiqueta.pdf"'
        return response


class LabelBatchDownloadView(RoleRequiredMixin, View):
    """
    Impressão em lote — usada pela action do admin
    (`apps/equipment/admin.py`, "Baixar etiquetas em PDF") e reutilizável
    por qualquer outra tela que precise gerar várias etiquetas de uma vez.

    `?tema=light|dark` (pedido de 04/09/2026 — modal de escolha de tema
    antes do download, interceptando a mesma action do admin sem criar
    nenhuma tela nova): validado aqui, no backend — nunca confiamos que o
    JS do modal vai sempre mandar um valor correto (usuário pode desabilitar
    JS, forjar a URL, etc.). Ausente ou omitido cai no padrão "light", que
    é o comportamento de sempre desta rota; qualquer valor que não seja
    exatamente "light" ou "dark" é rejeitado com 400, nunca silenciosamente
    tratado como um dos dois.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        theme = request.GET.get("tema", LABEL_THEME_LIGHT)
        if theme not in VALID_LABEL_THEMES:
            return HttpResponse(
                f"Tema de etiqueta inválido: {theme!r}. Use 'light' ou 'dark'.",
                content_type="text/plain",
                status=400,
            )
        patrimonios = request.GET.getlist("patrimonio")
        equipment_list = list(Equipment.objects.filter(patrimonio__in=patrimonios).select_related("model", "category"))
        pdf_bytes = generate_labels_pdf(equipment_list, theme=theme)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="etiquetas-locus.pdf"'
        return response


def _active_equipment_for_export(request=None):
    """
    Base comum das duas exportações em lote abaixo: todos os equipamentos
    ativos (nunca os inativos/"excluídos" via soft delete — seção 3 do
    pedido), na mesma ordenação (categoria, código do modelo, patrimônio)
    para o resultado ser determinístico e fácil de conferir.

    `?batch=<uuid>` (melhoria operacional da Fase 1, 25/08/2026, "Exportar
    etiquetas/QR Codes deste lote" na tela de resultado do cadastro em
    lote) restringe o resultado só aos equipamentos daquela operação. Sem
    o parâmetro, o comportamento é exatamente o de antes — todos os
    equipamentos ativos.
    """
    qs = Equipment.objects.filter(is_active=True).select_related("model", "category").order_by(
        "category__name", "model__code", "model_sequence"
    )
    batch_value = request.GET.get("batch") if request is not None else None
    if batch_value:
        try:
            uuid.UUID(batch_value)
        except (ValueError, AttributeError, TypeError):
            pass
        else:
            qs = qs.filter(batch_id=batch_value)
    return qs


class QRCodeZipExportView(RoleRequiredMixin, View):
    """
    Botão "Exportar QR Codes" na listagem de equipamentos e "Exportar QR
    Codes deste lote" na tela de resultado do cadastro em lote (mesma
    rota nos dois lugares).

    Repaginada em 08/09/2026 (correção do requisito de etiquetas): antes
    baixava um .zip de PNGs de QR crus (`generate_qr_zip`); passou a
    baixar um .zip com as etiquetas no padrão novo 6x6
    (`generate_square_labels_zip`), no tema escolhido no modal
    LIGHT/DARK que agora intercepta este botão — "é o botão que já
    existe", reaproveitado em vez de criar uma tela nova. Mesma
    organização de pastas Categoria/Código-do-modelo/Patrimônio de
    sempre; só o conteúdo de cada arquivo (e a extensão, .pdf em vez de
    .png) mudou.

    `generate_qr_zip` voltou a ter um chamador em 10/09/2026 —
    `QRCodeOnlyZipExportView` abaixo, o botão "Exportar QR Codes (puro)",
    pedido justamente porque este botão aqui (apesar do nome) não baixa
    mais QR "cru" nenhum desde a repaginação acima.

    `?tema=light|dark` validado no backend (nunca só confiado do JS do
    modal) — mesmo raciocínio de `LabelBatchDownloadView` abaixo.
    `?batch=<uuid>` continua funcionando exatamente como antes (via
    `_active_equipment_for_export`), sem nenhuma mudança de escopo.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        theme, error_response = _validated_theme(request)
        if error_response is not None:
            return error_response
        zip_bytes = generate_square_labels_zip(_active_equipment_for_export(request), theme=theme)
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="etiquetas-locus.zip"'
        return response


class QRCodeOnlyZipExportView(RoleRequiredMixin, View):
    """
    Botão "Exportar QR Codes (puro)" (pedido de 10/09/2026) — QR Code
    "cru", sem nenhuma composição de etiqueta: sem código do modelo, sem
    identificador legado, sem borda, sem texto, sem logo. Reaproveita
    `generate_qr_zip` (services.py) tal como já existia — mesma origem/
    dado do QR de sempre (`generate_qr_png`/`equipment_url`, a MESMA URL
    permanente do patrimônio codificada em qualquer outro QR do sistema),
    nenhum segundo padrão de QR criado.

    Deliberadamente uma view/rota separada de `QRCodeZipExportView`
    acima (o botão "Exportar QR Codes" já existente, que desde
    08/09/2026 baixa as etiquetas 6x6, não QR puro) — o nome antigo já
    estava em uso para outra coisa, então esta função ganhou um botão e
    uma rota próprios em vez de reaproveitar o texto/rota já ocupados
    (ver ajuste de 10/09/2026 para o raciocínio completo).

    Sem tema (`?tema=`): QR puro não tem "etiqueta" nenhuma para ter
    LIGHT/DARK — não intercepta o modal de tema (sem
    `data-label-theme-trigger` no botão do template).

    Mesma seleção de equipamentos, mesma permissão (`CAN_MANAGE_EQUIPMENT`,
    igual a toda outra view deste arquivo) e mesma organização de pastas
    Categoria/Código-do-modelo/Patrimônio.png dos outros dois zips em
    lote — nenhuma UX nova inventada para esta ação.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        zip_bytes = generate_qr_zip(_active_equipment_for_export(request))
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="qrcodes-locus.zip"'
        return response


class ModelLabelBatchDownloadView(RoleRequiredMixin, View):
    """
    Etiquetas 6x6 em lote de UM modelo — botão novo no cabeçalho do card
    de cada modelo na listagem agrupada (pedido de 08/09/2026), ao lado
    das contagens. Abre o mesmo modal LIGHT/DARK dos outros fluxos e
    baixa um único PDF combinado (uma página por equipamento — mesmo
    raciocínio de `LabelBatchDownloadView`, não um .zip: um único modelo
    não tem "organização de pastas" para preservar, e um PDF só é mais
    prático para imprimir todas de uma vez).

    Só equipamento ATIVO do modelo entra (mesma regra de sempre das
    outras exportações em lote). Modelo inexistente → 404 padrão do
    Django. Modelo existente mas sem nenhum equipamento ativo → 404 com
    mensagem explicativa (nada para gerar).
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request, model_id: int):
        equipment_model = get_object_or_404(EquipmentModel, pk=model_id)
        theme, error_response = _validated_theme(request)
        if error_response is not None:
            return error_response
        equipment_list = list(
            Equipment.objects.filter(model_id=model_id, is_active=True).select_related("model", "category")
        )
        if not equipment_list:
            return HttpResponse(
                "Nenhum equipamento ativo para este modelo.",
                content_type="text/plain",
                status=404,
            )
        pdf_bytes = generate_square_labels_pdf(equipment_list, theme=theme)
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="etiquetas-{equipment_model.code}.pdf"'
        return response


class LabelZipExportView(RoleRequiredMixin, View):
    """
    Exportação em lote das etiquetas (uma PDF por equipamento, página
    única no tamanho físico exato) de todos os equipamentos ativos (ou,
    com `?batch=<uuid>`, só os de um lote de cadastro específico) — mesma
    organização Categoria/Código-do-modelo/Patrimônio.pdf da exportação de
    QR Codes acima (seção 4 do pedido). Botão "Exportar Etiquetas" na
    listagem de equipamentos e "Exportar Etiquetas deste lote" na tela de
    resultado do cadastro em lote.
    """

    allowed_roles = CAN_MANAGE_EQUIPMENT

    def get(self, request):
        zip_bytes = generate_labels_zip(_active_equipment_for_export(request))
        response = HttpResponse(zip_bytes, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="etiquetas-locus.zip"'
        return response
