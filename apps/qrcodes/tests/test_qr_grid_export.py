"""
Testes da exportação em lote de QR Codes PUROS em PDF —
`qrcodes:model_qr_grid` / `ModelQRGridDownloadView`.

CORREÇÃO de 23/09/2026 (a mais recente, a que este arquivo documenta com
mais detalhe): a grade A4 (`generate_qr_grid_pdf`, 3×6 QRs por folha)
imprimia errado na prática — adesivo alimentado folha a folha, sem o
operador desabilitar "ajustar à página" no driver, saía cortado. A view
passou a entregar um PDF MULTIPÁGINA (`generate_qr_batch_pdf`) onde CADA
página é 1 adesivo físico inteiro (60×40mm) com 1 QR centralizado — o
mesmo conceito de impressão que já funciona em `generate_labels_pdf`/
`generate_square_labels_pdf`. Nome da URL/view/arquivo (`model_qr_grid`/
`ModelQRGridDownloadView`/`qrcodes-{code}.pdf`) mantido de propósito (ver
`apps/qrcodes/services.py` para o raciocínio completo).

`generate_qr_grid_pdf`/`templates/qrcodes/qr_grid.html` continuam no
código (não foram removidos, só deixaram de ser o que esta view entrega)
— cobertos diretamente, sem passar por nenhuma view/URL, em
`LegacyQrGridServiceStillWorksTest` no fim deste arquivo.

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
    QR_BATCH_HEIGHT_MM,
    QR_BATCH_QR_SIZE_MM,
    QR_BATCH_WIDTH_MM,
    QR_GRID_CELL_HEIGHT_MM,
    QR_GRID_CELL_WIDTH_MM,
    QR_GRID_COLUMNS,
    QR_GRID_GUTTER_MM,
    QR_GRID_PAGE_HEIGHT_MM,
    QR_GRID_PAGE_SIZE,
    QR_GRID_PAGE_WIDTH_MM,
    QR_GRID_QR_SIZE_MM,
    QR_GRID_ROWS,
    equipment_url,
    generate_qr_batch_pdf,
    generate_qr_grid_pdf,
    generate_qr_png,
)

User = get_user_model()

# Pontos por milímetro (1 polegada = 72pt = 25.4mm) — usado para converter
# as coordenadas em pontos que pdfplumber/pypdf reportam para milímetros,
# a mesma unidade em que o requisito físico (60×40mm, margens) foi
# especificado. Medir em mm direto do PDF (não do screenshot rasterizado)
# é o que garante que a confirmação é objetiva, não visual/"a olho".
PT_PER_MM = 72 / 25.4


class ModelQRGridDownloadViewTest(TestCase):
    """
    QR Codes puros em lote por modelo, um PDF multipágina (1 página = 1
    adesivo) — mesmo escopo/permissão de `qrcodes:model_label_batch`
    (`ModelLabelBatchDownloadView`), reaproveitados sem duplicação de
    lógica.
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

    # 8. N equipamentos SEMPRE geram um PDF de EXATAMENTE N páginas — o
    # exemplo literal do pedido de correção ("se forem 26 equipamentos, o
    # PDF deve ter 26 páginas"). Diferente da grade antiga (que só
    # cresceria de página a cada 18 itens), aqui não existe "página
    # cheia": cada equipamento é sempre a sua própria página.
    def test_n_equipment_produces_a_pdf_with_exactly_n_pages(self):
        big_model = EquipmentModel.objects.create(category=self.category, name="Grande", code="GRANDE1")
        creator = User.objects.first()
        total = 26  # o próprio exemplo numérico do pedido de correção
        equipments = [create_equipment(NewEquipmentData(model_id=big_model.pk, created_by=creator)) for _ in range(total)]

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(big_model.pk))
        self.assertEqual(response.status_code, 200)
        reader = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(reader.pages), total, "26 equipamentos devem gerar um PDF de exatamente 26 páginas.")
        total_images = self._unique_image_count(response.content)
        self.assertEqual(total_images, total, "1 QR por equipamento, nenhum a mais nem a menos.")
        self.assertEqual(len(equipments), total)

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
    # explícita da view (`order_by("patrimonio")`); com o PDF multipágina,
    # a ordem de leitura é literalmente a ordem das páginas (página 1 =
    # 1º patrimônio, página 2 = 2º, etc.).
    #
    # Usa `pdfplumber` (não `pypdf.page.images`) para decidir qual imagem
    # pertence a qual página: o WeasyPrint compartilha o `/Resources`
    # entre páginas, então `pypdf` pode listar a MESMA imagem em várias
    # páginas mesmo quando ela só é desenhada numa (mesma ressalva já
    # documentada em `_decode_all_qrs` acima) — `pdfplumber` lê o que
    # realmente foi desenhado no content stream de cada página.
    def test_deterministic_order_by_patrimonio(self):
        ordered_model = EquipmentModel.objects.create(category=self.category, name="Ordenado", code="ORD1")
        creator = User.objects.first()
        equipments = [create_equipment(NewEquipmentData(model_id=ordered_model.pk, created_by=creator)) for _ in range(4)]
        expected_order = [eq.patrimonio for eq in sorted(equipments, key=lambda e: e.patrimonio)]

        self.client.login(username="qrgrid_admin", password="senha-forte-123")
        response = self.client.get(self._url(ordered_model.pk))
        reader = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(reader.pages), 4, "1 página por equipamento — ordem = ordem das páginas.")

        # `pypdf` nomeia cada imagem com sufixo de extensão (ex.:
        # "i0f5....png"), `pdfplumber` reporta o mesmo nome sem ele —
        # normaliza removendo o sufixo antes de cruzar os dois.
        all_images = {img.name.rsplit(".", 1)[0]: img.data for page in reader.pages for img in page.images}
        page_order = []
        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            for page in pdf.pages:
                self.assertEqual(len(page.images), 1, "Cada página deve conter exatamente 1 QR.")
                image_name = page.images[0]["name"]
                decoded = decode(Image.open(io.BytesIO(all_images[image_name])))
                self.assertEqual(len(decoded), 1)
                url = decoded[0].data.decode()
                page_order.append(url.rstrip("/").rsplit("/", 1)[-1])
        self.assertEqual(page_order, expected_order, "A página N deve corresponder ao N-ésimo patrimônio na ordenação.")

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

    # 14. Nome de arquivo amigável, mantido igual à convenção já usada
    # antes da correção (`qrcodes-{code}.pdf`) — só o CONTEÚDO do PDF
    # mudou, nunca o nome do arquivo entregue.
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


