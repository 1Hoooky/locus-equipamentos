"""
`AddressForm` — reaproveitado por `apps.clients` (endereço fiscal) e
`apps.operations` (endereço operacional de `Location`), mesmo raciocínio
de `apps.core.services` (um único ponto de verdade para editar um
`Address`, nunca duas implementações de formulário divergindo).
"""

from django import forms

from apps.core.models import Address

TEXT_INPUT_CLASS = "field-input"


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf", "reference_notes")
        widgets = {"reference_notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
