"""
Painel visual "Movimentar equipamento" — ficha privada do equipamento
(rodada de UX/UI seguinte à listagem agrupada por modelo, item 21 do
histórico deste projeto). Cobre o checklist de 14 itens do pedido:

 1-2. ações permitidas continuam presentes / proibidas continuam ausentes
      (por status — `MovementPanelStatusCoverageTest`).
 3-4. permissões preservadas / CONSULTA não ganha escrita
      (`MovementPanelPermissionTest`).
 5.   URLs continuam apontando para `operations:movement_create`
      (`MovementPanelPermissionTest`/`MovementCardLinksAndIconsTest`).
 6-7. cada card tem texto visível e o ícone esperado
      (`MovementCardLinksAndIconsTest`).
 9.   manutenção aberta continua bloqueando as movimentações que já
      bloqueava, mesmo quando o status sozinho permitiria
      (`MovementPanelBlockedByOpenMaintenanceTest` — reproduz o MESMO
      cenário já coberto por
      `apps.maintenance.tests.test_maintenance_movement_compatibility`,
      agora verificando o PAINEL, não só o `create_movement()`).
10.   ação técnica (Maintenance, "Abrir manutenção") nunca é confundida
      com Movement ("Enviar à manutenção") — hrefs/ícones diferentes,
      os dois continuam visíveis lado a lado
      (`MovementActionsNeverConfusedWithMaintenanceTest`).

Os itens 8 ("nenhuma regra de Movement foi alterada"), 12 ("fragmento
HTMX da listagem agrupada continua funcionando"), 13 ("QR/Etiqueta
continuam obedecendo às permissões existentes") e 14 ("suíte da
listagem agrupada continua passando") são garantidos pela suíte JÁ
EXISTENTE — `apps.operations.tests.test_movement_services`/
`test_movement_concurrency`/`test_movement_destination_selection`,
`apps.maintenance.tests.test_maintenance_movement_*`,
`apps.equipment.tests.test_equipment_grouped_listing`, e os testes de
QR/etiqueta espalhados em `apps.equipment`/`apps.qrcodes` — todos
rodados sem nenhuma alteração nesta etapa (ver relatório de entrega).
Não duplicados aqui de propósito: duas cópias da MESMA garantia podem
divergir com o tempo: uma passa a mentir enquanto a outra já capturou
uma regressão real.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import Role
from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client
from apps.equipment.models import Status
from apps.equipment.movement_panel import available_movement_actions
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.services import NewMaintenanceData, open_maintenance
from apps.operations.models import LocationType, MovementType
from apps.operations.services import NewLocationData, NewMovementData, create_location, create_movement

User = get_user_model()


def _set_status(equipment, status):
    equipment.status = status
    equipment.save(update_fields=["status"])
    return equipment


class MovementPanelStatusCoverageTest(TestCase):
    """Itens 1-2: só os MovementTypes cujo `required_statuses` bate com o status atual viram card."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Painel")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Painel", code="MVPN")
        cls.admin = User.objects.create_user(username="painel_admin", password="senha-forte-123", role=Role.ADMIN)

    def _equipment(self, status):
        equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        return _set_status(equipment, status)

    def test_disponivel_mostra_instalar_e_enviar_manutencao(self):
        equipment = self._equipment(Status.DISPONIVEL)
        types = {a.movement_type for a in available_movement_actions(equipment)}
        self.assertEqual(types, {"INSTALACAO", "ENVIO_MANUTENCAO"})

    def test_em_operacao_mostra_retirar_transferir_retorno_estoque_e_enviar_manutencao(self):
        equipment = self._equipment(Status.EM_OPERACAO)
        types = {a.movement_type for a in available_movement_actions(equipment)}
        self.assertEqual(types, {"RETIRADA", "TRANSFERENCIA", "RETORNO_ESTOQUE", "ENVIO_MANUTENCAO"})

    def test_manutencao_mostra_retorno_estoque_e_retorno_manutencao(self):
        equipment = self._equipment(Status.MANUTENCAO)
        types = {a.movement_type for a in available_movement_actions(equipment)}
        self.assertEqual(types, {"RETORNO_ESTOQUE", "RETORNO_MANUTENCAO"})

    def test_inativo_nao_mostra_nenhuma_movimentacao(self):
        equipment = self._equipment(Status.INATIVO)
        self.assertEqual(available_movement_actions(equipment), [])

    def test_ordem_segue_movement_type_choices(self):
        # EM_OPERACAO admite 4 tipos — confirma que a ordem do painel é a
        # MESMA de `apps.operations.forms.MOVEMENT_TYPE_CHOICES`, nunca
        # uma ordem arbitrária/alfabética inventada no template.
        equipment = self._equipment(Status.EM_OPERACAO)
        types = [a.movement_type for a in available_movement_actions(equipment)]
        self.assertEqual(types, ["RETIRADA", "TRANSFERENCIA", "RETORNO_ESTOQUE", "ENVIO_MANUTENCAO"])


