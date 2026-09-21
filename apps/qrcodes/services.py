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

# --------------------------------------------------------------------------
# PADRÃO FÍSICO DO ADESIVO — fonte ÚNICA de verdade para o tamanho do
# CANVAS impresso (rodada de padronização física, pedido explícito: o
# adesivo real disponível para uso da Locus é 60×40mm). Tanto a etiqueta
# "antiga"/completa quanto a "nova"/simplificada abaixo imprimem nesse
# MESMO canvas — só a composição (o que é desenhado dentro dele) muda
# entre as duas. É esta constante única que evita o problema que motivou
# a mudança: um renderer futuro "esquecido" num tamanho antigo (ex.:
# Admin ainda em 100×50) enquanto os demais já usam o padrão novo — todo
# fluxo físico deste app (individual, lote, admin, cadastro em lote) lê
# o tamanho daqui, nunca de um valor duplicado em paralelo.
#
# IMPORTANTE: isto é o tamanho do ADESIVO/CANVAS físico, não do QR Code.
# O QR em si (`generate_qr_png` acima) é e continua sendo SEMPRE
# quadrado, gerado sem nenhuma noção de "60×40" — cada renderer abaixo
# decide, por conta própria, que fração quadrada desse canvas retangular
# o QR ocupa (ver `SIMPLE_LABEL_QR_SIZE_MM`/`QR_GRID_QR_SIZE_MM` abaixo).
STICKER_WIDTH_MM = 60
STICKER_HEIGHT_MM = 40

# Etiqueta "antiga"/completa (seção 1 da especificação original) — nomes
# mantidos por compatibilidade com o resto do código/testes que já os
# importava; só o VALOR passou a vir do padrão único de adesivo acima
# (antes: 100×50, fixo aqui mesmo). `generate_labels_pdf` abaixo e
# `templates/qrcodes/label.html` continuam lendo o tamanho só daqui,
# nunca com um valor fixo escrito em outro lugar.
LABEL_WIDTH_MM = STICKER_WIDTH_MM
LABEL_HEIGHT_MM = STICKER_HEIGHT_MM

# Tema visual da etiqueta (pedido de 04/09/2026: modal LIGHT/DARK antes
# do download em lote — ver apps/equipment/admin.py e
# apps/qrcodes/views.py::LabelBatchDownloadView). Só estes dois valores
# são aceitos, em qualquer camada que receba um tema vindo de fora
# (query string/POST) — nunca um valor livre. "light" é o padrão em
# TODAS as funções abaixo, então nenhum chamador pré-existente (etiqueta
# individual, exportação em .zip) muda de comportamento por não informar
# tema nenhum.
LABEL_THEME_LIGHT = "light"
LABEL_THEME_DARK = "dark"
VALID_LABEL_THEMES = {LABEL_THEME_LIGHT, LABEL_THEME_DARK}


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
    }


