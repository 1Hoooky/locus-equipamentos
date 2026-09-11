"""
Formulários do CRM (LocusHub, Etapa 1).

`Opportunity` usa `forms.Form` (não `ModelForm`) + os services de
`apps/crm/services.py` — mesmo raciocínio já usado em
`apps.clients.forms.ClientForm`/`apps.operations.services`: a criação/
edição real tem regras de negócio (elegibilidade de `owner`, `client`
imutável após criado, `stage`/ganho/perda exclusivos de
`change_opportunity_stage()`) que não cabem, com segurança, num
`ModelForm` genérico — o form só valida ENTRADA, o service decide o que
de fato é permitido escrever.

`CommercialSource`/`OpportunityStage`/`LossReason` são configuração
simples (mesmo formato de `Category`, `apps.catalog.forms`) — `ModelForm`
comum é suficiente e correto: não há regra de negócio além do que já está
em `Meta.permissions`/`clean()` do próprio modelo.
"""

from django import forms

from apps.clients.models import Client
from apps.crm.models import ActivityType, BusinessType, CommercialSource, LossReason, OpportunityStage
from apps.crm.services import eligible_owner_queryset

TEXT_INPUT_CLASS = "field-input"


def _apply_input_class(fields, *, skip: tuple[str, ...] = ()) -> None:
    for name, field in fields.items():
        if name in skip:
            continue
        field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


# ---------------------------------------------------------------------------
# Oportunidade
# ---------------------------------------------------------------------------


class OpportunityCreateForm(forms.Form):
    """
    `title` usa o rótulo "Nome da oportunidade" (em vez de "Título",
    usado em `OpportunityUpdateForm`) — pedido explícito da rodada de
    "criação rápida em drawer" (11/09/2026): o rótulo aparece tanto no
    drawer quanto na rota tradicional `/crm/oportunidades/nova/`, que
    reaproveita este MESMO form — nenhuma duplicação de label entre os
    dois pontos de entrada. Puramente texto de UI; não afeta validação
    nem o nome real do campo (`title`, inalterado em `NewOpportunityData`/
    `Opportunity`).
    """

    client = forms.ModelChoiceField(label="Cliente", queryset=Client.objects.filter(is_active=True).order_by("company_name"))
    title = forms.CharField(label="Nome da oportunidade", max_length=200)
    owner = forms.ModelChoiceField(label="Responsável comercial", queryset=eligible_owner_queryset())
    source = forms.ModelChoiceField(
        label="Origem", queryset=CommercialSource.objects.filter(is_active=True).order_by("order", "name")
    )
    business_type = forms.ChoiceField(label="Tipo de negócio", choices=BusinessType.choices)
    stage = forms.ModelChoiceField(
        label="Etapa inicial",
        queryset=OpportunityStage.objects.filter(is_active=True, is_won=False, is_lost=False).order_by("order", "name"),
        help_text="Só etapas ativas que não são de ganho/perda — uma oportunidade nunca nasce ganha ou perdida.",
    )
    expected_close_date = forms.DateField(label="Previsão de fechamento", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    estimated_value = forms.DecimalField(label="Valor estimado", max_digits=12, decimal_places=2, required=False, min_value=0)
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)


