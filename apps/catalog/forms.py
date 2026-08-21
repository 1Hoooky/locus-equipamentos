"""
Formulários de categoria/modelo — telas próprias do fechamento da Fase 1
(substituem o Django admin como interface operacional). `code` de
`EquipmentModel` é travado no formulário assim que o modelo já tem
equipamento vinculado — espelha `EquipmentModel.clean()`, que é quem
garante a regra de verdade (defesa em profundidade, mesmo padrão já usado
no Django admin em `apps/catalog/admin.py`).
"""

from django import forms

from apps.catalog.models import Category, EquipmentModel

TEXT_INPUT_CLASS = "border border-gray-300 rounded-md px-3 py-1.5 text-sm w-full"


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "is_active":
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class EquipmentModelForm(forms.ModelForm):
    class Meta:
        model = EquipmentModel
        fields = ("category", "name", "code", "manufacturer", "is_active")
        help_texts = {
            "code": "Usado na composição do patrimônio (LOC-{CODE}-{SEQUENCE}). Maiúsculas e números, 2 a 20 caracteres.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.has_equipment():
            self.fields["code"].disabled = True
            self.fields["code"].help_text = (
                "Travado: este modelo já tem equipamento vinculado. Corrigir o código depois "
                "disso é um procedimento administrativo excepcional, fora deste formulário "
                "(especificação, seção 8) — os patrimônios já emitidos mantêm o prefixo antigo."
            )
        for name, field in self.fields.items():
            if name != "is_active":
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
