"""
Formulários das telas próprias de equipamento — fechamento da Fase 1
(telas de cadastro/edição, reclassificação e reemissão substituindo o
Django admin como interface operacional).

Deliberadamente NÃO expõem: `patrimonio`/`model_sequence` (imutáveis,
gerados pelo serviço), `status`/`condition` na edição (têm tela própria
com motivo obrigatório e geram `StatusHistory`/`ConditionHistory` — ver
`apps/equipment/services.py`), `current_location`/`current_client`
(uso pleno só a partir da Fase 2, fora do escopo deste fechamento).
"""

from django import forms

from apps.catalog.models import EquipmentModel
from apps.equipment.models import Condition, Equipment
from apps.equipment.services import MAX_BATCH_QUANTITY

TEXT_INPUT_CLASS = "field-input"


class EquipmentCreateForm(forms.Form):
    """
    Não é um ModelForm: a criação passa sempre por
    `apps.equipment.services.create_equipment()` (geração atômica do
    patrimônio), nunca por um `Equipment(...)` instanciado direto do
    formulário — este form só valida a entrada do usuário.
    """

    model = forms.ModelChoiceField(
        queryset=EquipmentModel.objects.filter(is_active=True).select_related("category").order_by(
            "category__name", "name"
        ),
        label="Modelo",
    )
    serial_number = forms.CharField(label="Serial do fabricante", max_length=100, required=False)
    legacy_code = forms.CharField(label="Código legado", max_length=100, required=False)
    supplier = forms.CharField(label="Fornecedor", max_length=150, required=False)
    acquisition_date = forms.DateField(label="Data de aquisição", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    acquisition_value = forms.DecimalField(label="Valor de aquisição", max_digits=10, decimal_places=2, required=False)
    condition = forms.ChoiceField(label="Condição inicial", choices=Condition.choices, initial=Condition.BOM)
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "notes":
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
            else:
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class EquipmentBatchCreateForm(forms.Form):
    """
    Cadastro em lote — mesmo raciocínio de `EquipmentCreateForm` (não é um
    ModelForm; a criação real passa por
    `apps.equipment.services.create_equipment_batch()`). Deliberadamente
    NÃO pede serial do fabricante nem código legado: são identificadores
    individuais por unidade física e não podem ser preenchidos em massa
    para um lote inteiro (pedido explícito do usuário).
    """

    model = forms.ModelChoiceField(
        queryset=EquipmentModel.objects.filter(is_active=True).select_related("category").order_by(
            "category__name", "name"
        ),
        label="Modelo",
    )
    quantity = forms.IntegerField(
        label="Quantidade",
        min_value=1,
        max_value=MAX_BATCH_QUANTITY,
        help_text=f"Máximo de {MAX_BATCH_QUANTITY} unidades por operação.",
    )
    condition = forms.ChoiceField(label="Condição inicial", choices=Condition.choices, initial=Condition.BOM)
    supplier = forms.CharField(label="Fornecedor", max_length=150, required=False)
    acquisition_date = forms.DateField(
        label="Data de aquisição", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    acquisition_value = forms.DecimalField(label="Valor de aquisição", max_digits=10, decimal_places=2, required=False)
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class EquipmentUpdateForm(forms.ModelForm):
    """
    Edição normal do equipamento — nunca toca em `model`, `patrimonio`,
    `model_sequence`, `status` ou `condition` (ver docstring do módulo).
    """

    class Meta:
        model = Equipment
        fields = ("serial_number", "legacy_code", "supplier", "acquisition_date", "acquisition_value", "notes")
        widgets = {
            "acquisition_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class ChangeStatusForm(forms.Form):
    new_status = forms.ChoiceField(label="Novo status", choices=[])
    reason = forms.CharField(label="Motivo", widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, current_status=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.equipment.models import Status

        self.fields["new_status"].choices = [c for c in Status.choices if c[0] != current_status]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class ChangeConditionForm(forms.Form):
    new_condition = forms.ChoiceField(label="Nova condição", choices=[])
    reason = forms.CharField(label="Motivo", widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, current_condition=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["new_condition"].choices = [c for c in Condition.choices if c[0] != current_condition]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class ReclassifyModelForm(forms.Form):
    new_model = forms.ModelChoiceField(
        queryset=EquipmentModel.objects.filter(is_active=True).select_related("category").order_by(
            "category__name", "name"
        ),
        label="Modelo correto",
    )
    reason = forms.CharField(label="Motivo (obrigatório)", widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, current_model=None, **kwargs):
        super().__init__(*args, **kwargs)
        if current_model is not None:
            self.fields["new_model"].queryset = self.fields["new_model"].queryset.exclude(pk=current_model.pk)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class SupersedeEquipmentForm(forms.Form):
    new_model = forms.ModelChoiceField(
        queryset=EquipmentModel.objects.filter(is_active=True).select_related("category").order_by(
            "category__name", "name"
        ),
        label="Modelo correto",
    )
    reason = forms.CharField(label="Motivo (obrigatório)", widget=forms.Textarea(attrs={"rows": 3}))
    confirm_reprint = forms.BooleanField(
        label="Confirmo que vou reimprimir a etiqueta física com o novo patrimônio.",
        required=True,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "confirm_reprint":
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