class MovementPanelBlockedByOpenMaintenanceTest(TestCase):
    """
    Item 9: mesmo cenário de
    `apps.maintenance.tests.test_maintenance_movement_compatibility`
    (Maintenance aberta SEM movimento enquanto DISPONIVEL, depois um
    RETORNO_ESTOQUE traz o status de volta a DISPONIVEL "por fora", sem
    fechar a ficha) — agora verificando que o PAINEL também esconde
    exatamente os mesmos 4 tipos que `create_movement()` já rejeitava.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Painel Bloqueio")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Painel Bloqueio", code="MVPB")
        cls.admin = User.objects.create_user(username="painel_bloq_admin", password="senha-forte-123", role=Role.ADMIN)
        cls.tecnico = User.objects.create_user(
            username="painel_bloq_tecnico", password="senha-forte-123", role=Role.OPERACIONAL
        )
        cls.estoque = create_location(NewLocationData(name="Estoque Painel Bloqueio", type=LocationType.ESTOQUE))

    def test_disponivel_com_manutencao_aberta_por_fora_nao_mostra_nenhum_card(self):
        equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        # DISPONIVEL -> abre manutenção sem movimento (muda status para MANUTENCAO).
        open_maintenance(
            NewMaintenanceData(
                equipment_id=equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        # RETORNO_ESTOQUE traz de volta a DISPONIVEL "por fora" — Maintenance segue ABERTA.
        create_movement(
            NewMovementData(
                equipment_id=equipment.pk,
                movement_type=MovementType.RETORNO_ESTOQUE,
                created_by=self.admin,
                destination_location=self.estoque,
            )
        )
        equipment.refresh_from_db()
        self.assertEqual(equipment.status, Status.DISPONIVEL)

        # DISPONIVEL sozinho admitiria INSTALACAO/ENVIO_MANUTENCAO — os
        # dois estão em `_BLOCKED_BY_OPEN_MAINTENANCE`, então ficam de
        # fora enquanto a Maintenance seguir aberta.
        self.assertEqual(available_movement_actions(equipment), [])

    def test_manutencao_com_manutencao_aberta_mostra_os_dois_retornos_normalmente(self):
        equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        open_maintenance(
            NewMaintenanceData(
                equipment_id=equipment.pk, maintenance_type="CORRETIVA", responsible=self.tecnico, created_by=self.admin
            )
        )
        equipment.refresh_from_db()
        self.assertEqual(equipment.status, Status.MANUTENCAO)

        # RETORNO_ESTOQUE/RETORNO_MANUTENCAO NÃO estão em
        # `_BLOCKED_BY_OPEN_MAINTENANCE` — continuam disponíveis mesmo
        # com a ficha técnica aberta (são os fatos físicos que trazem o
        # equipamento de volta).
        types = {a.movement_type for a in available_movement_actions(equipment)}
        self.assertEqual(types, {"RETORNO_ESTOQUE", "RETORNO_MANUTENCAO"})


class MovementPanelPermissionTest(TestCase):
    """Itens 3-5: permissões preservadas, CONSULTA sem escrita, hrefs corretos."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Painel Permissão")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Painel Permissão", code="MVPP")
        creator = User.objects.create_user(username="painel_perm_creator", password="senha-forte-123", role=Role.ADMIN)
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=creator))
        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL, Role.CONSULTA):
            User.objects.create_user(username=f"painel_perm_{role.lower()}", password="senha-forte-123", role=role)

    def _get(self, role):
        self.client.login(username=f"painel_perm_{role.lower()}", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/")
        self.client.logout()
        return response

    def test_admin_administrativo_operacional_veem_o_painel(self):
        for role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL):
            with self.subTest(role=role):
                content = self._get(role).content.decode()
                self.assertIn("Movimentar equipamento", content)
                self.assertIn("Instalar", content)  # DISPONIVEL por padrão em create_equipment

    def test_consulta_nao_ve_o_painel_nem_o_link_do_formulario_completo(self):
        # Rodada de UX/UI mobile-first (31/08/2026): o link para o
        # formulário completo de movimentação foi reescrito de "Ver
        # formulário completo de movimentação" para "Outras movimentações"
        # (mesmo href, sem `?movement_type=`, agora de baixa ênfase visual
        # abaixo da grade de cards) — o comportamento continua o mesmo:
        # Consulta não vê nem o painel nem este link secundário.
        content = self._get(Role.CONSULTA).content.decode()
        self.assertNotIn("Movimentar equipamento", content)
        self.assertNotIn("Outras movimentações", content)
        self.assertNotIn(f"/operacao/movimentar/{self.equipment.patrimonio}/", content)

    def test_consulta_nao_consegue_acessar_o_endpoint_de_movimentacao_diretamente(self):
        # Escondido na ficha não é suficiente sozinho — confirma que o
        # backend (RoleRequiredMixin/CAN_REGISTER_OPERATIONS, já
        # existente) também recusa, mesmo tentando a URL direto.
        self.client.login(username="painel_perm_consulta", password="senha-forte-123")
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        self.assertEqual(response.status_code, 403)

    def test_card_instalar_aponta_para_movement_create_com_tipo_na_querystring(self):
        content = self._get(Role.ADMIN).content.decode()
        self.assertIn(
            f'/operacao/movimentar/{self.equipment.patrimonio}/?movement_type=INSTALACAO',
            content,
        )