def generate_label_pdf(equipment: Equipment, theme: str = LABEL_THEME_LIGHT) -> bytes:
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

    `theme`: "light" (padrão, layout já existente, byte-a-byte igual ao
    de antes desta opção existir) ou "dark" (mesma estrutura, ver
    `templates/qrcodes/label.html`). Quem valida um tema vindo de fora
    (query string/POST) é o chamador (`LabelBatchDownloadView`) — esta
    função só aceita o valor já validado.
    """
    return generate_labels_pdf([equipment], theme=theme)


def generate_labels_pdf(equipment_list: list[Equipment], theme: str = LABEL_THEME_LIGHT) -> bytes:
    """
    Etiquetas em lote — uma página por equipamento, cada página no
    tamanho físico exato da etiqueta (não um grid solto numa folha A4):
    é o formato que serviços de gráfica/impressão de etiqueta esperam, e
    é reaproveitado tanto por `generate_label_pdf` (uma etiqueta) quanto
    pela ação "Baixar etiquetas em PDF" do admin e por
    `generate_labels_zip` (uma etiqueta por arquivo, dentro do .zip).

    `theme` é único para o PDF inteiro (todas as páginas geradas nesta
    chamada usam o mesmo tema) — o pedido de 04/09/2026 é escolher
    LIGHT/DARK uma vez, antes do download de um lote inteiro, nunca por
    equipamento individual dentro do mesmo lote.
    """
    labels = [_label_context(eq) for eq in equipment_list]
    html_string = render_to_string(
        "qrcodes/label.html",
        {
            "labels": labels,
            "label_width_mm": LABEL_WIDTH_MM,
            "label_height_mm": LABEL_HEIGHT_MM,
            "theme": theme,
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

    Nenhuma view usa mais esta função diretamente desde 08/09/2026 (o
    botão "Exportar QR Codes" passou a baixar as etiquetas 6x6 — ver
    `generate_square_labels_zip` abaixo) — mantida aqui, com sua
    cobertura de teste, porque é código funcional que pode voltar a ser
    reaproveitado (ex.: uma exportação de QR "cru" sem etiqueta, se
    algum fluxo futuro precisar disso de novo).
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

    Continua gerando a etiqueta ANTIGA/completa (`generate_label_pdf`/
    `templates/qrcodes/label.html`) de propósito: é a função por trás do
    botão "Exportar Etiquetas", que o pedido de 08/09/2026 (correção do
    requisito de etiquetas) explicitamente decidiu manter como está,
    sem tocar. O padrão novo 6x6 (`generate_square_labels_zip`) é uma
    função à parte, nunca uma alteração desta aqui — do contrário
    "Exportar Etiquetas" mudaria de formato/tema sem ter sido pedido.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for equipment in equipment_list:
            zip_file.writestr(_equipment_zip_path(equipment, "pdf"), generate_label_pdf(equipment))
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Etiqueta "nova"/simplificada — nome de função/variável "square" herdado
# de quando este formato era literalmente quadrado (60x60mm, correção de
# requisito de 08/09/2026); mantido por compatibilidade com o resto do
# código/testes mesmo agora que o canvas não é mais quadrado — é o MESMO
# padrão único de adesivo (`STICKER_WIDTH_MM`/`STICKER_HEIGHT_MM`) da
# etiqueta antiga acima, só a composição interna que é diferente: SÓ QR
# Code, código do modelo (`model.code`, ex. "NI23BT" — NUNCA o nome
# comercial/descritivo, ex. "Big Tank") e identificador legado, nesta
# ordem, de cima para baixo, sem título/rótulo antes de cada linha. Sem
# logo, sem patrimônio novo, sem código de barras, sem URL escrita — tudo
# isso é próprio da etiqueta ANTIGA (`generate_label_pdf` acima) e
# permanece intocado lá.
#
# Deliberadamente um conjunto de funções/template SEPARADO (nunca uma
# alteração de `generate_label_pdf`/`generate_labels_pdf`/`label.html`):
# essas funções antigas continuam alimentando "Exportar Etiquetas"
# (`generate_labels_zip` acima) e a ação de lote do Django admin
# (`LabelBatchDownloadView`/`apps/equipment/admin.py`), que o pedido de
# 08/09/2026 decidiu manter exatamente como estão. Reaproveitar a mesma
# função para os dois formatos faria "Exportar Etiquetas" mudar de
# aparência sem ter sido pedido.
#
# O QR em si é gerado por `generate_qr_png`/`_qr_data_uri` acima, sem
# nenhuma alteração — mesmo destino permanente do patrimônio, em
# qualquer tema, exatamente a mesma regra de sempre (seção "Regra
# central" no topo deste arquivo).
# --------------------------------------------------------------------------

SIMPLE_LABEL_WIDTH_MM = STICKER_WIDTH_MM
SIMPLE_LABEL_HEIGHT_MM = STICKER_HEIGHT_MM

# Tamanho do QR dentro da etiqueta simplificada — FIXO nos dois casos
# (com ou sem identificador legado): o pedido de padronização física
# permite "redistribuir discretamente o espaço vertical para favorecer o
# QR" quando a linha do legado não existe, mas manter um único valor de
# QR nos dois casos evita dois "pesos" visuais diferentes para o mesmo
# formato de etiqueta — a diferença fica só no espaço livre ao redor
# (centralizado verticalmente pelo template), nunca no tamanho do QR em
# si. 27mm foi o valor auditado/medido fisicamente no PDF real (via
# WeasyPrint + pdfplumber, não "no olho"): o maior que cabe, no cenário
# mais apertado (COM identificador legado — 3 linhas de conteúdo no
# canvas de 40mm de altura), sem cortar nenhum texto — uma primeira
# tentativa em 30mm estourava a altura disponível e cortava a linha do
# legado inteira (`overflow: hidden` no `.label`); ver
# docs/apps/qrcodes.md.
SIMPLE_LABEL_QR_SIZE_MM = 27


def _square_label_context(equipment: Equipment) -> dict:
    """
    Só os 3 dados exigidos pelo padrão 6x6: QR, código do modelo e
    identificador legado.

    Ajuste visual de 08/09/2026: a etiqueta mostra `model.code` (ex.:
    "NI23BT"), nunca `model.name` (o nome comercial/descritivo, ex.:
    "Big Tank") — pedido explícito para uma etiqueta de identificação de
    patrimônio limpa e técnica, sem depender do comprimento variável de
    um nome de exibição. `model.code` já é a fonte da verdade existente
    no cadastro do modelo (`apps/catalog/models.py`, único, validado por
    regex, usado também na composição do patrimônio) — nenhuma tabela
    nova foi criada para essa tradução.

    `legacy_code` pode estar em branco — quem decide omitir a linha
    quando vazio é o template, não esta função.
    """
    return {
        "model_code": equipment.model.code,
        "legacy_code": equipment.legacy_code,
        "qr_data_uri": _qr_data_uri(equipment),
    }


def generate_square_label_pdf(equipment: Equipment, theme: str = LABEL_THEME_LIGHT) -> bytes:
    """Etiqueta 6x6 de um único equipamento — usada pelo download individual (`LabelDownloadView`)."""
    return generate_square_labels_pdf([equipment], theme=theme)


def generate_square_labels_pdf(equipment_list: list[Equipment], theme: str = LABEL_THEME_LIGHT) -> bytes:
    """
    Etiquetas 6x6 em lote — uma página por equipamento, mesmo raciocínio
    de `generate_labels_pdf` (página única no tamanho físico exato, não
    um grid solto numa folha A4). Usada pelo download em lote por
    modelo (`ModelLabelBatchDownloadView`, um PDF combinado — "baixar
    todas as etiquetas daquele modelo", pedido de 08/09/2026).

    `theme` é único para o PDF inteiro, mesmo raciocínio de
    `generate_labels_pdf`: escolhido uma vez no modal, nunca por
    equipamento individual dentro do mesmo lote.
    """
    labels = [_square_label_context(eq) for eq in equipment_list]
    html_string = render_to_string(
        "qrcodes/label_square.html",
        {
            "labels": labels,
            "label_width_mm": SIMPLE_LABEL_WIDTH_MM,
            "label_height_mm": SIMPLE_LABEL_HEIGHT_MM,
            "qr_size_mm": SIMPLE_LABEL_QR_SIZE_MM,
            "theme": theme,
        },
    )
    return HTML(string=html_string).write_pdf()


def generate_square_labels_zip(equipment_list: list[Equipment], theme: str = LABEL_THEME_LIGHT) -> bytes:
    """
    .zip com uma etiqueta 6x6 em PDF por equipamento, mesma organização
    Categoria/Código-do-modelo/Patrimônio.pdf de sempre — usada pelo
    botão "Exportar QR Codes" (repaginado em 08/09/2026 para baixar as
    etiquetas 6x6 no tema escolhido, em vez de PNGs de QR crus; ver
    `QRCodeZipExportView`).
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for equipment in equipment_list:
            zip_file.writestr(_equipment_zip_path(equipment, "pdf"), generate_square_label_pdf(equipment, theme=theme))
    return buffer.getvalue()


# --------------------------------------------------------------------------
# Exportação em lote de QR "puro" — UM ÚNICO PDF em grade A4, pronto para
# impressão (pedido de 16/09/2026). Distinta de `generate_qr_zip` acima
# (que gera um .zip com um PNG solto por equipamento, sem paginação
# nenhuma) — aqui o objetivo é um documento único que alguém imprime de
# uma vez, com vários QRs por folha.
#
# Regra central (a mesma do topo deste arquivo): cada QR vem de
# `generate_qr_png`/`equipment_url` — a MESMA função/URL usada por
# QUALQUER outro QR do sistema (individual, etiqueta 6x6, etiqueta
# antiga, `generate_qr_zip`). Esta seção só adiciona uma COMPOSIÇÃO em
# grade nova; nenhuma lógica de geração/URL de QR é duplicada.
# --------------------------------------------------------------------------

# Medidas da grade, centralizadas aqui como as demais constantes deste
# módulo (mesmo raciocínio de LABEL_WIDTH_MM/LABEL_HEIGHT_MM acima) — o
# template (`templates/qrcodes/qr_grid.html`) só lê estes números, nunca
# um valor fixo escrito lá.
#
# RODADA DE PADRONIZAÇÃO FÍSICA (adesivo real 60×40mm): cada CÉLULA da
# grade passou a ser, literalmente, 1 adesivo (`STICKER_WIDTH_MM` ×
# `STICKER_HEIGHT_MM` — o mesmo canvas das etiquetas antiga/simplificada
# acima), não mais um quadrado do tamanho exato do QR. Isso muda a
# composição: o QR (sempre quadrado) fica CENTRALIZADO dentro da célula
# retangular, com uma margem visível ao redor — antes (célula quadrada de
# 50×50mm) o QR preenchia a célula inteira, sem sobra nenhuma.
#
# CORREÇÃO de 16/09/2026 (registro histórico, ainda válida): a primeira
# versão usava célula de ~48mm e margem uniforme de 10mm — a validação
# visual/física mostrou a grade deslocada para a esquerda (a margem
# direita sobrando não era compensada). A técnica de cálculo desta seção
# (margens derivadas matematicamente, nunca auto-centralização de
# flex/margin:auto) é a mesma daquela correção, só reaplicada às novas
# medidas:
#
#      largura da grade  = 3×60 + 2×2 (gutter) = 184mm
#      altura da grade    = 6×40 + 5×2 (gutter) = 250mm
#      margem horizontal = (210 - 184) / 2 = 13mm de cada lado
#      margem vertical    = (297 - 250) / 2 = 23.5mm de cada lado
#    Essas margens são o `padding` do `.qr-page` no template (`@page`
#    fica com `margin: 0`, controle 100% explícito em mm) — nunca
#    resultado de auto-centralização/flex `justify-content: center`,
#    que dependeria do render engine para não introduzir arredondamento.
QR_GRID_PAGE_WIDTH_MM = 210  # A4 retrato
QR_GRID_PAGE_HEIGHT_MM = 297  # A4 retrato
QR_GRID_CELL_WIDTH_MM = STICKER_WIDTH_MM  # cada célula = 1 adesivo real (60mm)
QR_GRID_CELL_HEIGHT_MM = STICKER_HEIGHT_MM  # (40mm)
# Tamanho do QR dentro de cada célula — auditado/medido fisicamente no
# PDF real (mesma técnica de `SIMPLE_LABEL_QR_SIZE_MM` acima): o maior
# quadrado que cabe com folga simétrica nos dois eixos da célula 60×40
# (2mm de margem vertical, ~12mm de margem horizontal) sem encostar nas
# bordas — ver docs/apps/qrcodes.md.
QR_GRID_QR_SIZE_MM = 36
QR_GRID_GUTTER_MM = 2
QR_GRID_COLUMNS = 3
QR_GRID_ROWS = 6
QR_GRID_PAGE_SIZE = QR_GRID_COLUMNS * QR_GRID_ROWS  # 18

QR_GRID_WIDTH_MM = QR_GRID_COLUMNS * QR_GRID_CELL_WIDTH_MM + (QR_GRID_COLUMNS - 1) * QR_GRID_GUTTER_MM  # 184
QR_GRID_HEIGHT_MM = QR_GRID_ROWS * QR_GRID_CELL_HEIGHT_MM + (QR_GRID_ROWS - 1) * QR_GRID_GUTTER_MM  # 250
QR_GRID_MARGIN_HORIZONTAL_MM = (QR_GRID_PAGE_WIDTH_MM - QR_GRID_WIDTH_MM) / 2  # 13.0
QR_GRID_MARGIN_VERTICAL_MM = (QR_GRID_PAGE_HEIGHT_MM - QR_GRID_HEIGHT_MM) / 2  # 23.5


def _qr_grid_cell_context(equipment: Equipment) -> dict:
    """
    Só o QR em si — nenhum outro dado do equipamento (pedido explícito:
    "QR puro", sem logo/nome/descrição/patrimônio/barcode/texto
    comercial). `caption` existe só como ponto de extensão: hoje é
    sempre `None` (nenhuma opção de UI liga isso), mas o template já
    sabe renderizar uma legenda opcional por célula se um dia isso for
    pedido — sem precisar reescrever o gerador/grade.
    """
    return {"qr_data_uri": _qr_data_uri(equipment), "caption": None}


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def generate_qr_grid_pdf(equipment_list: list[Equipment], theme: str = LABEL_THEME_LIGHT) -> bytes:
    """
    UM ÚNICO PDF A4, multi-página, com os QR Codes PUROS dos
    equipamentos em `equipment_list`, em grade (`QR_GRID_COLUMNS` ×
    `QR_GRID_ROWS` por página) — pronto para impressão.

    A paginação é decidida aqui em Python (`_chunked`), não deixada para
    o WeasyPrint resolver sozinho: quebra de página automática dentro de
    uma grade/flexbox não é confiável entre motores de renderização, então
    cada "folha" já chega ao template só com os itens que cabem numa
    página A4 — o template (`qrcodes/qr_grid.html`) só desenha o que
    recebe, sem decidir quebra nenhuma.

    Ordem de `equipment_list` é responsabilidade do CHAMADOR (mesmo
    padrão de `generate_labels_pdf`/`generate_square_labels_pdf` acima) —
    esta função nunca reordena.

    `theme` (pedido de 16/09/2026, mesma rodada da correção de
    dimensionamento) — "light" (padrão) ou "dark", reaproveitando o MESMO
    modal/`?tema=` já usado por `generate_labels_pdf`/
    `generate_square_labels_pdf` acima (validado pelo chamador via
    `views.py::_validated_theme`, nunca validado aqui — mesmo padrão do
    resto deste arquivo). Só muda o fundo da página; o QR em si nunca é
    invertido em nenhum tema (mesma regra incondicional de
    `_square_label_context`/`label_square.html` — "priorize
    confiabilidade de leitura"), porque o PNG de `generate_qr_png` já é
    opaco com fundo branco.
    """
    pages = _chunked([_qr_grid_cell_context(eq) for eq in equipment_list], QR_GRID_PAGE_SIZE) or [[]]
    html_string = render_to_string(
        "qrcodes/qr_grid.html",
        {
            "pages": pages,
            "page_width_mm": QR_GRID_PAGE_WIDTH_MM,
            "page_height_mm": QR_GRID_PAGE_HEIGHT_MM,
            "cell_width_mm": QR_GRID_CELL_WIDTH_MM,
            "cell_height_mm": QR_GRID_CELL_HEIGHT_MM,
            "qr_size_mm": QR_GRID_QR_SIZE_MM,
            "gutter_mm": QR_GRID_GUTTER_MM,
            "margin_horizontal_mm": QR_GRID_MARGIN_HORIZONTAL_MM,
            "margin_vertical_mm": QR_GRID_MARGIN_VERTICAL_MM,
            "theme": theme,
        },
    )
    return HTML(string=html_string).write_pdf()
