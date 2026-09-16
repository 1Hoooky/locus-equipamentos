"""
Testes da exportação em lote de QR Codes PUROS em PDF (pedido de
16/09/2026) — `qrcodes:model_qr_grid` / `ModelQRGridDownloadView` /
`generate_qr_grid_pdf`.

O ponto mais importante aqui, igual ao resto da suíte de qrcodes: não é
só "o PDF foi gerado" — é que cada QR aponta para a MESMA URL permanente
usada por QUALQUER outro QR do sistema (nunca um segundo padrão), que o
escopo é exatamente o mesmo do botão "Etiquetas em lote" já existente
(mesmo modelo, só equipamento ativo), que a operação é 100% leitura (sem
side effect em Equipment/Movement/StatusHistory/ConditionHistory/
Attachment), e que a permissão é reforçada no backend — não só escondida
na UI.
"""

import io

import pdfplumber
from django.contrib.auth import get_user_model
from django.test import TestCase
from PIL import Image
from pypdf import PdfReader
from pyzbar.pyzbar import decode

from apps.accounts.models import Role
from apps.attachments.models import Attachment
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.models import ConditionHistory, Equipment, StatusHistory
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Movement
from apps.qrcodes.services import (
    LABEL_THEME_DARK,
    LABEL_THEME_LIGHT,
    QR_GRID_CELL_SIZE_MM,
    QR_GRID_COLUMNS,
    QR_GRID_GUTTER_MM,
    QR_GRID_HEIGHT_MM,
    QR_GRID_MARGIN_HORIZONTAL_MM,
    QR_GRID_MARGIN_VERTICAL_MM,
    QR_GRID_PAGE_HEIGHT_MM,
    QR_GRID_PAGE_SIZE,
    QR_GRID_PAGE_WIDTH_MM,
    QR_GRID_ROWS,
    QR_GRID_WIDTH_MM,
    equipment_url,
    generate_qr_grid_pdf,
    generate_qr_png,
)

User = get_user_model()

# Pontos por milímetro (1 polegada = 72pt = 25.4mm) — usado para converter
# as coordenadas em pontos que pdfplumber/pypdf reportam para milímetros,
# a mesma unidade em que o requisito físico (50x50mm, margens, gutter) foi
# especificado. Medir em mm direto do PDF (não do screenshot rasterizado)
# é o que garante que a confirmação é objetiva, não visual/"a olho".
PT_PER_MM = 72 / 25.4


