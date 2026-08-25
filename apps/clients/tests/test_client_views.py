"""
Testes HTTP das telas de cliente — matriz de permissões (v1.0, seção 11),
cadastro completamente manual sem BrasilAPI (validação obrigatória #8), e
o fluxo de dois botões da consulta de CNPJ (#7) na camada HTTP.
"""

from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clients.models import Client, ClientType

User = get_user_model()

VALID_CNPJ = "11.222.333/0001-81"


def _fake_response(status_code=200, json_data=None):
    from unittest.mock import Mock

    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    return response


class ClientListAccessTest(TestCase):
    """Todos os 4 perfis podem consultar (CAN_VIEW_CLIENTS, v1.0 seção 11)."""

    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"list_{role.lower()}", password="senha-forte-123", role=role)

    def test_all_roles_can_list_clients(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            with self.subTest(role=role):
                self.client.login(username=f"list_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/clientes/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get("/clientes/")
        self.assertEqual(response.status_code, 302)


class ClientCreatePermissionTest(TestCase):
    """CAN_MANAGE_CLIENTS: só Admin/Administrativo (v1.0, seção 11)."""

    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"create_{role.lower()}", password="senha-forte-123", role=role)

    def test_admin_and_administrativo_can_access_create_form(self):
        for role in ("ADMIN", "ADMINISTRATIVO"):
            with self.subTest(role=role):
                self.client.login(username=f"create_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/clientes/novo/")
                self.assertEqual(response.status_code, 200)
                self.client.logout()

    def test_operacional_and_consulta_cannot_access_create_form(self):
        for role in ("OPERACIONAL", "CONSULTA"):
            with self.subTest(role=role):
                self.client.login(username=f"create_{role.lower()}", password="senha-forte-123")
                response = self.client.get("/clientes/novo/")
                self.assertEqual(response.status_code, 403)
                self.client.logout()


class ClientUpdatePermissionTest(TestCase):
    def setUp(self):
        for role in ("ADMIN", "ADMINISTRATIVO", "OPERACIONAL", "CONSULTA"):
            User.objects.create_user(username=f"upd_{role.lower()}", password="senha-forte-123", role=role)
        self.client_record = Client.objects.create(company_name="Cliente Para Editar LTDA")

    def test_permission_matrix_for_update_form_access(self):
        for role, expected in (("ADMIN", 200), ("ADMINISTRATIVO", 200), ("OPERACIONAL", 403), ("CONSULTA", 403)):
            with self.subTest(role=role):
                self.client.login(username=f"upd_{role.lower()}", password="senha-forte-123")
                response = self.client.get(f"/clientes/{self.client_record.pk}/editar/")
                self.assertEqual(response.status_code, expected)
                self.client.logout()


class ManualClientRegistrationTest(TestCase):
    """Validação obrigatória #8: cadastro completamente manual, sem NUNCA chamar a BrasilAPI."""

    def setUp(self):
        User.objects.create_user(username="cadastrador", password="senha-forte-123", role="ADMINISTRATIVO")
        self.client.login(username="cadastrador", password="senha-forte-123")

    def test_save_without_ever_calling_lookup_creates_client(self):
        # GET inicial só para obter o token de proteção contra reenvio
        # (bug #3) — sem ele, `action=save` é tratado como uma tentativa de
        # reenvio e nada é criado.
        submission_token = self.client.get("/clientes/novo/").context["submission_token"]

        with patch("httpx.get") as mock_get:
            response = self.client.post(
                "/clientes/novo/",
                {
                    "action": "save",
                    "submission_token": submission_token,
                    "client_type": ClientType.PJ,
                    "document": VALID_CNPJ,
                    "company_name": "Cliente Totalmente Manual LTDA",
                    "trade_name": "",
                    "registration_status": "",
                    "state_registration": "",
                    "phone": "",
                    "email": "",
                    "contact_name": "",
                    "notes": "",
                    "fiscal_cep": "",
                    "fiscal_logradouro": "",
                    "fiscal_numero": "",
                    "fiscal_complemento": "",
                    "fiscal_bairro": "",
                    "fiscal_cidade": "",
                    "fiscal_uf": "",
                    "initial_location_name": "",
                    "operational_cep": "",
                    "operational_logradouro": "",
                    "operational_numero": "",
                    "operational_complemento": "",
                    "operational_bairro": "",
                    "operational_cidade": "",
                    "operational_uf": "",
                    "operational_reference_notes": "",
                },
            )
            mock_get.assert_not_called()

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Client.objects.filter(company_name="Cliente Totalmente Manual LTDA").exists())


