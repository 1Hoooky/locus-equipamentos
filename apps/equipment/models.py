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

import uuid

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


class EquipmentBatch(models.Model):
    """
    Registro mínimo de UMA operação de "adicionar equipamentos em lote"
    (melhoria operacional da Fase 1, pedida em 25/08/2026, depois do
    congelamento original).

    Não é uma segunda arquitetura de auditoria de criação: quem/quando
    criou cada unidade continua sendo `Equipment.created_by`/`created_at`,
    exatamente como no cadastro individual — `apps.equipment.services.
    create_equipment_batch()` só chama `create_equipment()` `quantity`
    vezes, sem duplicar nada disso. Este model existe para resolver um
    problema distinto: depois que o lote é criado, como localizar de novo
    "quais equipamentos nasceram juntos nesta operação", para as ações de
    "ver equipamentos deste lote" e "exportar etiquetas/QR só deste lote".

    Deliberadamente NÃO usamos o intervalo numérico de `model_sequence`
    para isso, mesmo a operação de lote sendo atômica e livre de corrida
    (mesmo `select_for_update()` de `create_equipment()`): um equipamento
    pode ser reclassificado para OUTRO modelo depois
    (`services.reclassify_model()`), o que o tiraria silenciosamente do
    intervalo original — efeito colateral de uma regra pensada para outra
    finalidade (corrigir classificação errada), não uma decisão real sobre
    associação de lote. A FK direta `Equipment.batch` é uma marca
    permanente e explícita, no mesmo espírito de `patrimonio`/
    `model_sequence` (imutáveis após a criação, nunca expostos em nenhum
    formulário de edição).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model = models.ForeignKey(EquipmentModel, on_delete=models.PROTECT, related_name="equipment_batches")
    quantity = models.PositiveIntegerField()
    condition = models.CharField(max_length=20, choices=Condition.choices)
    first_patrimonio = models.CharField(max_length=40)
    last_patrimonio = models.CharField(max_length=40)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="equipment_batches_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "lote de cadastro de equipamentos"
        verbose_name_plural = "lotes de cadastro de equipamentos"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Lote {self.model.code} x{self.quantity} ({self.first_patrimonio} → {self.last_patrimonio})"


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
    # editable=False (Fase 2, delta v1.1 seção 1): current_client é campo
    # DERIVADO de current_location.client, só escrito por
    # apps.operations.services.create_movement() dentro do mesmo save()
    # que current_location — nunca editável isoladamente por form/admin.
    current_client = models.ForeignKey(
        "clients.Client",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="equipment_with_client",
        editable=False,
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

    # Preenchido só quando o equipamento nasce via cadastro em lote
    # (services.create_equipment_batch()) — nulo para cadastro individual
    # e para toda a base existente antes desta melhoria. Nunca exposto em
    # formulário de edição (mesmo raciocínio de patrimonio/model_sequence).
    batch = models.ForeignKey(
        EquipmentBatch, null=True, blank=True, on_delete=models.SET_NULL, related_name="equipment_items", editable=False
    )

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


class StatusHistory(models.Model):
    """
    Evento estruturado de mudança de status — especificação, seções 6, 8 e
    16 ("Eventos estruturados de domínio"). Complementa (não substitui) o
    snapshot genérico do django-simple-history: aqui o `reason` é sempre
    obrigatório e o registro é sempre criado pelo mesmo caminho
    (`apps.equipment.services.change_status()`), nunca por edição direta —
    é o que garante consistência (seção 8 do pedido de fechamento da Fase 1).
    """

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="status_history")
    old_value = models.CharField(max_length=20, choices=Status.choices)
    new_value = models.CharField(max_length=20, choices=Status.choices)
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="status_changes")
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    class Meta:
        verbose_name = "histórico de status"
        verbose_name_plural = "histórico de status"
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return f"{self.equipment.patrimonio}: {self.old_value} → {self.new_value}"


class ConditionHistory(models.Model):
    """Evento estruturado de mudança de condição — mesmo raciocínio de `StatusHistory`."""

    equipment = models.ForeignKey(Equipment, on_delete=models.CASCADE, related_name="condition_history")
    old_value = models.CharField(max_length=20, choices=Condition.choices)
    new_value = models.CharField(max_length=20, choices=Condition.choices)
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="condition_changes")
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

    class Meta:
        verbose_name = "histórico de condição"
        verbose_name_plural = "histórico de condição"
        ordering = ["-changed_at"]

    def __str__(self) -> str:
        return f"{self.equipment.patrimonio}: {self.old_value} → {self.new_value}"
