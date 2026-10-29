"""
Testes de regressão permanentes — DATA-002 / ABUSE-001 (Auditoria Geral
Adversarial, 14/10/2026; Saneamento Pós-Auditoria, P0-03).

Achado original: `generate_contract()` não verificava se já existia um
`Contract` para a `ProposalVersion` antes de criar — reenvio sequencial
(dois POSTs comuns, sem nenhuma corrida) e concorrência real (duas
threads/duas sessões simultâneas) produziam DOIS `Contract`, dois
números `CONTR-*` consumidos e dois `Attachment` CONTRATO para a MESMA
versão. A auditoria pré-correção desta rodada também confirmou,
adicionalmente, que `issue_proposal()` tem a MESMA causa raiz (decisão
check-then-act sobre `ProposalVersion.status` sem lock) e duplica o PDF
de Proposta sob concorrência real (não sob reenvio sequencial comum,
porque aí o efeito colateral de `generate_documents()` já mascarava o
problema).

CORREÇÃO (P0-03): `generate_contract()` e `issue_proposal()` agora
travam a própria `ProposalVersion` (`select_for_update()`) e relêem seu
estado FRESCO sob o lock antes de decidir — nunca decidem sobre a
instância recebida por parâmetro. Ver docstrings dessas funções em
`apps/crm/services.py` para o detalhe de cada uma. A idempotência nova
de `issue_proposal()` é DELIMITADA: só o status ISSUED (reemissão
duplicada) é absorvido silenciosamente; ACCEPTED (ou qualquer outro
status não-DRAFT/ISSUED) continua rejeitado com `ValueError`, exatamente
como antes desta correção (ver `IssueProposalStatusSemanticsTest`).

`TransactionTestCase` (nunca `TestCase`) nos testes de concorrência real,
pelo mesmo motivo de `test_stage_change_concurrency.py`/
`test_proposal_creation_concurrency.py`: threads precisam de conexões e
transações PostgreSQL de verdade para o `select_for_update()` ter algo a
serializar.

Nota sobre `ContentType`/`TransactionTestCase`: `TransactionTestCase`
TRUNCA tabelas entre métodos de teste (ao contrário de `TestCase`, que só
reverte uma transação) — isso pode deixar o cache em nível de processo
de `ContentType.objects` (usado por `GenericForeignKey`, aqui
`Attachment.content_object`) apontando para um `content_type_id` que não
existe mais na tabela recém-truncada de um método de teste posterior na
mesma classe, produzindo um `IntegrityError` espúrio (`content_type_id=N
not present in table django_content_type`) que é um artefato do arcabouço
de teste do Django (ticket conhecido, ~#10827), não um bug da aplicação.
`ContentType.objects.clear_cache()` em `setUp()` evita isso.
"""

import threading

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test import Client as DjangoTestClient
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from decimal import Decimal
from datetime import date

from apps.attachments.models import AttachmentCategory
from apps.attachments.services import attachments_for
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import (
    BusinessType,
    CommercialSource,
    Contract,
    Opportunity,
    OpportunityStage,
    ProposalVersionStatus,
)
from apps.crm.services import (
    DocumentType,
    ProposalInstallmentData,
    ProposalItemData,
    accept_proposal_version,
    add_installment,
    add_proposal_item,
    generate_contract,
    generate_documents,
    get_or_create_active_proposal,
    issue_proposal,
)

User = get_user_model()

REPEAT_SCENARIO_TIMES = 4


def _user_with_perms(username, *codenames):
    user = User.objects.create_user(username=username, password="senha-forte-123")
    if codenames:
        perms = Permission.objects.filter(codename__in=codenames, content_type__app_label="crm")
        group, _ = Group.objects.get_or_create(name=f"perm-{username}")
        group.permissions.set(perms)
        user.groups.add(group)
    return user


class _BaseSetupMixin:
    """
    Setup comum (não-concorrente e concorrente): 1 Opportunity + 1
    Proposal/ProposalVersion DRAFT com 1 item e pagamento reconciliado
    (pronta para emitir/gerar contrato), seguindo o mesmo padrão de
    `_payment_test_helpers.add_full_installment` usado no resto da
    suíte — reimplementado aqui (sem importar o helper de TestCase) só
    para não acoplar um util pensado para `TestCase` a `TransactionTestCase`.
    """

    def _build_common_fixtures(self, user_codenames=("add_opportunities", "view_opportunities", "change_opportunities", "issue_proposal_documents", "generate_contract")):
        self.user = _user_with_perms("op_data002", *user_codenames)
        self.client_obj = Client.objects.create(company_name="Cliente DATA-002")
        self.source = CommercialSource.objects.create(name="Site")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_ganho = OpportunityStage.objects.create(name="Ganho", order=2, is_won=True)
        self.category = Category.objects.create(name="Categoria DATA-002")
        self.model = EquipmentModel.objects.create(category=self.category, name="Modelo DATA-002", code="D002")

    def _new_opportunity_with_draft_version(self, suffix):
        opportunity = Opportunity.objects.create(
            client=self.client_obj,
            title=f"Oportunidade DATA-002 {suffix}",
            owner=self.user,
            source=self.source,
            business_type=BusinessType.LOCACAO,
            stage=self.stage_novo,
            created_by=self.user,
        )
        proposal = get_or_create_active_proposal(opportunity=opportunity, created_by=self.user)
        version = proposal.latest_version
        add_proposal_item(
            proposal_version=version,
            data=ProposalItemData(equipment_model=self.model, quantity=1, unit_price=Decimal("1000.00")),
        )
        add_installment(
            proposal_version=version,
            data=ProposalInstallmentData(payment_method="PIX", amount=version.total, due_date=date(2026, 12, 31)),
        )
        return opportunity, version

    def _login(self, user):
        client = DjangoTestClient()
        client.force_login(user)
        return client


