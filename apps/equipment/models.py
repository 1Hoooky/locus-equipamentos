"""
Equipamento — especificação, seções 5, 6 e 8.

Pontos que este arquivo protege deliberadamente:
- `patrimonio` e `model_sequence` são preenchidos uma única vez, na
  criação, pelo serviço em `apps/equipment/services.py`. Não são
  `editable=False` por acidente — é para que nenhuma tela de edição normal
  consiga alterá-los, mesmo por engano.
- O sistema nunca "faz parsing" do patrimônio para descobrir o modelo — a
  fonte da verdade é sempre a FK `model`.
- `superseded_by` só é usado no procedimento excepcional de reemissão de
  patrimônio (seção 8) — nunca em fluxo normal.
"""

from django.core.exceptions import ValidationError
from django.db import models
from simple_history.models import HistoricalRecords

from apps.accounts.models import User
from apps.catalog.models import Category, EquipmentModel
from apps.core.models import SoftDeleteModel, TimeStampedModel


class Status(models.TextChoices):
    DISPONIVEL = "DISPONIVEL", "Disponível"
    EM_OPERACAO = "EM_OPERACAO", "Em operação"
    MANUTENCAO = "MANUTENCAO", "Manutenção"
    INATIVO = "INATIVO", "Inativo"


class Condition(models.TextChoices):
    BOM = "BOM", "Bom"
    MEDIO = "MEDIO", "Médio"
    RUIM = "RUIM", "Ruim"
    INUTILIZAVEL = "INUTILIZAVEL", "Inutilizável"


class Equipment(TimeStampedModel, SoftDeleteModel):
    # --- Identidade permanente ---------------------------------------
    patrimonio = models.CharField(max_length=40, unique=True, editable=False)
    model = models.ForeignKey(EquipmentModel, on_delete=models.PROTECT)
    model_sequence = models.PositiveIntegerField(editable=False)

    # Denormalizado a partir de `model.category` só para acelerar busca/
    # filtro por categoria sem precisar de join — nunca é a fonte da
    # verdade (essa é sempre `model.category`).
    category = models.ForeignKey(Category, on_delete=models.PROTECT, editable=False)

    # --- Dados de aquisição --------------------------------------------
    serial_number = models.CharField(max_length=100, blank=True)
    legacy_code = models.CharField(
        max_length=100, blank=True, help_text="Código da planilha antiga, preservado só para rastreabilidade."
    )
    supplier = models.CharField(max_length=150, blank=True)
    acquisition_date = models.DateField(null=True, blank=True)
    acquisition_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # --- Estado operacional ----------------------------------------------
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DISPONIVEL)
    condition = models.CharField(max_length=20, choices=Condition.choices, default=Condition.BOM)

    # --- Localização/cliente (uso pleno a partir da Fase 2) ---------------
    current_location = models.ForeignKey(
        "operations.Location", null=True, blank=True, on_delete=models.SET_NULL, related_name="equipment_here"
    )
    current_client = models.ForeignKey(
        "clients.Client", null=True, blank=True, on_delete=models.SET_NULL, related_name="equipment_with_client"
    )

    # --- Reemissão excepcional de patrimônio (seção 8) --------------------
    superseded_by = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="supersedes"
    )

    # --- Manutenção/higienização (datas-resumo; eventos completos na Fase 2)
    last_maintenance_date = models.DateField(null=True, blank=True)
    last_cleaning_date = models.DateField(null=True, blank=True)
    next_maintenance_date = models.DateField(null=True, blank=True)

    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="equipment_created")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "equipamento"
        verbose_name_plural = "equipamentos"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["model", "model_sequence"], name="uniq_model_sequence_per_model"),
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["condition"]),
            models.Index(fields=["category"]),
        ]

    def clean(self):
        super().clean()
        if self.pk:
            original = Equipment.objects.filter(pk=self.pk).first()
            if original and (
                original.patrimonio != self.patrimonio or original.model_sequence != self.model_sequence
            ):
                raise ValidationError(
                    "Patrimônio e model_sequence são imutáveis após a criação "
                    "(especificação, seção 5 e 8). Use o fluxo de reclassificação "
                    "de modelo para corrigir uma classificação errada sem tocar "
                    "no patrimônio."
                )

    def __str__(self) -> str:
        return self.patrimonio
