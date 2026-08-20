"""
Localização — especificação, seção 6 e 8.

Mesmo raciocínio do app `clients`: o schema de `Location` entra na Fase 1
porque `Equipment.current_location` precisa de um destino, mas os fluxos
de movimentação/manutenção/higienização (`Movement`, `Maintenance`,
`Cleaning`) são backlog de Fase 2 (seção 21 da especificação) — as
tabelas deles chegam junto com as telas, não antes, para não migrar
schema "no escuro" sem a lógica que o acompanha.
"""

from django.db import models

from apps.clients.models import Client
from apps.core.models import SoftDeleteModel, TimeStampedModel


class LocationType(models.TextChoices):
    ESTOQUE = "ESTOQUE", "Estoque/Barracão"
    CLIENTE = "CLIENTE", "Cliente"
    MANUTENCAO = "MANUTENCAO", "Manutenção"
    TRANSPORTE = "TRANSPORTE", "Transporte"
    OUTRO = "OUTRO", "Outro"


class Location(TimeStampedModel, SoftDeleteModel):
    name = models.CharField(max_length=150)
    type = models.CharField(max_length=20, choices=LocationType.choices)
    client = models.ForeignKey(
        Client, null=True, blank=True, on_delete=models.SET_NULL, help_text="Preenchido quando type=CLIENTE."
    )
    address = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "localização"
        verbose_name_plural = "localizações"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
