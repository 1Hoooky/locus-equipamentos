"""
Geração de QR Code, código de barras, etiqueta e exportações em lote —
especificação, seção 14 ("Estratégia para QR Codes e etiquetas") e seção
12 (telas), estendida para o sistema de etiquetas patrimoniais.

Regra central, que nada neste arquivo pode violar: o QR codifica SÓ a URL
permanente do patrimônio (`SITE_BASE_URL + /equipamentos/{patrimonio}/`),
nunca dados do equipamento. Quem quiser ver status/cliente/condição
precisa acessar a URL e passar pela checagem de autenticação — o QR em si
não carrega nada que precise ser mantido em sincronia. O código de barras
adicionado nesta rodada segue o mesmo princípio: representa só o
`patrimonio` (o mesmo texto já usado na etiqueta e no QR), nunca um
identificador novo ou uma segunda lógica de geração.

Nada aqui grava arquivo em disco — QR, código de barras e etiqueta são
gerados inteiramente em memória (bytes/BytesIO) e as exportações em lote
(`generate_qr_zip`/`generate_labels_zip`) montam o .zip também em memória,
de propósito: o disco do Free tier da Render é efêmero, e mesmo no VPS não
há motivo para acumular milhares de arquivos gerados sob demanda.
"""

import base64
import io
import re
import zipfile

import barcode
import qrcode
from barcode.writer import ImageWriter
from django.conf import settings
from django.template.loader import render_to_string
from django.urls import reverse
from weasyprint import HTML

from apps.equipment.models import Equipment

# Tamanho físico da etiqueta (seção 1 do pedido): centralizado aqui, não
# espalhado pelo template/CSS, para que uma alteração futura de tamanho
# (ex.: passar para 80×40mm) seja só trocar estes dois números — o
# gerador (`generate_labels_pdf` abaixo) e o template
# (`templates/qrcodes/label.html`) leem o tamanho daqui, nunca com um
# valor fixo escrito em outro lugar.
LABEL_WIDTH_MM = 100
LABEL_HEIGHT_MM = 50

# Texto fixo do rodapé da etiqueta — deliberadamente uma constante, não
# derivado de `settings.SITE_BASE_URL`: em ambiente de desenvolvimento/
# validação isso mostraria "localhost:8000" (ou o domínio de staging) na
# etiqueta impressa, o que é informação técnica/de debug, não uma marca
# adequada para uma etiqueta física aprovada pelo layout de referência.
LABEL_FOOTER_TEXT = "www.locuslocacoes.com.br"


def equipment_url(equipment: Equipment) -> str:
    path = reverse("equipment:detail", kwargs={"patrimonio": equipment.patrimonio})
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}"


def generate_qr_png(equipment: Equipment) -> bytes:
    """PNG do QR apontando para a URL permanente do equipamento — única lógica de geração de QR do sistema."""
    img = qrcode.make(equipment_url(equipment))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _qr_data_uri(equipment: Equipment) -> str:
    png_bytes = generate_qr_png(equipment)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def generate_barcode_png(equipment: Equipment) -> bytes:
    """
    PNG do código de barras (Code128 — suporta letras, números e hífen,
    exatamente o alfabeto do patrimônio) representando o `patrimonio`.
    Mesma string do QR e do texto grande da etiqueta: nenhum identificador
    novo é criado aqui, só mais uma representação visual do mesmo dado.
    """
    code = barcode.get("code128", equipment.patrimonio, writer=ImageWriter())
    buffer = io.BytesIO()
    # write_text=False: o patrimônio já aparece em destaque, em fonte
    # grande, logo abaixo do código de barras na etiqueta — duplicar o
    # texto (menor e mais apertado) embutido na própria imagem do código
    # só poluiria o layout sem ganhar legibilidade.
    #
    # module_width=0.41mm (padrão da biblioteca é 0.2mm): ajuste só de
    # RENDERIZAÇÃO, não de codificação — deixa as barras proporcionalmente
    # mais largas/baixas (aspect ratio ≈ 6.8, medido pixel a pixel na
    # referência visual aprovada pelo usuário), para caber uma barra larga
    # e legível na faixa branca compacta da etiqueta sem precisar de altura
    # excessiva. O conteúdo codificado (`equipment.patrimonio`) não muda.
    code.write(
        buffer,
        options={"write_text": False, "quiet_zone": 2.0, "module_height": 10.0, "module_width": 0.41},
    )
    return buffer.getvalue()


def _barcode_data_uri(equipment: Equipment) -> str:
    png_bytes = generate_barcode_png(equipment)
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _label_context(equipment: Equipment) -> dict:
    return {
        "patrimonio": equipment.patrimonio,
        "model_name": equipment.model.name,
        "category_name": equipment.category.name,
        "qr_data_uri": _qr_data_uri(equipment),
        "barcode_data_uri": _barcode_data_uri(equipment),
        "footer_text": LABEL_FOOTER_TEXT,
    }


