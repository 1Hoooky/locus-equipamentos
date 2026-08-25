"""
Regressão do bug relatado (#3): Enter repetido durante a criação de
cliente disparava múltiplos cadastros/duplicatas. A correção é um token
de sessão de uso único (mesmo padrão de `EquipmentBatchConfirmView`,
`apps/equipment/views.py`) — não depende só de desabilitar o botão no
navegador.

O CNPJ passou a ser o campo obrigatório do cadastro (a razão social virou
opcional — decisão revista a pedido do usuário, depois da correção do
bug #3 original). Isso significa que "cliente sem documento" deixou de
ser um cenário criável — os testes que provavam a proteção "mesmo sem
documento" foram adaptados para provar o equivalente com o campo agora
opcional (`company_name` em branco), mantendo a mesma ideia: a proteção
contra reenvio não depende de nenhum campo específico estar preenchido.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clients.models import Client, ClientType

User = get_user_model()

VALID_CNPJ = "11.222.333/0001-81"


def _save_post_data(submission_token, **overrides):
    data = {
        "action": "save",
        "submission_token": submission_token,
        "client_type": ClientType.PJ,
        # CNPJ é obrigatório agora — ver docstring do módulo.
        "document": VALID_CNPJ,
        "company_name": "Cliente Reenvio LTDA",
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


class ClientCreateDoubleSubmitTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="reenvio_user", password="senha-forte-123", role="ADMINISTRATIVO")
        self.client.login(username="reenvio_user", password="senha-forte-123")

    def _get_token(self):
        response = self.client.get("/clientes/novo/")
        self.assertEqual(response.status_code, 200)
        token = response.context["submission_token"]
        self.assertTrue(token)
        return token

    def test_repeated_submission_with_same_token_does_not_create_duplicate(self):
        token = self._get_token()
        data = _save_post_data(token, document="11.222.333/0001-81")

        first = self.client.post("/clientes/novo/", data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(Client.objects.filter(document="11222333000181").count(), 1)

        # Segundo Enter/clique com o MESMO token — nada novo é criado.
        second = self.client.post("/clientes/novo/", data)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Client.objects.filter(document="11222333000181").count(), 1)
        self.assertEqual(Client.objects.count(), 1)

    def test_double_submit_protection_works_with_blank_company_name(self):
        """
        A proteção não pode depender de nenhum campo opcional estar
        preenchido — só o token importa. `company_name` é o campo opcional
        agora (o CNPJ é que é obrigatório), então é ele que fica em
        branco aqui para provar isso.
        """
        token = self._get_token()
        data = _save_post_data(token, company_name="")  # já usa o VALID_CNPJ padrão de _save_post_data

        first = self.client.post("/clientes/novo/", data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(Client.objects.filter(document="11222333000181", company_name="").count(), 1)

        second = self.client.post("/clientes/novo/", data)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Client.objects.filter(document="11222333000181").count(), 1)

    def test_missing_session_token_blocks_save_instead_of_creating(self):
        """POST direto sem nunca ter feito o GET (sem token pendente na sessão) é tratado como reenvio, não cria nada."""
        data = _save_post_data("um-token-qualquer-forjado", company_name="Cliente Sem Sessão LTDA")
        response = self.client.post("/clientes/novo/", data)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Client.objects.filter(company_name="Cliente Sem Sessão LTDA").exists())

    def test_lookup_does_not_consume_token_and_save_still_succeeds_after_lookup(self):
        token = self._get_token()
        lookup_response = self.client.post(
            "/clientes/novo/",
            {
                "action": "lookup",
                "submission_token": token,
                "client_type": ClientType.PJ,
                "document": "",
                "company_name": "",
            },
        )
        self.assertEqual(lookup_response.status_code, 200)
        # O mesmo token continua válido depois da consulta.
        self.assertEqual(lookup_response.context["submission_token"], token)

        save_response = self.client.post(
            "/clientes/novo/", _save_post_data(token, company_name="Cliente Pós Consulta LTDA")
        )
        self.assertEqual(save_response.status_code, 302)
        self.assertTrue(Client.objects.filter(company_name="Cliente Pós Consulta LTDA").exists())

    def test_validation_error_reissues_token_so_retry_still_works(self):
        token = self._get_token()
        invalid_data = _save_post_data(token, document="")  # CNPJ obrigatório agora
        invalid_response = self.client.post("/clientes/novo/", invalid_data)
        self.assertEqual(invalid_response.status_code, 200)
        self.assertIn("document", invalid_response.context["form"].errors)

        new_token = invalid_response.context["submission_token"]
        self.assertTrue(new_token)

        retry_response = self.client.post(
            "/clientes/novo/", _save_post_data(new_token, company_name="Cliente Corrigido LTDA")
        )
        self.assertEqual(retry_response.status_code, 302)
        self.assertTrue(Client.objects.filter(company_name="Cliente Corrigido LTDA").exists())

    def test_stale_token_from_earlier_page_load_is_rejected(self):
        """Um token de uma exibição anterior (já substituído por uma nova) não pode mais ser usado."""
        old_token = self._get_token()
        # Um segundo carregamento da página emite outro token e substitui o da sessão.
        new_token = self._get_token()
        self.assertNotEqual(old_token, new_token)

        response = self.client.post(
            "/clientes/novo/", _save_post_data(old_token, company_name="Cliente Token Velho LTDA")
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Client.objects.filter(company_name="Cliente Token Velho LTDA").exists())
