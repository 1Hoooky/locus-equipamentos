"""
Geração de QR Code e etiqueta — especificação, seção 14 ("Estratégia
para QR Codes e etiquetas") e seção 12 (telas).

Regra central: o QR codifica SÓ a URL permanente do patrimônio
(`SITE_BASE_URL + /equipamentos/{patrimonio}/`), nunca dados do
equipamento. Quem quiser ver status/cliente/condição precisa acessar a
URL e passar pela checagem de autenticação — o QR em si não carrega
nada que precise ser mantido em sincronia.
"""

import base64
import io

import qrcode
from django.template.loader import render_to_string
from django.urls import reverse
from weasyprint import HTML

from apps.equipment.models import Equipment


def equipment_url(equipment: Equipment) -> str:
    from django.conf import settings

    path = reverse("equipment:detail", kwargs={"patrimonio": equipment.patrimonio})
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def generate_qr_png(equipment: Equipment) -> bytes:
    """PNG do QR apontando para a URL permanente do equipamento."""
    img = qrcode.make(equipment_url(equipment))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _qr_data_uri(equipment: Equipment) -> str:
    png_bytes = generate_qr_png(equipment)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def generate_label_pdf(equipment: Equipment) -> bytes:
    """
    Etiqueta de um único equipamento (seção 14): nome/logo Locus, modelo,
    patrimônio em texto grande e legível sem QR, e o QR Code.
    """
    return generate_labels_pdf([equipment])


def generate_labels_pdf(equipment_list: list[Equipment]) -> bytes:
    """Etiquetas em lote — uma por equipamento, várias por página."""
    labels = [
        {
            "patrimonio": eq.patrimonio,
            "model_name": eq.model.name,
            "category_name": eq.category.name,
            "qr_data_uri": _qr_data_uri(eq),
        }
        for eq in equipment_list
    ]
    html_string = render_to_string("qrcodes/label.html", {"labels": labels})
    return HTML(string=html_string).write_pdf()
