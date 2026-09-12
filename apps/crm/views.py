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

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.functions import Greatest
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import ListView

from apps.accounts.permissions import SuperuserRequiredMixin
from apps.clients.models import Client
from apps.core.forms import HardDeleteConfirmForm
from apps.core.hard_delete import HardDeleteBlocked
from apps.core.templatetags.currency import format_brl
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
    hard_delete_opportunity,
    preview_opportunity_hard_delete,
    update_opportunity,
)

# ---------------------------------------------------------------------------
# Oportunidades
# ---------------------------------------------------------------------------


def _filtered_opportunities_queryset(params):
    """
    Filtro compartilhado de Oportunidades — fonte ÚNICA de "quais
    oportunidades entram na conta", usada tanto pelo Kanban
    (`OpportunityListView`, agrupamento por etapa) quanto pelo endpoint
    AJAX de mudança de etapa (`OpportunityStageChangeView`, para
    recalcular os totais de origem/destino respeitando os MESMOS filtros
    ativos na tela no momento do arraste — sem isso, o total da coluna
    "piscaria" fora de sincronia com o que o usuário está vendo filtrado).

    `params` é qualquer `QueryDict`-like com `.get()` (`request.GET` nas
    duas chamadoras — o endpoint AJAX recebe os filtros ativos na própria
    querystring da URL de POST, ver `static/crm/kanban.js`).

    Sem filtro por `stage` aqui (diferente da antiga listagem em tabela):
    no Kanban a própria COLUNA já é a etapa — filtrar por etapa além
    disso não faria sentido estrutural nenhum, e por isso o seletor de
    "Etapa" foi removido da tela (decisão de produto, 11/09/2026).
    """
    qs = Opportunity.objects.select_related("client", "owner", "source", "stage")

    owner = params.get("owner", "")
    source = params.get("source", "")
    business_type = params.get("business_type", "")
    client = params.get("client", "")
    q = params.get("q", "").strip()

    # owner/source/client filtram por PK (FK) — um valor não numérico
    # (ex.: "?owner=abc", URL adulterada à mão) faria o ORM levantar
    # ValueError ao preparar o lookup (500 em vez de simplesmente ignorar
    # um filtro inválido). Mesmo cuidado já aplicado em
    # apps.equipment.filters.filter_equipment_queryset para
    # category/model — ignora silenciosamente, não propaga erro.
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


def _default_new_opportunity_stage():
    """
    Etapa inicial sugerida ao ABRIR "Nova oportunidade" (drawer OU rota
    tradicional) — UX pedida na rodada de 11/09/2026 ("criação rápida em
    drawer"): a primeira etapa ATIVA pela ordem configurada que não seja
    de ganho nem de perda. Puramente uma SUGESTÃO de `initial=` no form —
    nunca hardcoded ("ORÇAMENTO" ou qualquer nome fixo), nunca contorna a
    validação real: `OpportunityCreateForm.stage` continua restrito ao
    MESMO queryset (`is_active=True, is_won=False, is_lost=False`) e
    `apps.crm.services.create_opportunity()` continua sendo quem de fato
    rejeita qualquer etapa de ganho/perda/inativa — esta função só decide
    QUAL etapa desse conjunto já vem pré-marcada no `<select>`, o usuário
    pode sempre trocar por outra etapa elegível antes de criar. Se não
    houver nenhuma etapa elegível configurada, retorna `None` e o campo
    nasce sem seleção (mesmo comportamento de hoje).
    """
    return (
        OpportunityStage.objects.filter(is_active=True, is_won=False, is_lost=False)
        .order_by("order", "name")
        .first()
    )


def _new_opportunity_create_form(data=None):
    """
    Fábrica única do `OpportunityCreateForm` "em branco" (GET) — usada
    tanto pela rota tradicional (`OpportunityCreateView.get`) quanto pelo
    Kanban (`OpportunityListView.get`, para o drawer) — para as duas
    nascerem com a MESMA etapa inicial sugerida (`_default_new_opportunity_
    stage`), nunca divergindo entre os dois pontos de entrada. `data`
    (POST) nunca passa por aqui — um form BOUND nunca deve ter `initial`
    reaplicado por cima do que o usuário enviou.
    """
    initial = {}
    default_stage = _default_new_opportunity_stage()
    if default_stage is not None:
        initial["stage"] = default_stage.pk
    return OpportunityCreateForm(initial=initial)


