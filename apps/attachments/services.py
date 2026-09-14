"""
Services de `apps.attachments` — único caminho suportado para criar um
`Attachment` (nunca `Attachment.objects.create()` direto em view/service
de outro app, para manter o `upload_to`/metadados consistentes num só
lugar — mesma disciplina do resto do projeto).
"""

from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.db import models

from apps.accounts.models import User
from apps.attachments.models import Attachment, AttachmentCategory, AttachmentSource


@dataclass
class NewAttachmentData:
    content_object: models.Model
    category: str
    created_by: User
    file_content: bytes
    filename: str
    source: str = AttachmentSource.SYSTEM
    description: str = ""


def create_attachment(data: NewAttachmentData) -> Attachment:
    if data.category not in AttachmentCategory.values:
        raise ValueError(f"Categoria de anexo inválida: {data.category!r}.")
    if data.source not in AttachmentSource.values:
        raise ValueError(f"Origem de anexo inválida: {data.source!r}.")

    attachment = Attachment(
        content_object=data.content_object,
        category=data.category,
        source=data.source,
        original_filename=data.filename,
        description=data.description,
        created_by=data.created_by,
    )
    attachment.file.save(data.filename, ContentFile(data.file_content), save=False)
    attachment.save()
    return attachment


def attachments_for(content_object: models.Model):
    """Anexos de um objeto qualquer, mais recentes primeiro — leitura simples, sem paginação (volume baixo por objeto)."""
    from django.contrib.contenttypes.models import ContentType

    content_type = ContentType.objects.get_for_model(content_object)
    return Attachment.objects.filter(content_type=content_type, object_id=content_object.pk).select_related("created_by")
