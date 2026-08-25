"""
Formulários de `Location`/`Movement` — Fase 2 (Operação). `LocationForm`
não é `ModelForm`: criação sempre passa por
`apps.operations.services.create_location()`. `MovementForm` só oferece os
seis tipos com tela autorizada nesta etapa (instalação, retirada,
transferência, retorno ao estoque, envio/retorno de manutenção) —
`MovementType.OUTRO` não tem fluxo de UI nesta etapa (existe só porque o
enum já previa o valor; ver `apps.operations.services._validate_transition`).

Dois bugs corrigidos em `MovementForm.destination_location`:

1. A lista de destino mostrava só o nome da `Location` (ex.: "Maringá"),
   insuficiente quando dois clientes diferentes têm unidades com o mesmo
   nome — `DestinationLocationSelect`/`_destination_label` rotulam
   destinos do tipo Cliente como "Cliente — Unidade".
2. O select oferecia TODOS os destinos ativos, inclusive tipos
   incompatíveis com a movimentação escolhida (ex.: unidades de cliente
   aparecendo para "Retirada"). A queryset agora é filtrada pelo
   `movement_type` já submetido (reaproveitando a MESMA regra de
   `apps.operations.services._REQUIRED_DESTINATION_TYPE` — nunca uma
   cópia divergente), inclusive excluindo a localização atual do
   equipamento para TRANSFERENCIA. Isso já rejeita no FORM (antes mesmo
   de chegar no service) um destino incompatível manipulado direto no
   POST; `create_movement()` continua sendo a autoridade final (dupla
   camada, mesmo padrão já usado em outros formulários deste app).
"""

from django import forms

from apps.clients.models import Client
from apps.operations.models import Location, LocationType, MovementType
from apps.operations.services import _REQUIRED_DESTINATION_TYPE

TEXT_INPUT_CLASS = "border border-gray-300 rounded-md px-3 py-1.5 text-sm w-full"


class DestinationLocationSelect(forms.Select):
    """
    Acrescenta `data-type="CLIENTE"/"ESTOQUE"/"MANUTENCAO"/...` em cada
    `<option>` — usado só pelo JS de conveniência do template
    (`movement_form.html`) para re-filtrar o select no navegador quando o
    usuário troca o tipo de movimentação, sem precisar de um round-trip
    ao servidor. A filtragem que REALMENTE importa (segurança) é a da
    queryset do campo, montada em `MovementForm.__init__` — funciona
    igual com JS desabilitado.
    """

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-type"] = instance.type
        return option


def _destination_label(location: Location) -> str:
    """
    Bug corrigido: o select mostrava só `location.name` (ex.: "Maringá"),
    insuficiente quando clientes diferentes têm unidades com o mesmo nome
    — unidades do tipo Cliente agora aparecem como "Cliente — Unidade".
    """
    if location.type == LocationType.CLIENTE and location.client_id:
        return f"{location.client.display_name()} — {location.name}"
    return location.name


def _destination_queryset(movement_type: str | None, *, exclude_location_id: int | None = None):
    """
    Reaproveita `apps.operations.services._REQUIRED_DESTINATION_TYPE` —
    nunca uma cópia da regra que poderia divergir com o tempo. Sem
    `movement_type` (GET inicial, antes de qualquer escolha) devolve
    todos os destinos ativos, já que ainda não há como saber qual tipo
    será escolhido; o JS de conveniência re-filtra no navegador assim que
    o usuário escolhe, e o bind em POST sempre filtra de verdade.
    """
    queryset = Location.objects.filter(is_active=True).select_related("client")
    required_type = _REQUIRED_DESTINATION_TYPE.get(movement_type)
    if required_type:
        queryset = queryset.filter(type=required_type)
    if movement_type == MovementType.TRANSFERENCIA and exclude_location_id is not None:
        queryset = queryset.exclude(pk=exclude_location_id)
    return queryset.order_by("type", "name")

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
        queryset=Location.objects.filter(is_active=True).select_related("client").order_by("type", "name"),
        widget=DestinationLocationSelect,
    )
    reason = forms.CharField(label="Observação (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, current_location=None, **kwargs):
        """
        `current_location` (a `Location` atual do equipamento sendo
        movimentado) é opcional só para não quebrar quem já instanciava
        `MovementForm()` sem argumento — mas `MovementCreateView` sempre
        passa (ver apps/operations/views.py), porque é o que permite
        excluir a localização atual das opções de TRANSFERENCIA (bug
        #7: "transferência para a mesma unidade").
        """
        super().__init__(*args, **kwargs)
        self.current_location = current_location

        # Bug corrigido: o select oferecia TODOS os destinos ativos,
        # inclusive tipos incompatíveis com o `movement_type` escolhido.
        # Num form vinculado (POST), `self.data` já tem o tipo submetido —
        # filtra a queryset de verdade, o que faz o próprio
        # `ModelChoiceField` rejeitar (antes mesmo do service) um destino
        # manipulado direto no POST que não bate com o tipo. Num form NÃO
        # vinculado (GET inicial), ainda não há tipo escolhido: mantém
        # todos os destinos ativos (o JS do template refina a exibição
        # assim que o usuário escolhe o tipo).
        movement_type = self.data.get("movement_type") if self.is_bound else None
        exclude_id = current_location.pk if current_location is not None else None
        self.fields["destination_location"].queryset = _destination_queryset(movement_type, exclude_location_id=exclude_id)
        self.fields["destination_location"].label_from_instance = _destination_label

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
