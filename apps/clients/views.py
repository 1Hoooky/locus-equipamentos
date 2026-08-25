"""
Views de cliente — Fase 2 (Operação, arquitetura v1.0 seção 3/4/12).

`ClientCreateView` implementa o fluxo de dois botões num único POST
proposto no v1.0 (seção 4): `action=lookup` consulta a BrasilAPI e
re-renderiza o MESMO formulário com os campos preenchidos para revisão
(nada é salvo); `action=save` sempre passa por
`apps.clients.services.create_client()`, com ou sem dado de consulta —
o cadastro manual completo funciona exatamente igual, sem nenhuma
dependência da consulta ter sido usada.
"""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import CAN_MANAGE_CLIENTS, CAN_VIEW_CLIENTS, RoleRequiredMixin
from apps.clients.forms import ClientForm, ClientUpdateForm
from apps.clients.lookup import CompanyLookupError, CompanyLookupNotFound, CompanyLookupService
from apps.clients.models import Client
from apps.clients.services import ClientUpdateData, NewClientData, create_client, update_client, update_fiscal_address
from apps.core.forms import AddressForm
from apps.core.services import AddressData


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
        return render(request, "clients/client_form.html", {"form": ClientForm(), "is_new": True})

    def post(self, request):
        action = request.POST.get("action", "save")

        if action == "lookup":
            return self._handle_lookup(request)
        return self._handle_save(request)

    def _handle_lookup(self, request):
        raw_document = request.POST.get("document", "")
        data = request.POST.copy()
        try:
            result = CompanyLookupService.lookup(raw_document)
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
            # 2) — só preenche o mesmo formulário, que ainda depende de
            # "Salvar" para persistir qualquer coisa.
            data["company_name"] = result.company_name or data.get("company_name", "")
            data["trade_name"] = result.trade_name or data.get("trade_name", "")
            data["registration_status"] = result.registration_status or data.get("registration_status", "")
            data["phone"] = result.phone or data.get("phone", "")
            data["email"] = result.email or data.get("email", "")
            data["fiscal_cep"] = result.address_cep or data.get("fiscal_cep", "")
            data["fiscal_logradouro"] = result.address_logradouro or data.get("fiscal_logradouro", "")
            data["fiscal_numero"] = result.address_numero or data.get("fiscal_numero", "")
            data["fiscal_complemento"] = result.address_complemento or data.get("fiscal_complemento", "")
            data["fiscal_bairro"] = result.address_bairro or data.get("fiscal_bairro", "")
            data["fiscal_cidade"] = result.address_cidade or data.get("fiscal_cidade", "")
            data["fiscal_uf"] = result.address_uf or data.get("fiscal_uf", "")
            messages.success(request, "Dados encontrados — revise antes de salvar.")

        form = ClientForm(data)
        form.is_valid()  # só para popular field.errors se algo ficou incoerente; não bloqueia a revisão
        return render(request, "clients/client_form.html", {"form": form, "is_new": True})

    def _handle_save(self, request):
        form = ClientForm(request.POST)
        if not form.is_valid():
            return render(request, "clients/client_form.html", {"form": form, "is_new": True})

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
            return render(request, "clients/client_form.html", {"form": form, "is_new": True})

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
