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

from decimal import Decimal

from django import forms
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.html import format_html

from apps.catalog.models import EquipmentModel
from apps.clients.models import Client
from apps.crm.models import (
    ActivityType,
    BillingMode,
    BusinessType,
    CommercialPlan,
    CommercialSource,
    LossReason,
    OpportunityStage,
    PaymentMethod,
    ProposalItemType,
    ServiceCatalogItem,
)
from apps.crm.services import DocumentType, eligible_owner_queryset
from apps.equipment.models import Equipment, Status as EquipmentStatus
from apps.operations.forms import location_display_label
from apps.operations.models import Location, LocationType

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


class EquipmentAutocompleteWidget(forms.Widget):
    """
    Widget do campo "Equipamento" de `EquipmentLinkForm` — Aba
    "Equipamentos", RODADA 3 DE REFINAMENTOS (14/09/2026, seção 60-68).
    MESMO raciocínio/contrato de `ClientAutocompleteWidget` acima
    (reaproveita, de propósito, o CSS genérico `.client-autocomplete-*`
    de `templates/_design_tokens.html` — já documentado lá como
    "reaproveitamento futuro em outro campo de busca-e-seleção"; só os
    atributos `data-*` são próprios, para não colidir com o widget de
    Cliente se algum dia aparecerem na mesma página): dois `<input>` (um
    texto visível de busca, sem `name`; um oculto com o `name` real do
    campo), busca real no backend (`apps.crm.views.
    OpportunityEquipmentSearchView`, via `static/crm/
    equipment_link_autocomplete.js`), campo continua sendo um
    `ModelChoiceField` de verdade — o POST só pode conter um PK de
    `Equipment` já dentro do queryset restrito do form (`status=
    DISPONIVEL`), nunca um valor "confiado" de texto digitado.

    A busca precisa saber PARA QUAL Oportunidade é (`opportunity_id`,
    passado pelo form) só para montar a URL — a queryset de busca em si
    não depende da Oportunidade (qualquer patrimônio disponível pode ser
    vinculado a qualquer Oportunidade; não existe reserva de estoque por
    cliente neste projeto).
    """

    def __init__(self, *args, opportunity_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.opportunity_id = opportunity_id

    def render(self, name, value, attrs=None, renderer=None):
        display_name = ""
        equipment_pk = ""
        if value not in (None, ""):
            try:
                equipment = Equipment.objects.filter(pk=value).select_related("model").first()
            except (ValueError, TypeError):
                equipment = None
            if equipment is not None:
                equipment_pk = equipment.pk
                display_name = f"{equipment.patrimonio} — {equipment.model.name}"

        widget_id = (attrs or {}).get("id") or f"id_{name}"
        search_url = reverse("crm:opportunity_equipment_search", args=[self.opportunity_id]) if self.opportunity_id else ""
        return format_html(
            '<div class="client-autocomplete" data-equipment-autocomplete data-equipment-autocomplete-url="{}">'
            '<input type="text" id="{}" class="field-input" autocomplete="off" '
            'placeholder="Buscar por patrimônio ou número de série..." value="{}" data-equipment-autocomplete-input '
            'role="combobox" aria-expanded="false" aria-autocomplete="list">'
            '<input type="hidden" name="{}" value="{}" data-equipment-autocomplete-hidden>'
            '<div class="client-autocomplete-dropdown" data-equipment-autocomplete-dropdown role="listbox" hidden></div>'
            "</div>",
            search_url,
            widget_id,
            display_name,
            name,
            equipment_pk,
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
    # RODADA 3 (14/09/2026): `ActivityType` deixou de ser `TextChoices` e
    # virou entidade configurável (mesmo padrão de CommercialSource/
    # OpportunityStage/LossReason) — o campo agora lista só os tipos
    # ATIVOS, na mesma ordem de exibição usada nos demais seletores.
    activity_type = forms.ModelChoiceField(
        label="Tipo", queryset=ActivityType.objects.filter(is_active=True).order_by("order", "name")
    )
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


class ActivityTypeForm(forms.ModelForm):
    """
    RODADA 3 DE REFINAMENTOS (14/09/2026) — mesmo padrão exato de
    `CommercialSourceForm`/`LossReasonForm` acima; `code` nunca aparece
    aqui (não está em `fields`) — é um detalhe técnico interno, não algo
    que o Administrador edita.
    """

    class Meta:
        model = ActivityType
        fields = ("name", "order", "is_active")
        labels = {"name": "Nome", "order": "Ordem", "is_active": "Ativo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields, skip=("is_active",))


class ServiceCatalogItemForm(forms.ModelForm):
    """
    RODADA 4 (REFINAMENTO DA COMPOSIÇÃO COMERCIAL, 15/09/2026, seção 21)
    — mesmo padrão exato de `ActivityTypeForm`/`CommercialSourceForm`
    acima: entidade configurável, sem exclusão física (só `is_active`).
    """

    class Meta:
        model = ServiceCatalogItem
        fields = ("name", "order", "unit_label", "is_active")
        labels = {"name": "Nome", "order": "Ordem", "unit_label": "Unidade comercial", "is_active": "Ativo"}
        help_texts = {"unit_label": "Ex.: 'hora', 'diária', 'un' — usado como '3 horas', 'R$ 150,00/hora'."}

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
    """
    Adicionar/editar um item de `ProposalVersion` — seção 8/17/18/22.

    RODADA 4 (REFINAMENTO DA COMPOSIÇÃO COMERCIAL, 15/09/2026, seção
    18-25): passou a suportar dois tipos de item — `item_type` decide
    qual dos dois campos de referência (`equipment_model`/`service`) é
    obrigatório; os dois campos ficam sempre presentes no HTML (nenhum
    fica de fora do form só por causa do tipo escolhido), mas o `clean()`
    exige exatamente um preenchido, coerente com `item_type` — o
    JavaScript (`static/crm/proposal_composition.js`) só alterna qual
    grupo fica VISÍVEL, puramente de apresentação; a validação real é
    100% aqui + `apps.crm.services._validate_item_fields()`.
    """

    # `required=False` DE PROPÓSITO (RODADA 4, 15/09/2026): o `<select>`
    # sempre manda um valor vindo de um POST real do navegador (o campo é
    # obrigatório NA TELA — `initial=EQUIPAMENTO` garante uma opção já
    # selecionada), mas um POST que já existia ANTES desta rodada
    # (integrações, scripts, os próprios testes automatizados de rodadas
    # anteriores) nunca incluía `item_type` — exigi-lo aqui quebraria
    # esses chamadores por uma mudança que, para eles, é 100% equivalente
    # a "Equipamento" (o único tipo que existia). `clean()` abaixo aplica
    # o mesmo default `EQUIPAMENTO` quando o campo vem ausente/vazio,
    # preservando compatibilidade sem abrir mão da validação cruzada.
    item_type = forms.ChoiceField(
        label="Tipo",
        choices=ProposalItemType.choices,
        initial=ProposalItemType.EQUIPAMENTO,
        required=False,
        widget=forms.Select(attrs={"data-item-type-select": ""}),
    )
    equipment_model = forms.ModelChoiceField(
        label="Produto/Modelo",
        queryset=EquipmentModel.objects.filter(is_active=True).select_related("category").order_by("category__name", "name"),
        required=False,
        help_text="Reaproveita o catálogo real (seção 9) — nunca um LOC-* de patrimônio (seção 10).",
        widget=forms.Select(attrs={"data-item-type-field": ProposalItemType.EQUIPAMENTO}),
    )
    service = forms.ModelChoiceField(
        label="Serviço",
        queryset=ServiceCatalogItem.objects.filter(is_active=True).order_by("order", "name"),
        required=False,
        help_text="Catálogo de serviços comerciais (RODADA 4) — nunca cria/altera Equipment ou Movement.",
        widget=forms.Select(attrs={"data-item-type-field": ProposalItemType.SERVICO}),
    )
    quantity = forms.IntegerField(label="Quantidade", min_value=1)
    unit_price = forms.DecimalField(label="Valor unitário", max_digits=10, decimal_places=2, min_value=0)
    # RODADA 3 DE REFINAMENTOS (14/09/2026): desconto do item deixou de
    # ser PERCENTUAL e virou um valor MONETÁRIO em R$ (mesma unidade do
    # desconto geral, que já era R$ — experiência consistente, seção
    # 51-60). `max_value` fixo não existe mais (o teto é dinâmico: nunca
    # maior que o bruto quantidade × valor unitário — validado em
    # `clean()` abaixo E de novo em `apps.crm.services._validate_item_fields()`,
    # mesma defesa em profundidade já usada noutros forms do projeto).
    item_discount_amount = forms.DecimalField(
        label="Desconto do item (R$)", max_digits=10, decimal_places=2, min_value=0, required=False
    )
    notes = forms.CharField(label="Observação", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)

    def clean(self):
        cleaned = super().clean()
        # Default de compatibilidade (ver comentário do campo acima):
        # ausente/vazio vira EQUIPAMENTO, nunca um erro de validação.
        item_type = cleaned.get("item_type") or ProposalItemType.EQUIPAMENTO
        cleaned["item_type"] = item_type
        equipment_model = cleaned.get("equipment_model")
        service = cleaned.get("service")
        if item_type == ProposalItemType.SERVICO:
            if service is None:
                self.add_error("service", "Selecione um serviço do catálogo.")
            if equipment_model is not None:
                self.add_error("equipment_model", "Um item de Serviço não pode ter um Modelo selecionado.")
        elif item_type == ProposalItemType.EQUIPAMENTO:
            if equipment_model is None:
                self.add_error("equipment_model", "Selecione um produto/modelo.")
            if service is not None:
                self.add_error("service", "Um item de Equipamento não pode ter um Serviço selecionado.")

        quantity = cleaned.get("quantity")
        unit_price = cleaned.get("unit_price")
        discount = cleaned.get("item_discount_amount") or Decimal("0.00")
        if quantity is not None and unit_price is not None:
            gross = Decimal(quantity) * unit_price
            if discount > gross:
                self.add_error(
                    "item_discount_amount",
                    "Desconto não pode ser maior que o valor bruto do item (quantidade × valor unitário).",
                )
        return cleaned


class PriceTableItemForm(forms.Form):
    """
    Edição inline de UMA linha da Tabela de Preços (`crm:price_table_item_row`)
    — Tabela de Preços V1, 16/09/2026. `forms.Form` (não `ModelForm`), mesmo
    raciocínio de `ProposalItemForm` logo acima: a escrita real passa por
    `apps.crm.services.set_price_table_item()` (resolve/cria a `PriceTable`,
    `select_for_update()`, histórico) — este form só valida o valor digitado.
    """

    unit_price = forms.DecimalField(
        label="Valor",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        error_messages={"min_value": "O valor não pode ser negativo."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)


def _opportunity_delivery_location_queryset(client: Client | None):
    """
    RODADA 4 (CORREÇÃO — "Local de entrega/operação", 15/09/2026): o
    campo mostra EXCLUSIVAMENTE as `Location`s do CLIENTE da própria
    `Opportunity` — nunca uma busca/autocomplete global entre todos os
    clientes do sistema (a especificação anterior que pedia isso foi
    corrigida). Sem `client` (chamador não passou `opportunity`, ex.:
    instanciação avulsa em teste) devolve uma queryset VAZIA — nunca
    "todas as Locations" como fallback, que reabriria a brecha que esta
    correção fecha. `type=LocationType.CLIENTE` é redundante com
    `client=client` (a `CheckConstraint` do model já garante que só
    Locations desse tipo têm `client` preenchido) mas deixa a intenção
    explícita na leitura do código. Reaproveita o mesmo campo
    `Location.client` (FK real, já existente desde a Fase 2) — nenhum
    relacionamento novo foi inventado.
    """
    if client is None:
        return Location.objects.none()
    return Location.objects.filter(is_active=True, type=LocationType.CLIENTE, client=client).order_by("name")


def _client_location_display_label(location: Location) -> str:
    """
    RODADA 4 — como o queryset acima já restringe as opções a um único
    cliente (o da própria `Opportunity`), repetir "Cliente — Unidade" em
    toda linha do select é ruído puro (nunca há ambiguidade entre
    clientes diferentes dentro deste campo, ao contrário do select de
    destino de `MovementForm`, que mistura Locations de vários clientes
    e por isso precisa de `location_display_label`). Mostra só o nome da
    unidade.
    """
    return location.name


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
    # FECHAMENTO DA PROPOSTA COMERCIAL (23/09/2026, seção 5): plano
    # comercial real — nunca hardcodado via string. Queryset escopada por
    # `opportunity.business_type` em `__init__` (mesmo raciocínio de
    # `delivery_location`, abaixo): só oferece planos coerentes com o
    # tipo de negócio desta Opportunity.
    commercial_plan = forms.ModelChoiceField(
        label="Plano comercial",
        queryset=CommercialPlan.objects.none(),
        required=False,
        help_text="Exibido no cabeçalho do PDF (ex. 'PROPOSTA COMERCIAL — LOCAÇÃO MENSAL').",
    )

    contracted_start_date = forms.DateField(label="Início do contrato", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    contracted_end_date = forms.DateField(label="Fim do contrato", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_delivery_date = forms.DateField(label="Entrega prevista", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_delivery_time = forms.TimeField(label="Horário de entrega", required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    expected_pickup_date = forms.DateField(label="Retirada prevista", required=False, widget=forms.DateInput(attrs={"type": "date"}))
    expected_pickup_time = forms.TimeField(label="Horário de retirada", required=False, widget=forms.TimeInput(attrs={"type": "time"}))
    delivery_location = forms.ModelChoiceField(
        label="Local de entrega/operação",
        # Default de CLASSE vazio de propósito — a queryset real (RODADA
        # 4: só as Locations do CLIENTE desta Opportunity, nunca busca
        # global) é montada em `__init__`, que exige o `opportunity` para
        # poder escopar; sem ele, fica vazia (nunca "todas as Locations"
        # como fallback — ver `_opportunity_delivery_location_queryset`).
        queryset=Location.objects.none(),
        required=False,
        help_text="Reaproveita Location real (seção 41) — nunca sobrescreve o endereço fiscal do cliente. Mostra só as unidades do cliente desta oportunidade.",
    )
    # Evento / responsável no local (seção 27/28) — pertencem à
    # negociação/operação desta versão, nunca ao cadastro fiscal do
    # Client (nunca sobrescrevem `Client.contact_name`/`Client.phone`).
    event_name = forms.CharField(
        label="Evento", required=False, max_length=150,
        help_text="Opcional — ex. 'Expoingá 2027', 'Casamento XYZ'.",
    )
    onsite_responsible_name = forms.CharField(label="Responsável no local", required=False, max_length=150)
    onsite_responsible_phone = forms.CharField(label="Telefone do responsável", required=False, max_length=30)

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

    def __init__(self, *args, opportunity=None, **kwargs):
        """
        `opportunity` (RODADA 4, CORREÇÃO — "Local de entrega/operação"):
        precisa ser passado por quem instancia este form dentro de uma
        `Opportunity` real (`OpportunityDetailView.get()`,
        `ProposalConditionsSaveView.post()`) para que `delivery_location`
        só ofereça Locations do `opportunity.client` — nunca de outro
        cliente. Igual ao raciocínio já usado em
        `MovementForm.__init__`/`current_location` (mesmo padrão:
        queryset do campo montada em `__init__`, não como default
        estático de classe). Opcional (`None`) só para instanciação
        avulsa (ex.: testes que checam só `.fields`, sem contexto de
        Opportunity) — nesse caso `delivery_location` fica com queryset
        vazia, nunca "todas as Locations".
        """
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)
        self.opportunity = opportunity
        client = opportunity.client if opportunity is not None else None
        self.fields["delivery_location"].queryset = _opportunity_delivery_location_queryset(client)
        self.fields["delivery_location"].label_from_instance = _client_location_display_label
        # Seção 5: só planos ATIVOS e coerentes com o `business_type`
        # desta Opportunity — nunca "todos os planos" (ex. não oferecer
        # um plano de Locação numa Opportunity de Venda).
        business_type = opportunity.business_type if opportunity is not None else None
        plan_qs = CommercialPlan.objects.filter(is_active=True)
        if business_type is not None:
            plan_qs = plan_qs.filter(business_type=business_type)
        self.fields["commercial_plan"].queryset = plan_qs
        # RODADA 4 (reorganização Ajustes financeiros/Resumo
        # financeiro/Informações complementares, 15/09/2026): o template
        # só tem UM `<form id="proposal-conditions-form">`, que envolve
        # física/visualmente só "Condições comerciais" e
        # "Período/Logística" (fecha antes do bloco Produtos/Serviços,
        # que tem seu PRÓPRIO `<form>` de "Adicionar produto/serviço" —
        # aninhar um `<form>` dentro do outro é HTML inválido). Os campos
        # de "Ajustes financeiros"/"Informações complementares" (e o
        # botão "Salvar rascunho") são renderizados MAIS ABAIXO na
        # página, fisicamente FORA desse `<form>` — o atributo HTML5
        # `form="proposal-conditions-form"` em cada um deles é o que os
        # associa ao mesmo `<form>` mesmo sem serem descendentes dele no
        # DOM, exatamente o padrão nativo do HTML para "um formulário,
        # campos em qualquer lugar da página" (suportado por todos os
        # navegadores modernos). Corrige um bug real herdado das rodadas
        # anteriores: a tela tinha DOIS `<form action="...conditions_save...">`
        # separados — um sem nenhum botão "Salvar rascunho" (Condições/
        # Período/`delivery_location`) e outro com o botão (Ajustes/
        # Informações complementares) — então clicar "Salvar rascunho"
        # nunca enviava `payment_method`/datas/`delivery_location` ao
        # backend, e `update_draft_conditions()` gravava esses campos
        # como vazios a cada "Salvar rascunho" (regressão silenciosa,
        # nunca pega pelos testes porque `self.client.post()` testa
        # direto no endpoint, sem passar pela renderização real do HTML).
        for field in self.fields.values():
            field.widget.attrs["form"] = "proposal-conditions-form"

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("contracted_start_date")
        end = cleaned.get("contracted_end_date")
        if start and end and end < start:
            self.add_error("contracted_end_date", "A data final contratada não pode ser anterior à data inicial.")
        # RODADA 4 — segunda camada de defesa (a primeira já é a própria
        # queryset do `ModelChoiceField`, escopada por `opportunity` em
        # `__init__`: um `delivery_location` de outro cliente já é
        # rejeitado ali com "Faça uma escolha válida..."). Esta checagem
        # explícita só existe para dar um erro mais claro e nunca deixar
        # passar uma Location de outro cliente mesmo que, no futuro, o
        # form seja reaproveitado sem passar `opportunity` corretamente.
        delivery_location = cleaned.get("delivery_location")
        if delivery_location is not None and self.opportunity is not None:
            if delivery_location.client_id != self.opportunity.client_id:
                self.add_error(
                    "delivery_location",
                    "Este local de entrega/operação não pertence ao cliente desta oportunidade.",
                )
        return cleaned


class ProposalInstallmentForm(forms.Form):
    """
    Uma parcela de "Condições de pagamento" (seção 18/21) — "[+ Adicionar
    parcela]": Forma de pagamento (select, TODAS as opções de
    `PaymentMethod`, incluindo Outro — diferente de `ProposalConditionsForm.
    payment_method` acima, que remove Outro por não ter onde detalhar;
    aqui `payment_method_other` existe e é validado em `clean()`), Valor
    (R$), Vencimento (data). `sequence` não é um campo do formulário — é
    decidido pelo service (`add_installment()`/próxima sequência livre,
    seção 20) para nunca depender do usuário digitar a ordem certa.
    """

    payment_method = forms.ChoiceField(label="Forma de pagamento", choices=PaymentMethod.choices)
    payment_method_other = forms.CharField(
        label="Descrição (quando Outro)", required=False, max_length=100,
        help_text="Preencha só quando 'Forma de pagamento' = Outro.",
    )
    amount = forms.DecimalField(label="Valor (R$)", max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    due_date = forms.DateField(label="Vencimento", widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("payment_method") == PaymentMethod.OUTRO and not cleaned.get("payment_method_other"):
            self.add_error("payment_method_other", "Descreva a forma de pagamento quando selecionar 'Outro'.")
        return cleaned


class DocumentGenerationForm(forms.Form):
    """Dropdown "Gerar documento" (seção 6/64/65)."""

    document_type = forms.ChoiceField(label="Tipo de documento", choices=DocumentType.choices)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_input_class(self.fields)


class PriceTableRateForm(forms.Form):
    """
    Edição inline de UMA célula da matriz de Preços de Locação
    (`crm:price_table_rate_cell`) — RODADA 1 (16/09/2026). MESMO
    raciocínio de `PriceTableItemForm` acima: `forms.Form`, a escrita real
    passa por `apps.crm.services.set_price_table_rate()` (resolve/cria o
    `PriceTableItem` âncora, `select_for_update()`, histórico) — este
    form só valida os dois valores digitados na célula (valor e modo de
    cobrança).
    """

    amount = forms.DecimalField(
        label="Valor",
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        error_messages={"min_value": "O valor não pode ser negativo."},
    )
    billing_mode = forms.ChoiceField(label="Cobrança", choices=BillingMode.choices, initial=BillingMode.TERM_TOTAL)

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


# ---------------------------------------------------------------------------
# Equipamentos — vínculo Oportunidade↔patrimônio real (RODADA 3 DE
# REFINAMENTOS, 14/09/2026, seção 60-68).
# ---------------------------------------------------------------------------


class EquipmentLinkForm(forms.Form):
    """
    "Vincular equipamento" — `equipment` é restrito a patrimônio REAL,
    ativo e `status=DISPONIVEL` (a mesma exigência que `apps.operations.
    services.create_movement()`/`MovementType.INSTALACAO` já impõe; o
    form só evita que um patrimônio indisponível sequer apareça como
    opção válida — a validação de verdade continua no service, dupla
    camada de sempre). `destination_location` é restrito às unidades
    ATIVAS do tipo Cliente do PRÓPRIO cliente desta Oportunidade —
    nunca uma unidade "solta" de outro cliente.
    """

    equipment = forms.ModelChoiceField(
        label="Equipamento (patrimônio)",
        queryset=Equipment.objects.filter(is_active=True, status=EquipmentStatus.DISPONIVEL).select_related("model"),
    )
    destination_location = forms.ModelChoiceField(label="Local de instalação", queryset=Location.objects.none())
    reason = forms.CharField(label="Observação (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, opportunity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.opportunity = opportunity
        opportunity_id = opportunity.pk if opportunity is not None else None
        self.fields["equipment"].widget = EquipmentAutocompleteWidget(opportunity_id=opportunity_id)

        client_locations = Location.objects.none()
        if opportunity is not None:
            client_locations = (
                Location.objects.filter(is_active=True, type=LocationType.CLIENTE, client_id=opportunity.client_id)
                .select_related("client")
                .annotate(
                    active_sibling_count=Count(
                        "client__locations", filter=Q(client__locations__is_active=True), distinct=True
                    )
                )
                .order_by("name")
            )
        self.fields["destination_location"].queryset = client_locations
        self.fields["destination_location"].label_from_instance = location_display_label

        _apply_input_class(self.fields, skip=("equipment",))


class EquipmentUnlinkForm(forms.Form):
    """
    "Desvincular" — `destination_location` restrito às unidades ATIVAS
    do tipo Estoque (o mesmo destino que `MovementType.RETIRADA` exige
    em `apps.operations.services.create_movement()`).
    """

    destination_location = forms.ModelChoiceField(label="Devolver para", queryset=Location.objects.none())
    reason = forms.CharField(label="Observação (opcional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination_location"].queryset = Location.objects.filter(
            is_active=True, type=LocationType.ESTOQUE
        ).order_by("name")
        _apply_input_class(self.fields)
