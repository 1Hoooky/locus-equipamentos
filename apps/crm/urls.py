from django.urls import path

from apps.crm import views

app_name = "crm"

urlpatterns = [
    path("oportunidades/", views.OpportunityListView.as_view(), name="opportunity_list"),
    path("oportunidades/nova/", views.OpportunityCreateView.as_view(), name="opportunity_create"),
    path(
        "oportunidades/clientes/buscar/",
        views.OpportunityClientAutocompleteView.as_view(),
        name="opportunity_client_autocomplete",
    ),
    path("oportunidades/<int:pk>/", views.OpportunityDetailView.as_view(), name="opportunity_detail"),
    path("oportunidades/<int:pk>/editar/", views.OpportunityUpdateView.as_view(), name="opportunity_update"),
    path("oportunidades/<int:pk>/etapa/", views.OpportunityStageChangeView.as_view(), name="opportunity_change_stage"),
    path(
        "oportunidades/<int:pk>/excluir-definitivamente/",
        views.OpportunityHardDeleteView.as_view(),
        name="opportunity_hard_delete",
    ),
    path(
        "oportunidades/<int:pk>/atividades/nova/",
        views.CommercialActivityCreateView.as_view(),
        name="activity_create",
    ),
    # Produtos e Serviços / Proposta Comercial + Contrato (14/09/2026)
    path(
        "oportunidades/<int:pk>/produtos-servicos/itens/adicionar/",
        views.ProposalItemAddView.as_view(),
        name="proposal_item_add",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/itens/<int:item_pk>/editar/",
        views.ProposalItemUpdateView.as_view(),
        name="proposal_item_update",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/itens/<int:item_pk>/remover/",
        views.ProposalItemRemoveView.as_view(),
        name="proposal_item_remove",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/condicoes/",
        views.ProposalConditionsSaveView.as_view(),
        name="proposal_conditions_save",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/nova-versao/",
        views.ProposalNewVersionView.as_view(),
        name="proposal_new_version",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/gerar-documento/",
        views.ProposalGenerateDocumentView.as_view(),
        name="proposal_generate_document",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/aceitar/",
        views.ProposalAcceptVersionView.as_view(),
        name="proposal_accept_version",
    ),
    path(
        "oportunidades/<int:pk>/produtos-servicos/disponibilidade/",
        views.AvailabilityCheckView.as_view(),
        name="proposal_availability_check",
    ),
    path(
        "oportunidades/<int:pk>/anexos/<int:attachment_pk>/download/",
        views.AttachmentDownloadView.as_view(),
        name="attachment_download",
    ),
    path("configuracoes/origens/", views.CommercialSourceListView.as_view(), name="commercial_source_list"),
    path("configuracoes/origens/nova/", views.CommercialSourceCreateView.as_view(), name="commercial_source_create"),
    path(
        "configuracoes/origens/<int:pk>/editar/",
        views.CommercialSourceUpdateView.as_view(),
        name="commercial_source_update",
    ),
    path("configuracoes/etapas/", views.OpportunityStageListView.as_view(), name="opportunity_stage_list"),
    path("configuracoes/etapas/nova/", views.OpportunityStageCreateView.as_view(), name="opportunity_stage_create"),
    path(
        "configuracoes/etapas/<int:pk>/editar/",
        views.OpportunityStageUpdateView.as_view(),
        name="opportunity_stage_update",
    ),
    path("configuracoes/motivos-perda/", views.LossReasonListView.as_view(), name="loss_reason_list"),
    path("configuracoes/motivos-perda/nova/", views.LossReasonCreateView.as_view(), name="loss_reason_create"),
    path(
        "configuracoes/motivos-perda/<int:pk>/editar/",
        views.LossReasonUpdateView.as_view(),
        name="loss_reason_update",
    ),
]
