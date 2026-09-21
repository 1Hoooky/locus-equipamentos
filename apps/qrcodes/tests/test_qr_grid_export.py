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
    QR_GRID_CELL_HEIGHT_MM,
    QR_GRID_CELL_WIDTH_MM,
    QR_GRID_COLUMNS,
    QR_GRID_GUTTER_MM,
    QR_GRID_HEIGHT_MM,
    QR_GRID_MARGIN_HORIZONTAL_MM,
    QR_GRID_MARGIN_VERTICAL_MM,
    QR_GRID_PAGE_HEIGHT_MM,
    QR_GRID_PAGE_SIZE,
    QR_GRID_PAGE_WIDTH_MM,
    QR_GRID_QR_SIZE_MM,
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
    Duas rodadas de correção física medidas aqui, ambas via `pdfplumber`
    direto no conteúdo do PDF (em milímetros) — nunca só "olhando" um
    screenshot:

    1. Correção de 16/09/2026 (registro histórico): a exportação já
       funcionava, mas a validação visual/física real mostrou a grade
       deslocada para a esquerda e o QR fora do requisito então vigente
       de 50×50mm exatos (a primeira versão usava célula de ~48mm).

    2. Rodada de padronização física (adesivo real 60×40mm): a CÉLULA da
       grade deixou de ser do tamanho exato do QR e passou a ser o
       adesivo inteiro (`QR_GRID_CELL_WIDTH_MM` × `QR_GRID_CELL_HEIGHT_MM`
       = 60×40mm) — o QR (`QR_GRID_QR_SIZE_MM` = 36mm, sempre quadrado)
       fica centralizado dentro dela, com folga visível ao redor. Os
       testes abaixo distinguem explicitamente "posição da CÉLULA" de
       "posição do QR": como `pdfplumber` só enxerga a imagem do QR (a
       célula não tem nenhum retângulo desenhado), a margem/gutter
       medida a partir da imagem é sempre `margem_da_página +
       folga_da_célula` — nunca só a margem da página sozinha.

    O bug raiz de 16/09/2026 (para registro, ainda relevante — a técnica
    de `{% localize off %}` continua em uso): `LANGUAGE_CODE="pt-br"`
    fazia o Django renderizar `margin_*_mm` fracionários com VÍRGULA
    decimal ("23,5mm", CSS inválido) no template — corrigido com
    `{% localize off %}` em `templates/qrcodes/qr_grid.html`. Os testes
    de margem abaixo travam essa regressão: sem `{% localize off %}`, a
    margem medida seria bem menor que a esperada, não os valores
    calculados aqui.
    """

    # Folga entre a borda do QR e a borda da célula/adesivo que o contém
    # — o que sobra da célula (60×40mm) depois do QR (36×36mm),
    # distribuído igualmente nos dois lados de cada eixo.
    CELL_MARGIN_HORIZONTAL_MM = (QR_GRID_CELL_WIDTH_MM - QR_GRID_QR_SIZE_MM) / 2  # 12.0
    CELL_MARGIN_VERTICAL_MM = (QR_GRID_CELL_HEIGHT_MM - QR_GRID_QR_SIZE_MM) / 2  # 2.0

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

    # 2 e 3. Cada QR mede EXATAMENTE 36×36mm — nunca o tamanho da célula
    # inteira (isso seria a grade ANTES da padronização física) nem
    # qualquer outro valor aproximado.
    def test_each_qr_image_is_exactly_36x36mm(self):
        self.assertEqual(QR_GRID_QR_SIZE_MM, 36, "O QR dentro da célula deve ser exatamente 36mm.")
        self.assertNotEqual(QR_GRID_QR_SIZE_MM, QR_GRID_CELL_WIDTH_MM, "O QR não pode voltar a ocupar a célula inteira — a célula agora é o adesivo (60×40mm), maior que o QR.")

        self._create_equipment(QR_GRID_PAGE_SIZE)
        pdf_bytes = self._download()
        pages = self._images_by_page(pdf_bytes)
        self.assertEqual(len(pages[0]), QR_GRID_PAGE_SIZE)
        for img in pages[0]:
            self.assertAlmostEqual(img["x1"] - img["x0"], 36.0, places=1, msg="Largura do QR deve ser exatamente 36mm.")
            self.assertAlmostEqual(img["bottom"] - img["top"], 36.0, places=1, msg="Altura do QR deve ser exatamente 36mm.")

    # 4, 5 e 6. 3 colunas × 6 linhas = 18 por página — cada célula é 1
    # adesivo real (60×40mm).
    def test_grid_is_three_columns_by_six_rows_of_eighteen(self):
        self.assertEqual(QR_GRID_COLUMNS, 3)
        self.assertEqual(QR_GRID_ROWS, 6)
        self.assertEqual(QR_GRID_PAGE_SIZE, 18)
        self.assertEqual(QR_GRID_CELL_WIDTH_MM, 60)
        self.assertEqual(QR_GRID_CELL_HEIGHT_MM, 40)

    # 7 e 8. O "passo" da grade (distância entre o início de uma célula e
    # o início da próxima) é célula + gutter, tanto na horizontal quanto
    # na vertical — o jeito mais robusto de confirmar o gutter entre
    # CÉLULAS, já que `pdfplumber` só enxerga o QR (menor que a célula),
    # não a célula em si.
    def test_grid_pitch_between_cells_is_cell_size_plus_gutter(self):
        self.assertEqual(QR_GRID_GUTTER_MM, 2)
        self._create_equipment(QR_GRID_PAGE_SIZE)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]
        rows = [images[i : i + QR_GRID_COLUMNS] for i in range(0, QR_GRID_PAGE_SIZE, QR_GRID_COLUMNS)]

        expected_horizontal_pitch = QR_GRID_CELL_WIDTH_MM + QR_GRID_GUTTER_MM  # 62mm
        expected_vertical_pitch = QR_GRID_CELL_HEIGHT_MM + QR_GRID_GUTTER_MM  # 42mm

        for row in rows:
            for col in range(QR_GRID_COLUMNS - 1):
                self.assertAlmostEqual(
                    row[col + 1]["x0"] - row[col]["x0"],
                    expected_horizontal_pitch,
                    places=1,
                    msg="Passo horizontal entre colunas deve ser célula (60mm) + gutter (2mm) = 62mm.",
                )

        for col in range(QR_GRID_COLUMNS):
            for row_index in range(QR_GRID_ROWS - 1):
                self.assertAlmostEqual(
                    rows[row_index + 1][col]["top"] - rows[row_index][col]["top"],
                    expected_vertical_pitch,
                    places=1,
                    msg="Passo vertical entre linhas deve ser célula (40mm) + gutter (2mm) = 42mm.",
                )

    # 7b. O espaço visível entre um QR e o próximo (edge a edge, não
    # célula a célula) é o gutter mais a folga de cada célula ao redor
    # do QR — reforça o teste de "passo" acima com o número final que
    # alguém mediria com uma régua na impressão real.
    def test_visible_gap_between_adjacent_qr_images_matches_gutter_plus_cell_margins(self):
        self._create_equipment(QR_GRID_PAGE_SIZE)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]
        rows = [images[i : i + QR_GRID_COLUMNS] for i in range(0, QR_GRID_PAGE_SIZE, QR_GRID_COLUMNS)]

        expected_horizontal_gap = QR_GRID_GUTTER_MM + 2 * self.CELL_MARGIN_HORIZONTAL_MM  # 2 + 24 = 26mm
        expected_vertical_gap = QR_GRID_GUTTER_MM + 2 * self.CELL_MARGIN_VERTICAL_MM  # 2 + 4 = 6mm

        self.assertAlmostEqual(rows[0][1]["x0"] - rows[0][0]["x1"], expected_horizontal_gap, places=1)
        self.assertAlmostEqual(rows[1][0]["top"] - rows[0][0]["bottom"], expected_vertical_gap, places=1)

    # 9 e 10. A grade fica centralizada HORIZONTALMENTE na folha — margem
    # esquerda igual à margem direita, calculada matematicamente (não "no
    # olho"). A margem medida a partir do QR é a margem da PÁGINA mais a
    # folga da CÉLULA ao redor do QR (o QR não preenche mais a célula
    # inteira, ver comentário da classe). Este teste também é o que trava
    # a regressão de `{% localize off %}`: sem ela, a margem medida seria
    # bem menor que o esperado.
    def test_grid_is_horizontally_centered_with_equal_margins(self):
        self._create_equipment(QR_GRID_PAGE_SIZE)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]

        leftmost_x0 = min(img["x0"] for img in images)
        rightmost_x1 = max(img["x1"] for img in images)
        left_margin = leftmost_x0
        right_margin = QR_GRID_PAGE_WIDTH_MM - rightmost_x1
        expected_margin = QR_GRID_MARGIN_HORIZONTAL_MM + self.CELL_MARGIN_HORIZONTAL_MM  # 13 + 12 = 25mm

        self.assertAlmostEqual(left_margin, right_margin, places=1, msg="Margem esquerda e direita devem ser idênticas — grade centralizada.")
        self.assertAlmostEqual(left_margin, expected_margin, places=1)
        self.assertAlmostEqual(left_margin, 25.0, places=1)
        self.assertGreater(left_margin, 1.0, "Se a margem for ~0mm, a grade voltou a ficar colada na borda esquerda (bug antigo).")

    # 11. Margem vertical (topo/base) medida a partir do QR = margem da
    # página + folga vertical da célula; grade 184×250mm — os números da
    # padronização física, confirmados direto do PDF.
    def test_grid_and_vertical_margins_match_the_requested_layout(self):
        self._create_equipment(QR_GRID_PAGE_SIZE)
        pdf_bytes = self._download()
        images = self._images_by_page(pdf_bytes)[0]

        top_margin = min(img["top"] for img in images)
        bottom_margin = QR_GRID_PAGE_HEIGHT_MM - max(img["bottom"] for img in images)
        expected_margin = QR_GRID_MARGIN_VERTICAL_MM + self.CELL_MARGIN_VERTICAL_MM  # 23.5 + 2 = 25.5mm

        self.assertAlmostEqual(top_margin, expected_margin, places=1)
        self.assertAlmostEqual(top_margin, 25.5, places=1)
        self.assertAlmostEqual(bottom_margin, 25.5, places=1)
        self.assertAlmostEqual(QR_GRID_WIDTH_MM, 184.0, places=1)
        self.assertAlmostEqual(QR_GRID_HEIGHT_MM, 250.0, places=1)
        self.assertAlmostEqual(QR_GRID_MARGIN_HORIZONTAL_MM, 13.0, places=1)
        self.assertAlmostEqual(QR_GRID_MARGIN_VERTICAL_MM, 23.5, places=1)

    # 12. Nenhuma página extra/branca para um lote que fecha exatamente
    # em páginas cheias (18, 36).
    def test_no_extra_blank_page_for_exact_multiples_of_page_size(self):
        for quantity, expected_pages in ((QR_GRID_PAGE_SIZE, 1), (QR_GRID_PAGE_SIZE * 2, 2)):
            with self.subTest(quantity=quantity):
                model = EquipmentModel.objects.create(category=self.category, name=f"Exato {quantity}", code=f"EXATO{quantity}")
                for _ in range(quantity):
                    create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.creator))
                self.client.login(username="qrgridfisico_admin", password="senha-forte-123")
                response = self.client.get(f"/qrcodes/modelo/{model.pk}/qrcodes.pdf")
                reader = PdfReader(io.BytesIO(response.content))
                self.assertEqual(len(reader.pages), expected_pages)

    # 13. Múltiplas páginas para lotes que passam de um múltiplo exato —
    # mesmo raciocínio dos exemplos originais do pedido (um a mais que
    # fecha página, outro que passa de duas), reescalados para o novo
    # tamanho de página (18 por folha, era 15).
    def test_multiple_pages_for_batches_past_a_full_page(self):
        for quantity, expected_pages in ((QR_GRID_PAGE_SIZE + 1, 2), (QR_GRID_PAGE_SIZE * 2 + 1, 3)):
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
        # diferentes por ter menos itens. A posição do QR é a margem da
        # página + a folga da célula ao redor dele (ver comentário da
        # classe — o QR não preenche mais a célula inteira).
        self.assertAlmostEqual(row1[0]["x0"], QR_GRID_MARGIN_HORIZONTAL_MM + self.CELL_MARGIN_HORIZONTAL_MM, places=1)
        self.assertAlmostEqual(row1[0]["top"], QR_GRID_MARGIN_VERTICAL_MM + self.CELL_MARGIN_VERTICAL_MM, places=1)
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
