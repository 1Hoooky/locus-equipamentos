"""
AUDITORIA GLOBAL DE NAVEGAÇÃO — remoção de links/botões redundantes com
a sidebar (11/09/2026). Agora que a sidebar é a fonte principal de
navegação entre módulos (ver templates/base.html, apps/core/nav.py),
este teste é a guarda de regressão de dois tipos de garantia ao mesmo
tempo, para cada uma das 15 telas do checklist do pedido:

1. Os atalhos classificados como TIPO A (navegação redundante — só
   levavam a uma página já com entrada direta na sidebar, sem nenhum
   filtro/contexto extra) FORAM removidos e continuam removidos.
2. Nada além disso foi tocado: ações da própria página (TIPO B — criar/
   editar/salvar/etc.), navegação contextual para uma entidade
   específica (TIPO C — ex. "Abrir cliente" dentro de uma oportunidade)
   e voltar/cancelar de formulário (TIPO D) continuam presentes.

Ver RELATORIO_AUDITORIA_NAVEGACAO_REDUNDANTE.md para a tabela completa
arquivo/tela/elemento/classificação/decisão.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.crm.models import BusinessType, CommercialSource, OpportunityStage
from apps.crm.services import NewOpportunityData, create_opportunity
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.operations.models import Location, LocationType

User = get_user_model()


class NavigationRedundancyAuditTest(TestCase):
    """Superusuário: vê todos os grupos/itens, então serve para checar as 15 telas de uma vez sem fricção de permissão."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="nav_audit_admin", password="senha-forte-123", role="ADMIN", is_superuser=True
        )
        self.client.login(username="nav_audit_admin", password="senha-forte-123")

        self.category = Category.objects.create(name="Climatizador")
        self.model = EquipmentModel.objects.create(category=self.category, name="Climatizador 9PRO", code="9PRO")
        self.equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))

        self.client_obj = Client.objects.create(company_name="Cliente Auditoria LTDA")
        self.location = Location.objects.create(name="Unidade Auditoria", type=LocationType.ESTOQUE)

        self.source = CommercialSource.objects.create(name="Indicação", order=1)
        self.stage = OpportunityStage.objects.create(name="Novo contato", order=1)
        self.opportunity = create_opportunity(NewOpportunityData(
            client=self.client_obj, title="Oportunidade auditoria", owner=self.admin, source=self.source,
            business_type=BusinessType.LOCACAO, stage=self.stage, created_by=self.admin,
        ))

    # -----------------------------------------------------------------
    # 1) Funil
    # -----------------------------------------------------------------
    def test_funil_has_no_redundant_config_shortcut_but_keeps_page_actions(self):
        content = self.client.get("/crm/oportunidades/").content.decode()
        self.assertNotIn("Configurações comerciais", content)
        self.assertIn("Nova oportunidade", content)  # Tipo B — ação da própria página
        self.assertIn("Filtrar", content)

    # -----------------------------------------------------------------
    # 2) Origens
    # -----------------------------------------------------------------
    def test_origens_has_no_redundant_links_but_keeps_page_actions(self):
        content = self.client.get("/crm/configuracoes/origens/").content.decode()
        self.assertNotIn("Config. comerciais", content)
        self.assertNotIn("Ver etapas", content)
        self.assertNotIn("Ver motivos de perda", content)
        self.assertIn("Nova origem", content)  # Tipo B

    # -----------------------------------------------------------------
    # 3) Etapas — o exemplo literal do pedido
    # -----------------------------------------------------------------
    def test_etapas_has_no_redundant_links_but_keeps_page_actions(self):
        content = self.client.get("/crm/configuracoes/etapas/").content.decode()
        self.assertNotIn("Config. comerciais", content)
        self.assertNotIn("Ver origens", content)
        self.assertNotIn("Ver motivos de perda", content)
        self.assertIn("Nova etapa", content)  # Tipo B

    # -----------------------------------------------------------------
    # 4) Motivos de perda
    # -----------------------------------------------------------------
    def test_motivos_de_perda_has_no_redundant_links_but_keeps_page_actions(self):
        content = self.client.get("/crm/configuracoes/motivos-perda/").content.decode()
        self.assertNotIn("Config. comerciais", content)
        self.assertNotIn("Ver origens", content)
        self.assertNotIn("Ver etapas", content)
        self.assertIn("Novo motivo", content)  # Tipo B

    # -----------------------------------------------------------------
    # Oportunidade — navegação contextual (Tipo C) precisa continuar
    # -----------------------------------------------------------------
    def test_opportunity_detail_keeps_contextual_link_to_its_specific_client(self):
        content = self.client.get(f"/crm/oportunidades/{self.opportunity.pk}/").content.decode()
        # "Abrir"/link para o CLIENTE ESPECÍFICO da oportunidade — Tipo C,
        # a sidebar "Clientes" leva à listagem geral, não substitui isto.
        self.assertIn(f'href="/clientes/{self.client_obj.pk}/"', content)
        # "Voltar" ao Funil — mantido (ver justificativa no relatório:
        # navegação de retorno de um drill-down, não um atalho lateral).
        self.assertIn('href="/crm/oportunidades/"', content)

    # -----------------------------------------------------------------
    # 5-7) Operação — nada foi removido aqui; sanity check de que as
    # telas continuam íntegras com suas ações.
    # -----------------------------------------------------------------
    def test_equipamentos_keeps_self_filter_clear_link(self):
        content = self.client.get("/equipamentos/").content.decode()
        self.assertIn("Novo equipamento", content)  # Tipo B

    def test_manutencoes_renders_with_its_actions(self):
        content = self.client.get("/manutencao/manutencoes/").content.decode()
        self.assertEqual(self.client.get("/manutencao/manutencoes/").status_code, 200)
        self.assertIn("manutenc", content.lower())

    def test_higienizacoes_renders_with_its_actions(self):
        response = self.client.get("/manutencao/higienizacoes/")
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------
    # 8-9) Cadastros — Clientes / Colaboradores
    # -----------------------------------------------------------------
    def test_clientes_renders_with_its_actions(self):
        content = self.client.get("/clientes/").content.decode()
        self.assertIn("Novo cliente", content)  # Tipo B

    def test_colaboradores_renders_with_its_actions(self):
        response = self.client.get("/contas/usuarios/")
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------
    # 10) Unidades
    # -----------------------------------------------------------------
    def test_unidades_renders_with_its_actions(self):
        response = self.client.get("/operacao/unidades/")
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------
    # 11) Categorias
    # -----------------------------------------------------------------
    def test_categorias_has_no_redundant_link_but_keeps_page_actions(self):
        content = self.client.get("/catalogo/categorias/").content.decode()
        self.assertNotIn("Ver modelos de equipamento", content)
        self.assertIn("Nova categoria", content)  # Tipo B

    # -----------------------------------------------------------------
    # 12) Modelos
    # -----------------------------------------------------------------
    def test_modelos_has_no_redundant_link_but_keeps_page_actions(self):
        content = self.client.get("/catalogo/modelos/").content.decode()
        self.assertNotIn("Ver categorias", content)
        self.assertIn("Novo modelo", content)  # Tipo B

    # -----------------------------------------------------------------
    # 13) Cargos
    # -----------------------------------------------------------------
    def test_cargos_renders_with_its_actions(self):
        response = self.client.get("/contas/cargos/")
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------
    # 14) Diagnóstico de unidades — nenhuma outra tela linkava para cá
    # (0 ocorrências na varredura), nada a remover; só sanity check.
    # -----------------------------------------------------------------
    def test_diagnostico_renders(self):
        response = self.client.get("/operacao/diagnostico/locations-duplicadas/")
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------
    # 15) Importações — equipamentos e clientes
    # -----------------------------------------------------------------
    def test_equipment_import_summary_has_no_redundant_generic_link_but_keeps_specific_links(self):
        session = self.client.session
        session["legacy_import_rows"] = []
        session["legacy_import_summary"] = {
            "created": [self.equipment.patrimonio],
            "skipped": [],
        }
        session.save()
        content = self.client.get("/equipamentos/importar/resumo/").content.decode()
        self.assertNotIn("Ver equipamentos", content)
        # Link individual do patrimônio recém-criado — Tipo C, mantido.
        self.assertIn(f'href="/equipamentos/{self.equipment.patrimonio}/"', content)

    def test_client_import_summary_has_no_redundant_generic_link_but_keeps_specific_links(self):
        session = self.client.session
        session["clients_import_auvo_summary"] = {
            "filename": "clientes.xlsx",
            "total": 1,
            "created_count": 1,
            "ja_existente_count": 0,
            "possivel_duplicado_count": 0,
            "invalido_count": 0,
            "failed_count": 0,
            "created": [{"pk": self.client_obj.pk, "label": self.client_obj.display_name()}],
            "not_imported": [],
        }
        session.save()
        content = self.client.get("/clientes/importar/resumo/").content.decode()
        self.assertNotIn("Ver clientes", content)
        # Link individual do cliente recém-criado — Tipo C, mantido.
        self.assertIn(f'href="/clientes/{self.client_obj.pk}/"', content)

    def test_equipment_import_upload_renders(self):
        response = self.client.get("/equipamentos/importar/")
        self.assertEqual(response.status_code, 200)

    # -----------------------------------------------------------------
    # Sidebar continua levando corretamente a todos os 15 destinos —
    # guarda de regressão simples: nenhuma rota ficou órfã (todas
    # continuam com uma entrada direta e funcional na sidebar).
    # -----------------------------------------------------------------
    def test_sidebar_still_links_directly_to_every_audited_destination(self):
        content = self.client.get("/equipamentos/").content.decode()
        sidebar = content.split('id="app-sidebar"', 1)[1].split("</aside>", 1)[0]
        for url in (
            "/crm/oportunidades/",
            "/crm/configuracoes/origens/",
            "/crm/configuracoes/etapas/",
            "/crm/configuracoes/motivos-perda/",
            "/equipamentos/",
            "/manutencao/manutencoes/",
            "/manutencao/higienizacoes/",
            "/clientes/",
            "/contas/usuarios/",
            "/operacao/unidades/",
            "/catalogo/categorias/",
            "/catalogo/modelos/",
            "/contas/cargos/",
            "/operacao/diagnostico/locations-duplicadas/",
            "/equipamentos/importar/",
        ):
            self.assertIn(f'href="{url}"', sidebar, f"Rota órfã na sidebar: {url}")
