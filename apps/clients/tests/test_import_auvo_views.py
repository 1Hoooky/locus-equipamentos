"""
Testes HTTP do fluxo de importação de clientes do Auvo (upload → revisão →
confirmação → resumo) — LocusHub, 08/09/2026. Cobre a matriz de permissões
(só Administrador, checada no backend — `CAN_IMPORT_CLIENTS`), o fluxo
completo até a criação real de `Client`/`Address`/`Location`, e as garantias
de segurança pedidas explicitamente: nenhuma sobrescrita automática, só
NOVOS são criados na confirmação, nada é gravado durante a prévia, e o
cadastro manual continua exigindo CPF/CNPJ (a exceção fica restrita ao
importador).
"""

import io

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from apps.clients.import_auvo import REQUIRED_HEADERS
from apps.clients.models import Client, ClientType
from apps.clients.services import NewClientData, create_client
from apps.operations.models import Location

User = get_user_model()

VALID_CNPJ_1 = "11.222.333/0001-81"
VALID_CNPJ_2 = "11.444.777/0001-61"
VALID_CPF = "529.982.247-25"


def _row(**values) -> list:
    return [str(values.get(h, "")) for h in REQUIRED_HEADERS]


def _build_xlsx_bytes(data_rows, headers=REQUIRED_HEADERS, include_explanatory_row=True):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    if include_explanatory_row:
        ws.append(["explicativa"] * len(headers))
    for row in data_rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


def _uploaded_file(data_rows, name="clientes_auvo.xlsx", **kwargs):
    content = _build_xlsx_bytes(data_rows, **kwargs)
    return SimpleUploadedFile(
        name, content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


class ImportPermissionMatrixTest(TestCase):
    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"imp_{role.lower()}", password="senha-forte-123", role=role)

    def test_only_admin_can_reach_upload_view(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"imp_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/clientes/importar/")
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_only_admin_can_reach_review_view(self):
        for role, expected in (("ADMIN", 302), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"imp_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/clientes/importar/revisar/")
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_only_admin_can_reach_summary_view(self):
        for role, expected in (("ADMIN", 302), ("ADMINISTRATIVO", 403), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"imp_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/clientes/importar/resumo/")
                self.assertEqual(response.status_code, expected)
                self.client.logout()

    def test_non_admin_cannot_confirm_import_via_direct_post(self):
        """
        Mesmo que um usuário comum monte manualmente um POST para a tela de
        revisão (sem nunca ter passado pelo upload), a permissão é checada
        antes de qualquer leitura de sessão — não há bypass possível.
        """
        self.client.login(username="imp_operacional", password="senha-forte-123")
        response = self.client.post("/clientes/importar/revisar/")
        self.assertEqual(response.status_code, 403)
        self.client.logout()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get("/clientes/importar/")
        self.assertEqual(response.status_code, 302)

    def test_import_button_only_visible_to_admin_in_client_list(self):
        self.client.login(username="imp_admin", password="senha-forte-123")
        response = self.client.get("/clientes/")
        self.assertContains(response, "Importar clientes")
        self.client.logout()

        self.client.login(username="imp_administrativo", password="senha-forte-123")
        response = self.client.get("/clientes/")
        self.assertNotContains(response, "Importar clientes")
        self.client.logout()


class UploadValidationTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="up_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="up_admin", password="senha-forte-123")

    def test_wrong_extension_is_rejected(self):
        fake = SimpleUploadedFile("clientes.csv", b"a,b,c", content_type="text/csv")
        response = self.client.post("/clientes/importar/", {"file": fake})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ".xlsx")
        self.assertEqual(Client.objects.count(), 0)

    def test_garbage_content_with_xlsx_extension_is_rejected(self):
        fake = SimpleUploadedFile("clientes.xlsx", b"nao e um excel de verdade", content_type="application/octet-stream")
        response = self.client.post("/clientes/importar/", {"file": fake})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "planilha")

    def test_missing_file_is_rejected(self):
        response = self.client.post("/clientes/importar/", {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Selecione um arquivo")

    def test_valid_file_redirects_to_review(self):
        upload = _uploaded_file([_row(Nome="Cliente Válido", **{"CPF ou CNPJ": VALID_CNPJ_1})])
        response = self.client.post("/clientes/importar/", {"file": upload})
        self.assertRedirects(response, "/clientes/importar/revisar/")

    def test_nothing_is_created_during_upload_or_review(self):
        upload = _uploaded_file([_row(Nome="Cliente Válido", **{"CPF ou CNPJ": VALID_CNPJ_1})])
        self.client.post("/clientes/importar/", {"file": upload})
        self.client.get("/clientes/importar/revisar/")
        self.assertEqual(Client.objects.count(), 0)


class ReviewFilterTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="rev_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="rev_admin", password="senha-forte-123")
        rows = [
            _row(Nome="Novo Cliente", **{"CPF ou CNPJ": VALID_CNPJ_1}),
            _row(Nome="Sem Nome Nem Razão", **{"CPF ou CNPJ": "123"}),
        ]
        self.client.post("/clientes/importar/", {"file": _uploaded_file(rows)})

    def test_review_without_upload_redirects(self):
        self.client.logout()
        User.objects.create_user(username="rev2_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="rev2_admin", password="senha-forte-123")
        response = self.client.get("/clientes/importar/revisar/")
        self.assertRedirects(response, "/clientes/importar/")

    def test_review_shows_counts(self):
        response = self.client.get("/clientes/importar/revisar/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["counts"]["NOVO"], 1)
        self.assertEqual(response.context["counts"]["INVALIDO"], 1)

    def test_review_filter_by_category(self):
        response = self.client.get("/clientes/importar/revisar/?categoria=INVALIDO")
        self.assertEqual(len(response.context["rows"]), 1)
        self.assertEqual(response.context["rows"][0].classification, "INVALIDO")


class ConfirmImportTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="conf_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="conf_admin", password="senha-forte-123")

        # Cliente pré-existente, usado para testar JÁ EXISTENTE e a garantia
        # de "nenhuma sobrescrita automática".
        self.existing = create_client(
            NewClientData(client_type=ClientType.PJ, company_name="Nome Original Preservado LTDA", document=VALID_CNPJ_2)
        )

        # Um outro cliente qualquer, não relacionado à importação — usado só
        # para garantir que dados operacionais existentes não são afetados.
        self.unrelated = create_client(
            NewClientData(client_type=ClientType.PJ, company_name="Cliente Não Relacionado LTDA", document="11.333.666/0001-88")
        )

    def _post_confirm(self, rows):
        self.client.post("/clientes/importar/", {"file": _uploaded_file(rows)})
        return self.client.post("/clientes/importar/revisar/")

    def test_confirm_without_session_redirects_to_upload(self):
        response = self.client.post("/clientes/importar/revisar/")
        self.assertRedirects(response, "/clientes/importar/")

    def test_only_novo_rows_are_created(self):
        rows = [
            _row(Nome="Cliente Novo", **{"CPF ou CNPJ": VALID_CNPJ_1}),
            _row(Nome="Cliente Já Existe", **{"CPF ou CNPJ": VALID_CNPJ_2}),  # mesmo doc do self.existing
            _row(Nome="Cliente Doc Inválido", **{"CPF ou CNPJ": "123"}),
        ]
        response = self._post_confirm(rows)
        self.assertRedirects(response, "/clientes/importar/resumo/")

        # 2 pré-existentes (setUp) + 1 novo criado agora.
        self.assertEqual(Client.objects.count(), 3)
        self.assertTrue(Client.objects.filter(document="11222333000181").exists())

        summary = self.client.session["clients_import_auvo_summary"]
        self.assertEqual(summary["created_count"], 1)
        self.assertEqual(summary["ja_existente_count"], 1)
        self.assertEqual(summary["invalido_count"], 1)

    def test_existing_client_is_not_overwritten(self):
        rows = [_row(Nome="Nome Diferente Vindo Do Auvo", **{"CPF ou CNPJ": VALID_CNPJ_2, "Razão social": "Razão Social Diferente"})]
        self._post_confirm(rows)
        self.existing.refresh_from_db()
        self.assertEqual(self.existing.company_name, "Nome Original Preservado LTDA")

    def test_unrelated_existing_client_is_untouched(self):
        rows = [_row(Nome="Cliente Novo", **{"CPF ou CNPJ": VALID_CNPJ_1})]
        self._post_confirm(rows)
        self.unrelated.refresh_from_db()
        self.assertEqual(self.unrelated.company_name, "Cliente Não Relacionado LTDA")

    def test_created_client_has_fiscal_address_and_single_principal_location(self):
        rows = [
            _row(
                Nome="Cliente Endereço",
                **{
                    "CPF ou CNPJ": VALID_CNPJ_1,
                    "CEP de cobrança": "87.083-304",
                    "Logradouro endereço de cobrança": "Av. Brasil",
                    "Número endereço de cobrança": "100",
                    "Bairro de cobrança": "Centro",
                    "Cidade de cobrança": "Maringá",
                    "Estado de cobrança": "PR",
                },
            )
        ]
        self._post_confirm(rows)
        client = Client.objects.get(document="11222333000181")

        self.assertIsNotNone(client.fiscal_address)
        self.assertEqual(client.fiscal_address.logradouro, "Av. Brasil")
        self.assertEqual(client.fiscal_address.cidade, "Maringá")

        locations = Location.objects.filter(client=client)
        self.assertEqual(locations.count(), 1)
        self.assertEqual(locations.first().name, "Unidade principal")
        # Local de entrega/operacional não é deduzido do endereço fiscal.
        self.assertIsNone(locations.first().address)

    def test_client_without_document_can_be_created_by_import(self):
        rows = [_row(Nome="Cliente Sem Doc", **{"Razão social": "Cliente Sem Doc LTDA"})]
        self._post_confirm(rows)
        client = Client.objects.get(company_name="Cliente Sem Doc LTDA")
        self.assertEqual(client.document, "")

    def test_reimporting_same_file_does_not_duplicate(self):
        rows = [_row(Nome="Cliente Reimportado", Código="AUVO-999", **{"CPF ou CNPJ": VALID_CNPJ_1})]
        self._post_confirm(rows)
        self.assertEqual(Client.objects.filter(auvo_code="AUVO-999").count(), 1)

        # Reenvia a MESMA planilha — o cliente já importado deve ser
        # reconhecido (por auvo_code) e não duplicado.
        response = self._post_confirm(rows)
        summary = self.client.session["clients_import_auvo_summary"]
        self.assertEqual(summary["created_count"], 0)
        self.assertEqual(summary["ja_existente_count"], 1)
        self.assertEqual(Client.objects.filter(auvo_code="AUVO-999").count(), 1)


class ManualCreationStillRequiresDocumentTest(TestCase):
    """
    Garantia de segurança pedida explicitamente: a exceção
    `require_document=False` fica restrita ao importador — o cadastro manual
    (`ClientCreateView`/`ClientForm`) continua exigindo CPF/CNPJ como sempre
    exigiu, sem nenhum caminho para um usuário comum "explorar" a exceção.
    """

    def setUp(self):
        User.objects.create_user(username="manual_admin", password="senha-forte-123", role="ADMIN")
        self.client.login(username="manual_admin", password="senha-forte-123")

    def test_manual_create_view_rejects_blank_document(self):
        response = self.client.post(
            "/clientes/novo/",
            {
                "action": "save",
                "client_type": "PJ",
                "document": "",
                "company_name": "Cliente Sem Documento LTDA",
            },
        )
        self.assertEqual(response.status_code, 200)  # form re-renderizado com erro, não redireciona
        self.assertEqual(Client.objects.count(), 0)

    def test_create_client_service_still_requires_document_by_default(self):
        with self.assertRaises(ValueError):
            create_client(NewClientData(client_type=ClientType.PJ, company_name="Sem Doc", document=""))