def _stage_summary(stage, params):
    """
    Contagem + valor total consolidado de uma etapa, respeitando os
    filtros ativos (`params`) — usado pelo endpoint AJAX para devolver os
    totais atualizados de origem/destino depois de um arraste, sem o
    front precisar duplicar nenhuma lógica de soma/formatação (mesma
    função `format_brl` usada em todo o resto do sistema).

    Mesma regra de `display_value` do Kanban: valor de fechamento se a
    oportunidade já está fechada (ganha), senão o valor estimado (ou zero
    se nenhum dos dois foi informado) — nunca os dois somados.
    """
    stage_opportunities = _filtered_opportunities_queryset(params).filter(stage_id=stage.pk)
    total = Decimal(0)
    count = 0
    for opportunity in stage_opportunities:
        count += 1
        total += opportunity.closed_value if opportunity.closed_value is not None else (opportunity.estimated_value or Decimal(0))
    return {"id": stage.pk, "count": count, "total_value_display": format_brl(total)}


class OpportunityListView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Funil Kanban de oportunidades — SUBSTITUI por completo a antiga
    listagem em tabela paginada (decisão de produto, 11/09/2026: "Kanban
    substitui a listagem por completo"). Continua no MESMO nome de
    view/URL/endpoint (`crm:opportunity_list`, `/crm/oportunidades/`) —
    nenhum link/teste existente para a listagem precisa mudar de destino.

    Sem paginação: um funil mostra TODAS as oportunidades do filtro
    corrente, agrupadas por etapa — "próxima página" não é um conceito
    que existe num Kanban. Em volume muito grande isso pode significar
    uma coluna com scroll interno longo; nenhum "carregar mais" por
    coluna foi pedido nesta rodada.
    """

    permission_required = "crm.view_opportunities"

    def get(self, request):
        opportunities = list(_filtered_opportunities_queryset(request.GET).order_by("-created_at"))

        # `display_value`: MESMA regra usada em `_stage_summary` acima —
        # atributo calculado em memória (nunca gravado no banco), só para
        # o template não repetir a mesma expressão condicional em cada
        # card.
        for opportunity in opportunities:
            opportunity.display_value = (
                opportunity.closed_value if opportunity.closed_value is not None else (opportunity.estimated_value or Decimal(0))
            )

        opportunities_by_stage = {}
        for opportunity in opportunities:
            opportunities_by_stage.setdefault(opportunity.stage_id, []).append(opportunity)

        columns = []
        for stage in OpportunityStage.objects.filter(is_active=True).order_by("order", "name"):
            stage_opportunities = opportunities_by_stage.get(stage.pk, [])
            total = sum((o.display_value for o in stage_opportunities), Decimal(0))
            columns.append(
                {
                    "stage": stage,
                    "opportunities": stage_opportunities,
                    "count": len(stage_opportunities),
                    "total_value_display": format_brl(total),
                }
            )

        can_add_opportunity = request.user.has_perm("crm.add_opportunities")
        context = {
            "columns": columns,
            "sources": CommercialSource.objects.filter(is_active=True).order_by("order", "name"),
            "business_type_choices": Opportunity._meta.get_field("business_type").choices,
            "selected_source": request.GET.get("source", ""),
            "selected_business_type": request.GET.get("business_type", ""),
            "q": request.GET.get("q", ""),
            "can_change_stage": request.user.has_perm("crm.change_opportunity_stage"),
            "can_add_opportunity": can_add_opportunity,
            # Form de criação rápida embutido no drawer lateral do Kanban
            # (rodada "CRIAÇÃO RÁPIDA SEM SAIR DO FUNIL", 11/09/2026) — só
            # instanciado (e só as queries de `client`/`owner`/`source`/
            # `stage` elegíveis disparadas) para quem TEM a permissão;
            # sem permissão nenhuma nem o botão "+ Nova oportunidade"
            # aparece no template. Mesmo form/mesma fábrica usados pela
            # rota tradicional (`OpportunityCreateView.get`) — nunca uma
            # segunda definição de campos.
            "create_form": _new_opportunity_create_form() if can_add_opportunity else None,
            "can_manage_settings": request.user.has_perm("crm.manage_commercial_settings"),
            # Embutido via `json_script` no template para o JS de
            # drag-and-drop montar o <select> de motivo de perda do modal
            # exigido ao soltar um card numa etapa `is_lost` — nunca
            # interpolado cru (XSS-safe, mesmo padrão de `json_script` do
            # próprio Django).
            "loss_reasons": list(LossReason.objects.filter(is_active=True).order_by("order", "name").values("id", "name")),
        }
        return render(request, "crm/opportunity_list.html", context)


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
        # Já vem ordenada `-created_at` acima — o primeiro item é sempre o
        # mais recente. `None` (nunca uma string vazia) quando não há
        # nenhuma atividade OU quando o usuário não tem
        # `view_commercial_activities`, para o template distinguir
        # "sem atividade" de "sem permissão para ver".
        last_activity = activities.first() if can_view_activities else None

        can_change_stage = request.user.has_perm("crm.change_opportunity_stage")

        # REDESIGN COMPLETO DA TELA INTERNA DA OPORTUNIDADE (12/09/2026):
        # "Registrar perda"/"Orçamento aceito" nunca hardcodeiam qual
        # etapa é ganho/perda — sempre a CONFIGURAÇÃO real (`is_won`/
        # `is_lost`, só entre etapas ATIVAS). Zero, uma ou várias etapas
        # podem estar marcadas (ver docstring de `OpportunityStage`) — os
        # botões só aparecem quando existe pelo menos uma candidata, e a
        # tela apresenta um `<select>` dentro do modal quando há mais de
        # uma (nunca escolhe sozinha por nome/heurística).
        # Materializadas em lista (não querysets "vivos") de propósito:
        # o template reusa cada uma mais de uma vez (contagem para
        # decidir select-com-múltiplas-opções vs. campo único, iteração
        # das opções, valor da única candidata) — uma lista evita repetir
        # a mesma consulta a cada uso, ao contrário de um QuerySet.
        won_stages = list(OpportunityStage.objects.filter(is_active=True, is_won=True).order_by("order", "name"))
        lost_stages = list(OpportunityStage.objects.filter(is_active=True, is_lost=True).order_by("order", "name"))
        all_active_stages = list(OpportunityStage.objects.filter(is_active=True).order_by("order", "name"))

        # A interface precisa refletir o estado JÁ alcançado: uma
        # oportunidade já perdida não mostra "Registrar perda" como se
        # ainda estivesse aberta, e vice-versa para "Orçamento aceito"
        # (pedido explícito). A ação OPOSTA continua disponível — reabrir
        # por engano é uma mudança de etapa normal, já suportada pelo
        # `change_opportunity_stage()` (semântica de "reabertura").
        can_show_registrar_perda = can_change_stage and bool(lost_stages) and not opportunity.stage.is_lost
        can_show_orcamento_aceito = can_change_stage and bool(won_stages) and not opportunity.stage.is_won

        context = {
            "opportunity": opportunity,
            "stage_changes": stage_changes,
            "activities": activities,
            "last_activity": last_activity,
            "can_view_activities": can_view_activities,
            "can_change_opportunity": request.user.has_perm("crm.change_opportunities"),
            "can_change_stage": can_change_stage,
            "can_add_activity": request.user.has_perm("crm.add_commercial_activities"),
            "stage_change_form": OpportunityStageChangeForm() if can_change_stage else None,
            "activity_form": CommercialActivityForm() if can_view_activities and request.user.has_perm("crm.add_commercial_activities") else None,
            "won_stages": won_stages,
            "lost_stages": lost_stages,
            "all_active_stages": all_active_stages,
            "can_show_registrar_perda": can_show_registrar_perda,
            "can_show_orcamento_aceito": can_show_orcamento_aceito,
        }
        return render(request, "crm/opportunity_detail.html", context)


class OpportunityCreateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Rota tradicional de criação — MANTIDA de propósito (rodada "CRIAÇÃO
    RÁPIDA EM DRAWER", 11/09/2026: "NÃO remover automaticamente a rota
    tradicional... pode continuar existindo como fallback/compatibilidade/
    acesso direto"). Serve três papéis agora: (1) acesso direto por URL/
    bookmark; (2) fallback sem JavaScript — o botão "+ Nova oportunidade"
    do Kanban continua sendo um `<a href>` de verdade para esta MESMA URL,
    só interceptado por JS quando disponível (ver templates/crm/
    opportunity_list.html + static/crm/opportunity_quick_create.js); (3)
    resposta ao POST do PRÓPRIO drawer, via `fetch()` para esta mesma URL
    — o drawer não é uma arquitetura paralela, é o MESMO endpoint, só
    detectado pelo cabeçalho `X-Requested-With: XMLHttpRequest` (idêntico
    ao padrão já usado em `OpportunityStageChangeView`) para decidir a
    FORMA da resposta:
      - GET sempre continua devolvendo a página cheia (o drawer nunca
        busca este form via AJAX — nasce já embutido no HTML do Kanban,
        ver `OpportunityListView.get`, para abrir instantaneamente sem
        round-trip extra);
      - POST inválido: AJAX recebe só o FRAGMENTO de campos (com erros
        bound, re-injetado no drawer sem fechar/perder o que já foi
        digitado); não-AJAX continua recebendo a página cheia de sempre;
      - POST válido: AJAX recebe JSON (card pronto + resumo da coluna,
        para o Kanban se atualizar sem recarregar); não-AJAX continua
        com o redirect + mensagem de sempre.
    Em NENHUM dos dois caminhos a validação ou a regra de negócio muda —
    os dois chamam exatamente o mesmo `OpportunityCreateForm` e o mesmo
    `apps.crm.services.create_opportunity()`.
    """

    permission_required = "crm.add_opportunities"

    def get(self, request):
        return render(request, "crm/opportunity_form.html", {"form": _new_opportunity_create_form(), "is_new": True})

    def post(self, request):
        form = OpportunityCreateForm(request.POST)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if not form.is_valid():
            if is_ajax:
                return render(request, "crm/_opportunity_quick_create_fields.html", {"form": form}, status=400)
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
                    # "Valor estimado"/"Previsão de fechamento" REMOVIDOS da
                    # criação (pedido de 12/09/2026: "quando colocarmos os
                    # equipamentos os valores vão puxar automático" — não
                    # tem necessidade de pedir na criação). `NewOpportunityData`
                    # já tem os dois como `None` por padrão — continuam
                    # editáveis depois via `OpportunityUpdateForm`, que NÃO
                    # foi tocado; só a criação ficou mais enxuta.
                    notes=cleaned["notes"],
                )
            )
        except ValueError as exc:
            form.add_error(None, str(exc))
            if is_ajax:
                return render(request, "crm/_opportunity_quick_create_fields.html", {"form": form}, status=400)
            return render(request, "crm/opportunity_form.html", {"form": form, "is_new": True})

        if is_ajax:
            # Mesma regra de `display_value` de `OpportunityListView`/
            # `_stage_summary` — uma oportunidade recém-criada nunca tem
            # `closed_value` (não pode nascer ganha/perdida, ver
            # `create_opportunity`), mas a expressão completa é repetida
            # aqui por clareza/defesa em profundidade, não só `estimated_
            # value`.
            opportunity.display_value = (
                opportunity.closed_value if opportunity.closed_value is not None else (opportunity.estimated_value or Decimal(0))
            )
            card_html = render_to_string(
                "crm/_opportunity_kanban_card.html",
                {
                    "opportunity": opportunity,
                    "stage": opportunity.stage,
                    "can_change_stage": request.user.has_perm("crm.change_opportunity_stage"),
                },
                request=request,
            )
            # A oportunidade recém-criada só é inserida visualmente no
            # Kanban se ela também passaria pelos FILTROS ativos no
            # momento (busca/origem/tipo de negócio, os mesmos 3 campos
            # da toolbar) — mesma fonte única de verdade do resto da
            # tela (`_filtered_opportunities_queryset`), nunca uma cópia
            # da lógica de filtro reimplementada em JS. Criada no banco
            # de qualquer forma; só a apresentação imediata respeita o
            # filtro corrente (ver static/crm/opportunity_quick_create.js).
            matches_current_filters = _filtered_opportunities_queryset(request.GET).filter(pk=opportunity.pk).exists()
            return JsonResponse(
                {
                    "ok": True,
                    "message": f"Oportunidade \"{opportunity.title}\" criada.",
                    "stage_id": opportunity.stage_id,
                    "matches_current_filters": matches_current_filters,
                    "destination_stage": _stage_summary(opportunity.stage, request.GET),
                    "card_html": card_html,
                }
            )

        messages.success(request, f"Oportunidade \"{opportunity.title}\" criada.")
        return redirect("crm:opportunity_detail", pk=opportunity.pk)