def generate_label_pdf(equipment: Equipment) -> bytes:
    """
    Etiqueta de um único equipamento (seção 1 do pedido): página única no
    tamanho físico exato (`LABEL_WIDTH_MM` × `LABEL_HEIGHT_MM`), com
    identificação da Locus, código de barras e patrimônio em destaque na
    metade esquerda, e QR Code grande com margem de segurança na direita.

    Gerada inteiramente a partir dos dados atuais do equipamento (nunca
    armazenada como imagem estática) — o que também é o motivo pelo qual
    uma etiqueta impressa hoje continua válida mesmo que o equipamento
    seja reclassificado depois: o QR aponta para a URL permanente do
    patrimônio, não para um snapshot; reimprimir só reflete os dados afixo
    atuais (modelo/categoria), sem invalidar o identificador em si.
    """
    return generate_labels_pdf([equipment])


def generate_labels_pdf(equipment_list: list[Equipment]) -> bytes:
    """
    Etiquetas em lote — uma página por equipamento, cada página no
    tamanho físico exato da etiqueta (não um grid solto numa folha A4):
    é o formato que serviços de gráfica/impressão de etiqueta esperam, e
    é reaproveitado tanto por `generate_label_pdf` (uma etiqueta) quanto
    pela ação "Baixar etiquetas em PDF" do admin e por
    `generate_labels_zip` (uma etiqueta por arquivo, dentro do .zip).
    """
    labels = [_label_context(eq) for eq in equipment_list]
    html_string = render_to_string(
        "qrcodes/label.html",
        {
            "labels": labels,
            "label_width_mm": LABEL_WIDTH_MM,
            "label_height_mm": LABEL_HEIGHT_MM,
        },
    )
    return HTML(string=html_string).write_pdf()


# --------------------------------------------------------------------------
# Sanitização de nomes usados como pasta/arquivo dentro dos .zip abaixo.
# --------------------------------------------------------------------------

_UNSAFE_PATH_CHARS = re.compile(r"[^A-Za-z0-9 _.\-()]+")


def _sanitize_path_segment(value: str, *, fallback: str) -> str:
    """
    `category.name` é texto livre (pode ter "/", acentos incomuns ou
    qualquer coisa que alguém digite) e vira nome de pasta dentro do
    .zip — sem sanitizar, um nome de categoria com "/" quebraria a
    estrutura Categoria/Modelo/Patrimônio (viraria uma subpasta extra
    não intencional) ou, em casos como ".." isolado, poderia ser
    interpretado por algum descompactador como navegação de diretório.
    `model.code`/`patrimonio` já são gerados num formato seguro
    (validados por regex em `apps/catalog/models.py` e
    `apps/equipment/services.py`), mas passam pelo mesmo filtro por
    defesa em profundidade — nunca custa nada aqui.
    """
    cleaned = _UNSAFE_PATH_CHARS.sub("_", value.strip())
    cleaned = cleaned.strip("._ ")
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    if not cleaned or cleaned in {".", ".."}:
        return fallback
    return cleaned


def _equipment_zip_path(equipment: Equipment, extension: str) -> str:
    """Categoria/Código-do-modelo/Patrimônio.ext — mesma organização exigida para os dois tipos de exportação em lote."""
    category = _sanitize_path_segment(equipment.category.name, fallback="SEM-CATEGORIA")
    model_code = _sanitize_path_segment(equipment.model.code, fallback="SEM-MODELO")
    # Patrimônio é a chave única do sistema — mesmo sanitizado (deveria
    # ser sempre um no-op, dado o formato LOC-[CODE]-[SEQUENCE]), não há
    # risco de dois equipamentos colidirem no mesmo caminho dentro do zip.
    patrimonio = _sanitize_path_segment(equipment.patrimonio, fallback=f"equipamento-{equipment.pk}")
    return f"{category}/{model_code}/{patrimonio}.{extension}"


def generate_qr_zip(equipment_list: list[Equipment]) -> bytes:
    """
    .zip com um PNG de QR por equipamento, organizado em
    Categoria/Código-do-modelo/Patrimônio.png (seção 3 do pedido). Só
    monta o .zip em memória (`io.BytesIO`) — nada é escrito em disco.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for equipment in equipment_list:
            zip_file.writestr(_equipment_zip_path(equipment, "png"), generate_qr_png(equipment))
    return buffer.getvalue()


def generate_labels_zip(equipment_list: list[Equipment]) -> bytes:
    """
    .zip com uma etiqueta em PDF por equipamento (página única, tamanho
    físico exato), na mesma organização Categoria/Código-do-modelo/
    Patrimônio.pdf usada por `generate_qr_zip` (seção 4 do pedido: "manter
    a mesma organização por categoria/modelo"). Também só em memória.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for equipment in equipment_list:
            zip_file.writestr(_equipment_zip_path(equipment, "pdf"), generate_label_pdf(equipment))
    return buffer.getvalue()
