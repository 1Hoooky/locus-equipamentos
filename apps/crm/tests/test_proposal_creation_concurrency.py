"""
Teste de concorrência real de `get_or_create_active_proposal()` — DATA-001
(Auditoria Geral Adversarial, 14/10/2026; Saneamento Pós-Auditoria, P0-02).

Mesmo espírito de `test_stage_change_concurrency.py`: duas threads reais,
PostgreSQL real, `TransactionTestCase` (nunca `TestCase` — só sob conexões
de banco DE VERDADE o `select_for_update()` tem algo a serializar).

ANTES da correção (base a3d224c, sem lock nenhum em
`get_or_create_active_proposal()`): 1 Opportunity + 0 Proposal + duas
threads concorrentes produzia, de forma reprodutível (4/4 execuções na
auditoria pré-correção desta rodada), DUAS `Proposal` distintas para a
mesma Opportunity — uma delas órfã do fluxo visual (só a mais recente por
`created_at` é exibida em qualquer tela do sistema).

DEPOIS: `get_or_create_active_proposal()` trava a `Opportunity` (já
existente nas duas transações, mesmo padrão de `change_opportunity_stage()`)
ANTES de ler/decidir sobre Proposal — a segunda chamada só enxerga o
estado após a primeira ter comitado, nunca decide criar uma segunda.

Este teste NÃO investiga concorrência de `ProposalVersion`/
`ensure_editable_version()` (TOCTOU relacionado, mas diferente, registrado
como achado colateral separado — fora do escopo de DATA-001).
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage, Proposal, ProposalVersionStatus
from apps.crm.services import ProposalItemData, add_proposal_item, get_or_create_active_proposal
from decimal import Decimal

User = get_user_model()

REPEAT_SCENARIO_TIMES = 4


class ProposalCreationConcurrencyTest(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="concorrente_data001", password="x")
        self.client_obj = Client.objects.create(company_name="Cliente DATA-001")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.category = Category.objects.create(name="Categoria DATA-001")
        self.model = EquipmentModel.objects.create(category=self.category, name="Modelo DATA-001", code="D001")

    def _new_opportunity(self, suffix):
        return Opportunity.objects.create(
            client=self.client_obj,
            title=f"Oportunidade DATA-001 {suffix}",
            owner=self.user,
            source=self.source,
            business_type=BusinessType.LOCACAO,
            stage=self.stage_novo,
            created_by=self.user,
        )

    def _concurrent_get_or_create(self, opportunity):
        """Dispara as duas threads simultâneas via Barrier; devolve (results, errors)."""
        barrier = threading.Barrier(2)
        results = {}
        errors = {}
        lock = threading.Lock()

        def worker(name):
            try:
                barrier.wait(timeout=5)
                proposal = get_or_create_active_proposal(opportunity=opportunity, created_by=self.user)
                with lock:
                    results[name] = proposal.pk
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors[name] = repr(exc)
            finally:
                # Threads próprias não compartilham a conexão do thread
                # principal — cada uma abre a sua ao primeiro acesso ao
                # banco, e precisa fechá-la explicitamente ao terminar
                # (mesmo padrão de test_stage_change_concurrency.py).
                connection.close()

        t_a = threading.Thread(target=worker, args=("A",))
        t_b = threading.Thread(target=worker, args=("B",))
        t_a.start()
        t_b.start()
        t_a.join(timeout=10)
        t_b.join(timeout=10)

        self.assertFalse(t_a.is_alive(), "thread A não terminou — possível deadlock")
        self.assertFalse(t_b.is_alive(), "thread B não terminou — possível deadlock")
        return results, errors

    def test_duas_threads_concorrentes_produzem_uma_unica_proposal(self):
        """
        Repete o cenário várias vezes (não depende de uma única execução,
        conforme protocolo) — Opportunity nova a cada rodada, sempre
        partindo de ZERO Proposal.
        """
        for i in range(1, REPEAT_SCENARIO_TIMES + 1):
            opportunity = self._new_opportunity(f"rodada {i}")

            results, errors = self._concurrent_get_or_create(opportunity)

            self.assertEqual(errors, {}, f"rodada {i}: nenhuma thread deveria gerar exceção, veio {errors}")
            self.assertIn("A", results, f"rodada {i}: thread A não retornou resultado")
            self.assertIn("B", results, f"rodada {i}: thread B não retornou resultado")
            self.assertEqual(
                results["A"], results["B"],
                f"rodada {i}: as duas threads deveriam retornar o MESMO Proposal.pk, vieram {results}",
            )

            # Exatamente 1 Proposal para a Opportunity ao final — nunca 2.
            proposals_count = opportunity.proposals.count()
            self.assertEqual(proposals_count, 1, f"rodada {i}: esperava exatamente 1 Proposal, encontrei {proposals_count}")

            proposal = opportunity.proposals.get()
            self.assertEqual(proposal.pk, results["A"])

            # Estrutura inicial esperada: exatamente 1 ProposalVersion, v1, DRAFT.
            versions = list(proposal.versions.all())
            self.assertEqual(len(versions), 1, f"rodada {i}: esperava exatamente 1 ProposalVersion, encontrei {len(versions)}")
            self.assertEqual(versions[0].version_number, 1)
            self.assertEqual(versions[0].status, ProposalVersionStatus.DRAFT)

            # Uma terceira chamada, agora sequencial (sem concorrência),
            # continua devolvendo a MESMA Proposal — idempotência
            # preservada após a correção, não só durante a corrida.
            proposal_terceira_chamada = get_or_create_active_proposal(opportunity=opportunity, created_by=self.user)
            self.assertEqual(proposal_terceira_chamada.pk, proposal.pk, f"rodada {i}: terceira chamada deveria reaproveitar a mesma Proposal")
            self.assertEqual(opportunity.proposals.count(), 1, f"rodada {i}: terceira chamada não deveria criar uma segunda Proposal")

    def test_apos_concorrencia_nao_existe_segunda_proposal_onde_item_possa_ficar_orfao(self):
        """
        Prova do impacto comercial (não investiga concorrência de
        ProposalVersion/ensure_editable_version — isso é o achado
        colateral registrado, fora de escopo aqui): depois de confirmar
        que as duas threads concorrentes convergiram para a MESMA
        Proposal, adiciona dois itens a essa Proposal/versão resultante
        (sequencialmente, chamada direta a add_proposal_item — não
        exercita o possível TOCTOU de ensure_editable_version()) e
        demonstra que ambos pertencem à mesma Proposal/versão esperada e
        continuam visíveis pela mesma query usada pelo fluxo real
        (`opportunity.proposals.order_by("-created_at").first()`).
        """
        opportunity = self._new_opportunity("prova de impacto")

        results, errors = self._concurrent_get_or_create(opportunity)
        self.assertEqual(errors, {})
        self.assertEqual(results["A"], results["B"])

        # Pré-condição do teste de impacto: a corrida realmente aconteceu
        # (duas threads, mesmo resultado) e já está formalmente provado
        # que existe exatamente 1 Proposal — nenhuma segunda Proposal
        # onde um item pudesse ficar órfão/invisível.
        self.assertEqual(Proposal.objects.filter(opportunity=opportunity).count(), 1)

        proposal = opportunity.proposals.get()
        version = proposal.latest_version
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("1000.00")),
        )
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(equipment_model=self.model, quantity=2, unit_price=Decimal("500.00")),
        )

        # Mesma definição de "proposta ativa"/"versão exibida" usada por
        # OpportunityDetailView.get() e GenerateDocumentView.post() — a
        # fonte única de verdade do fluxo visual real.
        proposal_exibida_na_tela = opportunity.proposals.order_by("-created_at").first()
        self.assertEqual(proposal_exibida_na_tela.pk, proposal.pk)

        itens_visiveis = list(proposal_exibida_na_tela.latest_version.items.all())
        self.assertEqual(len(itens_visiveis), 2, "os dois itens devem estar na MESMA Proposal/versão exibida, nenhum órfão")

        # Não existe, em momento algum após a correção, uma segunda
        # Proposal nesta Opportunity onde um item pudesse ter ficado
        # órfão — a limitação explícita é que isto só cobre a criação da
        # Proposal (DATA-001); a possível corrida em
        # ensure_editable_version() (versão, não Proposal) permanece
        # como achado colateral, não investigada aqui.
        self.assertEqual(Proposal.objects.filter(opportunity=opportunity).count(), 1)
