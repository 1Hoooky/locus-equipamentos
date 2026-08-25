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
        with patch("httpx.get") as mock_get:
            response = self.client.post(
                "/clientes/novo/",
                {
                    "action": "save",
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