class MovementCardLinksAndIconsTest(TestCase):
    """Itens 6-7: cada card tem texto visível e o ícone esperado (sem cair no fallback 'desconhecido')."""

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Painel Ícones")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Painel Ícones", code="MVPI")
        cls.admin = User.objects.create_user(username="painel_icone_admin", password="senha-forte-123", role=Role.ADMIN)

    def _render(self, status):
        equipment = create_equipment(NewEquipmentData(model_id=self.model.pk, created_by=self.admin))
        _set_status(equipment, status)
        self.client.login(username="painel_icone_admin", password="senha-forte-123")
        response = self.client.get(f"/equipamentos/{equipment.patrimonio}/")
        self.client.logout()
        return response.content.decode()

    def test_nenhum_icone_cai_no_fallback_desconhecido(self):
        # `apps.core.templatetags.icons.icon()` imprime um comentário
        # "icon desconhecido: ..." (fail-safe) quando o nome não existe
        # no dicionário vendorizado — teste de regressão simples: se
        # algum dos 6 ícones novos não tivesse sido vendorizado, isto
        # pegaria o problema sem precisar inspecionar path SVG por path.
        content = self._render(Status.EM_OPERACAO)  # 4 tipos, mais cobertura de ícone
        self.assertNotIn("icon desconhecido", content)

    def test_cada_tipo_disponivel_mostra_texto_e_icone_esperados(self):
        expected = {
            "INSTALACAO": ("Instalar", "arrow-right-circle"),
            "ENVIO_MANUTENCAO": ("Enviar à manutenção", "wrench-screwdriver"),
        }
        content = self._render(Status.DISPONIVEL)
        for movement_type, (label, icon_name) in expected.items():
            with self.subTest(movement_type=movement_type):
                self.assertIn(label, content)

        # Ícones vendorizados: confirma que os `d=` path das duas ações
        # visíveis neste status realmente aparecem no SVG renderizado
        # (não só que o nome do ícone "existe" em abstrato).
        from apps.core.templatetags.icons import _ICONS

        self.assertIn(_ICONS["arrow-right-circle"].split('d="')[1].split('"')[0][:20], content)
        self.assertIn(_ICONS["wrench-screwdriver"].split('d="')[1].split('"')[0][:20], content)

    def test_texto_do_card_esta_sempre_visivel_nunca_so_icone(self):
        content = self._render(Status.MANUTENCAO)
        self.assertIn('<span class="movement-action-card-label">Retorno ao estoque</span>', content)
        self.assertIn('<span class="movement-action-card-label">Retorno da manutenção</span>', content)


