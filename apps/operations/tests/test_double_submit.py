"""
Regressão do 2º reteste manual: a proteção contra reenvio criada para o
cadastro de cliente não tinha sido generalizada — Enter repetido em "Nova
unidade" criava várias `Location` idênticas ("teste2" repetida no print
do usuário). A correção extrai o mecanismo para
`apps.core.submission.SubmissionGuard` (token de sessão de uso único,
consumido ANTES de chamar o service, com POST → Redirect → GET no
sucesso) e o aplica a `LocationCreateView` e `MovementCreateView`.

Deliberadamente SEM `UNIQUE(name)` em `Location`: dois clientes
diferentes podem legitimamente ter unidades com o mesmo nome — a
proteção é por submissão, não por unicidade de nome.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType, Movement, MovementType
from apps.operations.services import NewLocationData, create_location

User = get_user_model()


class LocationCreateDoubleSubmitTest(TestCase):
    def setUp(self):
        User.objects.create_user(username="unidade_reenvio", password="senha-forte-123", role="ADMINISTRATIVO")
        self.client.login(username="unidade_reenvio", password="senha-forte-123")

    def _post_data(self, token, name="Unidade Reenvio"):
        return {
            "submission_token": token,
            "name": name,
            "type": LocationType.ESTOQUE,
            "client": "",
            "cep": "",
            "logradouro": "",
            "numero": "",
            "complemento": "",
            "bairro": "",
            "cidade": "",
            "uf": "",
            "reference_notes": "",
        }

    def _get_token(self):
        response = self.client.get("/operacao/unidades/novo/")
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]

    def test_repeated_submission_creates_only_one_location(self):
        """Reprodução do print do usuário: vários Enters seguidos com o mesmo formulário — só UMA unidade pode nascer."""
        token = self._get_token()
        data = self._post_data(token, name="teste2")

        first = self.client.post("/operacao/unidades/novo/", data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(Location.objects.filter(name="teste2").count(), 1)

        # "Muitos Enters": várias tentativas com o MESMO token.
        for _ in range(5):
            retry = self.client.post("/operacao/unidades/novo/", data)
            self.assertEqual(retry.status_code, 302)
        self.assertEqual(Location.objects.filter(name="teste2").count(), 1)

    def test_missing_or_forged_token_creates_nothing(self):
        response = self.client.post("/operacao/unidades/novo/", self._post_data("token-forjado", name="Fantasma"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Location.objects.filter(name="Fantasma").exists())

    def test_two_clients_can_still_have_units_with_the_same_name(self):
        """A proteção é por submissão — nomes iguais entre clientes DIFERENTES continuam válidos (sem UNIQUE(name))."""
        cliente_a = Client.objects.create(company_name="Cliente A LTDA")
        cliente_b = Client.objects.create(company_name="Cliente B LTDA")
        for cliente in (cliente_a, cliente_b):
            token = self._get_token()
            data = self._post_data(token, name="Matriz")
            data["type"] = LocationType.CLIENTE
            data["client"] = cliente.pk
            response = self.client.post("/operacao/unidades/novo/", data)
            self.assertEqual(response.status_code, 302)
        self.assertEqual(Location.objects.filter(name="Matriz").count(), 2)

    def test_validation_error_reissues_token_so_retry_still_works(self):
        token = self._get_token()
        data = self._post_data(token, name="")  # nome obrigatório
        response = self.client.post("/operacao/unidades/novo/", data)
        self.assertEqual(response.status_code, 200)

        new_token = response.context["submission_token"]
        self.assertTrue(new_token)
        retry = self.client.post("/operacao/unidades/novo/", self._post_data(new_token, name="Unidade Corrigida"))
        self.assertEqual(retry.status_code, 302)
        self.assertTrue(Location.objects.filter(name="Unidade Corrigida").exists())


class MovementCreateDoubleSubmitTest(TestCase):
    def setUp(self):
        category = Category.objects.create(name="Aquecedor")
        model = EquipmentModel.objects.create(category=category, name="Aquecedor Reenvio", code="AQRV")
        self.user = User.objects.create_user(
            username="mov_reenvio", password="senha-forte-123", role="OPERACIONAL"
        )
        self.client.login(username="mov_reenvio", password="senha-forte-123")

        self.cliente = Client.objects.create(company_name="Cliente Reenvio Mov LTDA")
        self.unidade = create_location(
            NewLocationData(name="Unidade Reenvio Mov", type=LocationType.CLIENTE, client=self.cliente)
        )
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.user))
        self.url = f"/operacao/movimentar/{self.equipment.patrimonio}/"

    def _get_token(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.context["submission_token"]

    def test_repeated_submission_creates_only_one_movement(self):
        token = self._get_token()
        data = {
            "submission_token": token,
            "movement_type": MovementType.INSTALACAO,
            "destination_location": self.unidade.pk,
            "reason": "",
        }
        first = self.client.post(self.url, data)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(Movement.objects.count(), 1)

        for _ in range(3):
            self.client.post(self.url, data)
        # A 2ª tentativa já é barrada pelo TOKEN — nem chega no service
        # (que também a rejeitaria por status, mas a proteção não pode
        # depender de cada regra de transição específica).
        self.assertEqual(Movement.objects.count(), 1)

    def test_missing_token_creates_no_movement(self):
        response = self.client.post(
            self.url,
            {
                "movement_type": MovementType.INSTALACAO,
                "destination_location": self.unidade.pk,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 302)  # redirect informativo para a ficha do equipamento
        self.assertEqual(Movement.objects.count(), 0)

    def test_business_error_reissues_token_so_retry_still_works(self):
        # 1ª tentativa: transferência com equipamento ainda DISPONIVEL —
        # form válido, token consumido, service rejeita (status).
        token = self._get_token()
        response = self.client.post(
            self.url,
            {
                "submission_token": token,
                "movement_type": MovementType.TRANSFERENCIA,
                "destination_location": self.unidade.pk,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())

        # O token reemitido na resposta permite corrigir e enviar de novo.
        new_token = response.context["submission_token"]
        retry = self.client.post(
            self.url,
            {
                "submission_token": new_token,
                "movement_type": MovementType.INSTALACAO,
                "destination_location": self.unidade.pk,
                "reason": "",
            },
        )
        self.assertEqual(retry.status_code, 302)
        self.assertEqual(Movement.objects.count(), 1)

    def test_tokens_are_scoped_per_equipment(self):
        """Duas abas movimentando equipamentos DIFERENTES não podem invalidar o token uma da outra."""
        other_equipment = create_equipment(
            NewEquipmentData(model_id=self.equipment.model_id, created_by=self.user)
        )
        other_url = f"/operacao/movimentar/{other_equipment.patrimonio}/"

        token_a = self._get_token()
        token_b = self.client.get(other_url).context["submission_token"]  # GET da outra aba, DEPOIS

        # O GET da aba B não pode ter invalidado o token da aba A.
        response = self.client.post(
            self.url,
            {
                "submission_token": token_a,
                "movement_type": MovementType.INSTALACAO,
                "destination_location": self.unidade.pk,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 302)

        response_b = self.client.post(
            other_url,
            {
                "submission_token": token_b,
                "movement_type": MovementType.INSTALACAO,
                "destination_location": self.unidade.pk,
                "reason": "",
            },
        )
        self.assertEqual(response_b.status_code, 302)
        self.assertEqual(Movement.objects.count(), 2)
