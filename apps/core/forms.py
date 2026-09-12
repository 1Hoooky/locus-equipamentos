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
        labels = {
            "cep": "CEP",
            "logradouro": "Logradouro",
            "numero": "Número",
            "complemento": "Complemento",
            "bairro": "Bairro",
            "cidade": "Cidade",
            "uf": "UF",
            "reference_notes": "Observações de referência",
        }
        widgets = {"reference_notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class HardDeleteConfirmForm(forms.Form):
    """
    Formulário mínimo de confirmação reaproveitado pelas 3 telas de
    exclusão definitiva (`ClientHardDeleteView`/`EquipmentHardDeleteView`/
    `OpportunityHardDeleteView`, rodada "HARD DELETE DURANTE
    DESENVOLVIMENTO", 11/09/2026) — mesmo padrão já usado por
    `apps.equipment.forms.SupersedeEquipmentForm.confirm_reprint` para
    uma ação excepcional de um único clique: um checkbox obrigatório,
    nunca um `window.confirm()` de JS nem um "digite o nome para
    confirmar" (a tela já mostra a prévia de impacto antes do checkbox —
    dado suficiente para uma decisão informada, sem fricção extra).
    """

    confirm = forms.BooleanField(
        label=(
            "Confirmo que quero excluir definitivamente este registro (e os dependentes exclusivos "
            "listados acima) e entendo que esta ação NÃO pode ser desfeita."
        ),
        required=True,
    )
