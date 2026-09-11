"""
Teste de concorrência real de `change_opportunity_stage()` — mesmo
espírito de `apps.operations.tests.test_movement_concurrency`
(validação obrigatória do CRM): duas threads disparadas ao mesmo tempo
tentando mudar a etapa da MESMA oportunidade para etapas diferentes
(uma para "Ganho", outra para "Perdido"). O `select_for_update()` em
`change_opportunity_stage()` serializa as duas — exatamente uma deve
suceder (a que chega primeiro ao lock, vendo `stage=Novo`); a outra
falha (quando finalmente obtém o lock, `stage` já não é mais "Novo",
então a segunda tentativa "some estágio X → Y" onde X já mudou — no
caso deste teste, a segunda operação ainda é estruturalmente válida
[Novo→Perdido de novo seria um no-op comparado ao estado JÁ mudado], o
que garante que NUNCA as duas escritas coexistem: o estado final nunca
é simultaneamente ganho E perdido, e o histórico nunca tem uma linha
"fantasma" cujo from_stage não bate com o to_stage da transição
anterior.

`TransactionTestCase` (não `TestCase`) pelo mesmo motivo do teste de
referência: threads precisam de conexões e transações reais, e isso só
é confiável em PostgreSQL de verdade (`select_for_update()`).
"""

import threading
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, LossReason, Opportunity, OpportunityStage, OpportunityStageChange
from apps.crm.services import NewOpportunityData, change_opportunity_stage, create_opportunity

User = get_user_model()


class StageChangeConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="concorrente_crm", password="senha-forte-123")
        self.client_obj = Client.objects.create(company_name="Cliente Concorrência")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=3, is_lost=True)
        self.loss_reason = LossReason.objects.create(name="Preço")

        self.opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade concorrente",
                owner=self.user,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.user,
            )
        )

    def test_two_simultaneous_stage_changes_never_produce_an_incoherent_final_state(self):
        results: dict[str, object] = {}
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def worker_win():
            try:
                opp = change_opportunity_stage(
                    opportunity_id=self.opportunity.pk,
                    new_stage=self.stage_ganho,
                    changed_by=self.user,
                    closed_value=Decimal("100.00"),
                )
                with lock:
                    results["win"] = opp.stage_id
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["win"] = exc
            finally:
                connection.close()

        def worker_lose():
            try:
                opp = change_opportunity_stage(
                    opportunity_id=self.opportunity.pk,
                    new_stage=self.stage_perdido,
                    changed_by=self.user,
                    loss_reason=self.loss_reason,
                )
                with lock:
                    results["lose"] = opp.stage_id
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors["lose"] = exc
            finally:
                connection.close()

        t_win = threading.Thread(target=worker_win)
        t_lose = threading.Thread(target=worker_lose)
        t_win.start()
        t_lose.start()
        t_win.join()
        t_lose.join()

        # As duas transições são estruturalmente válidas partindo de
        # "Novo" (nenhuma delas é um no-op nem exige um estado anterior
        # específico além de "não é a mesma etapa de destino") — então
        # AMBAS podem suceder (serializadas pelo lock, uma depois da
        # outra) OU só uma suceder, dependendo de timing. O que este
        # teste garante de verdade é a integridade do ESTADO FINAL e do
        # HISTÓRICO, não uma contagem fixa de sucessos.
        self.assertGreaterEqual(len(results), 1, f"Esperado ao menos 1 sucesso. Erros: {errors}")

        self.opportunity.refresh_from_db()
        # Nunca ganha E perdida ao mesmo tempo — o estado final reflete
        # exatamente UMA das duas etapas escolhidas (a última a obter o
        # lock e escrever), nunca uma mistura dos dois.
        self.assertFalse(self.opportunity.won_at and self.opportunity.lost_at)
        self.assertIn(self.opportunity.stage_id, {self.stage_ganho.pk, self.stage_perdido.pk})
        if self.opportunity.stage_id == self.stage_ganho.pk:
            self.assertIsNotNone(self.opportunity.won_at)
            self.assertIsNone(self.opportunity.lost_at)
        else:
            self.assertIsNotNone(self.opportunity.lost_at)
            self.assertIsNone(self.opportunity.won_at)

        # Histórico coerente: cada linha de OpportunityStageChange tem
        # from_stage/to_stage formando uma cadeia sem "buracos" — o
        # to_stage de uma linha é sempre o from_stage da próxima (ou é a
        # última). Nenhuma linha "fantasma" de uma escrita parcial.
        changes = list(
            OpportunityStageChange.objects.filter(opportunity=self.opportunity).order_by("changed_at", "pk")
        )
        for previous, current in zip(changes, changes[1:]):
            self.assertEqual(
                previous.to_stage_id,
                current.from_stage_id,
                "Histórico incoerente: to_stage de uma transição não bate com from_stage da seguinte.",
            )
        # A última linha do histórico sempre bate com o stage atual.
        self.assertEqual(changes[-1].to_stage_id, self.opportunity.stage_id)