class MovementActionsNeverConfusedWithMaintenanceTest(TestCase):
    """
    Item 10: "Enviar à manutenção" (Movement, dentro do painel) e "Abrir
    manutenção" (Maintenance, fora do painel) continuam sendo ações
    visualmente e semanticamente diferentes — mesma separação de sempre,
    só agora com o card visual ao lado.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Painel Separação")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Painel Separação", code="MVPS")
        cls.admin = User.objects.create_user(username="painel_sep_admin", password="senha-forte-123", role=Role.ADMIN)
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=cls.admin))

    def setUp(self):
        self.client.login(username="painel_sep_admin", password="senha-forte-123")

    def test_enviar_a_manutencao_e_abrir_manutencao_tem_hrefs_diferentes(self):
        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        # Movement: card do painel, aponta para operations:movement_create.
        self.assertIn(
            f"/operacao/movimentar/{self.equipment.patrimonio}/?movement_type=ENVIO_MANUTENCAO", content
        )
        # Maintenance: link de sempre, fora do painel, aponta para maintenance:maintenance_open.
        self.assertIn(f"/manutencao/manutencoes/abrir/?equipment={self.equipment.pk}", content)
        self.assertIn("Enviar à manutenção", content)
        self.assertIn("Abrir manutenção", content)

    def test_icones_diferentes_para_enviar_a_manutencao_e_abrir_manutencao(self):
        from apps.core.templatetags.icons import _ICONS

        content = self.client.get(f"/equipamentos/{self.equipment.patrimonio}/").content.decode()
        # "Abrir manutenção" (Maintenance) usa o ícone "wrench" de sempre;
        # o card "Enviar à manutenção" (Movement) usa "wrench-screwdriver"
        # — vendorizado à parte NESTA etapa, justamente para não repetir
        # visualmente o mesmo ícone de um conceito diferente (auditoria,
        # seção 12 do pedido).
        self.assertNotEqual(_ICONS["wrench"], _ICONS["wrench-screwdriver"])
        wrench_fragment = _ICONS["wrench"].split('d="')[1].split('"')[0][:20]
        wrench_screwdriver_fragment = _ICONS["wrench-screwdriver"].split('d="')[1].split('"')[0][:20]
        self.assertIn(wrench_fragment, content)
        self.assertIn(wrench_screwdriver_fragment, content)


class MovementCreatePreSelectionTest(TestCase):
    """
    O card do painel só pré-seleciona o tipo no formulário completo —
    mesmo padrão já usado por `?equipment=` em
    `apps.maintenance.views.MaintenanceOpenView`/`CleaningCreateView`
    (ver `apps.maintenance.tests.test_equipment_ficha_and_timeline.
    MaintenanceOpenPreSelectionTest`). Nunca trava o campo, nunca pula a
    validação do backend no POST.
    """

    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Categoria Pré-seleção")
        cls.model = EquipmentModel.objects.create(category=category, name="Modelo Pré-seleção", code="MVPS2")
        cls.admin = User.objects.create_user(username="preselect_admin", password="senha-forte-123", role=Role.ADMIN)
        cls.equipment = create_equipment(NewEquipmentData(model_id=cls.model.pk, created_by=cls.admin))

    def setUp(self):
        self.client.login(username="preselect_admin", password="senha-forte-123")

    def test_movement_type_valido_na_querystring_pre_seleciona_o_form(self):
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/?movement_type=INSTALACAO")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["form"].initial.get("movement_type"), "INSTALACAO")

    def test_sem_querystring_form_continua_sem_pre_selecao(self):
        response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("movement_type", response.context["form"].initial)

    def test_movement_type_invalido_e_ignorado_sem_quebrar_a_pagina(self):
        # Nunca repassa cru pro form.initial — valida contra as choices
        # reais antes (MOVEMENT_TYPE_CHOICES), então um valor arbitrário
        # na querystring não vira um "selected" inválido nem erro 500.
        response = self.client.get(
            f"/operacao/movimentar/{self.equipment.patrimonio}/?movement_type=<script>alert(1)</script>"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("movement_type", response.context["form"].initial)
        self.assertNotIn("<script>alert(1)</script>", response.content.decode())

    def test_pre_selecao_nao_muda_o_resultado_do_post(self):
        # A pré-seleção é só conveniência de exibição — o POST continua
        # exigindo os mesmos campos e validando via create_movement(),
        # exatamente como antes desta melhoria.
        cliente = Client.objects.create(company_name="Cliente Pré-seleção LTDA")
        unidade = create_location(NewLocationData(name="Unidade Pré-seleção", type=LocationType.CLIENTE, client=cliente))

        get_response = self.client.get(f"/operacao/movimentar/{self.equipment.patrimonio}/?movement_type=INSTALACAO")
        token = get_response.context["submission_token"]
        response = self.client.post(
            f"/operacao/movimentar/{self.equipment.patrimonio}/",
            {
                "submission_token": token,
                "movement_type": "INSTALACAO",
                "destination_location": unidade.pk,
                "reason": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.status, Status.EM_OPERACAO)
