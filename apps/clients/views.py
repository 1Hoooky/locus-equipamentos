"""
Views de cliente — Fase 2 (Operação, arquitetura v1.0 seção 3/4/12).

`ClientCreateView` implementa o fluxo de dois botões num único POST
proposto no v1.0 (seção 4): `action=lookup` consulta a BrasilAPI e
re-renderiza o MESMO formulário com os campos preenchidos para revisão
(nada é salvo); `action=save` sempre passa por
`apps.clients.services.create_client()`, com ou sem dado de consulta —
o cadastro manual completo funciona exatamente igual, sem nenhuma
dependência da consulta ter sido usada.

Proteção contra reenvio (bug corrigido: Enter repetido durante a criação
disparava múltiplos cadastros/duplicatas) — token de sessão de uso único,
mesmo padrão já usado em `EquipmentBatchConfirmView`
(`apps/equipment/views.py`): cada exibição do formulário de criação emite
um token novo guardado em `request.session`; `action=save` só chama
`create_client()` se o token enviado no POST bater com o da sessão, e o
consome (`del request.session[...]`) ANTES de chamar o service — uma
segunda tentativa com o mesmo token (duplo Enter, duplo clique, "voltar" +
reenviar) não encontra mais nada pendente. Funciona mesmo para cliente sem
documento, onde a unicidade de `document` (segunda camada de defesa) não
se aplica.
"""

import uuid

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import CAN_MANAGE_CLIENTS, CAN_VIEW_CLIENTS, RoleRequiredMixin
from apps.clients.forms import CNPJLookupForm, ClientForm, ClientUpdateForm
from apps.clients.lookup import CompanyLookupError, CompanyLookupNotFound, CompanyLookupService
from apps.clients.models import Client
from apps.clients.services import ClientUpdateData, NewClientData, create_client, update_client, update_fiscal_address
from apps.core.forms import AddressForm
from apps.core.services import AddressData

SESSION_KEY_CLIENT_CREATE_TOKEN = "client_create_submission_token"


def _issue_submission_token(request) -> str:
    """Emite (e guarda na sessão) um novo token de uso único para o formulário de criação de cliente."""
    token = uuid.uuid4().hex
    request.session[SESSION_KEY_CLIENT_CREATE_TOKEN] = token
    return token


def _pending_submission_token(request) -> str:
    """
    Token já pendente na sessão para esta exibição do formulário, ou um
    novo emitido na hora se não houver nenhum (ex.: sessão expirou entre a
    consulta e o preenchimento). Usado pelo fluxo `action=lookup`, que
    NUNCA consome o token — só `action=save` bem-sucedido em chegar ao
    service é que consome.
    """
    token = request.session.get(SESSION_KEY_CLIENT_CREATE_TOKEN)
    if not token:
        token = _issue_submission_token(request)
    return token


def _address_data_from_cleaned(cleaned: dict, prefix: str) -> AddressData:
    return AddressData(
        cep=cleaned.get(f"{prefix}_cep", ""),
        logradouro=cleaned.get(f"{prefix}_logradouro", ""),
        numero=cleaned.get(f"{prefix}_numero", ""),
        complemento=cleaned.get(f"{prefix}_complemento", ""),
        bairro=cleaned.get(f"{prefix}_bairro", ""),
        cidade=cleaned.get(f"{prefix}_cidade", ""),
        uf=cleaned.get(f"{prefix}_uf", ""),
        reference_notes=cleaned.get(f"{prefix}_reference_notes", ""),
    )


def _initial_from_post(post) -> dict:
    """
    Reconstrói um dict de `initial=` para um `ClientForm` NÃO vinculado a
    partir do que o usuário já tinha digitado em `post`. Usado só pelo
    fluxo de "Consultar CNPJ" (bug corrigido: reconstruir como
    `ClientForm(request.POST)` — formulário VINCULADO — dispara a
    validação completa (razão social obrigatória etc.) assim que o
    template acessa `field.errors`, mesmo sem o view chamar
    `is_valid()` explicitamente, porque `BoundField.errors` aciona
    `full_clean()` de forma preguiçosa. Um formulário NÃO vinculado
    (`ClientForm(initial=...)`) nunca roda validação de campo nenhuma —
    é a única forma de reexibir os dados digitados sem validar nada além
    do que a própria ação pede.
    """
    initial = {name: post.get(name, "") for name in ClientForm.base_fields if name != "use_fiscal_as_operational"}
    initial["use_fiscal_as_operational"] = "use_fiscal_as_operational" in post
    return initial