class OpportunityUpdateForm(forms.Form):
    title = forms.CharField(label="Título", max_length=200)
    owner = forms.ModelChoiceField(label="Responsável comercial", queryset=eligible_owner_queryset())
    source = forms.ModelChoiceField(
        label="Origem", queryset=CommercialSource.objects.filter(is_active=True).order_by("order", "name")
    )
    business_type = forms.ChoiceField(label="Tipo de negócio", choices=BusinessType.choices)
    expected_close_date = forms.DateField(label="Previsão de fechamento", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    estimated_value = forms.DecimalField(label="Valor estimado", max_digits=12, decimal_places=2, required=False, min_value=0)
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        # `owner_instance`/`source_instance` (opcional): quando o
        # `owner`/`source` ATUAL da oportunidade não está mais nos
        # querysets padrão (usuário desativado depois, ou origem
        # desativada depois) o form ainda precisa conseguir exibir o
        # valor atual como selecionado — sem isso o campo apareceria
        # em branco/inválido só por editar uma oportunidade antiga.
        owner_instance = kwargs.pop("owner_instance", None)
        source_instance = kwargs.pop("source_instance", None)
        super().__init__(*args, **kwargs)
        if owner_instance is not None and not self.fields["owner"].queryset.filter(pk=owner_instance.pk).exists():
            self.fields["owner"].queryset = self.fields["owner"].queryset | type(owner_instance).objects.filter(
                pk=owner_instance.pk
            )
        if source_instance is not None and not self.fields["source"].queryset.filter(pk=source_instance.pk).exists():
            self.fields["source"].queryset = self.fields["source"].queryset | type(source_instance).objects.filter(
                pk=source_instance.pk
            )
        _apply_input_class(self.fields)


class OpportunityStageChangeForm(forms.Form):
    """
    Form único de mudança de etapa — cobre etapa intermediária, ganho e
    perda (a diferença é só QUAIS campos extras a etapa escolhida exige;
    ver `clean()`). `stage` inclui TODAS as etapas ativas (intermediárias
    + ganho + perda) — a tela decide, via JS opcional/progressive
    enhancement, mostrar/esconder `loss_reason`/`loss_notes`/
    `closed_value` conforme a etapa escolhida, mas a validação real
    (campo obrigatório em etapa de perda) é sempre no backend, aqui e em
    `apps.crm.services.change_opportunity_stage()` — nunca só no HTML.
    """

    stage = forms.ModelChoiceField(
        label="Nova etapa", queryset=OpportunityStage.objects.filter(is_active=True).order_by("order", "name")
    )
    reason = forms.CharField(label="Observação da transição", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    loss_reason = forms.ModelChoiceField(
        label="Motivo da perda",
        queryset=LossReason.objects.filter(is_active=True).order_by("order", "name"),
        required=False,
    )
    loss_notes = forms.CharField(label="Observação da perda", required=False, widget=forms.Textarea(attrs={"rows": 2}))
    closed_value = forms.DecimalField(label="Valor de fechamento", max_digits=12, decimal_places=2, required=False, min_value=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)

    def clean(self):
        cleaned = super().clean()
        stage = cleaned.get("stage")
        if stage is not None and stage.is_lost and not cleaned.get("loss_reason"):
            self.add_error("loss_reason", "Motivo de perda é obrigatório ao marcar a oportunidade como perdida.")
        return cleaned


# ---------------------------------------------------------------------------
# Atividade comercial
# ---------------------------------------------------------------------------


class CommercialActivityForm(forms.Form):
    activity_type = forms.ChoiceField(label="Tipo", choices=ActivityType.choices)
    description = forms.CharField(label="Descrição", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    occurred_at = forms.DateTimeField(
        label="Quando aconteceu", required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"})
    )
    scheduled_for = forms.DateTimeField(
        label="Próximo passo agendado para",
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        help_text="Alimentará a futura Agenda Central — nenhuma agenda existe ainda nesta etapa.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)


# ---------------------------------------------------------------------------
# Configuração comercial — Origem, Etapa, Motivo de perda
# ---------------------------------------------------------------------------


class CommercialSourceForm(forms.ModelForm):
    class Meta:
        model = CommercialSource
        fields = ("name", "order", "is_active")
        labels = {"name": "Nome", "order": "Ordem", "is_active": "Ativo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields, skip=("is_active",))


class OpportunityStageForm(forms.ModelForm):
    class Meta:
        model = OpportunityStage
        fields = ("name", "order", "is_won", "is_lost", "is_active")
        labels = {
            "name": "Nome",
            "order": "Ordem",
            "is_won": "É etapa de ganho",
            "is_lost": "É etapa de perda",
            "is_active": "Ativo",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields, skip=("is_won", "is_lost", "is_active"))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_won") and cleaned.get("is_lost"):
            self.add_error("is_lost", "Uma etapa não pode ser simultaneamente de ganho e de perda.")
        return cleaned


class LossReasonForm(forms.ModelForm):
    class Meta:
        model = LossReason
        fields = ("name", "order", "is_active")
        labels = {"name": "Nome", "order": "Ordem", "is_active": "Ativo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields, skip=("is_active",))
