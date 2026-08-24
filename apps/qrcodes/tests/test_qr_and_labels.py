"""
Testes de QR Code, código de barras, etiqueta e exportações em lote —
especificação, seção 14, e o pedido de sistema de etiquetas patrimoniais.

O ponto mais importante aqui não é "o PNG/PDF/ZIP foi gerado" — é que a
URL codificada no QR é a permanente correta, que o código de barras
decodifica exatamente para o mesmo `patrimonio`, que a estrutura de
pastas dentro dos .zip é a exigida, que só equipamento ativo entra nas
exportações em lote, e que o download dessas rotas respeita a matriz de
permissões (seção 11: Administrador/Administrativo).
"""

import io
import os
import zipfile

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.qrcodes.services import (
    LABEL_HEIGHT_MM,
    LABEL_WIDTH_MM,
    _sanitize_path_segment,
    equipment_url,
    generate_barcode_png,
    generate_label_pdf,
    generate_labels_zip,
    generate_qr_png,
    generate_qr_zip,
)

User = get_user_model()

MM_TO_PT = 2.834645669


class QRServiceTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        user = User.objects.create_user(username="cadastrador", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=user))

    def test_equipment_url_is_permanent_and_uses_site_base_url(self):
        url = equipment_url(self.equipment)
        self.assertEqual(url, f"{settings.SITE_BASE_URL}/equipamentos/{self.equipment.patrimonio}/")

    def test_generate_qr_png_returns_valid_png(self):
        png_bytes = generate_qr_png(self.equipment)
        self.assertTrue(png_bytes.startswith(b"\x89PNG"), "Não parece um PNG válido.")

    def test_qr_decodes_to_the_permanent_equipment_url(self):
        """
        Não basta o PNG ser válido — o conteúdo do QR precisa ser
        exatamente a URL permanente do patrimônio (seção 14: "O QR NÃO
        armazenará informações adicionais. A URL identifica o
        equipamento."). Decodificamos de verdade em vez de confiar que
        `generate_qr_png` fez a coisa certa.
        """
        import io

        from PIL import Image
        from pyzbar.pyzbar import decode

        png_bytes = generate_qr_png(self.equipment)
        decoded = decode(Image.open(io.BytesIO(png_bytes)))

        self.assertEqual(len(decoded), 1, "QR deveria conter exatamente um código.")
        self.assertEqual(decoded[0].data.decode(), equipment_url(self.equipment))

    def test_generate_label_pdf_returns_valid_pdf(self):
        pdf_bytes = generate_label_pdf(self.equipment)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"), "Não parece um PDF válido.")


class BarcodeServiceTest(TestCase):
    """Código de barras (Code128) representando o patrimônio — seção 1 do pedido."""

    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        user = User.objects.create_user(username="cadastrador_barcode", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=user))

    def test_generate_barcode_png_returns_valid_png(self):
        png_bytes = generate_barcode_png(self.equipment)
        self.assertTrue(png_bytes.startswith(b"\x89PNG"), "Não parece um PNG válido.")

    def test_barcode_decodes_to_the_patrimonio(self):
        """
        O código de barras precisa representar exatamente o mesmo
        `patrimonio` do QR e do texto grande da etiqueta — nenhum
        identificador novo, nenhuma reinterpretação.
        """
        from PIL import Image
        from pyzbar.pyzbar import decode

        png_bytes = generate_barcode_png(self.equipment)
        decoded = decode(Image.open(io.BytesIO(png_bytes)))

        self.assertEqual(len(decoded), 1, "Código de barras deveria conter exatamente um código.")
        self.assertEqual(decoded[0].type, "CODE128")
        self.assertEqual(decoded[0].data.decode(), self.equipment.patrimonio)


