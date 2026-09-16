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
    QR_GRID_COLUMNS,
    QR_GRID_PAGE_SIZE,
    QR_GRID_ROWS,
    equipment_url,
    generate_qr_png,
)

User = get_user_model()


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

    def _url(self, model_id):
        return f"/qrcodes/modelo/{model_id}/qrcodes.pdf"

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