class ModelQRGridDownloadViewTest(TestCase):
    """
    QR Codes puros em lote por modelo, um único PDF A4 em grade — mesmo
    escopo/permissão de `qrcodes:model_label_batch` (`ModelLabelBatchDownloadView`),
    reaproveitados sem duplicação de lógica.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model_a = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.model_b = EquipmentModel.objects.create(category=self.category, name="9 Pro", code="9PRO")
        creator = User.objects.create_user(username="cadastrador_qrgrid", password="senha-forte-123")

        self.eq_a1 = create_equipment(NewEquipmentData(model_id=self.model_a.pk, created_by=creator))
        self.eq_a2 = create_equipment(NewEquipmentData(model_id=self.model_a.pk, created_by=creator))
        self.eq_b1 = create_equipment(NewEquipmentData(model_id=self.model_b.pk, created_by=creator))
        self.inactive_a = create_equipment(NewEquipmentData(model_id=self.model_a.pk, created_by=creator))
        self.inactive_a.is_active = False
        self.inactive_a.save(update_fields=["is_active"])

        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"qrgrid_{role.lower()}", password="senha-forte-123", role=role)

    def _url(self, model_id, *, tema=None):
        base = f"/qrcodes/modelo/{model_id}/qrcodes.pdf"
        return f"{base}?tema={tema}" if tema is not None else base

    def _decode_all_qrs(self, pdf_bytes):
        """
        Decodifica todo QR embutido no PDF (todas as páginas), deduplicado
        por nome de objeto de imagem — o `/Resources` do WeasyPrint é
        compartilhado entre páginas, então `page.images` do pypdf pode
        listar o mesmo XObject em mais de uma página mesmo quando ele só é
        desenhado em uma; deduplicar é o que garante 1 resultado por
        imagem realmente distinta, não por página.
        """
        reader = PdfReader(io.BytesIO(pdf_bytes))
        seen = {}
        for page in reader.pages:
            for img in page.images:
                if img.name in seen:
                    continue
                pil_img = Image.open(io.BytesIO(img.data))
                decoded = decode(pil_img)
                self.assertEqual(len(decoded), 1, "Cada imagem embutida deve conter exatamente 1 QR decodificável.")
                seen[img.name] = decoded[0].data.decode()
        return list(seen.values())

    def _unique_image_count(self, pdf_bytes):
        reader = PdfReader(io.BytesIO(pdf_bytes))
        names = set()
        for page in reader.pages:
            for img in page.images:
                names.add(img.name)
        return len(names)

    # 1. Requer autenticação — anônimo é barrado (redirect para login),
    # igual a qualquer outra rota de qrcodes.
    def test_anonymous_user_is_not_allowed(self):
        response = self.client.get(self._url(self.model_a.pk))
        self.assertNotEqual(response.status_code, 200)

    # 2. Admin e Administrativo podem baixar — a MESMA matriz de
    # permissão de `model_label_batch` (o botão existente ao lado).
    def test_permission_matches_the_existing_label_batch_export(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO):
            with self.subTest(role=role):
                self.client.login(username=f"qrgrid_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._url(self.model_a.pk))
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    # 3. Operacional/Consulta são proibidos no BACKEND — não é só a UI
    # que esconde o botão; a rota em si devolve 403 mesmo se acessada
    # diretamente pela URL.
    def test_operacional_and_consulta_are_forbidden_by_the_backend(self):
        for role in (Role.OPERACIONAL, Role.CONSULTA):
            with self.subTest(role=role):
                self.client.login(username=f"qrgrid_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._url(self.model_a.pk))
                self.assertEqual(response.status_code, 403)
                self.client.logout()

    # 4 e 5. HTTP 200 e Content-Type application/pdf.
    def test_response_is_200_with_pdf_content_type(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    # 6. Um único equipamento ativo gera um PDF válido de 1 página com 1 QR.
    def test_single_equipment_produces_a_valid_one_page_pdf(self):
        solo_model = EquipmentModel.objects.create(category=self.category, name="Solo", code="SOLO1")
        creator = User.objects.first()
        create_equipment(NewEquipmentData(model_id=solo_model.pk, created_by=creator))

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(solo_model.pk))
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(reader.pages), 1)
        self.assertEqual(len(list(reader.pages[0].images)), 1)

    # 7. Múltiplos equipamentos do mesmo modelo geram um PDF válido, com
    # 1 QR por equipamento.
    def test_multiple_equipment_produces_a_valid_pdf_with_one_qr_each(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        self.assertEqual(response.status_code, 200)
        total_images = self._unique_image_count(response.content)
        self.assertEqual(
            total_images,
            2,
            "Só os 2 equipamentos ATIVOS do modelo A entram — nunca o inativo, nunca os do modelo B.",
        )

    # 8. Lote grande (mais que uma página) continua um PDF válido,
    # multi-página, com exatamente 1 QR por equipamento no total.
    def test_large_batch_spans_multiple_pages_and_stays_a_valid_pdf(self):
        big_model = EquipmentModel.objects.create(category=self.category, name="Grande", code="GRANDE1")
        creator = User.objects.first()
        total = QR_GRID_PAGE_SIZE + 5  # força pelo menos 2 páginas
        equipments = [create_equipment(NewEquipmentData(model_id=big_model.pk, created_by=creator)) for _ in range(total)]

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(big_model.pk))
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(io.BytesIO(response.content))
        self.assertGreaterEqual(len(reader.pages), 2, "Lote maior que uma página cheia deve gerar múltiplas páginas.")
        total_images = self._unique_image_count(response.content)
        self.assertEqual(total_images, total, "1 QR por equipamento, nenhum a mais nem a menos.")
        self.assertEqual(QR_GRID_COLUMNS * QR_GRID_ROWS, QR_GRID_PAGE_SIZE)

    # 9. Exatamente 1 QR por Equipment — reforça 7/8 de forma direta,
    # comparando contagem de QR decodificado com a queryset esperada.
    def test_exactly_one_qr_per_equipment(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        decoded_urls = self._decode_all_qrs(response.content)
        expected = {self.eq_a1.patrimonio, self.eq_a2.patrimonio}
        decoded_patrimonios = {url.rstrip("/").rsplit("/", 1)[-1] for url in decoded_urls}
        self.assertEqual(len(decoded_urls), 2)
        self.assertEqual(decoded_patrimonios, expected)

    # 10. O QR usa a MESMA URL/mecanismo do gerador individual
    # (`generate_qr_png`/`equipment_url`) — nenhum segundo padrão de QR
    # inventado para esta função.
    def test_qr_uses_the_same_url_as_the_individual_qr_generator(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        decoded_urls = self._decode_all_qrs(response.content)
        self.assertEqual(
            set(decoded_urls),
            {equipment_url(self.eq_a1), equipment_url(self.eq_a2)},
        )
        # E o próprio PNG individual (`qrcodes:qr_png`) decodifica para a
        # mesma URL — confirmando que é a mesma origem/dado, não uma
        # segunda lógica de geração.
        individual_response = self.client.get(f"/qrcodes/{self.eq_a1.patrimonio}/qr.png")
        individual_decoded = decode(Image.open(io.BytesIO(individual_response.content)))
        self.assertEqual(individual_decoded[0].data.decode(), equipment_url(self.eq_a1))

    # 11. Sem mistura de escopo: equipamento de outro modelo e
    # equipamento inativo do MESMO modelo nunca aparecem.
    def test_no_scope_mixing_across_models_or_inactive_equipment(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        decoded_urls = set(self._decode_all_qrs(response.content))
        self.assertNotIn(equipment_url(self.eq_b1), decoded_urls, "Equipamento de outro modelo não pode aparecer.")
        self.assertNotIn(equipment_url(self.inactive_a), decoded_urls, "Equipamento inativo não pode aparecer.")

    # 12. Ordem determinística — por `patrimonio`, igual à ordenação
    # explícita da view (`order_by("patrimonio")`).
    def test_deterministic_order_by_patrimonio(self):
        ordered_model = EquipmentModel.objects.create(category=self.category, name="Ordenado", code="ORD1")
        creator = User.objects.first()
        equipments = [create_equipment(NewEquipmentData(model_id=ordered_model.pk, created_by=creator)) for _ in range(4)]
        expected_order = [eq.patrimonio for eq in sorted(equipments, key=lambda e: e.patrimonio)]

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(ordered_model.pk))
        decoded_urls = self._decode_all_qrs(response.content)
        decoded_patrimonios = [url.rstrip("/").rsplit("/", 1)[-1] for url in decoded_urls]
        self.assertEqual(decoded_patrimonios, expected_order)

    # 13a. Exportar não altera nenhum registro de Equipment.
    def test_exporting_does_not_alter_any_equipment_record(self):
        before = list(
            Equipment.objects.filter(pk__in=[self.eq_a1.pk, self.eq_a2.pk, self.eq_b1.pk, self.inactive_a.pk])
            .order_by("pk")
            .values()
        )
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        self.assertEqual(response.status_code, 200)
        after = list(
            Equipment.objects.filter(pk__in=[self.eq_a1.pk, self.eq_a2.pk, self.eq_b1.pk, self.inactive_a.pk])
            .order_by("pk")
            .values()
        )
        self.assertEqual(before, after, "A exportação não deveria alterar nenhum campo de nenhum equipamento.")

    # 13b. Nenhum efeito colateral em Movement, StatusHistory,
    # ConditionHistory ou Attachment — operação estritamente de leitura,
    # sem gerar Attachment/`/media/` nenhum (a spec proíbe explicitamente
    # armazenar o PDF gerado).
    def test_exporting_creates_no_movement_history_or_attachment_records(self):
        movement_count_before = Movement.objects.count()
        status_history_before = StatusHistory.objects.count()
        condition_history_before = ConditionHistory.objects.count()
        attachment_count_before = Attachment.objects.count()

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        self.assertEqual(response.status_code, 200)

        self.assertEqual(Movement.objects.count(), movement_count_before)
        self.assertEqual(StatusHistory.objects.count(), status_history_before)
        self.assertEqual(ConditionHistory.objects.count(), condition_history_before)
        self.assertEqual(Attachment.objects.count(), attachment_count_before)

    # 14. Nome de arquivo amigável, seguindo a convenção já usada por
    # `model_label_batch` (`etiquetas-{code}.pdf`), trocando só o
    # prefixo (pedido explícito: exemplo "qrcodes-aqcp.pdf").
    def test_filename_follows_the_existing_naming_convention(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        self.assertEqual(
            response["Content-Disposition"],
            f'attachment; filename="qrcodes-{self.model_a.code}.pdf"',
        )

    # 15. QR "puro": o PDF não contém nenhum texto (nem patrimônio, nem
    # código do modelo, nem nome comercial) — só a imagem do QR.
    def test_pdf_has_no_text_content_at_all(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(self.model_a.pk))
        reader = PdfReader(io.BytesIO(response.content))
        full_text = "".join(page.extract_text() for page in reader.pages).strip()
        self.assertEqual(full_text, "", "QR puro não pode ter nenhum texto — nem patrimônio, nem código do modelo.")

    # 16. Modelo inexistente -> 404 (mesmo comportamento de
    # `model_label_batch`).
    def test_nonexistent_model_returns_404(self):
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(999999))
        self.assertEqual(response.status_code, 404)

    # 17. Modelo existente mas sem nenhum equipamento ativo -> 404 (nunca
    # um PDF vazio/quebrado).
    def test_model_with_no_active_equipment_returns_404(self):
        empty_model = EquipmentModel.objects.create(category=self.category, name="Modelo Vazio", code="VAZIOQR1")
        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(empty_model.pk))
        self.assertEqual(response.status_code, 404)

    # 18. O QR embutido no PDF é byte-a-byte igual ao PNG "puro" gerado
    # por `generate_qr_png` para o mesmo equipamento — reforça que
    # nenhuma segunda função/lógica de geração foi criada.
    def test_embedded_qr_image_bytes_match_generate_qr_png(self):
        solo_model = EquipmentModel.objects.create(category=self.category, name="Solo Bytes", code="SOLOB1")
        creator = User.objects.first()
        equipment = create_equipment(NewEquipmentData(model_id=solo_model.pk, created_by=creator))

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(solo_model.pk))
        reader = PdfReader(io.BytesIO(response.content))
        embedded_images = list(reader.pages[0].images)
        self.assertEqual(len(embedded_images), 1)

        expected_decoded = decode(Image.open(io.BytesIO(generate_qr_png(equipment))))
        actual_decoded = decode(Image.open(io.BytesIO(embedded_images[0].data)))
        self.assertEqual(actual_decoded[0].data, expected_decoded[0].data)


class ModelQRGridPhysicalDimensionsTest(TestCase):
    """
    Correção de 16/09/2026: a exportação já funcionava, mas a validação
    visual/física real mostrou a grade deslocada para a esquerda e o QR
    fora do requisito explícito de 50×50mm exatos (a primeira versão
    usava célula de ~48mm). Esta classe mede a posição/tamanho de cada
    imagem embutida DIRETO do conteúdo do PDF (via `pdfplumber`, em
    milímetros) — nunca só "olhando" um screenshot — para confirmar
    objetivamente os números pedidos: QR 50×50mm, grade 160×270mm,
    margens 25mm (horizontal) / 13.5mm (vertical), gutter 5mm.

    O bug raiz (para registro): `LANGUAGE_CODE="pt-br"` fazia o Django
    renderizar os `margin_*_mm` fracionários (13.5) com VÍRGULA decimal
    ("13,5mm", CSS inválido) no template — corrigido com
    `{% localize off %}` em `templates/qrcodes/qr_grid.html`. Um teste
    aqui (`test_grid_is_not_flush_to_the_page_origin`) trava
    especificamente essa regressão: sem `{% localize off %}`, a margem
    medida seria 0mm, não 25mm/13.5mm.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        creator = User.objects.create_user(username="cadastrador_qrgrid_fisico", password="senha-forte-123")
        self.creator = creator
        User.objects.create_user(username="qrgridfisico_admin", password="senha-forte-123", role=Role.ADMIN)

    def _create_equipment(self, quantity):
        return [create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.creator)) for _ in range(quantity)]

    def _download(self):
        self.client.login(username="qrgridfisico_admin", password="senha-forte-123")
        response = self.client.get(f"/qrcodes/modelo/{self.model.pk}/qrcodes.pdf")
        self.assertEqual(response.status_code, 200)
        return response.content

    def _images_by_page(self, pdf_bytes):
        """
        Lista, por página, as imagens embutidas com posição/tamanho em mm
        (x0/x1/top/bottom relativos ao canto superior esquerdo da
        página), ordenadas em ordem de leitura (linha, depois coluna) —
        mesma ordem em que a grade é preenchida.
        """
        pages_images = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                images = []
                for im in page.images:
                    images.append(
                        {
                            "x0": im["x0"] / PT_PER_MM,
                            "x1": im["x1"] / PT_PER_MM,
                            "top": im["top"] / PT_PER_MM,
                            "bottom": im["bottom"] / PT_PER_MM,
                        }
                    )
                images.sort(key=lambda im: (round(im["top"], 1), round(im["x0"], 1)))
                pages_images.append(images)
        return pages_images

    # 1. A4 = 210 × 297mm.
    def test_page_size_is_a4(self):
        equipment = self._create_equipment(1)
        pdf_bytes = self._download()
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page = pdf.pages[0]
            self.assertAlmostEqual(page.width / PT_PER_MM, QR_GRID_PAGE_WIDTH_MM, places=1)
            self.assertAlmostEqual(page.height / PT_PER_MM, QR_GRID_PAGE_HEIGHT_MM, places=1)
        self.assertEqual(QR_GRID_PAGE_WIDTH_MM, 210)
        self.assertEqual(QR_GRID_PAGE_HEIGHT_MM, 297)

    # 2 e 3. Cada QR mede EXATAMENTE 50×50mm — nunca mais 48mm (bug
    # corrigido) nem qualquer outro valor aproximado.
    def test_each_qr_image_is_exactly_50x50mm(self):
        self.assertEqual(QR_GRID_CELL_SIZE_MM, 50, "A célula/QR não pode mais ser 48mm nem nenhum valor aproximado — exatamente 50mm.")
        self.assertNotEqual(QR_GRID_CELL_SIZE_MM, 48)

        self._create_equipment(15)
        pdf_bytes = self._download()
        pages = self._images_by_page(pdf_bytes)
        self.assertEqual(len(pages[0]), 15)
        for img in pages[0]:
            self.assertAlmostEqual(img["x1"] - img["x0"], 50.0, places=1, msg="Largura do QR deve ser exatamente 50mm.")
            self.assertAlmostEqual(img["bottom"] - img["top"], 50.0, places=1, msg="Altura do QR deve ser exatamente 50mm.")

    # 4, 5 e 6. 3 colunas × 5 linhas = 15 por página.
    def test_grid_is_three_columns_by_five_rows_of_fifteen(self):
        self.assertEqual(QR_GRID_COLUMNS, 3)
        self.assertEqual(QR_GRID_ROWS, 5)
        self.assertEqual(QR_GRID_PAGE_SIZE, 15)

    # 7 e 8. Espaçamento (gutter) uniforme de 5mm, tanto entre colunas
    # quanto entre linhas.
    def test_gutter_between_columns_and_rows_is_uniform(self):
        self.assertEqual(QR_GRID_GUTTER_MM, 5)
        self._create_equipment(15)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]

        rows = [images[0:3], images[3:6], images[6:9], images[9:12], images[12:15]]
        for row in rows:
            self.assertAlmostEqual(row[1]["x0"] - row[0]["x1"], QR_GRID_GUTTER_MM, places=1, msg="Gutter horizontal (col 1→2) deve ser 5mm.")
            self.assertAlmostEqual(row[2]["x0"] - row[1]["x1"], QR_GRID_GUTTER_MM, places=1, msg="Gutter horizontal (col 2→3) deve ser 5mm.")

        for col in range(3):
            for row_index in range(4):
                current = rows[row_index][col]
                next_row = rows[row_index + 1][col]
                self.assertAlmostEqual(
                    next_row["top"] - current["bottom"], QR_GRID_GUTTER_MM, places=1, msg="Gutter vertical entre linhas deve ser 5mm."
                )

    # 9 e 10. A grade fica centralizada HORIZONTALMENTE na folha — margem
    # esquerda igual à margem direita, calculada matematicamente (não "no
    # olho"). Este teste também é o que trava a regressão de
    # `{% localize off %}`: sem ela, x0 seria 0mm, não 25mm.
    def test_grid_is_horizontally_centered_with_equal_margins(self):
        self._create_equipment(15)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]

        leftmost_x0 = min(img["x0"] for img in images)
        rightmost_x1 = max(img["x1"] for img in images)
        left_margin = leftmost_x0
        right_margin = QR_GRID_PAGE_WIDTH_MM - rightmost_x1

        self.assertAlmostEqual(left_margin, right_margin, places=1, msg="Margem esquerda e direita devem ser idênticas — grade centralizada.")
        self.assertAlmostEqual(left_margin, QR_GRID_MARGIN_HORIZONTAL_MM, places=1)
        self.assertAlmostEqual(left_margin, 25.0, places=1)
        self.assertGreater(left_margin, 1.0, "Se a margem for ~0mm, a grade voltou a ficar colada na borda esquerda (bug antigo).")

    # 11. Margem vertical (topo/base) = 13.5mm, grade 160×270mm — os
    # números do pedido, confirmados direto do PDF.
    def test_grid_and_vertical_margins_match_the_requested_layout(self):
        self._create_equipment(15)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]

        top_margin = min(img["top"] for img in images)
        bottom_margin = QR_GRID_PAGE_HEIGHT_MM - max(img["bottom"] for img in images)

        self.assertAlmostEqual(top_margin, QR_GRID_MARGIN_VERTICAL_MM, places=1)
        self.assertAlmostEqual(top_margin, 13.5, places=1)
        self.assertAlmostEqual(bottom_margin, 13.5, places=1)
        self.assertAlmostEqual(QR_GRID_WIDTH_MM, 160.0, places=1)
        self.assertAlmostEqual(QR_GRID_HEIGHT_MM, 270.0, places=1)

    # 12. Nenhuma página extra/branca para um lote que fecha exatamente
    # em páginas cheias (15, 30).
    def test_no_extra_blank_page_for_exact_multiples_of_page_size(self):
        for quantity, expected_pages in ((15, 1), (30, 2)):
            with self.subTest(quantity=quantity):
                model = EquipmentModel.objects.create(category=self.category, name=f"Exato {quantity}", code=f"EXATO{quantity}")
                for _ in range(quantity):
                    create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.creator))
                self.client.login(username="qrgridfisico_admin", password="senha-forte-123")
                response = self.client.get(f"/qrcodes/modelo/{model.pk}/qrcodes.pdf")
                reader = PdfReader(io.BytesIO(response.content))
                self.assertEqual(len(reader.pages), expected_pages)

    # 13. Múltiplas páginas para lotes que passam de um múltiplo exato —
    # confirma os exemplos do próprio pedido (16→2 páginas, 31→3 páginas).
    def test_multiple_pages_for_batches_past_a_full_page(self):
        for quantity, expected_pages in ((16, 2), (31, 3)):
            with self.subTest(quantity=quantity):
                model = EquipmentModel.objects.create(category=self.category, name=f"Passa {quantity}", code=f"PASSA{quantity}")
                for _ in range(quantity):
                    create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.creator))
                self.client.login(username="qrgridfisico_admin", password="senha-forte-123")
                response = self.client.get(f"/qrcodes/modelo/{model.pk}/qrcodes.pdf")
                reader = PdfReader(io.BytesIO(response.content))
                self.assertEqual(len(reader.pages), expected_pages)

    # 14 e 15. O QR continua decodificando corretamente para a URL certa
    # — a correção de layout não pode ter afetado o conteúdo/leitura do
    # QR.
    def test_qr_still_decodes_to_the_correct_url_after_the_layout_fix(self):
        equipment = self._create_equipment(1)[0]
        pdf_bytes = self._download()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        embedded = list(reader.pages[0].images)
        self.assertEqual(len(embedded), 1)
        decoded = decode(Image.open(io.BytesIO(embedded[0].data)))
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].data.decode(), equipment_url(equipment))

    # 16. Continua sem nenhum texto — QR puro, mesmo depois da correção
    # de layout (nenhuma legenda/borda/patrimônio foi introduzido).
    def test_still_no_text_content_after_the_layout_fix(self):
        self._create_equipment(3)
        pdf_bytes = self._download()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "".join(page.extract_text() for page in reader.pages).strip()
        self.assertEqual(full_text, "")

    # 9 (reforço). Página incompleta: os itens continuam preenchendo
    # esquerda→direita/cima→baixo nas MESMAS posições de grade da folha
    # cheia — nunca redistribuídos/centralizados entre si. Confirma
    # objetivamente o exemplo do pedido (4 QRs → 3 na linha 1, 1 na
    # linha 2, nunca "4 QRs centralizados no meio da página").
    def test_partial_page_keeps_the_same_grid_positions_and_page_margins(self):
        self._create_equipment(4)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]
        self.assertEqual(len(images), 4)

        # As 3 primeiras na linha 1 (mesmo `top`), a 4ª sozinha na linha 2.
        row1 = images[0:3]
        row2 = images[3:4]
        tops_row1 = {round(img["top"], 1) for img in row1}
        self.assertEqual(len(tops_row1), 1, "As 3 primeiras devem estar todas na mesma linha (mesmo `top`).")
        self.assertGreater(row2[0]["top"], row1[0]["top"], "O 4º item deve estar numa linha abaixo, nunca ao lado/centralizado.")

        # A origem da grade (margens) é a MESMA da folha cheia — a página
        # incompleta não veio "mais centralizada" nem com margens
        # diferentes por ter menos itens.
        self.assertAlmostEqual(row1[0]["x0"], QR_GRID_MARGIN_HORIZONTAL_MM, places=1)
        self.assertAlmostEqual(row1[0]["top"], QR_GRID_MARGIN_VERTICAL_MM, places=1)
        # E o 4º item (linha 2, coluna 1) fica na mesma coluna x0 do 1º —
        # preenchimento em ordem de leitura, nunca centralizado sozinho.
        self.assertAlmostEqual(row2[0]["x0"], row1[0]["x0"], places=1)

    # 16 (dados). A correção de layout não altera nenhum registro —
    # continua 100% leitura.
    def test_layout_fix_does_not_alter_any_equipment_record(self):
        equipment_list = self._create_equipment(3)
        before = list(Equipment.objects.filter(pk__in=[e.pk for e in equipment_list]).order_by("pk").values())
        self._download()
        after = list(Equipment.objects.filter(pk__in=[e.pk for e in equipment_list]).order_by("pk").values())
        self.assertEqual(before, after)