class LabelPdfContentTest(TestCase):
    """Conteúdo e dimensões físicas da etiqueta individual — seção 1 do pedido."""

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="NI23 Big Tank", code="NI23BT")
        user = User.objects.create_user(username="cadastrador_label", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=user))

    def _read_pdf(self, pdf_bytes: bytes):
        from pypdf import PdfReader

        return PdfReader(io.BytesIO(pdf_bytes))

    def test_label_pdf_shows_the_patrimonio_in_text(self):
        """
        O patrimônio precisa estar no PDF como texto real (extraível),
        não só "escondido" dentro da imagem do QR/código de barras —
        senão não seria de fato "escrito em destaque, legível" (seção 1).
        """
        pdf_bytes = generate_label_pdf(self.equipment)
        reader = self._read_pdf(pdf_bytes)
        text = reader.pages[0].extract_text()
        self.assertIn(self.equipment.patrimonio, text)

    def test_label_pdf_has_the_configured_physical_dimensions(self):
        """
        100×50mm por padrão, mas lido de `LABEL_WIDTH_MM`/`LABEL_HEIGHT_MM`
        (não um número mágico duplicado aqui) — é exatamente essa
        configurabilidade centralizada que a seção 1 do pedido exige.
        """
        pdf_bytes = generate_label_pdf(self.equipment)
        reader = self._read_pdf(pdf_bytes)
        box = reader.pages[0].mediabox

        self.assertAlmostEqual(float(box.width) / MM_TO_PT, LABEL_WIDTH_MM, places=1)
        self.assertAlmostEqual(float(box.height) / MM_TO_PT, LABEL_HEIGHT_MM, places=1)

    def test_label_pdf_is_a_single_page(self):
        pdf_bytes = generate_label_pdf(self.equipment)
        reader = self._read_pdf(pdf_bytes)
        self.assertEqual(len(reader.pages), 1)


class PathSanitizationTest(TestCase):
    """Sanitização dos nomes de pasta/arquivo dentro dos .zip de exportação."""

    def test_valid_name_is_kept_as_is(self):
        self.assertEqual(_sanitize_path_segment("Aquecedor", fallback="X"), "Aquecedor")

    def test_slash_is_removed_not_turned_into_a_subfolder(self):
        result = _sanitize_path_segment("Aquecedor/Resistência", fallback="X")
        self.assertNotIn("/", result)

    def test_directory_traversal_attempt_is_neutralized(self):
        result = _sanitize_path_segment("../../etc", fallback="X")
        self.assertNotIn("..", result)
        self.assertNotIn("/", result)

    def test_bare_dot_or_dotdot_falls_back(self):
        self.assertEqual(_sanitize_path_segment(".", fallback="FALLBACK"), "FALLBACK")
        self.assertEqual(_sanitize_path_segment("..", fallback="FALLBACK"), "FALLBACK")

    def test_empty_after_sanitizing_falls_back(self):
        result = _sanitize_path_segment("   ///   ", fallback="FALLBACK")
        self.assertEqual(result, "FALLBACK")

    def test_repeated_separators_collapse(self):
        result = _sanitize_path_segment("A//B  C", fallback="X")
        self.assertNotIn("__", result)


