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
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html

from apps.catalog.models import EquipmentModel
from apps.clients.models import Client
from apps.crm.models import (
    ActivityType,
    BusinessType,
    CommercialSource,
    LossReason,
    OpportunityStage,
    PaymentMethod,
)
from apps.crm.services import DocumentType, eligible_owner_queryset
from apps.operations.forms import location_display_label
from apps.operations.models import Location

TEXT_INPUT_CLASS = "field-input"


def _apply_input_class(fields, *, skip: tuple[str, ...] = ()) -> None:
    for name, field in fields.items():
        if name in skip:
            continue
        field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class ClientAutocompleteWidget(forms.Widget):
    """
    Widget do campo "Cliente" de `OpportunityCreateForm` (CORRIGIR
    DEFINITIVAMENTE O CAMPO CLIENTE — AUTOCOMPLETE PESQUISÁVEL,
    12/09/2026). Substitui o `<select>` nativo (que era renderizado com
    TODOS os clientes ativos no HTML, potencialmente centenas/milhares)
    por um input de texto de busca + um campo oculto — a busca de
    verdade roda no backend (`OpportunityClientAutocompleteView`),
    nunca no navegador.

    O CONTRATO de validação do campo nunca muda: continua sendo um
    `forms.ModelChoiceField`, e o que chega no POST é exatamente o PK do
    `Client` (o mesmo que um `<select name="client">` sempre enviou) —
    só a APRESENTAÇÃO é diferente. `ModelChoiceField.clean()` continua
    rejeitando qualquer PK que não esteja no queryset (cliente inativo,
    inexistente, ou qualquer valor inventado no POST) exatamente como
    antes — o usuário NUNCA pode "digitar um nome e confiar que existe";
    só um resultado de verdade, clicado/selecionado no dropdown
    (`static/crm/client_autocomplete.js`), preenche o campo oculto.

    Renderiza dois `<input>`: um texto VISÍVEL (busca, sem `name` —
    nunca é enviado no POST) e um OCULTO com o `name` real do campo (é
    o único que o Django e o `ModelChoiceField` enxergam). Ao reexibir
    um form BOUND com erro em outro campo, busca o `Client` pelo PK já
    submetido para preencher o texto visível com o nome de exibição —
    sem isso o campo pareceria "esquecido" a cada erro de validação
    (mesmo comportamento que o `<select>` nativo já tinha, preservado).

    Deliberadamente SEM `required` no HTML do campo oculto — colocar
    `required` num `<input type="hidden">` é um problema conhecido do
    HTML5: o navegador não consegue focar um campo oculto para mostrar o
    aviso de validação nativo e às vezes bloqueia o envio do formulário
    silenciosamente, sem nenhuma mensagem visível. A obrigatoriedade
    continua 100% validada no backend (`ModelChoiceField(required=True)`
    já rejeita client vazio/ausente, mensagem de erro exibida do jeito
    de sempre, `field-error` abaixo do campo).
    """

    def render(self, name, value, attrs=None, renderer=None):
        display_name = ""
        client_pk = ""
        if value not in (None, ""):
            # `value` aqui é o que veio de `self.data`/POST quando o form
            # é reexibido BOUND com erro em outro campo — pode ser
            # qualquer string enviada à mão (nunca necessariamente um PK
            # válido: é exatamente o "nunca confiar em texto digitado"
            # que este widget existe para impedir). Um valor não-numérico
            # (ex.: o próprio nome do cliente, digitado sem selecionar
            # nada do dropdown) faria `Client.objects.filter(pk=value)`
            # levantar `ValueError` (PK é inteiro) — tratado aqui como
            # "nenhum cliente", nunca refletido de volta como se fosse
            # uma seleção válida.
            try:
                client = Client.objects.filter(pk=value).first()
            except (ValueError, TypeError):
                client = None
            if client is not None:
                client_pk = client.pk
                display_name = client.display_name()

        widget_id = (attrs or {}).get("id") or f"id_{name}"
        # `data-client-autocomplete-url`: endpoint de busca (ver
        # `apps.crm.views.OpportunityClientAutocompleteView`) — sem este
        # atributo `static/crm/client_autocomplete.js` não tem para onde
        # mandar a requisição (`wrapper.getAttribute("data-client-
        # autocomplete-url")`) e o campo fica sem funcionar.
        search_url = reverse("crm:opportunity_client_autocomplete")
        return format_html(
            '<div class="client-autocomplete" data-client-autocomplete data-client-autocomplete-url="{}">'
            '<input type="text" id="{}" class="field-input" autocomplete="off" '
            'placeholder="Pesquisar cliente..." value="{}" data-client-autocomplete-input '
            'role="combobox" aria-expanded="false" aria-autocomplete="list">'
            '<input type="hidden" name="{}" value="{}" data-client-autocomplete-hidden>'
            '<div class="client-autocomplete-dropdown" data-client-autocomplete-dropdown role="listbox" hidden></div>'
            "</div>",
            search_url,
            widget_id,
            display_name,
            name,
            client_pk,
        )


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

    # Widget custom (ver `ClientAutocompleteWidget` acima) — o campo
    # continua um `ModelChoiceField` normal (mesma validação de sempre:
    # só um PK de `Client` ativo é aceito), só a apresentação vira
    # busca em vez de `<select>` com todos os clientes.
    client = forms.ModelChoiceField(
        label="Cliente",
        queryset=Client.objects.filter(is_active=True),
        widget=ClientAutocompleteWidget(),
    )
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
    # "Valor estimado"/"Previsão de fechamento" REMOVIDOS da criação
    # (pedido de 12/09/2026: "quando colocarmos os equipamentos os
    # valores vão puxar automático... não tem necessidade de existir"
    # aqui). Continuam existindo em `Opportunity`/`OpportunityUpdateForm`
    # — só deixaram de ser pedidos NA CRIAÇÃO; editáveis depois, se
    # necessário, pela tela de edição (inalterada).
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields, skip=("client",))


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


