"""
Localização e movimentação — especificação, seção 6 e 8; evoluído na Fase
2 (Operação, arquitetura aprovada em 25/08/2026, v1.0 + delta v1.1).

`Location` já existia como esqueleto de schema desde a Fase 1 (mesmo
raciocínio do app `clients`: `Equipment.current_location` precisa de um
destino). Agora ganha endereço estruturado e histórico. `Movement` é
novo: evento estruturado e imutável de movimentação operacional, no
mesmo espírito de `StatusHistory`/`ConditionHistory`
(`apps.equipment.models`) — nunca editado depois de criado, sempre
gravado por um único serviço (`apps.operations.services.create_movement`).
"""

from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import User
from apps.clients.models import Client
from apps.core.models import Address, SoftDeleteModel, TimeStampedModel
from apps.equipment.models import Equipment


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
        Client,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="locations",
        help_text="Preenchido quando type=CLIENTE — cada unidade/local do cliente é uma Location própria.",
    )
    # Endereço operacional — model próprio, nunca compartilhado com o
    # endereço fiscal do cliente (v1.0, seção 6/delta v1.1, seção 5).
    # on_delete=PROTECT: excluir o Address por engano não pode arrastar a
    # Location junto.
    address = models.OneToOneField(
        Address, null=True, blank=True, on_delete=models.PROTECT, related_name="location_operational_for"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "localização"
        verbose_name_plural = "localizações"
        ordering = ["name"]
        constraints = [
            # type=CLIENTE ⟺ client is not null (delta v1.1, seção 6/10) —
            # única linha, expressável em CheckConstraint real.
            models.CheckConstraint(
                check=(
                    models.Q(type=LocationType.CLIENTE, client__isnull=False)
                    | (~models.Q(type=LocationType.CLIENTE) & models.Q(client__isnull=True))
                ),
                name="location_client_matches_type",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MovementType(models.TextChoices):
    INSTALACAO = "INSTALACAO", "Instalação"
    RETIRADA = "RETIRADA", "Retirada"
    TRANSFERENCIA = "TRANSFERENCIA", "Transferência"
    RETORNO_ESTOQUE = "RETORNO_ESTOQUE", "Retorno ao estoque"
    ENVIO_MANUTENCAO = "ENVIO_MANUTENCAO", "Envio para manutenção"
    RETORNO_MANUTENCAO = "RETORNO_MANUTENCAO", "Retorno da manutenção"
    OUTRO = "OUTRO", "Outro"


class Movement(models.Model):
    """
    Evento de movimentação operacional — imutável após criado. Único
    caminho suportado para criar um registro aqui:
    `apps.operations.services.create_movement()` (nunca
    `Movement.objects.create()` direto em view/form — mesma disciplina de
    `StatusHistory`/`ConditionHistory`).

    `origin_location`/`destination_location` são FKs vivas (navegação e
    integridade); os quatro campos `*_name` abaixo são um snapshot
    imutável, preenchido uma única vez no momento da criação, para a
    timeline continuar representando corretamente o que foi registrado
    mesmo que a `Location`/`Client` referenciados sejam renomeados depois
    (delta v1.1, seção 3/4). `Movement.client` foi deliberadamente NÃO
    incluído — ver delta v1.1, seção 3 (seria ambíguo: "cliente" pode
    significar origem ou destino dependendo do tipo de movimentação).
    """

    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)

    origin_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="movements_from"
    )
    destination_location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.PROTECT, related_name="movements_to"
    )

    # Snapshot histórico — só nome (não endereço completo: a timeline não
    # exibe mais que isso, ver delta v1.1 seção 4). Nunca recalculado
    # depois de gravado.
    origin_location_name = models.CharField(max_length=150, blank=True)
    destination_location_name = models.CharField(max_length=150, blank=True)
    origin_client_name = models.CharField(max_length=200, blank=True)
    destination_client_name = models.CharField(max_length=200, blank=True)

    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="movements_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "movimentação"
        verbose_name_plural = "movimentações"
        ordering = ["-created_at"]
        constraints = [
            # Motivo obrigatório só para "Outro" (delta v1.1, seção 5) —
            # mesma linha (movement_type, reason), expressável em CheckConstraint real.
            models.CheckConstraint(
                check=~models.Q(movement_type=MovementType.OUTRO) | ~models.Q(reason=""),
                name="movement_outro_requires_reason",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.equipment.patrimonio}: {self.get_movement_type_display()}"