class ModelQRBatchPhysicalDimensionsTest(TestCase):
    """
    Validação física (via `pdfplumber` direto no conteúdo do PDF, em
    milímetros — nunca só "olhando" um screenshot) do formato adotado na
    CORREÇÃO de 23/09/2026: cada página do PDF passou a ser, literalmente,
    1 adesivo (`QR_BATCH_WIDTH_MM` × `QR_BATCH_HEIGHT_MM` = 60×40mm, o
    MESMO canvas físico único das etiquetas), com o QR
    (`QR_BATCH_QR_SIZE_MM` = 36mm, sempre quadrado) centralizado dentro
    dela — nunca mais uma folha A4 com várias colunas.

    Substitui a antiga `ModelQRGridPhysicalDimensionsTest`: os conceitos
    de "grade" (colunas/linhas, gutter entre células, página cheia de 18
    itens, página parcial preenchendo em ordem de leitura) deixaram de
    existir no formato entregue por esta view — não fazem mais sentido
    como asserção, porque o objeto que eles mediam (uma folha A4 com
    várias células) não é mais o que é gerado aqui. O requisito físico
    real que eles protegiam (QR centralizado, com folga simétrica,
    tamanho exato, sem corte) continua coberto abaixo, só que por página
    individual em vez de por célula de grade. A cobertura equivalente
    para a grade A4 antiga (ainda no código, só não usada por esta view)
    está em `LegacyQrGridServiceStillWorksTest`, no fim deste arquivo.
    """

    # Folga entre a borda do QR e a borda da página/adesivo que o contém
    # — o que sobra da página (60×40mm) depois do QR (36×36mm),
    # distribuído igualmente nos dois lados de cada eixo. Mesma conta da
    # grade antiga (por isso QR_BATCH_QR_SIZE_MM == QR_GRID_QR_SIZE_MM de
    # propósito, ver apps/qrcodes/services.py).
    MARGIN_HORIZONTAL_MM = (QR_BATCH_WIDTH_MM - QR_BATCH_QR_SIZE_MM) / 2  # 12.0
    MARGIN_VERTICAL_MM = (QR_BATCH_HEIGHT_MM - QR_BATCH_QR_SIZE_MM) / 2  # 2.0

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        creator = User.objects.create_user(username="cadastrador_qrbatch_fisico", password="senha-forte-123")
        self.creator = creator
        User.objects.create_user(username="qrbatchfisico_admin", password="senha-forte-123", role=Role.ADMIN)

    def _create_equipment(self, quantity):
        return [create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.creator)) for _ in range(quantity)]

    def _download(self):
        self.client.login(username="qrbatchfisico_admin", password="senha-forte-123")
        response = self.client.get(f"/qrcodes/modelo/{self.model.pk}/qrcodes.pdf")
        self.assertEqual(response.status_code, 200)
        return response.content

    def _measure_pages(self, pdf_bytes):
        """
        Para cada página: dimensão da própria página e posição/tamanho
        (em mm) da única imagem de QR nela — assume 1 imagem por página,
        confirmado por outro teste (`test_each_page_has_exactly_one_qr`).
        """
        measurements = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                images = page.images
                self.assertEqual(len(images), 1, "Cada página deve conter exatamente 1 imagem (o QR).")
                im = images[0]
                measurements.append(
                    {
                        "page_width": page.width / PT_PER_MM,
                        "page_height": page.height / PT_PER_MM,
                        "x0": im["x0"] / PT_PER_MM,
                        "x1": im["x1"] / PT_PER_MM,
                        "top": im["top"] / PT_PER_MM,
                        "bottom": im["bottom"] / PT_PER_MM,
                    }
                )
        return measurements

    # 1. Cada página mede exatamente 60×40mm — nunca A4, em nenhuma
    # página do lote (testado com várias páginas, não só a primeira).
    def test_every_page_measures_60x40mm(self):
        self.assertEqual(QR_BATCH_WIDTH_MM, 60)
        self.assertEqual(QR_BATCH_HEIGHT_MM, 40)
        self._create_equipment(5)
        pages = self._measure_pages(self._download())
        self.assertEqual(len(pages), 5)
        for page in pages:
            self.assertAlmostEqual(page["page_width"], 60.0, places=1)
            self.assertAlmostEqual(page["page_height"], 40.0, places=1)

    # 2. Cada página contém exatamente 1 imagem — reforça a suposição de
    # `_measure_pages` de forma independente/explícita.
    def test_each_page_has_exactly_one_qr(self):
        self._create_equipment(3)
        with pdfplumber.open(io.BytesIO(self._download())) as pdf:
            self.assertEqual(len(pdf.pages), 3)
            for page in pdf.pages:
                self.assertEqual(len(page.images), 1)

    # 3. Cada QR mede EXATAMENTE 36×36mm, em toda página — nunca a
    # página inteira, nunca deformado.
    def test_each_qr_image_is_exactly_36x36mm(self):
        self.assertEqual(QR_BATCH_QR_SIZE_MM, 36, "O QR de cada página deve ser exatamente 36mm.")
        self._create_equipment(5)
        pages = self._measure_pages(self._download())
        for page in pages:
            self.assertAlmostEqual(page["x1"] - page["x0"], 36.0, places=1, msg="Largura do QR deve ser exatamente 36mm.")
            self.assertAlmostEqual(page["bottom"] - page["top"], 36.0, places=1, msg="Altura do QR deve ser exatamente 36mm.")

    # 4. O QR fica CENTRALIZADO em cada página — margem esquerda = margem
    # direita = 12mm, margem superior = margem inferior = 2mm — calculado
    # matematicamente (nunca "no olho"), em toda página do lote.
    def test_qr_is_centered_on_every_page_with_symmetric_margins(self):
        self._create_equipment(5)
        pages = self._measure_pages(self._download())
        for page in pages:
            left_margin = page["x0"]
            right_margin = page["page_width"] - page["x1"]
            top_margin = page["top"]
            bottom_margin = page["page_height"] - page["bottom"]

            self.assertAlmostEqual(left_margin, right_margin, places=1, msg="Margem esquerda e direita devem ser idênticas — QR centralizado.")
            self.assertAlmostEqual(top_margin, bottom_margin, places=1, msg="Margem superior e inferior devem ser idênticas — QR centralizado.")
            self.assertAlmostEqual(left_margin, self.MARGIN_HORIZONTAL_MM, places=1)
            self.assertAlmostEqual(top_margin, self.MARGIN_VERTICAL_MM, places=1)

    # 5. N equipamentos => N páginas, sempre — testado com um N que não é
    # múltiplo de nada "especial" (nem 18, nem 15), porque essa noção de
    # "página cheia" não existe mais neste formato.
    def test_n_equipment_produces_n_pages(self):
        for quantity in (1, 4, 26):
            with self.subTest(quantity=quantity):
                model = EquipmentModel.objects.create(category=self.category, name=f"Qtd {quantity}", code=f"QTD{quantity}")
                for _ in range(quantity):
                    create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.creator))
                self.client.login(username="qrbatchfisico_admin", password="senha-forte-123")
                response = self.client.get(f"/qrcodes/modelo/{model.pk}/qrcodes.pdf")
                reader = PdfReader(io.BytesIO(response.content))
                self.assertEqual(len(reader.pages), quantity)

    # 6. O QR continua decodificando corretamente para a URL certa — a
    # correção de formato não pode ter afetado o conteúdo/leitura do QR.
    def test_qr_still_decodes_to_the_correct_url_after_the_fix(self):
        equipment = self._create_equipment(1)[0]
        pdf_bytes = self._download()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        embedded = list(reader.pages[0].images)
        self.assertEqual(len(embedded), 1)
        decoded = decode(Image.open(io.BytesIO(embedded[0].data)))
        self.assertEqual(len(decoded), 1)
        self.assertEqual(decoded[0].data.decode(), equipment_url(equipment))

    # 7. Continua sem nenhum texto — QR puro, mesmo depois da correção de
    # formato (nenhuma legenda/borda/patrimônio foi introduzido).
    def test_still_no_text_content_after_the_fix(self):
        self._create_equipment(3)
        pdf_bytes = self._download()
        reader = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "".join(page.extract_text() for page in reader.pages).strip()
        self.assertEqual(full_text, "")

    # 8. A correção de formato não altera nenhum registro — continua
    # 100% leitura.
    def test_fix_does_not_alter_any_equipment_record(self):
        equipment_list = self._create_equipment(3)
        before = list(Equipment.objects.filter(pk__in=[e.pk for e in equipment_list]).order_by("pk").values())
        self._download()
        after = list(Equipment.objects.filter(pk__in=[e.pk for e in equipment_list]).order_by("pk").values())
        self.assertEqual(before, after)