class BatchZipServiceTest(TestCase):
    """
    Geração dos .zip em si (nível de serviço, sem passar pela view/
    permissão) — estrutura de pastas, múltiplos equipamentos/modelos, e a
    garantia de que nada é gravado em disco.
    """

    def setUp(self):
        self.climatizadores = Category.objects.create(name="Climatizador")
        self.aquecedores = Category.objects.create(name="Aquecedor")
        self.model_ni23bt = EquipmentModel.objects.create(
            category=self.climatizadores, name="NI23 Big Tank", code="NI23BT"
        )
        self.model_9pro = EquipmentModel.objects.create(category=self.climatizadores, name="9 Pro", code="9PRO")
        self.model_aqcp = EquipmentModel.objects.create(category=self.aquecedores, name="Pirâmide", code="AQCP")
        user = User.objects.create_user(username="cadastrador_zip", password="senha-forte-123")

        self.eq1 = create_equipment(NewEquipmentData(model_id=self.model_ni23bt.pk, created_by=user))
        self.eq2 = create_equipment(NewEquipmentData(model_id=self.model_9pro.pk, created_by=user))
        self.eq3 = create_equipment(NewEquipmentData(model_id=self.model_aqcp.pk, created_by=user))
        self.equipment_list = [self.eq1, self.eq2, self.eq3]

    def test_generate_qr_zip_returns_a_valid_zip_of_pngs(self):
        zip_bytes = generate_qr_zip(self.equipment_list)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            self.assertIsNone(zf.testzip(), "Um ou mais arquivos do .zip estão corrompidos.")
            names = set(zf.namelist())
            self.assertEqual(
                names,
                {
                    f"Climatizador/NI23BT/{self.eq1.patrimonio}.png",
                    f"Climatizador/9PRO/{self.eq2.patrimonio}.png",
                    f"Aquecedor/AQCP/{self.eq3.patrimonio}.png",
                },
            )
            for name in names:
                self.assertTrue(zf.read(name).startswith(b"\x89PNG"))

    def test_generate_labels_zip_returns_a_valid_zip_of_single_page_pdfs(self):
        zip_bytes = generate_labels_zip(self.equipment_list)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            self.assertIsNone(zf.testzip())
            names = set(zf.namelist())
            self.assertEqual(
                names,
                {
                    f"Climatizador/NI23BT/{self.eq1.patrimonio}.pdf",
                    f"Climatizador/9PRO/{self.eq2.patrimonio}.pdf",
                    f"Aquecedor/AQCP/{self.eq3.patrimonio}.pdf",
                },
            )
            from pypdf import PdfReader

            for name in names:
                pdf_bytes = zf.read(name)
                self.assertTrue(pdf_bytes.startswith(b"%PDF"))
                reader = PdfReader(io.BytesIO(pdf_bytes))
                self.assertEqual(len(reader.pages), 1)

    def test_zip_generation_does_not_write_files_to_disk(self):
        """
        Requisito explícito do pedido: nada pode ser persistido no
        servidor (o disco do Free tier da Render é efêmero). Como as
        funções retornam `bytes` puros (não um caminho de arquivo nem um
        `FieldFile`), e comparamos o conteúdo de MEDIA_ROOT antes/depois
        para garantir que nenhum arquivo novo apareceu lá.
        """
        media_root = settings.MEDIA_ROOT
        before = set()
        if os.path.isdir(media_root):
            before = {os.path.join(dirpath, name) for dirpath, _, files in os.walk(media_root) for name in files}

        qr_zip = generate_qr_zip(self.equipment_list)
        labels_zip = generate_labels_zip(self.equipment_list)

        self.assertIsInstance(qr_zip, bytes)
        self.assertIsInstance(labels_zip, bytes)

        after = set()
        if os.path.isdir(media_root):
            after = {os.path.join(dirpath, name) for dirpath, _, files in os.walk(media_root) for name in files}
        self.assertEqual(before, after, "A geração dos .zip não deveria criar nenhum arquivo em MEDIA_ROOT.")


class QRDownloadPermissionTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        creator = User.objects.create_user(username="cadastrador2", password="senha-forte-123")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))

        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"qr_{role.lower()}", password="senha-forte-123", role=role)

    def _qr_url(self):
        return f"/qrcodes/{self.equipment.patrimonio}/qr.png"

    def _label_url(self):
        return f"/qrcodes/{self.equipment.patrimonio}/etiqueta.pdf"

    def test_admin_and_administrativo_can_download(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO):
            with self.subTest(role=role):
                self.client.login(username=f"qr_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._qr_url())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                self.client.logout()

    def test_operacional_and_consulta_are_forbidden(self):
        for role in (Role.OPERACIONAL, Role.CONSULTA):
            with self.subTest(role=role):
                self.client.login(username=f"qr_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._qr_url())
                self.assertEqual(response.status_code, 403)
                self.client.logout()

    def test_label_pdf_download(self):
        self.client.login(username="qr_admin", password="senha-forte-123")
        response = self.client.get(self._label_url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")


class LabelBatchDownloadViewTest(TestCase):
    """
    Ação pré-existente "Baixar etiquetas em PDF (lote)" do admin
    (`apps/equipment/admin.py`) — não fazia parte do pedido desta rodada,
    mas usa a mesma `generate_labels_pdf`/`templates/qrcodes/label.html`
    que foram redesenhadas aqui, então precisa continuar funcionando:
    uma página por patrimônio informado, no tamanho físico configurado.
    """

    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Torre", code="AQCT")
        creator = User.objects.create_user(username="cadastrador_batch_pdf", password="senha-forte-123")
        self.eq1 = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))
        self.eq2 = create_equipment(NewEquipmentData(model_id=model.pk, created_by=creator))
        User.objects.create_user(username="batch_pdf_admin", password="senha-forte-123", role=Role.ADMIN)

    def test_batch_pdf_has_one_page_per_patrimonio_at_the_configured_size(self):
        from pypdf import PdfReader

        self.client.login(username="batch_pdf_admin", password="senha-forte-123")
        url = f"/qrcodes/lote/etiquetas.pdf?patrimonio={self.eq1.patrimonio}&patrimonio={self.eq2.patrimonio}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")

        reader = PdfReader(io.BytesIO(response.content))
        self.assertEqual(len(reader.pages), 2)
        for page in reader.pages:
            self.assertAlmostEqual(float(page.mediabox.width) / MM_TO_PT, LABEL_WIDTH_MM, places=1)
            self.assertAlmostEqual(float(page.mediabox.height) / MM_TO_PT, LABEL_HEIGHT_MM, places=1)


