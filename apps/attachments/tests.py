"""
Testes de `apps.attachments` — implementação mínima real (14/09/2026, ver
docstring de `apps/attachments/models.py`). Cobre só o service/model em
si; o fluxo real de criação (emissão de proposta/contrato) é testado em
`apps.crm.tests.test_proposal_services`.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.attachments.models import Attachment, AttachmentCategory, AttachmentSource
from apps.attachments.services import NewAttachmentData, attachments_for, create_attachment
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, Opportunity, OpportunityStage

User = get_user_model()


class CreateAttachmentTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="anexo_user", password="x")
        client_obj = Client.objects.create(company_name="Cliente Anexo")
        source = CommercialSource.objects.create(name="Site")
        stage = OpportunityStage.objects.create(name="Novo", order=1)
        self.opportunity = Opportunity.objects.create(
            client=client_obj, title="Oportunidade Anexo", owner=self.user, source=source,
            business_type=BusinessType.LOCACAO, stage=stage, created_by=self.user,
        )

    def test_create_attachment_links_to_generic_object(self):
        attachment = create_attachment(
            NewAttachmentData(
                content_object=self.opportunity,
                category=AttachmentCategory.ORCAMENTO_PROPOSTA,
                created_by=self.user,
                file_content=b"%PDF-1.4 fake",
                filename="teste.pdf",
            )
        )
        self.assertEqual(attachment.content_object, self.opportunity)
        self.assertEqual(attachment.source, AttachmentSource.SYSTEM)
        self.assertTrue(attachment.file.name.endswith("teste.pdf"))

    def test_attachments_for_filters_by_object(self):
        other_opportunity = Opportunity.objects.create(
            client=self.opportunity.client, title="Outra", owner=self.user, source=self.opportunity.source,
            business_type=BusinessType.LOCACAO, stage=self.opportunity.stage, created_by=self.user,
        )
        create_attachment(
            NewAttachmentData(
                content_object=self.opportunity, category=AttachmentCategory.CONTRATO, created_by=self.user,
                file_content=b"a", filename="a.pdf",
            )
        )
        create_attachment(
            NewAttachmentData(
                content_object=other_opportunity, category=AttachmentCategory.CONTRATO, created_by=self.user,
                file_content=b"b", filename="b.pdf",
            )
        )
        self.assertEqual(attachments_for(self.opportunity).count(), 1)
        self.assertEqual(attachments_for(other_opportunity).count(), 1)

    def test_invalid_category_rejected(self):
        with self.assertRaises(ValueError):
            create_attachment(
                NewAttachmentData(
                    content_object=self.opportunity, category="NAO_EXISTE", created_by=self.user,
                    file_content=b"a", filename="a.pdf",
                )
            )

    def test_never_edited_after_creation_no_update_helper_exists(self):
        # Documenta a decisão de design (docstring de Attachment): sem
        # fluxo de edição nesta rodada — só create_attachment()/leitura.
        import apps.attachments.services as attachments_services

        self.assertFalse(hasattr(attachments_services, "update_attachment"))