class CnpjLookupFlowTest(TestCase):
    """Validação obrigatória #7 na camada HTTP: sucesso e indisponibilidade, sem nada salvo em nenhum dos dois casos."""

    def setUp(self):
        User.objects.create_user(username="consultador", password="senha-forte-123", role="ADMINISTRATIVO")
        self.client.login(username="consultador", password="senha-forte-123")

    def _base_post_data(self, action):
        return {
            "action": action,
            "client_type": ClientType.PJ,
            "document": VALID_CNPJ,
            "company_name": "",
            "trade_name": "",
            "registration_status": "",
            "state_registration": "",
            "phone": "",
            "email": "",
            "contact_name": "",
            "notes": "",
            "fiscal_cep": "",
            "fiscal_logradouro": "",
            "fiscal_numero": "",
            "fiscal_complemento": "",
            "fiscal_bairro": "",
            "fiscal_cidade": "",
            "fiscal_uf": "",
            "initial_location_name": "",
            "operational_cep": "",
            "operational_logradouro": "",
            "operational_numero": "",
            "operational_complemento": "",
            "operational_bairro": "",
            "operational_cidade": "",
            "operational_uf": "",
            "operational_reference_notes": "",
        }

    def test_lookup_success_fills_form_without_saving(self):
        payload = {"razao_social": "Empresa Consultada LTDA", "municipio": "Curitiba", "uf": "PR"}
        with patch("httpx.get", return_value=_fake_response(200, payload)):
            response = self.client.post("/clientes/novo/", self._base_post_data("lookup"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Empresa Consultada LTDA", response.content.decode())
        self.assertFalse(Client.objects.filter(company_name="Empresa Consultada LTDA").exists())

    def test_lookup_unavailable_lets_user_continue_manually(self):
        with patch("httpx.get", side_effect=httpx.TimeoutException("timed out")):
            response = self.client.post("/clientes/novo/", self._base_post_data("lookup"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Client.objects.filter(document="11222333000181").exists())
        # A mensagem de indisponibilidade deve orientar o cadastro manual.
        self.assertIn("cadastro manual", response.content.decode().lower())

    def test_lookup_not_found_lets_user_continue_manually(self):
        with patch("httpx.get", return_value=_fake_response(404)):
            response = self.client.post("/clientes/novo/", self._base_post_data("lookup"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("não encontrado", response.content.decode().lower())


class CnpjLookupDoesNotRequireFullFormTest(TestCase):
    """
    Regressão do bug relatado: 'Consultar CNPJ' exigia Razão Social (e o
    resto do cadastro completo) porque a mesma validação de `ClientForm`
    era acionada na hora de renderizar os erros de campo, mesmo sem o view
    chamar `is_valid()` explicitamente. `action=lookup` agora só valida
    tipo PJ (quando aplicável) + CNPJ presente/checksum válido — nada mais.
    """

    def setUp(self):
        User.objects.create_user(username="consultador_minimo", password="senha-forte-123", role="ADMINISTRATIVO")
        self.client.login(username="consultador_minimo", password="senha-forte-123")

    def test_only_valid_cnpj_and_lookup_action_is_enough(self):
        """Só client_type + document + action=lookup — nenhum outro campo no POST."""
        payload = {"razao_social": "Empresa Só CNPJ LTDA"}
        with patch("httpx.get", return_value=_fake_response(200, payload)):
            response = self.client.post(
                "/clientes/novo/", {"action": "lookup", "client_type": ClientType.PJ, "document": VALID_CNPJ}
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Empresa Só CNPJ LTDA", response.content.decode())
        self.assertFalse(Client.objects.filter(company_name="Empresa Só CNPJ LTDA").exists())

    def test_blank_company_name_does_not_block_lookup(self):
        payload = {"razao_social": "Empresa Encontrada LTDA"}
        with patch("httpx.get", return_value=_fake_response(200, payload)):
            response = self.client.post(
                "/clientes/novo/",
                {"action": "lookup", "client_type": ClientType.PJ, "document": VALID_CNPJ, "company_name": ""},
            )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # Nem em português nem em inglês pode aparecer um erro de campo
        # obrigatório para razão social nesta tela.
        self.assertNotIn("Este campo é obrigatório", content)
        self.assertNotIn("This field is required", content)
        # A prova mais direta: o form devolvido ao template está SEM
        # nenhum erro (é um form não vinculado — nunca roda full_clean()).
        self.assertEqual(response.context["form"].errors, {})
        self.assertFalse(response.context["form"].is_bound)
        self.assertIn("Empresa Encontrada LTDA", content)

    def test_lookup_with_invalid_cnpj_checksum_shows_document_error_not_company_name(self):
        response = self.client.post(
            "/clientes/novo/",
            {"action": "lookup", "client_type": ClientType.PJ, "document": "11.222.333/0001-80", "company_name": ""},
        )
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertNotIn("Este campo é obrigatório", content)
        self.assertEqual(response.context["form"].errors, {})

    def test_lookup_without_document_does_not_raise_and_does_not_require_company_name(self):
        response = self.client.post(
            "/clientes/novo/", {"action": "lookup", "client_type": ClientType.PJ, "document": "", "company_name": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].errors, {})

    def _full_save_payload(self, **overrides):
        data = {
            "action": "save",
            "client_type": ClientType.PJ,
            "document": VALID_CNPJ,
            "company_name": "",
            "trade_name": "",
            "registration_status": "",
            "state_registration": "",
            "phone": "",
            "email": "",
            "contact_name": "",
            "notes": "",
            "fiscal_cep": "",
            "fiscal_logradouro": "",
            "fiscal_numero": "",
            "fiscal_complemento": "",
            "fiscal_bairro": "",
            "fiscal_cidade": "",
            "fiscal_uf": "",
            "initial_location_name": "",
            "operational_cep": "",
            "operational_logradouro": "",
            "operational_numero": "",
            "operational_complemento": "",
            "operational_bairro": "",
            "operational_cidade": "",
            "operational_uf": "",
            "operational_reference_notes": "",
        }
        data.update(overrides)
        return data

    def test_save_action_no_longer_requires_company_name(self):
        """
        Decisão revista a pedido do usuário: razão social virou opcional
        (o CNPJ é que é obrigatório agora) — o inverso do que valia antes.
        """
        token = self.client.get("/clientes/novo/").context["submission_token"]
        response = self.client.post(
            "/clientes/novo/", self._full_save_payload(submission_token=token, company_name="")
        )
        self.assertEqual(response.status_code, 302)
        client = Client.objects.get(document="11222333000181")
        self.assertEqual(client.company_name, "")

    def test_save_action_requires_document(self):
        """O formulário COMPLETO (ação Salvar) exige CNPJ — o campo que virou obrigatório."""
        token = self.client.get("/clientes/novo/").context["submission_token"]
        response = self.client.post(
            "/clientes/novo/",
            self._full_save_payload(submission_token=token, document="", company_name="Empresa Sem CNPJ LTDA"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("document", response.context["form"].errors)
        self.assertFalse(Client.objects.filter(company_name="Empresa Sem CNPJ LTDA").exists())