class ModelQRGridThemeTest(TestCase):
    """
    Tema Claro/Escuro: "Exportar QR Codes em PDF" reaproveita o MESMO
    modal/`?tema=` já usado por "Etiquetas em lote" — nenhum modal novo,
    nenhuma validação de tema nova (`_validated_theme`, a mesma função de
    sempre), preservado sem alteração pela correção de 23/09/2026. Só o
    FUNDO da página muda; o QR em si nunca é invertido, e a geometria
    física (posição/tamanho/margem) tem que continuar idêntica nos dois
    temas.
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

    # 4. A geometria física (posição/tamanho do QR em cada página) é
    # IDÊNTICA nos dois temas — o tema muda só o fundo, nunca o
    # layout/dimensionamento.
    def test_physical_geometry_is_identical_regardless_of_theme(self):
        self._create_equipment(4)
        light_bytes = self._get(tema="light").content
        dark_bytes = self._get(tema="dark").content

        def measure(pdf_bytes):
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                result = []
                for page in pdf.pages:
                    im = page.images[0]
                    result.append(
                        (
                            round(im["x0"] / PT_PER_MM, 2),
                            round(im["top"] / PT_PER_MM, 2),
                            round((im["x1"] - im["x0"]) / PT_PER_MM, 2),
                            round((im["bottom"] - im["top"]) / PT_PER_MM, 2),
                        )
                    )
                return result

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

    # 9. `generate_qr_batch_pdf` sozinha (sem o client HTTP) também aceita
    # os dois temas nomeados via constante — reforça que a função de
    # serviço, não só a view, suporta o parâmetro.
    def test_service_function_accepts_both_theme_constants(self):
        equipment_list = self._create_equipment(2)
        light_pdf = generate_qr_batch_pdf(equipment_list, theme=LABEL_THEME_LIGHT)
        dark_pdf = generate_qr_batch_pdf(equipment_list, theme=LABEL_THEME_DARK)
        self.assertTrue(light_pdf.startswith(b"%PDF"))
        self.assertTrue(dark_pdf.startswith(b"%PDF"))
        self.assertNotEqual(light_pdf, dark_pdf)


class LegacyQrGridServiceStillWorksTest(TestCase):
    """
    `generate_qr_grid_pdf` (grade A4, 3×6 QRs por folha) NÃO foi removida
    pela correção de 23/09/2026 — só deixou de ser o que
    `ModelQRGridDownloadView` entrega (ver módulo/classes acima e
    `apps/qrcodes/services.py`). Fica disponível para reuso futuro,
    mantida com uma cobertura direta mínima (mesmo precedente já usado
    neste projeto para `generate_qr_zip`, que ficou "órfã" por um tempo
    sem deixar de ter teste — ver docs/apps/qrcodes.md, "Pontos
    importantes"). Chamada direta da função de serviço, sem passar por
    nenhuma view/URL — não existe mais nenhuma rota que a use.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.creator = User.objects.create_user(username="cadastrador_qrgrid_legado", password="senha-forte-123")

    def _create_equipment(self, quantity):
        return [create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.creator)) for _ in range(quantity)]

    def test_still_produces_an_a4_grid_of_18_per_page(self):
        self.assertEqual(QR_GRID_COLUMNS, 3)
        self.assertEqual(QR_GRID_ROWS, 6)
        self.assertEqual(QR_GRID_PAGE_SIZE, 18)
        self.assertEqual(QR_GRID_CELL_WIDTH_MM, 60)
        self.assertEqual(QR_GRID_CELL_HEIGHT_MM, 40)
        self.assertEqual(QR_GRID_QR_SIZE_MM, 36)

        equipment_list = self._create_equipment(QR_GRID_PAGE_SIZE + 1)
        pdf_bytes = generate_qr_grid_pdf(equipment_list, theme=LABEL_THEME_LIGHT)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            self.assertEqual(len(pdf.pages), 2, "19 itens devem gerar 2 páginas de grade (18 + 1).")
            page = pdf.pages[0]
            self.assertAlmostEqual(page.width / PT_PER_MM, QR_GRID_PAGE_WIDTH_MM, places=1)
            self.assertAlmostEqual(page.height / PT_PER_MM, QR_GRID_PAGE_HEIGHT_MM, places=1)
            self.assertEqual(len(page.images), QR_GRID_PAGE_SIZE)
            first_image = sorted(page.images, key=lambda im: (round(im["top"], 1), round(im["x0"], 1)))[0]
            self.assertAlmostEqual((first_image["x1"] - first_image["x0"]) / PT_PER_MM, 36.0, places=1)

    def test_still_decodes_correctly_and_accepts_both_themes(self):
        equipment_list = self._create_equipment(2)
        light_pdf = generate_qr_grid_pdf(equipment_list, theme=LABEL_THEME_LIGHT)
        dark_pdf = generate_qr_grid_pdf(equipment_list, theme=LABEL_THEME_DARK)
        self.assertTrue(light_pdf.startswith(b"%PDF"))
        self.assertTrue(dark_pdf.startswith(b"%PDF"))
        self.assertNotEqual(light_pdf, dark_pdf)

        reader = PdfReader(io.BytesIO(light_pdf))
        decoded_urls = set()
        for page in reader.pages:
            for img in page.images:
                decoded = decode(Image.open(io.BytesIO(img.data)))
                self.assertEqual(len(decoded), 1)
                decoded_urls.add(decoded[0].data.decode())
        self.assertEqual(decoded_urls, {equipment_url(eq) for eq in equipment_list})
