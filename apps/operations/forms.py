"""
Formulários de `Location`/`Movement` — Fase 2 (Operação). `LocationForm`
não é `ModelForm`: criação sempre passa por
`apps.operations.services.create_location()`. `MovementForm` só oferece os
seis tipos com tela autorizada nesta etapa (instalação, retirada,
transferência, retorno ao estoque, envio/retorno de manutenção) —
`MovementType.OUTRO` não tem fluxo de UI nesta etapa (existe só porque o
enum já previa o valor; ver `apps.operations.services._validate_transition`).
"""

from django import forms

from apps.clients.models import Client
from apps.operations.models import Location, LocationType, MovementType

TEXT_INPUT_CLASS = "border border-gray-300 rounded-md px-3 py-1.5 text-sm w-full"

# Mesma ordem da tabela status×movimentação (delta v1.1, seção 10).
MOVEMENT_TYPE_CHOICES = [
    (MovementType.INSTALACAO, MovementType.INSTALACAO.label),
    (MovementType.RETIRADA, MovementType.RETIRADA.label),
    (MovementType.TRANSFERENCIA, MovementType.TRANSFERENCIA.label),
    (MovementType.RETORNO_ESTOQUE, MovementType.RETORNO_ESTOQUE.label),
    (MovementType.ENVIO_MANUTENCAO, MovementType.ENVIO_MANUTENCAO.label),
    (MovementType.RETORNO_MANUTENCAO, MovementType.RETORNO_MANUTENCAO.label),
]


class LocationForm(forms.Form):
    name = forms.CharField(label="Nome da unidade/local", max_length=150)
    type = forms.ChoiceField(label="Tipo", choices=LocationType.choices)
    client = forms.ModelChoiceField(
        label="Cliente",
        queryset=Client.objects.filter(is_active=True).order_by("company_name"),
        required=False,
        help_text="Obrigatório só para o tipo 'Cliente'.",
    )

    cep = forms.CharField(label="CEP", max_length=9, required=False)
    logradouro = forms.CharField(label="Logradouro", max_length=255, required=False)
    numero = forms.CharField(label="Número", max_length=20, required=False)
    complemento = forms.CharField(label="Complemento", max_length=100, required=False)
    bairro = forms.CharField(label="Bairro", max_length=100, required=False)
    cidade = forms.CharField(label="Cidade", max_length=100, required=False)
    uf = forms.CharField(label="UF", max_length=2, required=False)
    reference_notes = forms.CharField(label="Ponto de referência", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)

    def clean(self):
        # Mesma regra de apps.operations.services._validate_location_client_matches_type
        # — repetida aqui só para dar erro de campo amigável; a validação
        # que realmente decide é a do service (nunca só o form).
        cleaned = super().clean()
        type_ = cleaned.get("type")
        client = cleaned.get("client")
        if type_ == LocationType.CLIENTE and client is None:
            self.add_error("client", "Obrigatório para o tipo 'Cliente'.")
        elif type_ and type_ != LocationType.CLIENTE and client is not None:
            self.add_error("client", "Só localizações do tipo 'Cliente' podem ter um cliente vinculado.")
        return cleaned


class LocationUpdateForm(forms.Form):
    name = forms.CharField(label="Nome da unidade/local", max_length=150)
    type = forms.ChoiceField(label="Tipo", choices=LocationType.choices)
    client = forms.ModelChoiceField(
        label="Cliente",
        queryset=Client.objects.filter(is_active=True).order_by("company_name"),
        required=False,
        help_text="Obrigatório só para o tipo 'Cliente'.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)

    def clean(self):
        cleaned = super().clean()
        type_ = cleaned.get("type")
        client = cleaned.get("client")
        if type_ == LocationType.CLIENTE and client is None:
            self.add_error("client", "Obrigatório para o tipo 'Cliente'.")
        elif type_ and type_ != LocationType.CLIENTE and client is not None:
            self.add_error("client", "Só localizações do tipo 'Cliente' podem ter um cliente vinculado.")
        return cleaned


class MovementForm(forms.Form):
    movement_type = forms.ChoiceField(label="Tipo de movimentação", choices=MOVEMENT_TYPE_CHOICES)
    destination_location = forms.ModelChoiceField(
        label="Destino",
        queryset=Location.objects.filter(is_active=True).order_by("type", "name"),
    )
    reason = forms.CharField(label="Observação (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