class IssueProposalStatusSemanticsTest(_BaseSetupMixin, TestCase):
    """
    A idempotência nova de `issue_proposal()` resolve ESPECIFICAMENTE a
    reemissão de uma versão já ISSUED — nunca "qualquer status
    não-DRAFT". ACCEPTED (e qualquer status futuro além de DRAFT/ISSUED)
    precisa continuar rejeitado com `ValueError` exatamente como antes
    desta correção. Cobre também, explicitamente, a convenção de que
    `issue_proposal()` muta EM PLACE a MESMA instância Python recebida —
    o caller nunca precisa de `refresh_from_db()` manual para ver
    status/snapshots atualizados.
    """

    def setUp(self):
        self._build_common_fixtures()

    def test_issue_proposal_on_draft_issues_normally(self):
        _, version = self._new_opportunity_with_draft_version("draft")
        self.assertEqual(version.status, ProposalVersionStatus.DRAFT)

        returned = issue_proposal(proposal_version=version, issued_by=self.user)

        # Mutação em place: o MESMO objeto `version` recebido pelo
        # caller já reflete o novo status/snapshot, sem precisar de
        # refresh_from_db() manual — e é o mesmo objeto devolvido.
        self.assertIs(returned, version)
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertIsNotNone(version.issued_at)
        self.assertTrue(version.client_name_snapshot)
        self.assertEqual(
            attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).count(), 1,
        )

    def test_second_issue_proposal_call_on_now_issued_version_is_idempotent(self):
        _, version = self._new_opportunity_with_draft_version("idempotente")
        first = issue_proposal(proposal_version=version, issued_by=self.user)
        first_issued_at = version.issued_at

        # Segunda chamada, SEQUENCIAL, sobre a MESMA instância — já ISSUED.
        second = issue_proposal(proposal_version=version, issued_by=self.user)

        self.assertIs(second, version)
        self.assertIs(second, first)  # mesmíssimo objeto Python nas duas chamadas
        self.assertEqual(version.status, ProposalVersionStatus.ISSUED)
        self.assertEqual(version.issued_at, first_issued_at, "não deveria reemitir/atualizar issued_at")
        self.assertEqual(
            attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).count(), 1,
            "a segunda chamada não deveria duplicar o PDF/Attachment de Proposta",
        )

    def test_issue_proposal_on_accepted_version_still_raises_valueerror(self):
        _, version = self._new_opportunity_with_draft_version("aceita")
        issue_proposal(proposal_version=version, issued_by=self.user)
        accept_proposal_version(proposal_version=version, accepted_by=self.user, won_stage=self.stage_ganho)
        version.refresh_from_db()
        self.assertEqual(version.status, ProposalVersionStatus.ACCEPTED)

        with self.assertRaises(ValueError):
            issue_proposal(proposal_version=version, issued_by=self.user)

        # Nenhum PDF/Attachment adicional foi criado pela tentativa rejeitada.
        self.assertEqual(
            attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).count(), 1,
        )


class ContractSequentialIdempotencyTest(_BaseSetupMixin, TestCase):
    """TESTE 1 — CONTRATO SEQUENCIAL (seção 16 do protocolo P0-03)."""

    def setUp(self):
        self._build_common_fixtures()

    def test_generate_contract_called_twice_sequentially_reuses_same_contract(self):
        _, version = self._new_opportunity_with_draft_version("seq")
        issue_proposal(proposal_version=version, issued_by=self.user)

        first_contract = generate_contract(proposal_version=version, created_by=self.user)
        second_contract = generate_contract(proposal_version=version, created_by=self.user)

        self.assertEqual(
            first_contract.pk, second_contract.pk,
            "a segunda chamada deveria reaproveitar o MESMO Contract, não criar outro",
        )
        self.assertEqual(Contract.objects.filter(proposal_version=version).count(), 1)
        self.assertEqual(
            attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.CONTRATO).count(), 1,
        )
        # Nenhum segundo número CONTR-* consumido pela duplicação.
        self.assertEqual(first_contract.number, second_contract.number)

    def test_generate_documents_contrato_called_twice_sequentially_is_idempotent(self):
        """Mesma prova, mas pelo caminho público real (`generate_documents`), não direto no service."""
        _, version = self._new_opportunity_with_draft_version("seq-gd")

        generate_documents(proposal_version=version, document_type=DocumentType.CONTRATO, actor=self.user)
        version.refresh_from_db()
        generate_documents(proposal_version=version, document_type=DocumentType.CONTRATO, actor=self.user)
        version.refresh_from_db()

        self.assertEqual(Contract.objects.filter(proposal_version=version).count(), 1)
        self.assertEqual(
            attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.CONTRATO).count(), 1,
        )


