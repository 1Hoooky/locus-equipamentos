"""
Views do CRM (LocusHub, Etapa 1) — PRIMEIRO módulo do projeto a usar a
arquitetura NOVA de autorização (`User` → Cargo/`Group` → `Permission`,
via `PermissionRequiredMixin`/`perms.crm.*`) em vez do `RoleRequiredMixin`
legado. Nenhuma view aqui checa `role`/`CAN_*`/`RoleRequiredMixin` — só
`login_required` + `permission_required`, exatamente uma Permission do
catálogo por ação (ver `apps/accounts/permission_catalog.py`).

`LoginRequiredMixin` + `PermissionRequiredMixin` (ambos de
`django.contrib.auth.mixins`, nativos do Django) reproduzem EXATAMENTE o
comportamento de `RoleRequiredMixin` sem nenhum código novo:
`AccessMixin.handle_no_permission()` já redireciona anônimo para o login
e levanta `PermissionDenied` (403) para autenticado-sem-permissão, e
`ModelBackend.has_perm()` já dá bypass automático a `is_superuser=True`
(Administrador/superusuário continuam com acesso irrestrito, sem
precisar de nenhuma Permission concedida — mesma "válvula de segurança
operacional" do resto do sistema).

Toda escrita (POST) chama exclusivamente `apps/crm/services.py` — nunca
`Opportunity.objects.create()`/`.save()` direto numa view para os campos
de etapa/ganho/perda. `get_object_or_404(Opportunity, pk=pk)` (sem
filtro adicional por usuário/dono) é deliberado: a oportunidade PK 11
não existe "escondida" para quem tem `view_opportunities` só porque
pertence a outro `owner` — a permissão é a fronteira, não a posse. Um
usuário SEM `view_opportunities` nunca alcança nenhuma destas views
(bloqueado por `PermissionRequiredMixin` antes de qualquer query rodar),
então PK sequencial não vaza nada para quem não tem a permissão de ver
oportunidades (proteção IDOR real é "a permissão", não "esconder o PK").
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.crm.forms import (
    CommercialActivityForm,
    CommercialSourceForm,
    LossReasonForm,
    OpportunityCreateForm,
    OpportunityStageChangeForm,
    OpportunityStageForm,
    OpportunityUpdateForm,
)
from apps.crm.models import CommercialSource, LossReason, Opportunity, OpportunityStage
from apps.crm.services import (
    NewActivityData,
    NewOpportunityData,
    OpportunityUpdateData,
    change_opportunity_stage,
    create_activity,
    create_opportunity,
    update_opportunity,
)

# ---------------------------------------------------------------------------
# Oportunidades
# ---------------------------------------------------------------------------


class OpportunityListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.view_opportunities"
    model = Opportunity
    template_name = "crm/opportunity_list.html"
    context_object_name = "opportunities"
    paginate_by = 50

    def get_queryset(self):
        qs = Opportunity.objects.select_related("client", "owner", "source", "stage")

        stage = self.request.GET.get("stage", "")
        owner = self.request.GET.get("owner", "")
        source = self.request.GET.get("source", "")
        business_type = self.request.GET.get("business_type", "")
        client = self.request.GET.get("client", "")
        q = self.request.GET.get("q", "").strip()

        # stage/owner/source/client filtram por PK (FK) — um valor não
        # numérico (ex.: "?owner=abc", URL adulterada à mão) faria o ORM
        # levantar ValueError ao preparar o lookup (500 em vez de
        # simplesmente ignorar um filtro inválido). Mesmo cuidado já
        # aplicado em apps.equipment.filters.filter_equipment_queryset
        # para category/model — ignora silenciosamente, não propaga erro.
        if stage and stage.isdigit():
            qs = qs.filter(stage_id=stage)
        if owner and owner.isdigit():
            qs = qs.filter(owner_id=owner)
        if source and source.isdigit():
            qs = qs.filter(source_id=source)
        if business_type:
            qs = qs.filter(business_type=business_type)
        if client and client.isdigit():
            qs = qs.filter(client_id=client)
        if q:
            qs = qs.filter(
                Q(title__icontains=q) | Q(client__company_name__icontains=q) | Q(client__trade_name__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["stages"] = OpportunityStage.objects.filter(is_active=True).order_by("order", "name")
        context["sources"] = CommercialSource.objects.filter(is_active=True).order_by("order", "name")
        context["business_type_choices"] = Opportunity._meta.get_field("business_type").choices
        context["selected_stage"] = self.request.GET.get("stage", "")
        context["selected_owner"] = self.request.GET.get("owner", "")
        context["selected_source"] = self.request.GET.get("source", "")
        context["selected_business_type"] = self.request.GET.get("business_type", "")
        context["selected_client"] = self.request.GET.get("client", "")
        context["q"] = self.request.GET.get("q", "")
        return context


class OpportunityDetailView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.view_opportunities"

    def get(self, request, pk):
        opportunity = get_object_or_404(
            Opportunity.objects.select_related("client", "owner", "source", "stage", "loss_reason", "created_by"),
            pk=pk,
        )
        stage_changes = opportunity.stage_changes.select_related("from_stage", "to_stage", "changed_by")

        # `view_commercial_activities` é uma Permission PRÓPRIA — mesmo
        # tendo `view_opportunities` (chegou até aqui), um usuário sem
        # `view_commercial_activities` nunca recebe as atividades no
        # contexto: a checagem é no BACKEND (aqui), não só escondida no
        # template — evita vazar descrição/observação de atividade
        # comercial por qualquer variável de contexto acessível.
        can_view_activities = request.user.has_perm("crm.view_commercial_activities")
        activities = (
            opportunity.activities.select_related("created_by").order_by("-created_at")
            if can_view_activities
            else opportunity.activities.none()
        )

        context = {
            "opportunity": opportunity,
            "stage_changes": stage_changes,
            "activities": activities,
            "can_view_activities": can_view_activities,
            "can_change_opportunity": request.user.has_perm("crm.change_opportunities"),
            "can_change_stage": request.user.has_perm("crm.change_opportunity_stage"),
            "can_add_activity": request.user.has_perm("crm.add_commercial_activities"),
            "stage_change_form": OpportunityStageChangeForm() if request.user.has_perm("crm.change_opportunity_stage") else None,
            "activity_form": CommercialActivityForm() if can_view_activities and request.user.has_perm("crm.add_commercial_activities") else None,
        }
        return render(request, "crm/opportunity_detail.html", context)


class OpportunityCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.add_opportunities"

    def get(self, request):
        return render(request, "crm/opportunity_form.html", {"form": OpportunityCreateForm(), "is_new": True})

    def post(self, request):
        form = OpportunityCreateForm(request.POST)
        if not form.is_valid():
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": True})

        cleaned = form.cleaned_data
        try:
            opportunity = create_opportunity(
                NewOpportunityData(
                    client=cleaned["client"],
                    title=cleaned["title"],
                    owner=cleaned["owner"],
                    source=cleaned["source"],
                    business_type=cleaned["business_type"],
                    stage=cleaned["stage"],
                    created_by=request.user,
                    expected_close_date=cleaned["expected_close_date"],
                    estimated_value=cleaned["estimated_value"],
                    notes=cleaned["notes"],
                )
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": True})

        messages.success(request, f"Oportunidade \"{opportunity.title}\" criada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class OpportunityUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.change_opportunities"

    def get(self, request, pk):
        opportunity = get_object_or_404(Opportunity.objects.select_related("client", "owner", "source"), pk=pk)
        form = OpportunityUpdateForm(
            initial={
                "title": opportunity.title,
                "owner": opportunity.owner_id,
                "source": opportunity.source_id,
                "business_type": opportunity.business_type,
                "expected_close_date": opportunity.expected_close_date,
                "estimated_value": opportunity.estimated_value,
                "notes": opportunity.notes,
            },
            owner_instance=opportunity.owner,
            source_instance=opportunity.source,
        )
        return render(request, "crm/opportunity_form.html", {"form": form, "is_new": False, "opportunity": opportunity})

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity.objects.select_related("client", "owner", "source"), pk=pk)
        form = OpportunityUpdateForm(request.POST, owner_instance=opportunity.owner, source_instance=opportunity.source)
        if not form.is_valid():
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": False, "opportunity": opportunity})

        cleaned = form.cleaned_data
        try:
            update_opportunity(
                opportunity=opportunity,
                changed_by=request.user,
                data=OpportunityUpdateData(
                    title=cleaned["title"],
                    owner=cleaned["owner"],
                    source=cleaned["source"],
                    business_type=cleaned["business_type"],
                    expected_close_date=cleaned["expected_close_date"],
                    estimated_value=cleaned["estimated_value"],
                    notes=cleaned["notes"],
                ),
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": False, "opportunity": opportunity})

        messages.success(request, f"Oportunidade \"{opportunity.title}\" atualizada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class OpportunityStageChangeView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Só POST (deliberado — sem `get()`, então `GET` recebe 405 do próprio
    `django.views.View`): mudar etapa/ganhar/perder é sempre uma escrita,
    nunca uma navegação. Exige as DUAS permissões — ver a oportunidade E
    poder mudar sua etapa — para nunca alterar o estado de algo que o
    próprio usuário não teria como ver antes.
    """

    permission_required = ("crm.view_opportunities", "crm.change_opportunity_stage")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = OpportunityStageChangeForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível mudar a etapa — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            change_opportunity_stage(
                opportunity_id=opportunity.pk,
                new_stage=cleaned["stage"],
                changed_by=request.user,
                reason=cleaned["reason"],
                loss_reason=cleaned["loss_reason"],
                loss_notes=cleaned["loss_notes"],
                closed_value=cleaned["closed_value"],
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, f"Etapa alterada para \"{cleaned['stage'].name}\".")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class CommercialActivityCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Só POST — registrar atividade é sempre uma escrita (ver `OpportunityStageChangeView`)."""

    permission_required = ("crm.view_opportunities", "crm.add_commercial_activities")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = CommercialActivityForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Não foi possível registrar a atividade — corrija os erros abaixo.")
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        try:
            create_activity(
                NewActivityData(
                    opportunity=opportunity,
                    activity_type=cleaned["activity_type"],
                    created_by=request.user,
                    description=cleaned["description"],
                    occurred_at=cleaned["occurred_at"],
                    scheduled_for=cleaned["scheduled_for"],
                )
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        messages.success(request, "Atividade registrada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


# ---------------------------------------------------------------------------
# Configurações comerciais — Origem, Etapa, Motivo de perda.
#
# Mesmo padrão simples de `apps.catalog.views.CategoryListView/
# CreateView/UpdateView` — `ModelForm` direto, sem service dedicado
# (nenhuma regra de negócio além do que já está em `Meta.permissions`/
# `clean()` do próprio modelo). "Excluir" nunca existe aqui, de propósito
# — só editar `is_active` pelo mesmo form de edição (mesma convenção de
# `Category`), nunca DELETE de verdade (requisito: nunca apagar
# fisicamente origem/etapa/motivo já utilizado).
# ---------------------------------------------------------------------------


class CommercialSourceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = CommercialSource
    template_name = "crm/commercial_source_list.html"
    context_object_name = "sources"

    def get_queryset(self):
        return CommercialSource.objects.all().order_by("order", "name")


class CommercialSourceCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/commercial_source_form.html", {"form": CommercialSourceForm(), "is_new": True})

    def post(self, request):
        form = CommercialSourceForm(request.POST)
        if form.is_valid():
            source = form.save()
            messages.success(request, f"Origem comercial \"{source.name}\" criada.")
            return redirect("crm:commercial_source_list")
        return render(request, "crm/commercial_source_form.html", {"form": form, "is_new": True})


class CommercialSourceUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        source = get_object_or_404(CommercialSource, pk=pk)
        return render(
            request, "crm/commercial_source_form.html", {"form": CommercialSourceForm(instance=source), "is_new": False, "source": source}
        )

    def post(self, request, pk):
        source = get_object_or_404(CommercialSource, pk=pk)
        form = CommercialSourceForm(request.POST, instance=source)
        if form.is_valid():
            form.save()
            messages.success(request, f"Origem comercial \"{source.name}\" atualizada.")
            return redirect("crm:commercial_source_list")
        return render(request, "crm/commercial_source_form.html", {"form": form, "is_new": False, "source": source})


class OpportunityStageListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = OpportunityStage
    template_name = "crm/opportunity_stage_list.html"
    context_object_name = "stages"

    def get_queryset(self):
        return OpportunityStage.objects.all().order_by("order", "name")


class OpportunityStageCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/opportunity_stage_form.html", {"form": OpportunityStageForm(), "is_new": True})

    def post(self, request):
        form = OpportunityStageForm(request.POST)
        if form.is_valid():
            stage = form.save()
            messages.success(request, f"Etapa \"{stage.name}\" criada.")
            return redirect("crm:opportunity_stage_list")
        return render(request, "crm/opportunity_stage_form.html", {"form": form, "is_new": True})


class OpportunityStageUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        stage = get_object_or_404(OpportunityStage, pk=pk)
        return render(
            request, "crm/opportunity_stage_form.html", {"form": OpportunityStageForm(instance=stage), "is_new": False, "stage": stage}
        )

    def post(self, request, pk):
        stage = get_object_or_404(OpportunityStage, pk=pk)
        form = OpportunityStageForm(request.POST, instance=stage)
        if form.is_valid():
            form.save()
            messages.success(request, f"Etapa \"{stage.name}\" atualizada.")
            return redirect("crm:opportunity_stage_list")
        return render(request, "crm/opportunity_stage_form.html", {"form": form, "is_new": False, "stage": stage})


class LossReasonListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    permission_required = "crm.manage_commercial_settings"
    model = LossReason
    template_name = "crm/loss_reason_list.html"
    context_object_name = "reasons"

    def get_queryset(self):
        return LossReason.objects.all().order_by("order", "name")


class LossReasonCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request):
        return render(request, "crm/loss_reason_form.html", {"form": LossReasonForm(), "is_new": True})

    def post(self, request):
        form = LossReasonForm(request.POST)
        if form.is_valid():
            reason = form.save()
            messages.success(request, f"Motivo de perda \"{reason.name}\" criado.")
            return redirect("crm:loss_reason_list")
        return render(request, "crm/loss_reason_form.html", {"form": form, "is_new": True})


class LossReasonUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "crm.manage_commercial_settings"

    def get(self, request, pk):
        reason = get_object_or_404(LossReason, pk=pk)
        return render(
            request, "crm/loss_reason_form.html", {"form": LossReasonForm(instance=reason), "is_new": False, "reason": reason}
        )

    def post(self, request, pk):
        reason = get_object_or_404(LossReason, pk=pk)
        form = LossReasonForm(request.POST, instance=reason)
        if form.is_valid():
            form.save()
            messages.success(request, f"Motivo de perda \"{reason.name}\" atualizado.")
            return redirect("crm:loss_reason_list")
        return render(request, "crm/loss_reason_form.html", {"form": form, "is_new": False, "reason": reason})