class ModelQRGridThemeTest(TestCase):
    """
    Tema Claro/Escuro (pedido de 16/09/2026, decisão revista na mesma
    rodada da correção de dimensionamento): "Exportar QR Codes em PDF"
    passou a reaproveitar o MESMO modal/`?tema=` já usado por "Etiquetas
    em lote" — nenhum modal novo, nenhuma validação de tema nova
    (`_validated_theme`, a mesma função de sempre). Só o FUNDO da página
    muda; o QR em si nunca é invertido, e a geometria física (posição/
    tamanho/margem) da correção anterior tem que continuar idêntica nos
    dois temas.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.creator = User.objects.create_user(username="cadastrador_qrgrid_tema", password="senha-forte-123")
        User.objects.create_user(username="qrgridtema_admin", password="senha-forte-123", role=Role.ADMIN)

    def _create_equipment(self, quantity):
        return [create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.creator)) for _ in range(quantity)]

    def _url(self, *, tema=None):
        base = f"/qrcodes/modelo/{self.model.pk}/qrcodes.pdf"
        return f"{base}?tema={tema}" if tema is not None else base

    def _get(self, **kwargs):
        self.client.login(username="qrgridtema_admin", password="senha-forte-123")
        return self.client.get(self._url(**kwargs))

    # 1. Sem `?tema=`, continua caindo no padrão "light" — mesmo
    # comportamento de sempre desta e de toda outra rota deste app,
    # nenhuma mudança de comportamento para quem não usa o modal.
    def test_without_tema_defaults_to_light(self):
        self._create_equipment(1)
        response = self._get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    def test_accepts_light_explicitly(self):
        self._create_equipment(1)
        response = self._get(tema="light")
        self.assertEqual(response.status_code, 200)

    def test_accepts_dark(self):
        self._create_equipment(1)
        response = self._get(tema="dark")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

    # 2. Tema inválido continua rejeitado com 400 — mesma validação
    # (`_validated_theme`) de toda outra rota, nunca aceito
    # silenciosamente.
    def test_rejects_invalid_theme(self):
        self._create_equipment(1)
        response = self._get(tema="roxo")
        self.assertEqual(response.status_code, 400)

    # 3. Light e dark produzem PDFs BYTES DIFERENTES (o fundo realmente
    # muda) — não é um parâmetro aceito e ignorado.
    def test_light_and_dark_produce_different_pdf_bytes(self):
        self._create_equipment(3)
        light_bytes = self._get(tema="light").content
        dark_bytes = self._get(tema="dark").content
        self.assertNotEqual(light_bytes, dark_bytes)

    # 4. A geometria física da correção anterior (posição/tamanho de
    # cada QR, margens, gutter) é IDÊNTICA nos dois temas — o tema muda
    # só o fundo, nunca o layout/dimensionamento.
    def test_physical_geometry_is_identical_regardless_of_theme(self):
        self._create_equipment(4)
        light_bytes = self._get(tema="light").content
        dark_bytes = self._get(tema="dark").content

        def measure(pdf_bytes):
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page = pdf.pages[0]
                images = sorted(page.images, key=lambda im: (round(im["top"], 1), round(im["x0"], 1)))
                return [
                    (
                        round(im["x0"] / PT_PER_MM, 2),
                        round(im["top"] / PT_PER_MM, 2),
                        round((im["x1"] - im["x0"]) / PT_PER_MM, 2),
                        round((im["bottom"] - im["top"]) / PT_PER_MM, 2),
                    )
                    for im in images
                ]

        self.assertEqual(measure(light_bytes), measure(dark_bytes))

    # 5. O QR em si NUNCA é invertido — continua decodificando para a
    # MESMA URL correta em qualquer tema (mesma regra incondicional de
    # `label_square.html`: confiabilidade de leitura acima de estética).
    def test_qr_still_decodes_correctly_in_both_themes(self):
        equipment = self._create_equipment(1)[0]
        for tema in ("light", "dark"):
            with self.subTest(tema=tema):
                response = self._get(tema=tema)
                reader = PdfReader(io.BytesIO(response.content))
                embedded = list(reader.pages[0].images)
                self.assertEqual(len(embedded), 1)
                decoded = decode(Image.open(io.BytesIO(embedded[0].data)))
                self.assertEqual(len(decoded), 1)
                self.assertEqual(decoded[0].data.decode(), equipment_url(equipment))

    # 6. A própria imagem do QR (os bytes do PNG embutido) é
    # BYTE-A-BYTE IDÊNTICA em light e dark — reforça que o tema só pinta
    # o fundo da página, nunca gera um QR diferente/invertido.
    def test_embedded_qr_png_bytes_are_identical_across_themes(self):
        self._create_equipment(1)
        light_bytes = self._get(tema="light").content
        dark_bytes = self._get(tema="dark").content

        light_img = list(PdfReader(io.BytesIO(light_bytes)).pages[0].images)[0].data
        dark_img = list(PdfReader(io.BytesIO(dark_bytes)).pages[0].images)[0].data
        self.assertEqual(light_img, dark_img)

    # 7. Nome de arquivo não muda por causa do tema — continua
    # `qrcodes-{code}.pdf` nos dois casos (mesma convenção já
    # confirmada).
    def test_filename_does_not_change_with_theme(self):
        self._create_equipment(1)
        expected = f'attachment; filename="qrcodes-{self.model.code}.pdf"'
        for tema in ("light", "dark"):
            with self.subTest(tema=tema):
                response = self._get(tema=tema)
                self.assertEqual(response["Content-Disposition"], expected)

    # 8. Nenhum texto em nenhum dos dois temas — QR puro continua puro,
    # tema não introduziu nenhuma legenda/rótulo.
    def test_no_text_in_either_theme(self):
        self._create_equipment(2)
        for tema in ("light", "dark"):
            with self.subTest(tema=tema):
                response = self._get(tema=tema)
                reader = PdfReader(io.BytesIO(response.content))
                full_text = "".join(page.extract_text() for page in reader.pages).strip()
                self.assertEqual(full_text, "")

    # 9. `generate_qr_grid_pdf` sozinha (sem o client HTTP) também aceita
    # os dois temas nomeados via constante — reforça que a função de
    # serviço, não só a view, suporta o parâmetro.
    def test_service_function_accepts_both_theme_constants(self):
        equipment_list = self._create_equipment(2)
        light_pdf = generate_qr_grid_pdf(equipment_list, theme=LABEL_THEME_LIGHT)
        dark_pdf = generate_qr_grid_pdf(equipment_list, theme=LABEL_THEME_DARK)
        self.assertTrue(light_pdf.startswith(b"%PDF"))
        self.assertTrue(dark_pdf.startswith(b"%PDF"))
        self.assertNotEqual(light_pdf, dark_pdf)
