"""
Formulários de `Maintenance`/`Cleaning` — Fase 2 (UI operacional). Nenhum
formulário aqui é `ModelForm` ligado direto ao model: cada um espelha
exatamente o contrato de dados aceito pelo service correspondente
(`NewMaintenanceData`/`CloseMaintenanceData`/`NewCleaningData`), nunca mais
nem menos campos — o service continua sendo a única autoridade de
validação de domínio; o form só existe para coletar e filtrar
(select/queryset) o que o usuário pode ESCOLHER, mesmo padrão de
`apps.operations.forms.MovementForm`/`LocationForm`.

IMPORTANTE (revisão 27/08/2026): `NewMaintenanceData` NÃO aceita
`next_due_at` — só o MODEL `Maintenance` tem esse campo, mas nenhum
service atual o preenche na abertura (e não existe service de edição
posterior). Por isso `MaintenanceOpenForm` deliberadamente NÃO tem esse
campo — adicioná-lo seria mostrar ao usuário uma opção que o service
silenciosamente ignora. O mesmo vale para `CloseMaintenanceData`: não tem
campo de observações — só `service_performed`/`condition_after`/
`return_movement`.
"""

from django import forms

from apps.accounts.models import User
from apps.equipment.models import Condition, Equipment
from apps.maintenance.models import MaintenanceStatus, MaintenanceType
from apps.maintenance.services import _RETURN_MOVEMENT_TYPES
from apps.operations.models import Movement, MovementType

FIELD_CLASS = "field-input"


class SearchableEquipmentSelect(forms.Select):
    """
    Mesma técnica de `apps.operations.forms.DestinationLocationSelect`:
    acrescenta `data-search` em cada `<option>` para a pesquisa incremental
    (JS de conveniência no template) — patrimônio + modelo, minúsculas. A
    segurança real está na queryset do campo (montada em cada form
    abaixo), não neste widget.
    """

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex=subindex, attrs=attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-search"] = f"{instance.patrimonio} {instance.model.name}".lower()
        return option


def _equipment_queryset():
    return Equipment.objects.filter(is_active=True).select_related("model", "category").order_by("patrimonio")


def _equipment_queryset_without_open_maintenance():
    """
    Mesma queryset acima, excluindo equipamentos com Maintenance ABERTA e
    ATIVA — conveniência de UX (evita o usuário escolher um equipamento
    que o service vai rejeitar de qualquer forma); NUNCA a autoridade —
    `open_maintenance()` continua checando `has_open_maintenance()` por
    conta própria, então mesmo um valor forjado direto no POST (fora
    desta queryset) seria rejeitado do mesmo jeito.
    """
    return _equipment_queryset().exclude(
        maintenances__status=MaintenanceStatus.ABERTA, maintenances__is_active=True
    ).distinct()


def _departure_movement_label(movement: Movement) -> str:
    destino = movement.destination_location_name or "—"
    return f"Envio para manutenção — {movement.created_at:%d/%m/%Y %H:%M} ({destino})"


def _return_movement_label(movement: Movement) -> str:
    destino = movement.destination_location_name or "—"
    return f"{movement.get_movement_type_display()} — {movement.created_at:%d/%m/%Y %H:%M} ({destino})"


def _movement_label(movement: Movement) -> str:
    destino = movement.destination_location_name or "—"
    return f"{movement.get_movement_type_display()} — {movement.created_at:%d/%m/%Y %H:%M} ({destino})"


def departure_movement_queryset(equipment: Equipment | None):
    """
    Candidatos SEMANTICAMENTE válidos como `departure_movement` para o
    equipamento informado — mesmas checagens de tipo/vínculo de
    `apps.maintenance.services._validate_departure_movement()` (exceto a
    de status, que só é conhecida no momento exato do submit no service —
    aqui restringimos o que É POSSÍVEL escolher, o service decide o que é
    válido AGORA). Nunca mostra Movement de outro equipamento. Sem
    equipamento escolhido ainda: queryset vazia (nunca "todos os
    Movements do sistema").
    """
    if equipment is None:
        return Movement.objects.none()
    return (
        Movement.objects.filter(
            equipment=equipment, movement_type=MovementType.ENVIO_MANUTENCAO, maintenance_as_departure__isnull=True
        )
        .order_by("-created_at")
    )


def return_movement_queryset(equipment: Equipment):
    """Mesmo raciocínio de `departure_movement_queryset()`, para o fechamento — equipamento sempre conhecido (é o da própria Maintenance)."""
    return (
        Movement.objects.filter(
            equipment=equipment, movement_type__in=_RETURN_MOVEMENT_TYPES, maintenance_as_return__isnull=True
        )
        .order_by("-created_at")
    )