# ---------------------------------------------------------------------------
# Produtos e Serviços / Proposta Comercial (14/09/2026) — todos `forms.Form`
# (não `ModelForm`), mesmo raciocínio de `OpportunityCreateForm`/
# `OpportunityStageChangeForm`: a escrita real sempre passa por
# `apps.crm.services` (recálculo/imutabilidade/snapshot), o form só valida
# ENTRADA.
# ---------------------------------------------------------------------------


class ProposalItemForm(forms.Form):
    """Adicionar/editar um item de `ProposalVersion` — seção 8/17/18/22."""

    equipment_model = forms.ModelChoiceField(
        label="Produto/Modelo",
        queryset=EquipmentModel.objects.filter(is_active=True).select_related("category").order_by("category__name", "name"),
        help_text="Reaproveita o catálogo real (seção 9) — nunca um LOC-* de patrimônio (seção 10).",
    )
    quantity = forms.IntegerField(label="Quantidade", min_value=1)
    unit_price = forms.DecimalField(label="Valor unitário", max_digits=10, decimal_places=2, min_value=0)
    item_discount_percent = forms.DecimalField(
        label="Desconto do item (%)", max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False
    )
    notes = forms.CharField(label="Observação", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)


class ProposalConditionsForm(forms.Form):
    """
    Condições comerciais/período/logística/financeiro/textos de uma
    `ProposalVersion` em rascunho — "Salvar rascunho" (seção 5/56/57).

    REFINAMENTO VISUAL "PRODUTOS E SERVIÇOS" (14/09/2026) — correção da
    especificação original: `price_table_label` (Tabela de preço),
    `payment_method_other` (Outra forma) e `payment_condition` (Condição)
    SAEM deste form — nenhum dos três tinha um catálogo/opções reais por
    trás (auditoria confirmou: são só `CharField` livre em
    `ProposalVersion`, sem entidade correspondente em lugar nenhum do
    projeto), e a especificação corrigida pede para não inventar um
    catálogo/estado temporário agora. Os TRÊS CAMPOS CONTINUAM EXISTINDO
    no model (`apps.crm.models.ProposalVersion`) — não é seguro nem
    pedido remover persistência só por uma mudança visual; só deixam de
    ser expostos aqui. `services.ProposalConditionsData` recebe valores
    vazios (`""`) para os três — seus próprios defaults já cobrem isso
    (ver `ProposalConditionsSaveView.post()`).

    `payment_method` continua existindo e agora é o ÚNICO campo do bloco
    "Condições comerciais" — condições específicas de pagamento (ex.:
    "50% de entrada via PIX e 50% em boleto para 28 dias") passam a ser
    registradas no já existente `payment_info_notes` ("Informações de
    valor e pagamento", abaixo), que já cobria esse propósito. A opção
    "Outro" é removida das escolhas oferecidas aqui (`_PAYMENT_METHOD_CHOICES`)
    porque, sem `payment_method_other`/lógica condicional (explicitamente
    proibida pela correção), selecionar "Outro" não teria como ser
    detalhado — ficaria um beco sem saída de validação. O valor
    `PaymentMethod.OUTRO` continua existindo no enum do model (nenhuma
    migration): só não é mais OFERECIDO nesta tela. Uma versão antiga
    que já tenha `payment_method=OUTRO` salvo continua sendo aceita
    normalmente por este form (não é um dos `choices`, mas o campo não é
    `ModelChoiceField` restrito — é `ChoiceField` só para o WIDGET; o
    valor gravado no banco não muda por reabrir o formulário).
    """

    payment_method = forms.ChoiceField(
        label="Forma de pagamento",
        choices=(("", "—"),) + tuple((value, label) for value, label in PaymentMethod.choices if value != PaymentMethod.OUTRO),
        required=False,
    )

    contracted_start_date = forms.DateField(label="Início do contrato", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    contracted_end_date = forms.DateField(label="Fim do contrato", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_delivery_date = forms.DateField(label="Entrega prevista", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_delivery_time = forms.TimeField(label="Horário de entrega", required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    expected_pickup_date = forms.DateField(label="Retirada prevista", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_pickup_time = forms.TimeField(label="Horário de retirada", required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    delivery_location = forms.ModelChoiceField(
        label="Local de entrega/operação",
        # `active_sibling_count` alimenta `location_display_label` (mesma
        # annotation de `apps.operations.forms._destination_queryset`,
        # sem cópia divergente da lógica) — evita 1 query extra por
        # opção do select ao decidir "só o cliente" vs "Cliente —
        # Unidade".
        queryset=Location.objects.filter(is_active=True)
        .select_related("client")
        .annotate(
            active_sibling_count=Count(
                "client__locations", filter=Q(client__locations__is_active=True), distinct=True
            )
        )
        .order_by("type", "name"),
        required=False,
        help_text="Reaproveita Location real (seção 41) — nunca sobrescreve o endereço fiscal do cliente.",
    )

    general_discount = forms.DecimalField(label="Desconto geral (R$)", max_digits=12, decimal_places=2, min_value=0, required=False)
    interest_amount = forms.DecimalField(label="Juros (R$)", max_digits=12, decimal_places=2, min_value=0, required=False)
    freight_amount = forms.DecimalField(label="Frete (R$)", max_digits=12, decimal_places=2, min_value=0, required=False)

    special_clauses = forms.CharField(label="Cláusulas especiais", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    payment_info_notes = forms.CharField(
        label="Informações de valor e pagamento",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": "Ex.: 50% de entrada via PIX e 50% em boleto para 28 dias.",
            }
        ),
        help_text="Condições específicas de pagamento/parcelamento entram aqui (texto livre) — complementa 'Forma de pagamento' acima.",
    )
    general_notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)
        self.fields["delivery_location"].label_from_instance = location_display_label

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("contracted_start_date")
        end = cleaned.get("contracted_end_date")
        if start and end and end < start:
            self.add_error("contracted_end_date", "A data final contratada não pode ser anterior à data inicial.")
        return cleaned


class DocumentGenerationForm(forms.Form):
    """Dropdown "Gerar documento" (seção 6/64/65)."""

    document_type = forms.ChoiceField(label="Tipo de documento", choices=DocumentType.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)


class AcceptProposalVersionForm(forms.Form):
    """
    Aceite de uma versão (seção 71-74). `proposal_version`/`stage` são
    restritos por queryset pela VIEW (que conhece a Opportunity) — este
    form só valida o formato do POST.
    """

    proposal_version = forms.IntegerField(widget=forms.HiddenInput)
    stage = forms.ModelChoiceField(
        label="Etapa de ganho", queryset=OpportunityStage.objects.filter(is_active=True, is_won=True).order_by("order", "name")
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields, skip=("proposal_version",))