class OpportunityClientAutocompleteView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Endpoint pequeno e específico de busca de `Client` para o campo
    "Cliente" da criação de oportunidade (CORRIGIR DEFINITIVAMENTE O
    CAMPO CLIENTE — AUTOCOMPLETE PESQUISÁVEL, 12/09/2026). Substitui o
    `<select>` nativo que carregava TODOS os clientes ativos de uma vez
    por uma busca sob demanda: no máximo `RESULT_LIMIT` resultados por
    requisição, nunca a listagem completa — continua rápido com 700,
    2.000 ou 10.000 clientes porque a página NUNCA recebe a lista
    inteira, só o que o usuário efetivamente digitou.

    Só GET, exigindo `crm.add_opportunities` — a MESMA permissão já
    exigida para alcançar as duas telas onde o campo "Cliente" aparece
    (`/crm/oportunidades/nova/` e o drawer do Kanban). `client` não
    existe em `OpportunityUpdateForm` (é imutável depois de criada a
    oportunidade — ver docstring de `OpportunityCreateForm`), então
    nenhuma outra permissão precisa ser considerada aqui.

    Query com menos de `MIN_QUERY_LENGTH` caracteres devolve uma lista
    vazia SEM consultar o banco — não é um erro, é o estado normal
    enquanto o usuário ainda está digitando (o front-end já nem chega a
    disparar a requisição antes de 3 caracteres; esta checagem aqui é
    defesa em profundidade, nunca a única camada). Resposta
    deliberadamente mínima ("Não retornar dados fiscais completos"): só
    `id` e `name` (nome de exibição via `Client.display_name()` — nome
    fantasia, senão razão social, senão o próprio CNPJ), nunca
    documento/telefone/e-mail/endereço.

    Ordenação em 3 níveis, pedido explícito ("não resultados
    aleatórios"): (0) prefixo exato — nome ou CNPJ começam com o texto
    digitado; (1) contém — o texto aparece em qualquer posição; (2)
    similaridade aproximada real via `pg_trgm`/`TrigramWordSimilarity`
    (extensão ativada em `apps/clients/migrations/0006_pg_trgm_
    extension.py`, recurso NATIVO do Postgres, zero infraestrutura
    nova) — cobre erro de digitação/abreviação sem cair em substring
    puro nem em resultado aleatório. Dentro de cada nível, desempate por
    nome (ordem alfabética estável).

    `TrigramWordSimilarity` (Postgres `word_similarity()`), NÃO
    `TrigramSimilarity` (Postgres `similarity()`) — deliberado, medido
    manualmente contra o próprio exemplo da especificação ("KAU" deve
    achar também "Komodoro Ind"/"Kurizaki", que não contêm "kau"):
    `similarity('kau', 'komodoro ind')` ≈ 0.06 e `similarity('kau',
    'kurizaki')` ≈ 0.08 — abaixo de qualquer limiar útil sem também
    deixar passar ruído (`similarity()` penaliza demais a diferença de
    tamanho entre uma busca curta e um nome de cliente longo).
    `word_similarity('kau', 'komodoro ind')`/`word_similarity('kau',
    'kurizaki')` ≈ 0.25 (mede o melhor trecho contínuo do nome que se
    parece com a busca, em vez do nome inteiro) — já `word_similarity('kau',
    'construtora abc ltda')` = 0.0, então o limiar abaixo continua sem
    devolver nomes sem nenhuma relação real com o texto digitado.
    """

    permission_required = "crm.add_opportunities"

    RESULT_LIMIT = 20
    MIN_QUERY_LENGTH = 3
    SIMILARITY_THRESHOLD = 0.2

    def get(self, request):
        q = request.GET.get("q", "").strip()
        if len(q) < self.MIN_QUERY_LENGTH:
            return JsonResponse({"results": []})

        contains_q = Q(trade_name__icontains=q) | Q(company_name__icontains=q) | Q(document__icontains=q)
        starts_q = Q(trade_name__istartswith=q) | Q(company_name__istartswith=q) | Q(document__istartswith=q)

        clients = (
            Client.objects.filter(is_active=True)
            .annotate(
                similarity=Greatest(
                    TrigramWordSimilarity(q, "trade_name"),
                    TrigramWordSimilarity(q, "company_name"),
                    TrigramWordSimilarity(q, "document"),
                )
            )
            .filter(contains_q | Q(similarity__gte=self.SIMILARITY_THRESHOLD))
            .annotate(
                priority=Case(
                    When(starts_q, then=Value(0)),
                    When(contains_q, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            )
            .order_by("priority", "-similarity", "trade_name", "company_name")[: self.RESULT_LIMIT]
        )

        results = [{"id": client.pk, "name": client.display_name()} for client in clients]
        return JsonResponse({"results": results})


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


class OpportunityHardDeleteView(SuperuserRequiredMixin, View):
    """
    Exclusão DEFINITIVA (hard delete) — restrita à "autoridade máxima"
    (`is_superuser` puro, nunca `crm.change_opportunities`/nenhuma outra
    Permission do catálogo; ver `apps.core.hard_delete` e
    `apps.crm.services.hard_delete_opportunity`). Único caminho de
    exclusão real de `Opportunity` no sistema — o model nem é
    `SoftDeleteModel` (ver docstring de `apps.crm.models.Opportunity`),
    então antes desta rodada não havia NENHUMA forma de remover uma
    oportunidade, nem de teste.
    """

    def get(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        impact = preview_opportunity_hard_delete(opportunity)
        return render(
            request,
            "crm/opportunity_hard_delete_confirm.html",
            {"opportunity": opportunity, "impact": impact, "form": HardDeleteConfirmForm()},
        )

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        impact = preview_opportunity_hard_delete(opportunity)
        form = HardDeleteConfirmForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                "crm/opportunity_hard_delete_confirm.html",
                {"opportunity": opportunity, "impact": impact, "form": form},
            )

        try:
            result = hard_delete_opportunity(opportunity_id=opportunity.pk, actor=request.user)
        except HardDeleteBlocked as exc:
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        extra = f" ({result.total_dependents} registro(s) dependente(s) removido(s) junto.)" if result.total_dependents else ""
        messages.success(request, f"{result.target_label.capitalize()} foi excluída definitivamente.{extra}")
        return redirect("crm:opportunity_list")


class OpportunityStageChangeView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Só POST (deliberado — sem `get()`, então `GET` recebe 405 do próprio
    `django.views.View`): mudar etapa/ganhar/perder é sempre uma escrita,
    nunca uma navegação. Exige as DUAS permissões — ver a oportunidade E
    poder mudar sua etapa — para nunca alterar o estado de algo que o
    próprio usuário não teria como ver antes.

    MESMO endpoint para os dois fluxos da tela — o form inline da ficha
    da oportunidade (`opportunity_detail.html`, POST normal) E o
    arraste de card do Kanban (`static/crm/kanban.js`, POST via
    `fetch()`): a distinção é só a RESPOSTA (redirect+messages vs. JSON),
    nunca a validação nem a regra de negócio — as duas chamam exatamente
    o mesmo `OpportunityStageChangeForm` e o mesmo
    `apps.crm.services.change_opportunity_stage()`, então não existe
    nenhum caminho de escrita "mais permissivo" pelo Kanban. A detecção é
    pelo cabeçalho `X-Requested-With: XMLHttpRequest`, que
    `static/crm/kanban.js` sempre envia e o form HTML normal nunca envia
    (nenhum `fetch()`/`XMLHttpRequest` por trás de um `<form>` comum).
    """

    permission_required = ("crm.view_opportunities", "crm.change_opportunity_stage")

    def post(self, request, pk):
        opportunity = get_object_or_404(Opportunity, pk=pk)
        form = OpportunityStageChangeForm(request.POST)
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if not form.is_valid():
            errors = [error for field_errors in form.errors.values() for error in field_errors]
            if is_ajax:
                return JsonResponse(
                    {"ok": False, "error": " ".join(errors) or "Não foi possível mudar a etapa."}, status=400
                )
            messages.error(request, "Não foi possível mudar a etapa — corrija os erros abaixo.")
            for error in errors:
                messages.error(request, error)
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        cleaned = form.cleaned_data
        origin_stage = opportunity.stage
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
            if is_ajax:
                return JsonResponse({"ok": False, "error": str(exc)}, status=400)
            messages.error(request, str(exc))
            return redirect("crm:opportunity_detail", pk=opportunity.pk)

        if is_ajax:
            # Os filtros ativos no Kanban no momento do arraste chegam na
            # própria querystring desta URL de POST (ver
            # `static/crm/kanban.js`) — `request.GET` os enxerga
            # normalmente mesmo numa requisição POST (Django sempre
            # analisa a querystring da URL, independente do método).
            return JsonResponse(
                {
                    "ok": True,
                    "message": f"Etapa alterada para \"{cleaned['stage'].name}\".",
                    "origin_stage": _stage_summary(origin_stage, request.GET),
                    "destination_stage": _stage_summary(cleaned["stage"], request.GET),
                }
            )

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