class ClientListView(RoleRequiredMixin, ListView):
    """Todos os 4 perfis podem consultar (matriz da seção 11, v1.0)."""

    allowed_roles = CAN_VIEW_CLIENTS
    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 50

    def get_queryset(self):
        qs = Client.objects.filter(is_active=True).order_by("company_name")
        q = self.request.GET.get("q", "").strip()
        if q:
            from django.db.models import Q

            qs = qs.filter(
                Q(company_name__icontains=q) | Q(trade_name__icontains=q) | Q(document__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["q"] = self.request.GET.get("q", "")
        return context


class ClientDetailView(RoleRequiredMixin, View):
    allowed_roles = CAN_VIEW_CLIENTS

    def get(self, request, pk):
        client = get_object_or_404(Client.objects.select_related("fiscal_address"), pk=pk)
        locations = client.locations.filter(is_active=True).select_related("address").order_by("name")
        return render(
            request,
            "clients/client_detail.html",
            {"client": client, "locations": locations},
        )


class ClientCreateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_CLIENTS

    def get(self, request):
        token = _issue_submission_token(request)
        return render(
            request,
            "clients/client_form.html",
            {"form": ClientForm(), "is_new": True, "submission_token": token},
        )

    def post(self, request):
        action = request.POST.get("action", "save")

        if action == "lookup":
            return self._handle_lookup(request)
        return self._handle_save(request)

    def _handle_lookup(self, request):
        # Validação MÍNIMA da ação "Consultar CNPJ" — bug corrigido: isto
        # NUNCA foi (e não pode voltar a ser) `ClientForm(request.POST)` +
        # `is_valid()`/`errors`, que exige razão social e todo o resto do
        # cadastro completo. `CNPJLookupForm` só conhece `client_type` e
        # `document`.
        initial = _initial_from_post(request.POST)
        lookup_form = CNPJLookupForm(request.POST)
        # `action=lookup` nunca cria nada — não consome o token de reenvio,
        # só garante que a tela seguinte (com o resultado da consulta)
        # continua com um token válido para o eventual "Salvar".
        submission_token = _pending_submission_token(request)

        if not lookup_form.is_valid():
            for error in lookup_form.non_field_errors():
                messages.warning(request, error)
            document_errors = lookup_form.errors.get("document", [])
            for error in document_errors:
                messages.warning(request, f"CNPJ: {error}")
            form = ClientForm(initial=initial)
            return render(
                request,
                "clients/client_form.html",
                {"form": form, "is_new": True, "submission_token": submission_token},
            )

        try:
            result = CompanyLookupService.lookup(lookup_form.cleaned_data["document"])
        except CompanyLookupNotFound:
            messages.warning(
                request,
                "CNPJ não encontrado na base pública. Você pode continuar com o cadastro manual.",
            )
        except CompanyLookupError:
            messages.warning(
                request,
                "Não foi possível consultar o CNPJ automaticamente agora. Você pode continuar com o "
                "cadastro manual — nada foi perdido do que você já preencheu.",
            )
        else:
            # Resultado vem para REVISÃO, nunca salvo direto (v1.0, seção
            # 2) — só preenche os valores iniciais do MESMO formulário,
            # que ainda depende de "Salvar" para persistir qualquer coisa.
            initial["company_name"] = result.company_name or initial.get("company_name", "")
            initial["trade_name"] = result.trade_name or initial.get("trade_name", "")
            initial["registration_status"] = result.registration_status or initial.get("registration_status", "")
            initial["phone"] = result.phone or initial.get("phone", "")
            initial["email"] = result.email or initial.get("email", "")
            initial["fiscal_cep"] = result.address_cep or initial.get("fiscal_cep", "")
            initial["fiscal_logradouro"] = result.address_logradouro or initial.get("fiscal_logradouro", "")
            initial["fiscal_numero"] = result.address_numero or initial.get("fiscal_numero", "")
            initial["fiscal_complemento"] = result.address_complemento or initial.get("fiscal_complemento", "")
            initial["fiscal_bairro"] = result.address_bairro or initial.get("fiscal_bairro", "")
            initial["fiscal_cidade"] = result.address_cidade or initial.get("fiscal_cidade", "")
            initial["fiscal_uf"] = result.address_uf or initial.get("fiscal_uf", "")
            messages.success(request, "Dados encontrados — revise antes de salvar.")

        # NÃO vinculado (sem `data=`) — só `initial=`. Um form vinculado
        # aciona validação de campo (via `field.errors`, preguiçoso) assim
        # que o template renderiza; um form não vinculado nunca roda
        # `_clean_fields()`/`clean()`, então não há como um campo
        # obrigatório do cadastro completo "vazar" um erro nesta tela.
        form = ClientForm(initial=initial)
        return render(
            request,
            "clients/client_form.html",
            {"form": form, "is_new": True, "submission_token": submission_token},
        )

    def _handle_save(self, request):
        form = ClientForm(request.POST)
        if not form.is_valid():
            # Erro de validação de campo — não é uma tentativa de reenvio
            # (nada foi criado), então a página seguinte continua
            # utilizável: emite um token novo para o próximo "Salvar".
            token = _issue_submission_token(request)
            return render(
                request,
                "clients/client_form.html",
                {"form": form, "is_new": True, "submission_token": token},
            )

        submitted_token = request.POST.get("submission_token", "")
        expected_token = request.session.get(SESSION_KEY_CLIENT_CREATE_TOKEN)
        if not expected_token or submitted_token != expected_token:
            # Reenvio do mesmo formulário (Enter repetido, duplo clique em
            # "Salvar", "voltar" + reenviar, ou uma segunda requisição
            # concorrente que já consumiu o token) — bug corrigido: nada é
            # criado nesta tentativa, ao contrário de depender só de
            # desabilitar o botão no navegador. Funciona mesmo sem
            # documento informado.
            messages.info(
                request,
                "Este formulário já havia sido enviado. Se o cadastro não aparece na lista de clientes, "
                "tente novamente.",
            )
            return redirect("clients:list")

        # Consumido ANTES de chamar o service — uso único (mesmo padrão de
        # EquipmentBatchConfirmView.post, apps/equipment/views.py): uma
        # segunda tentativa com o MESMO token não encontra mais nada
        # pendente na sessão.
        del request.session[SESSION_KEY_CLIENT_CREATE_TOKEN]

        cleaned = form.cleaned_data
        fiscal_address = _address_data_from_cleaned(cleaned, "fiscal")
        initial_location_address = _address_data_from_cleaned(cleaned, "operational")

        try:
            client = create_client(
                NewClientData(
                    client_type=cleaned["client_type"],
                    company_name=cleaned["company_name"],
                    document=cleaned["document"],
                    trade_name=cleaned["trade_name"],
                    registration_status=cleaned["registration_status"],
                    state_registration=cleaned["state_registration"],
                    phone=cleaned["phone"],
                    email=cleaned["email"],
                    contact_name=cleaned["contact_name"],
                    notes=cleaned["notes"],
                    fiscal_address=fiscal_address,
                    initial_location_name=cleaned["initial_location_name"],
                    initial_location_address=initial_location_address,
                )
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            # Falha de negócio (ex.: documento duplicado) — o token já foi
            # consumido acima; emite um novo para a tentativa de correção
            # seguinte não ser barrada como "reenvio".
            token = _issue_submission_token(request)
            return render(
                request,
                "clients/client_form.html",
                {"form": form, "is_new": True, "submission_token": token},
            )

        messages.success(request, f"Cliente {client.display_name()} cadastrado com sucesso.")
        return redirect("clients:detail", pk=client.pk)


class ClientUpdateView(RoleRequiredMixin, View):
    allowed_roles = CAN_MANAGE_CLIENTS

    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        form = ClientUpdateForm(
            initial={
                "client_type": client.client_type,
                "document": client.document,
                "company_name": client.company_name,
                "trade_name": client.trade_name,
                "registration_status": client.registration_status,
                "state_registration": client.state_registration,
                "phone": client.phone,
                "email": client.email,
                "contact_name": client.contact_name,
                "notes": client.notes,
            }
        )
        return render(request, "clients/client_update_form.html", {"form": form, "client": client})

    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        form = ClientUpdateForm(request.POST)
        if not form.is_valid():
            return render(request, "clients/client_update_form.html", {"form": form, "client": client})

        cleaned = form.cleaned_data
        try:
            update_client(
                client=client,
                data=ClientUpdateData(
                    client_type=cleaned["client_type"],
                    company_name=cleaned["company_name"],
                    document=cleaned["document"],
                    trade_name=cleaned["trade_name"],
                    registration_status=cleaned["registration_status"],
                    state_registration=cleaned["state_registration"],
                    phone=cleaned["phone"],
                    email=cleaned["email"],
                    contact_name=cleaned["contact_name"],
                    notes=cleaned["notes"],
                ),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "clients/client_update_form.html", {"form": form, "client": client})

        messages.success(request, f"Cliente {client.display_name()} atualizado.")
        return redirect("clients:detail", pk=client.pk)


class ClientFiscalAddressUpdateView(RoleRequiredMixin, View):
    """Edita (ou cria, se ainda não existir) o endereço fiscal — nunca troca a FK, sempre o mesmo registro (v1.1 delta, seção 5)."""

    allowed_roles = CAN_MANAGE_CLIENTS

    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        form = AddressForm(instance=client.fiscal_address)
        return render(request, "clients/client_fiscal_address_form.html", {"form": form, "client": client})

    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        form = AddressForm(request.POST, instance=client.fiscal_address)
        if not form.is_valid():
            return render(request, "clients/client_fiscal_address_form.html", {"form": form, "client": client})

        data = AddressData(
            cep=form.cleaned_data["cep"],
            logradouro=form.cleaned_data["logradouro"],
            numero=form.cleaned_data["numero"],
            complemento=form.cleaned_data["complemento"],
            bairro=form.cleaned_data["bairro"],
            cidade=form.cleaned_data["cidade"],
            uf=form.cleaned_data["uf"],
            reference_notes=form.cleaned_data["reference_notes"],
        )
        update_fiscal_address(client=client, data=data)
        messages.success(request, "Endereço fiscal atualizado.")
        return redirect("clients:detail", pk=client.pk)
