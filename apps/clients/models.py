"""
Cliente — especificação, seção 6 e 8.

Schema já entra na Fase 1 (porque `Equipment.current_client` precisa
apontar para algum lugar), mas o uso operacional pleno — vincular
equipamentos, telas de cadastro, etc. — só chega na Fase 2 (backlog,
seção 21 da especificação). Por enquanto isto só existe para o schema
ficar pronto, sem exigir uma migration disruptiva mais tarde.
"""

from django.db import models

from apps.core.models import SoftDeleteModel, TimeStampedModel


class Client(TimeStampedModel, SoftDeleteModel):
    company_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, blank=True)
    document = models.CharField(max_length=30, blank=True, help_text="CNPJ/CPF, quando aplicável.")
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    contact_name = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "cliente"
        verbose_name_plural = "clientes"
        ordering = ["company_name"]

    def __str__(self) -> str:
        return self.trade_name or self.company_name
