"""
Regressão do bug relatado (#2): endereço fiscal × endereço operacional
quebrados na experiência de UI. Sintomas reportados: mesmo preenchendo o
endereço de entrega/operacional, a ficha do cliente só mostrava o
endereço fiscal; o checkbox "Usar endereço fiscal como endereço de
entrega" não dava nenhum retorno visual; e não havia como editar o
endereço operacional a partir da ficha do cliente (só o fiscal tinha um
link de edição).

A independência dos registros `Address` em si já era garantida na camada
de serviço — ver
`apps.clients.tests.test_client_services.FiscalAndOperationalAddressIndependenceTest`.
O que faltava era a camada de TELA: exibição das duas áreas (fiscal vs.
unidades/endereços operacionais) e um jeito claro de editar cada uma.
Estes testes cobrem a tela, não repetem a cobertura de serviço.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.clients.models import Client, ClientType
from apps.operations.models import Location

User = get_user_model()


VALID_CNPJ = "11.222.333/0001-81"


def _save_post_data(**overrides):
    data = {
        "action": "save",
        "client_type": ClientType.PJ,
        # CNPJ é o campo obrigatório do cadastro (decisão revista a
        # pedido do usuário — a razão social virou opcional).
        "document": VALID_CNPJ,
        "company_name": "Cliente Endereços LTDA",
        "trade_name": "",
        "registration_status": "",
        "state_registration": "",
        "phone": "",
        "email": "",
        "contact_name": "",
        "notes": "",
        "fiscal_cep": "80000-000",
        "fiscal_logradouro": "Rua Fiscal",
        "fiscal_numero": "100",
        "fiscal_complemento": "",
        "fiscal_bairro": "Centro",
        "fiscal_cidade": "Curitiba",
        "fiscal_uf": "PR",
        "initial_location_name": "Unidade Matriz",
        "use_fiscal_as_operational": "on",
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


class ClientDetailFiscalAndOperationalAddressTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="ficha_admin", password="senha-forte-123", role="ADMINISTRATIVO")
        User.objects.create_user(username="ficha_consulta", password="senha-forte-123", role="CONSULTA")
        self.client.login(username="ficha_admin", password="senha-forte-123")

    def _create_client_via_form(self, **overrides):
        """
        GET inicial só para obter o token de proteção contra reenvio (bug
        #3) exigido por `action=save` — sem ele, o POST seria tratado como
        uma tentativa de reenvio e nada seria criado.
        """
        token = self.client.get("/clientes/novo/").context["submission_token"]
        return self.client.post("/clientes/novo/", _save_post_data(submission_token=token, **overrides))

    def test_checkbox_checked_copies_fiscal_into_independent_operational_address(self):
        """O checkbox marcado copia os valores do fiscal, mas para uma linha `Address` DISTINTA."""
        response = self._create_client_via_form()
        self.assertEqual(response.status_code, 302)

        client_obj = Client.objects.get(company_name="Cliente Endereços LTDA")
        location = Location.objects.get(client=client_obj)

        self.assertEqual(location.address.logradouro, "Rua Fiscal")
        self.assertEqual(location.address.cidade, "Curitiba")
        self.assertNotEqual(client_obj.fiscal_address_id, location.address_id)

        # Editar um depois não pode alterar o outro — a garantia real de
        # integridade continua sendo o backend, não o JS de UX.
        self.client.post(
            f"/clientes/{client_obj.pk}/endereco-fiscal/",
            {
                "cep": "80000-000",
                "logradouro": "Rua Só Do Fiscal Depois",
                "numero": "100",
                "complemento": "",
                "bairro": "Centro",
                "cidade": "Curitiba",
                "uf": "PR",
                "reference_notes": "",
            },
        )
        location.address.refresh_from_db()
        self.assertEqual(location.address.logradouro, "Rua Fiscal")

        self.client.post(
            f"/operacao/unidades/{location.pk}/endereco/",
            {
                "cep": "80000-000",
                "logradouro": "Rua Só Da Unidade Depois",
                "numero": "100",
                "complemento": "",
                "bairro": "Centro",
                "cidade": "Curitiba",
                "uf": "PR",
                "reference_notes": "",
            },
        )
        client_obj.fiscal_address.refresh_from_db()
        self.assertEqual(client_obj.fiscal_address.logradouro, "Rua Só Do Fiscal Depois")

    def test_unchecking_checkbox_keeps_manually_entered_operational_address_distinct(self):
        token = self.client.get("/clientes/novo/").context["submission_token"]
        data = _save_post_data(submission_token=token, company_name="Cliente Endereço Próprio LTDA")
        del data["use_fiscal_as_operational"]  # checkbox desmarcado = campo ausente no POST
        data.update(
            {
                "operational_cep": "81000-000",
                "operational_logradouro": "Rua Operacional Própria",
                "operational_numero": "200",
                "operational_bairro": "Bairro Novo",
                "operational_cidade": "Londrina",
                "operational_uf": "PR",
            }
        )
        response = self.client.post("/clientes/novo/", data)
        self.assertEqual(response.status_code, 302)

        client_obj = Client.objects.get(company_name="Cliente Endereço Próprio LTDA")
        location = Location.objects.get(client=client_obj)

        self.assertEqual(location.address.logradouro, "Rua Operacional Própria")
        self.assertEqual(client_obj.fiscal_address.logradouro, "Rua Fiscal")

    def test_client_detail_shows_two_distinct_address_sections_with_unit_address_inline(self):
        self._create_client_via_form(company_name="Cliente Ficha LTDA")
        client_obj = Client.objects.get(company_name="Cliente Ficha LTDA")

        response = self.client.get(f"/clientes/{client_obj.pk}/")
        content = response.content.decode()

        self.assertIn("Endereço fiscal", content)
        self.assertIn("Unidades / endereços operacionais", content)
        self.assertIn("Unidade Matriz", content)
        # O endereço da unidade tem que aparecer na PRÓPRIA ficha do
        # cliente (dentro da seção de unidades), não só depois de navegar
        # até a tela de detalhe da unidade.
        section_unidades = content.split("Unidades / endereços operacionais")[1]
        self.assertIn("Rua Fiscal", section_unidades)

    def test_client_detail_shows_edit_address_link_per_unit_for_admin_only(self):
        self._create_client_via_form(company_name="Cliente Link Editar LTDA")
        client_obj = Client.objects.get(company_name="Cliente Link Editar LTDA")
        location = Location.objects.get(client=client_obj)
        edit_url = f"/operacao/unidades/{location.pk}/endereco/"

        response = self.client.get(f"/clientes/{client_obj.pk}/")
        self.assertIn(edit_url, response.content.decode())

        self.client.logout()
        self.client.login(username="ficha_consulta", password="senha-forte-123")
        response = self.client.get(f"/clientes/{client_obj.pk}/")
        self.assertNotIn(edit_url, response.content.decode())

    def test_client_created_without_unit_name_gets_principal_location_automatically(self):
        """
        2º reteste manual (item 3): a unidade não pode ser uma obrigação
        operacional artificial — o cadastro via formulário, SEM digitar
        nome de unidade, já resulta na Location principal com o endereço
        de entrega, pronta para receber instalação de equipamento.
        """
        response = self._create_client_via_form(
            company_name="Cliente Um Endereço LTDA", initial_location_name=""
        )
        self.assertEqual(response.status_code, 302)

        client_obj = Client.objects.get(company_name="Cliente Um Endereço LTDA")
        location = Location.objects.get(client=client_obj)
        self.assertEqual(location.name, "Unidade principal")
        # Checkbox "usar fiscal como entrega" marcado no payload padrão —
        # o endereço da unidade principal nasce copiado do fiscal, mas
        # como registro Address independente.
        self.assertEqual(location.address.logradouro, "Rua Fiscal")
        self.assertNotEqual(client_obj.fiscal_address_id, location.address_id)

        detail = self.client.get(f"/clientes/{client_obj.pk}/").content.decode()
        self.assertIn("Unidade principal", detail)

    def test_additional_unit_created_later_appears_on_client_detail_and_is_editable(self):
        self._create_client_via_form(company_name="Cliente Múltiplas Unidades LTDA")
        client_obj = Client.objects.get(company_name="Cliente Múltiplas Unidades LTDA")

        unit_token = self.client.get("/operacao/unidades/novo/").context["submission_token"]
        response = self.client.post(
            "/operacao/unidades/novo/",
            {
                "submission_token": unit_token,
                "name": "Unidade Filial",
                "type": "CLIENTE",
                "client": client_obj.pk,
                "cep": "82000-000",
                "logradouro": "Rua Filial",
                "numero": "300",
                "complemento": "",
                "bairro": "Filial",
                "cidade": "Maringá",
                "uf": "PR",
                "reference_notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        new_location = Location.objects.get(client=client_obj, name="Unidade Filial")
        detail_response = self.client.get(f"/clientes/{client_obj.pk}/")
        content = detail_response.content.decode()

        self.assertIn("Unidade Matriz", content)
        self.assertIn("Unidade Filial", content)
        self.assertIn(f"/operacao/unidades/{new_location.pk}/endereco/", content)
