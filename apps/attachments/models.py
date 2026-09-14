"""
Anexos — implementação mínima real (14/09/2026).

`apps.attachments` existia só como esqueleto vazio (nenhum model, nenhuma
migração) desde a fundação do projeto — o README documentava
explicitamente "Reservado para fotos/anexos — ainda não implementado".

A especificação de Produtos e Serviços/Proposta Comercial (seção 69) pede
integração OBRIGATÓRIA com um "módulo existente" de Anexos ("Não criar
storage paralelo") e a aba "Anexos" do Hub da Oportunidade (seção 2/3)
como se esse módulo já existisse. A auditoria desta rodada confirmou que
ele não existe — decisão tomada (documentada em
`RELATORIO_PRODUTOS_SERVICOS.md`): implementar aqui, agora, o modelo
MÍNIMO necessário para PDFs de Proposta/Contrato terem um lugar real de
armazenamento, em vez de (a) inventar um segundo local de armazenamento
dentro de `apps.crm` (violaria a própria regra "não criar storage
paralelo" na direção oposta) ou (b) bloquear a tarefa inteira numa
pergunta ao usuário sobre um app que já estava previsto na arquitetura
desde a Fase 1.

Desenho deliberadamente pequeno — só o suficiente para PDFs de
Proposta/Contrato (e, no futuro, fotos de equipamento/outros anexos)
terem onde viver, sem inventar recursos não pedidos (galeria, versionamento
de arquivo, aprovação, etc.):

- `GenericForeignKey` (não uma FK direta só para `Opportunity`): o
  próprio nome do app e o README ("fotos/anexos") sempre previram uso por
  mais de um domínio (equipamento, cliente, oportunidade...) — uma FK
  fixa a um único model exigiria uma segunda tabela/():model quando o
  próximo consumidor aparecesse, exatamente a duplicação que a
  especificação pede para evitar.
- `category`/`source` como `TextChoices` pequenos e fechados (não uma
  entidade configurável como `CommercialSource`): a especificação já diz
  exatamente quais categorias existem hoje ("Orçamento/Proposta",
  "Contrato") — nada a administrar pela interface ainda.
- Sem soft delete/histórico: nenhum fluxo de editar/excluir anexo foi
  pedido nesta rodada (mesmo raciocínio já usado em
  `apps.crm.models.CommercialActivity` — infraestrutura sem uso real de
  escrita não é criada agora).
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.accounts.models import User


class AttachmentCategory(models.TextChoices):
    ORCAMENTO_PROPOSTA = "ORCAMENTO_PROPOSTA", "Orçamento/Proposta"
    CONTRATO = "CONTRATO", "Contrato"
    OUTRO = "OUTRO", "Outro"


class AttachmentSource(models.TextChoices):
    SYSTEM = "SYSTEM", "Gerado pelo sistema"
    USER = "USER", "Enviado por usuário"


def _attachment_upload_to(instance: "Attachment", filename: str) -> str:
    # attachments/<app_label>/<model>/<object_id>/<filename> — namespace
    # simples por dono, sem depender de nenhuma lógica de negócio deste
    # app (ele não sabe nada sobre Opportunity/Proposal, deliberadamente).
    return f"attachments/{instance.content_type.app_label}/{instance.content_type.model}/{instance.object_id}/{filename}"


class Attachment(models.Model):
    """
    Um arquivo anexado a qualquer objeto do sistema (hoje: `Opportunity`,
    via Proposta/Contrato do CRM). Nunca editado depois de criado — um
    anexo substituído é um novo `Attachment`, o antigo continua existindo
    (mesmo espírito de imutabilidade de `Movement`/`StatusHistory`).
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    category = models.CharField(max_length=30, choices=AttachmentCategory.choices)
    source = models.CharField(max_length=10, choices=AttachmentSource.choices, default=AttachmentSource.SYSTEM)
    file = models.FileField(upload_to=_attachment_upload_to)
    original_filename = models.CharField(max_length=255, blank=True)
    description = models.CharField(max_length=255, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="attachments_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "anexo"
        verbose_name_plural = "anexos"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
        permissions = [
            ("view_attachments", "Pode ver anexos"),
        ]

    def __str__(self) -> str:
        return self.original_filename or f"Anexo #{self.pk}"
