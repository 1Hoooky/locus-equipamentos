"""
Formulários de cliente — Fase 2 (Operação). Nenhum é `ModelForm` de
criação: `ClientForm` só valida a entrada; a criação real sempre passa por
`apps.clients.services.create_client()` (nunca `Client(...)` instanciado
direto do formulário — mesma disciplina de `apps.equipment.forms`).

`ClientForm` cobre num único formulário: dados do cliente, endereço fiscal,
e (opcional) a unidade/endereço de entrega inicial — com o checkbox "usar
fiscal como entrega" (v1.0, seção 3) controlando se os campos de endereço
operacional aparecem preenchidos a partir do fiscal ou são digitados à
parte. É o mesmo formulário usado tanto para "Consultar CNPJ" quanto para
"Salvar" (dois botões, um único POST — v1.0 seção 4).
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.clients.models import ClientType
from apps.clients.validators import validate_document_for_type

TEXT_INPUT_CLASS = "border border-gray-300 rounded-md px-3 py-1.5 text-sm w-full"


class ClientForm(forms.Form):
    # --- Dados do cliente ---------------------------------------------
    # Decisão revista a pedido do usuário: o CNPJ (não a razão social) é
    # o campo obrigatório do cadastro — o inverso do que valia antes.
    client_type = forms.ChoiceField(label="Tipo", choices=ClientType.choices, initial=ClientType.PJ)
    document = forms.CharField(label="CNPJ", max_length=18)
    company_name = forms.CharField(label="Razão social", max_length=200, required=False)
    trade_name = forms.CharField(label="Nome fantasia", max_length=200, required=False)
    registration_status = forms.CharField(label="Situação cadastral", max_length=60, required=False)
    state_registration = forms.CharField(label="Inscrição estadual", max_length=20, required=False)
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    email = forms.EmailField(label="E-mail", required=False)
    contact_name = forms.CharField(label="Contato responsável", max_length=150, required=False)
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    # --- Endereço fiscal -------------------------------------------------
    fiscal_cep = forms.CharField(label="CEP", max_length=9, required=False)
    fiscal_logradouro = forms.CharField(label="Logradouro", max_length=255, required=False)
    fiscal_numero = forms.CharField(label="Número", max_length=20, required=False)
    fiscal_complemento = forms.CharField(label="Complemento", max_length=100, required=False)
    fiscal_bairro = forms.CharField(label="Bairro", max_length=100, required=False)
    fiscal_cidade = forms.CharField(label="Cidade", max_length=100, required=False)
    fiscal_uf = forms.CharField(label="UF", max_length=2, required=False)

    # --- Unidade/endereço de entrega inicial (opcional) ------------------
    initial_location_name = forms.CharField(label="Nome da unidade inicial", max_length=150, required=False)
    use_fiscal_as_operational = forms.BooleanField(
        label="Usar endereço fiscal como endereço de entrega", required=False, initial=True
    )
    operational_cep = forms.CharField(label="CEP", max_length=9, required=False)
    operational_logradouro = forms.CharField(label="Logradouro", max_length=255, required=False)
    operational_numero = forms.CharField(label="Número", max_length=20, required=False)
    operational_complemento = forms.CharField(label="Complemento", max_length=100, required=False)
    operational_bairro = forms.CharField(label="Bairro", max_length=100, required=False)
    operational_cidade = forms.CharField(label="Cidade", max_length=100, required=False)
    operational_uf = forms.CharField(label="UF", max_length=2, required=False)
    operational_reference_notes = forms.CharField(
        label="Ponto de referência", required=False, widget=forms.Textarea(attrs={"rows": 2})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "use_fiscal_as_operational":
                continue
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("use_fiscal_as_operational"):
            # Convenção de conveniência só de formulário (v1.0, seção 3):
            # copia os valores digitados/consultados do fiscal para os
            # campos operacionais antes de create_client() criar os DOIS
            # registros Address independentes.
            for suffix in ("cep", "logradouro", "numero", "complemento", "bairro", "cidade", "uf"):
                cleaned[f"operational_{suffix}"] = cleaned.get(f"fiscal_{suffix}", "")

        # CNPJ agora é o campo obrigatório (razão social virou opcional) —
        # valida o dígito verificador aqui, com erro amigável preso ao
        # campo, em vez de deixar só `create_client()` pegar isso (mesma
        # regra reaproveitada de `CNPJLookupForm.clean()`, nunca uma cópia
        # divergente).
        client_type = cleaned.get("client_type")
        document = cleaned.get("document")
        if client_type and document:
            try:
                cleaned["document"] = validate_document_for_type(document, client_type)
            except ValidationError as exc:
                self.add_error("document", exc)
        return cleaned


class CNPJLookupForm(forms.Form):
    """
    Validação MÍNIMA da ação "Consultar CNPJ" — bug relatado pelo usuário:
    a consulta não pode exigir os mesmos campos do cadastro completo
    (razão social, endereço etc.), só o necessário para consultar. Um
    formulário deliberadamente separado de `ClientForm`, em vez de
    reaproveitar `ClientForm.is_valid()`, é a correção arquitetural: as
    duas ações (`lookup`/`save`) agora rodam validações genuinamente
    diferentes, não a mesma validação "com um form parcialmente
    preenchido".
    """

    client_type = forms.ChoiceField(label="Tipo", choices=ClientType.choices)
    document = forms.CharField(label="CNPJ", max_length=18)

    def clean(self):
        cleaned = super().clean()
        client_type = cleaned.get("client_type")
        document = cleaned.get("document")
        if not client_type or not document:
            return cleaned

        if client_type != ClientType.PJ:
            # A consulta automática só existe para CNPJ (BrasilAPI) —
            # "tipo PJ, quando aplicável" (não é uma limitação nova desta
            # correção: CompanyLookupService sempre validou como CNPJ; só
            # não havia essa checagem amigável antes de chamar o serviço).
            raise ValidationError("Consulta automática está disponível só para CNPJ (Pessoa Jurídica).")

        try:
            cleaned["document"] = validate_document_for_type(document, client_type)
        except ValidationError as exc:
            self.add_error("document", exc)
        return cleaned


class ClientUpdateForm(forms.Form):
    """
    Edição de cliente — inclui `document` (editável pós-criação desde a
    v1.1). Não inclui endereço fiscal nem unidade: endereço se edita por
    `apps.core.forms.AddressForm` diretamente sobre o `Address` já
    vinculado; unidades adicionais têm tela própria
    (`apps.operations`).
    """

    # Decisão revista a pedido do usuário: o CNPJ (não a razão social) é
    # o campo obrigatório — o inverso do que valia antes (mesma mudança
    # de `ClientForm`).
    client_type = forms.ChoiceField(label="Tipo", choices=ClientType.choices)
    document = forms.CharField(label="CNPJ", max_length=18)
    company_name = forms.CharField(label="Razão social", max_length=200, required=False)
    trade_name = forms.CharField(label="Nome fantasia", max_length=200, required=False)
    registration_status = forms.CharField(label="Situação cadastral", max_length=60, required=False)
    state_registration = forms.CharField(label="Inscrição estadual", max_length=20, required=False)
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    email = forms.EmailField(label="E-mail", required=False)
    contact_name = forms.CharField(label="Contato responsável", max_length=150, required=False)
    notes = forms.CharField(label="Observações", required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)

    def clean(self):
        cleaned = super().clean()
        client_type = cleaned.get("client_type")
        document = cleaned.get("document")
        if client_type and document:
            try:
                cleaned["document"] = validate_document_for_type(document, client_type)
            except ValidationError as exc:
                self.add_error("document", exc)
        return cleaned