class MaintenanceOpenForm(forms.Form):
    """Espelha `NewMaintenanceData` exatamente — ver docstring do módulo."""

    equipment = forms.ModelChoiceField(
        label="Equipamento",
        queryset=_equipment_queryset_without_open_maintenance(),
        widget=SearchableEquipmentSelect,
    )
    maintenance_type = forms.ChoiceField(label="Tipo", choices=MaintenanceType.choices)
    diagnosis = forms.CharField(
        label="Diagnóstico", required=False, widget=forms.Textarea(attrs={"rows": 3})
    )
    responsible = forms.ModelChoiceField(
        label="Responsável",
        queryset=User.objects.filter(is_active=True).order_by("first_name", "username"),
    )
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    departure_movement = forms.ModelChoiceField(
        label="Movimentação de envio (opcional)",
        queryset=Movement.objects.none(),
        required=False,
        help_text="Só quando o equipamento foi fisicamente enviado para manutenção. Deixe em branco para manutenção no próprio local.",
    )

    def __init__(self, *args, initial_equipment: Equipment | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        # Equipamento efetivamente conhecido para restringir o queryset de
        # departure_movement: do POST vinculado (self.data), ou o
        # pré-selecionado vindo da ficha do equipamento (GET inicial).
        equipment = initial_equipment
        if self.is_bound:
            equipment_id = self.data.get("equipment")
            if equipment_id:
                equipment = Equipment.objects.filter(pk=equipment_id, is_active=True).first()

        self.fields["departure_movement"].queryset = departure_movement_queryset(equipment)
        self.fields["departure_movement"].label_from_instance = _departure_movement_label

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", FIELD_CLASS)


class MaintenanceCloseForm(forms.Form):
    """Espelha `CloseMaintenanceData` exatamente — sem campo de observações (o contrato não aceita)."""

    service_performed = forms.CharField(label="Serviço executado", widget=forms.Textarea(attrs={"rows": 3}))
    condition_after = forms.ChoiceField(
        label="Condição após a manutenção", choices=[("", "Sem alteração")] + list(Condition.choices), required=False
    )
    return_movement = forms.ModelChoiceField(
        label="Movimentação de retorno (opcional)",
        queryset=Movement.objects.none(),
        required=False,
        help_text="Só quando o equipamento já retornou fisicamente. Deixe em branco se ainda não houve retorno.",
    )

    def __init__(self, *args, equipment: Equipment, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["return_movement"].queryset = return_movement_queryset(equipment)
        self.fields["return_movement"].label_from_instance = _return_movement_label
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", FIELD_CLASS)


class MaintenanceCancelForm(forms.Form):
    """
    `cancel_maintenance()` aceita `reason=""` (opcional no service) — mas
    esta TELA exige um motivo explícito (política de UX pedida na
    revisão, não uma regra de domínio nova: `min_length` aqui não duplica
    nem contradiz o service, só é mais estrita para quem passa por esta
    tela específica).
    """

    reason = forms.CharField(
        label="Motivo do cancelamento", widget=forms.Textarea(attrs={"rows": 2}), min_length=3
    )
    confirm = forms.BooleanField(label="Confirmo o cancelamento desta manutenção.", required=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].widget.attrs.setdefault("class", FIELD_CLASS)


class CleaningForm(forms.Form):
    """Espelha `NewCleaningData` exatamente."""

    equipment = forms.ModelChoiceField(
        label="Equipamento",
        queryset=_equipment_queryset(),
        widget=SearchableEquipmentSelect,
    )
    performed_at = forms.DateTimeField(
        label="Data/hora realizada",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Em branco usa o momento do registro.",
    )
    responsible = forms.ModelChoiceField(
        label="Responsável",
        queryset=User.objects.filter(is_active=True).order_by("first_name", "username"),
    )
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    next_due_at = forms.DateField(
        label="Próxima higienização (opcional)", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    movement = forms.ModelChoiceField(
        label="Movimentação associada (opcional)",
        queryset=Movement.objects.none(),
        required=False,
        help_text="Só quando a higienização coincidiu com uma movimentação física. Qualquer tipo é aceito.",
    )

    def __init__(self, *args, initial_equipment: Equipment | None = None, **kwargs):
        super().__init__(*args, **kwargs)

        equipment = initial_equipment
        if self.is_bound:
            equipment_id = self.data.get("equipment")
            if equipment_id:
                equipment = Equipment.objects.filter(pk=equipment_id, is_active=True).first()

        if equipment is not None:
            self.fields["movement"].queryset = Movement.objects.filter(equipment=equipment).order_by("-created_at")
        self.fields["movement"].label_from_instance = _movement_label

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", FIELD_CLASS)


class CleaningCancelForm(forms.Form):
    """`cancel_cleaning()` não aceita motivo — só confirmação explícita."""

    confirm = forms.BooleanField(label="Confirmo o cancelamento deste registro de higienização.", required=True)
