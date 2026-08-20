"""
Categorias e modelos de equipamento — especificação, seção 6 e 8.

`EquipmentModel.code` é a peça central do novo padrão de patrimônio
(`LOC-{MODEL_CODE}-{SEQUENCE}`, seção 5): fica travado assim que o modelo
tiver ao menos um `Equipment` vinculado (ver `EquipmentModel.lock_reason`
e `apps/equipment/services.py`, que é quem de fato impede a edição).
"""

import re

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.utils.text import slugify
from simple_history.models import HistoricalRecords

from apps.core.models import SoftDeleteModel, TimeStampedModel

CODE_VALIDATOR = RegexValidator(
    regex=re.compile(r"^[A-Z0-9]{2,20}$"),
    message="O código deve ter de 2 a 20 caracteres, só letras maiúsculas e números, sem espaços.",
)


class Category(TimeStampedModel, SoftDeleteModel):
    """Categoria pai (ex.: Aquecedor, Climatizador). Extensível — sem limite fixo."""

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)

    class Meta:
        verbose_name = "categoria"
        verbose_name_plural = "categorias"
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class EquipmentModel(TimeStampedModel, SoftDeleteModel):
    """
    Modelo de equipamento dentro de uma categoria (ex.: "Aquecedor
    Pirâmide", code="AQCP"). Um administrador cadastra modelos novos pela
    interface — nenhum código de modelo fica fixo na aplicação.
    """

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="models")
    name = models.CharField(max_length=150, help_text="Nome de exibição, ex.: 'NI23 Big Tank'.")
    code = models.CharField(
        max_length=20,
        unique=True,
        validators=[CODE_VALIDATOR],
        help_text="Ex.: AQCP, NI23BT. Usado na composição do patrimônio. "
        "Trava para edição assim que houver um equipamento vinculado.",
    )
    manufacturer = models.CharField(max_length=150, blank=True)
    specs = models.JSONField(blank=True, default=dict, help_text="Campos livres por categoria (BTUs, voltagem, etc.).")

    # Contador interno da geração atômica de patrimônio (seção 8 da
    # especificação). Nunca editado manualmente — só via
    # apps.equipment.services.generate_patrimonio(), sob select_for_update().
    last_sequence = models.PositiveIntegerField(default=0, editable=False)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "modelo de equipamento"
        verbose_name_plural = "modelos de equipamento"
        ordering = ["category__name", "name"]

    def clean(self):
        super().clean()
        if self.code:
            self.code = self.code.upper().strip()
        if self.pk:
            original = EquipmentModel.objects.filter(pk=self.pk).first()
            if original and original.code != self.code and self.has_equipment():
                raise ValidationError(
                    {
                        "code": (
                            "Este modelo já tem equipamentos cadastrados — o código não pode "
                            "ser alterado pela interface normal (especificação, seção 8: "
                            "'Imutabilidade e reclassificação de modelo'). Isso exige um "
                            "procedimento administrativo excepcional, fora do CRUD comum."
                        )
                    }
                )

    def has_equipment(self) -> bool:
        return self.equipment_set.exists()

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"
