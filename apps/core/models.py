"""
Modelos base compartilhados por todo o projeto.

Nenhum dado real deve ser excluído fisicamente quando tiver valor de
histórico (regra de negócio da especificação, seção 5). `SoftDeleteModel`
existe justamente para isso: "excluir" um registro só marca `is_active =
False`, nunca remove a linha do banco.
"""

from django.db import models


class TimeStampedModel(models.Model):
    """Adiciona `created_at`/`updated_at` automáticos a qualquer modelo."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """
    Marca de inativação em vez de exclusão física.

    Importante: isto NÃO troca o manager padrão por um que filtra
    automaticamente `is_active=True` — cada app decide explicitamente,
    nas suas próprias querysets/views, se quer ver só ativos ou tudo.
    Um manager "mágico" que esconde inativos por padrão é uma fonte
    clássica de bugs sutis (ex.: relatório que "some" com equipamentos).
    """

    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True