class BatchZipViewTest(TestCase):
    """
    As duas rotas de exportação em lote (`qrcodes:qr_zip` e
    `qrcodes:label_zip`) — permissões, múltiplos equipamentos/modelos e
    exclusão de equipamento inativo, tudo através do client HTTP de
    verdade (não chamando o serviço direto), igual ao resto da suíte de
    permissões do projeto.
    """

    def setUp(self):
        self.category = Category.objects.create(name="Climatizador")
        self.model_a = EquipmentModel.objects.create(category=self.category, name="NI23 Big Tank", code="NI23BT")
        self.model_b = EquipmentModel.objects.create(category=self.category, name="9 Pro", code="9PRO")
        creator = User.objects.create_user(username="cadastrador_zip_view", password="senha-forte-123")

        self.active_a = create_equipment(NewEquipmentData(model_id=self.model_a.pk, created_by=creator))
        self.active_b = create_equipment(NewEquipmentData(model_id=self.model_b.pk, created_by=creator))
        self.inactive = create_equipment(NewEquipmentData(model_id=self.model_a.pk, created_by=creator))
        self.inactive.is_active = False
        self.inactive.save(update_fields=["is_active"])

        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"zip_{role.lower()}", password="senha-forte-123", role=role)

    def _qr_zip_url(self):
        return "/qrcodes/lote/qr.zip"

    def _label_zip_url(self):
        return "/qrcodes/lote/etiquetas.zip"

    def _namelist(self, response) -> set:
        with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
            return set(zf.namelist())

    def test_admin_and_administrativo_can_download_qr_zip(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO):
            with self.subTest(role=role):
                self.client.login(username=f"zip_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._qr_zip_url())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/zip")
                self.client.logout()

    def test_admin_and_administrativo_can_download_labels_zip(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO):
            with self.subTest(role=role):
                self.client.login(username=f"zip_{role.lower()}", password="senha-forte-123")
                response = self.client.get(self._label_zip_url())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "application/zip")
                self.client.logout()

    def test_operacional_and_consulta_are_forbidden_from_both_zip_exports(self):
        for role in (Role.OPERACIONAL, Role.CONSULTA):
            for url in (self._qr_zip_url(), self._label_zip_url()):
                with self.subTest(role=role, url=url):
                    self.client.login(username=f"zip_{role.lower()}", password="senha-forte-123")
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 403)
                    self.client.logout()

    def test_qr_zip_includes_multiple_equipment_and_models_but_excludes_inactive(self):
        self.client.login(username="zip_admin", password="senha-forte-123")
        response = self.client.get(self._qr_zip_url())
        names = self._namelist(response)

        self.assertIn(f"Climatizador/NI23BT/{self.active_a.patrimonio}.png", names)
        self.assertIn(f"Climatizador/9PRO/{self.active_b.patrimonio}.png", names)
        self.assertNotIn(f"Climatizador/NI23BT/{self.inactive.patrimonio}.png", names)
        self.assertEqual(len(names), 2, "Só os dois equipamentos ativos deveriam estar no .zip.")

    def test_labels_zip_includes_multiple_equipment_and_models_but_excludes_inactive(self):
        self.client.login(username="zip_admin", password="senha-forte-123")
        response = self.client.get(self._label_zip_url())
        names = self._namelist(response)

        self.assertIn(f"Climatizador/NI23BT/{self.active_a.patrimonio}.pdf", names)
        self.assertIn(f"Climatizador/9PRO/{self.active_b.patrimonio}.pdf", names)
        self.assertNotIn(f"Climatizador/NI23BT/{self.inactive.patrimonio}.pdf", names)
        self.assertEqual(len(names), 2, "Só os dois equipamentos ativos deveriam estar no .zip.")
