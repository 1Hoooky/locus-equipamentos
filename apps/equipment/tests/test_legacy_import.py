"""
Testes da importação assistida da planilha legada — especificação, seção 13
(fluxo D) e seção 3. Cobrem tanto o parser puro (`legacy_import.py`, que
NUNCA grava no banco) quanto o fluxo HTTP completo (upload → revisão →
confirmação), incluindo a proteção contra duplicidade em reimportação.
"""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.equipment.legacy_import import LegacyImportError, parse_legacy_workbook
from apps.equipment.models import Equipment

User = get_user_model()

HEADER_ROW = [
    "Categoria (Categoria PAI)",
    "Categoria  (SubCategoria)",
    "Descrição Sistema",
    "SerialNumber",
    "Categoria:",
    "Descrição:",
    "Dt.Aquisicao:",
    "Valor:",
    "FORNECEDOR",
]


def _build_workbook_bytes(rows, sheet_name="TOTAL EQUIPAMENTOS", headers=HEADER_ROW):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def _uploaded_file(rows, name="legado.xlsx", **kwargs):
    content = _build_workbook_bytes(rows, **kwargs)
    return SimpleUploadedFile(
        name, content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class _InMemoryUpload:
    """Simples wrapper com `.read()`, do mesmo jeito que `request.FILES['file']` expõe."""

    def __init__(self, content: bytes):
        self._content = content

    def read(self):
        return self._content


class ParseLegacyWorkbookTest(TestCase):
    def setUp(self):
        self.climatizador = Category.objects.create(name="Climatizador")
        self.aquecedor = Category.objects.create(name="Aquecedor")
        self.model_big_tank = EquipmentModel.objects.create(
            category=self.climatizador, name="NI23 Big Tank", code="NI23BT"
        )
        self.model_torre = EquipmentModel.objects.create(
            category=self.aquecedor, name="Aquecedor Torre", code="AQCT"
        )

    def _parse(self, rows, **kwargs):
        content = _build_workbook_bytes(rows, **kwargs)
        return parse_legacy_workbook(_InMemoryUpload(content))

    def test_matches_model_from_subcategoria_text(self):
        rows = [
            ["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-001", "", "", None, "1500.00", "Fornecedor X"],
        ]
        parsed = self._parse(rows)
        self.assertEqual(len(parsed), 1)
        row = parsed[0]
        self.assertEqual(row.suggested_model_id, self.model_big_tank.pk)
        self.assertFalse(row.has_issues)

    def test_flags_missing_legacy_code(self):
        rows = [["CLIMATIZADOR", "NI23 BIG TANK", "", "", "", "", None, None, ""]]
        parsed = self._parse(rows)
        self.assertTrue(parsed[0].has_issues)
        self.assertTrue(any("código de série" in issue for issue in parsed[0].issues))

    def test_flags_duplicate_legacy_code_against_existing_equipment(self):
        creator = User.objects.create_user(username="importador1", password="senha-forte-123")
        from apps.equipment.services import NewEquipmentData, create_equipment

        create_equipment(
            NewEquipmentData(model_id=self.model_big_tank.pk, created_by=creator, legacy_code="SN-DUP")
        )

        rows = [["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-DUP", "", "", None, None, ""]]
        parsed = self._parse(rows)
        self.assertTrue(parsed[0].has_issues)
        self.assertIsNone(parsed[0].suggested_model_id)
        self.assertTrue(any("Já existe um equipamento" in issue for issue in parsed[0].issues))

    def test_unknown_category_still_offers_full_model_list_but_no_suggestion(self):
        rows = [["CATEGORIA INEXISTENTE", "ALGO", "", "SN-002", "", "", None, None, ""]]
        parsed = self._parse(rows)
        row = parsed[0]
        self.assertTrue(row.has_issues)
        self.assertIsNone(row.suggested_model_id)
        # A linha continua classificável manualmente — não fica "travada" sem opções.
        candidate_ids = {model_id for model_id, _ in row.candidate_models}
        self.assertIn(self.model_big_tank.pk, candidate_ids)
        self.assertIn(self.model_torre.pk, candidate_ids)

    def test_flags_missing_subcategoria_and_descricao(self):
        rows = [["CLIMATIZADOR", "", "", "SN-003", "", "", None, None, ""]]
        parsed = self._parse(rows)
        self.assertTrue(any("Sem subcategoria" in issue for issue in parsed[0].issues))

    def test_blank_trailing_row_is_skipped(self):
        rows = [
            ["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-004", "", "", None, None, ""],
            ["", "", "", "", "", "", None, None, ""],
        ]
        parsed = self._parse(rows)
        self.assertEqual(len(parsed), 1)

    def test_missing_sheet_raises_error(self):
        content = _build_workbook_bytes([], sheet_name="OUTRA ABA")
        with self.assertRaises(LegacyImportError):
            parse_legacy_workbook(_InMemoryUpload(content))

    def test_missing_headers_raises_error(self):
        content = _build_workbook_bytes([], headers=["Coluna Errada"])
        with self.assertRaises(LegacyImportError):
            parse_legacy_workbook(_InMemoryUpload(content))

    def test_long_free_text_description_does_not_block_short_subcategoria_match(self):
        """
        Regressão: a coluna "Descrição:" costuma ser texto livre longo. Antes
        da correção, ela tinha prioridade sobre a subcategoria curta na
        tentativa de correspondência, e um SequenceMatcher contra um nome de
        modelo curto quase sempre dava uma razão baixa — zerando as
        sugestões automáticas mesmo quando a subcategoria batia perfeitamente
        com o nome do modelo.
        """
        rows = [
            [
                "AQUECEDOR",
                "AQUECEDOR TORRE",
                "",
                "SN-005",
                "",
                (
                    "NI48TP_LOC - AQUECEDOR EXTERNO DE AMBIENTE, A GÁS, TIPO TORRE, "
                    "MODELO NI48TP, EM AÇO PRETO, POTÊNCIA 48.000BTUS"
                ),
                None,
                None,
                "",
            ]
        ]
        parsed = self._parse(rows)
        self.assertEqual(parsed[0].suggested_model_id, self.model_torre.pk)


class LegacyImportViewFlowTest(TestCase):
    def setUp(self):
        self.climatizador = Category.objects.create(name="Climatizador")
        self.model_big_tank = EquipmentModel.objects.create(
            category=self.climatizador, name="NI23 Big Tank", code="NI23BT"
        )
        self.admin = User.objects.create_user(username="importer_admin", password="senha-forte-123", role=Role.ADMIN)
        User.objects.create_user(username="importer_consulta", password="senha-forte-123", role=Role.CONSULTA)

    def test_only_admin_can_reach_upload_view(self):
        self.client.login(username="importer_consulta", password="senha-forte-123")
        response = self.client.get("/equipamentos/importar/")
        self.assertEqual(response.status_code, 403)

    def test_review_without_session_redirects_to_upload(self):
        self.client.login(username="importer_admin", password="senha-forte-123")
        response = self.client.get("/equipamentos/importar/revisar/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/equipamentos/importar/", response.url)

    def test_full_upload_review_confirm_flow_creates_equipment(self):
        self.client.login(username="importer_admin", password="senha-forte-123")

        rows = [
            ["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-100", "Geração 1", "", None, "1200.50", "Fornecedor A"],
            ["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-101", "Geração 1", "", None, "1200.50", "Fornecedor A"],
        ]
        upload_response = self.client.post("/equipamentos/importar/", {"file": _uploaded_file(rows)})
        self.assertEqual(upload_response.status_code, 302)
        self.assertIn("/equipamentos/importar/revisar/", upload_response.url)

        review_response = self.client.get("/equipamentos/importar/revisar/")
        self.assertEqual(review_response.status_code, 200)
        self.assertContains(review_response, "SN-100")
        self.assertContains(review_response, "model_0")

        confirm_response = self.client.post(
            "/equipamentos/importar/revisar/",
            {"model_0": str(self.model_big_tank.pk), "model_1": str(self.model_big_tank.pk)},
        )
        self.assertEqual(confirm_response.status_code, 302)
        self.assertIn("/equipamentos/importar/resumo/", confirm_response.url)

        self.assertEqual(Equipment.objects.filter(legacy_code__in=["SN-100", "SN-101"]).count(), 2)

        summary_response = self.client.get("/equipamentos/importar/resumo/")
        self.assertEqual(summary_response.status_code, 200)
        self.assertContains(summary_response, "2")  # created_count

    def test_blank_model_choice_skips_row_without_creating_equipment(self):
        self.client.login(username="importer_admin", password="senha-forte-123")
        rows = [["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-200", "", "", None, None, ""]]
        self.client.post("/equipamentos/importar/", {"file": _uploaded_file(rows)})
        self.client.get("/equipamentos/importar/revisar/")

        response = self.client.post("/equipamentos/importar/revisar/", {"model_0": ""})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Equipment.objects.filter(legacy_code="SN-200").exists())

    def test_confirming_already_imported_legacy_code_is_skipped_defense_in_depth(self):
        """
        Simula reenvio de uma sessão de revisão desatualizada: o
        equipamento com este legacy_code já foi criado (por outra aba/
        confirmação) entre a tela de revisão ter sido montada e o
        Administrador clicar em "Confirmar importação".
        """
        self.client.login(username="importer_admin", password="senha-forte-123")
        rows = [["CLIMATIZADOR", "NI23 BIG TANK", "", "SN-300", "", "", None, None, ""]]
        self.client.post("/equipamentos/importar/", {"file": _uploaded_file(rows)})
        self.client.get("/equipamentos/importar/revisar/")  # popula a sessão

        # Um equipamento com o mesmo legacy_code é criado "por fora" antes da confirmação.
        from apps.equipment.services import NewEquipmentData, create_equipment

        create_equipment(
            NewEquipmentData(model_id=self.model_big_tank.pk, created_by=self.admin, legacy_code="SN-300")
        )

        response = self.client.post(
            "/equipamentos/importar/revisar/", {"model_0": str(self.model_big_tank.pk)}
        )
        self.assertEqual(response.status_code, 302)

        # Continua existindo só 1 equipamento com este código — não duplicou.
        self.assertEqual(Equipment.objects.filter(legacy_code="SN-300").count(), 1)

        summary_response = self.client.get("/equipamentos/importar/resumo/")
        self.assertContains(summary_response, "duplicidade")
