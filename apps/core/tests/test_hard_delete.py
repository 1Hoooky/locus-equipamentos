"""
Testes unitários de `apps.core.hard_delete` — a infraestrutura
COMPARTILHADA pelas 3 exclusões definitivas (Cliente/Equipamento/
Oportunidade, rodada "HARD DELETE DURANTE DESENVOLVIMENTO", 11/09/2026).
Cobertura de comportamento por entidade já vive nos testes de cada app
(`apps.clients.tests.test_client_hard_delete` etc.) — aqui só a peça
comum: tradução de `ProtectedError` em mensagem legível e a estrutura de
`HardDeleteImpact`.
"""

from django.db.models import ProtectedError
from django.test import TestCase

from apps.clients.models import Client, ClientType
from apps.core.hard_delete import HardDeleteImpact, describe_protected_error
from apps.operations.models import Location, LocationType


class DescribeProtectedErrorTest(TestCase):
    def test_groups_protected_objects_by_verbose_name_plural(self):
        client_obj = Client.objects.create(
            client_type=ClientType.PJ, company_name="Cliente Protect Teste", document="11.222.333/0001-81"
        )
        Location.objects.create(name="Unidade A", type=LocationType.CLIENTE, client=client_obj)
        Location.objects.create(name="Unidade B", type=LocationType.CLIENTE, client=client_obj)

        exc = None
        try:
            client_obj.delete()
        except ProtectedError as caught:
            exc = caught
        self.assertIsNotNone(exc, "Client.delete() deveria levantar ProtectedError com Location vinculada.")

        message = describe_protected_error(exc, subject='o cliente "Cliente Protect Teste"')
        self.assertIn("o cliente \"Cliente Protect Teste\"", message)
        self.assertIn("2 localizações", message)
        self.assertIn("COMPARTILHADOS", message)


class HardDeleteImpactTest(TestCase):
    def test_total_dependents_sums_all_counts(self):
        impact = HardDeleteImpact(target_label="alvo de teste", dependents={"a": 2, "b": 3})
        self.assertEqual(impact.total_dependents, 5)

    def test_total_dependents_is_zero_when_no_dependents(self):
        impact = HardDeleteImpact(target_label="alvo de teste")
        self.assertEqual(impact.total_dependents, 0)