class ContractConcurrencyTest(_BaseSetupMixin, TransactionTestCase):
    """TESTE 2 — CONTRATO CONCORRENTE (seção 16 do protocolo P0-03)."""

    def setUp(self):
        ContentType.objects.clear_cache()
        self._build_common_fixtures()

    def _concurrent_generate_contract(self, version):
        barrier = threading.Barrier(2)
        results = {}
        errors = {}
        lock = threading.Lock()

        def worker(name):
            try:
                barrier.wait(timeout=5)
                contract = generate_contract(proposal_version=version, created_by=self.user)
                with lock:
                    results[name] = (contract.pk, contract.number)
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors[name] = repr(exc)
            finally:
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

    def test_two_threads_generating_contract_simultaneously_converge_to_one_contract(self):
        for i in range(1, REPEAT_SCENARIO_TIMES + 1):
            _, version = self._new_opportunity_with_draft_version(f"conc {i}")
            issue_proposal(proposal_version=version, issued_by=self.user)

            results, errors = self._concurrent_generate_contract(version)

            self.assertEqual(errors, {}, f"rodada {i}: nenhuma exceção inesperada, veio {errors}")
            self.assertIn("A", results)
            self.assertIn("B", results)
            self.assertEqual(
                results["A"], results["B"],
                f"rodada {i}: as duas threads deveriam convergir para o MESMO Contract, vieram {results}",
            )

            self.assertEqual(
                Contract.objects.filter(proposal_version=version).count(), 1,
                f"rodada {i}: esperava exatamente 1 Contract",
            )
            self.assertEqual(
                attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.CONTRATO).count(), 1,
                f"rodada {i}: esperava exatamente 1 Attachment CONTRATO",
            )


class ProposalIssueConcurrencyTest(_BaseSetupMixin, TransactionTestCase):
    """TESTE 4 — PROPOSTA CONCORRENTE (seção 16 do protocolo P0-03)."""

    def setUp(self):
        ContentType.objects.clear_cache()
        self._build_common_fixtures()

    def _concurrent_issue(self, version):
        barrier = threading.Barrier(2)
        results = {}
        errors = {}
        lock = threading.Lock()

        def worker(name):
            try:
                barrier.wait(timeout=5)
                issued = issue_proposal(proposal_version=version, issued_by=self.user)
                with lock:
                    results[name] = issued.pk
            except Exception as exc:  # pragma: no cover - diagnóstico do teste
                with lock:
                    errors[name] = repr(exc)
            finally:
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

    def test_two_threads_issuing_same_draft_version_simultaneously_produce_single_pdf(self):
        for i in range(1, REPEAT_SCENARIO_TIMES + 1):
            _, version = self._new_opportunity_with_draft_version(f"issue-conc {i}")

            results, errors = self._concurrent_issue(version)

            self.assertEqual(errors, {}, f"rodada {i}: nenhuma exceção inesperada se o comportamento público pôde ser mantido idempotente, veio {errors}")
            self.assertIn("A", results)
            self.assertIn("B", results)

            version.refresh_from_db()
            self.assertEqual(version.status, ProposalVersionStatus.ISSUED, f"rodada {i}")
            self.assertEqual(
                attachments_for(version.proposal.opportunity).filter(category=AttachmentCategory.ORCAMENTO_PROPOSTA).count(), 1,
                f"rodada {i}: esperava exatamente 1 Attachment ORCAMENTO_PROPOSTA, nenhuma duplicação de PDF",
            )


class ContractHttpDoubleSubmitTest(_BaseSetupMixin, TestCase):
    """TESTE 3 — HTTP DOUBLE-SUBMIT (seção 16 do protocolo P0-03)."""

    def setUp(self):
        self._build_common_fixtures()

    def test_two_equivalent_posts_to_generate_document_endpoint_stay_idempotent(self):
        opportunity, version = self._new_opportunity_with_draft_version("http")
        client = self._login(self.user)

        resp1 = client.post(
            reverse("crm:proposal_generate_document", args=[opportunity.pk]), {"document_type": "CONTRATO"}
        )
        self.assertEqual(resp1.status_code, 302)

        resp2 = client.post(
            reverse("crm:proposal_generate_document", args=[opportunity.pk]), {"document_type": "CONTRATO"}
        )
        self.assertEqual(resp2.status_code, 302)

        self.assertEqual(Contract.objects.filter(proposal_version=version).count(), 1)
        self.assertEqual(
            attachments_for(opportunity).filter(category=AttachmentCategory.CONTRATO).count(), 1,
        )
