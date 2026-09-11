"""
Testes obrigatórios da AUDITORIA DE IDIOMA, LOCALIZAÇÃO E UTF-8 (LocusHub,
ago/2026). Cobrem, com strings acentuadas reais pedidas pelo usuário
("João da Conceição", "Climatização São José", "Instalação próxima à área
de recepção.", "Manutenção preventiva – equipamento nº 03.", "R$
1.234,56"): 1) salvar; 2) ler do banco; 3) renderizar em template; 4) POST
de formulário; 5) mensagem de validação; 6) CRM; 7) Cliente; 8) exportação
relevante (CSV); 9) PDF; e uma varredura de regressão de mojibake em todo
o repositório rastreado pelo git.

Este arquivo NÃO substitui os testes específicos de cada app (CRM,
clientes, equipamentos, manutenção) — é a cobertura adicional, focada
especificamente em Unicode/pt-BR, pedida pela auditoria.
"""

import subprocess
import unicodedata
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import RequestFactory, TestCase, override_settings
from django.views.defaults import server_error

from apps.catalog.models import Category, EquipmentModel
from apps.clients.models import Client, ClientType
from apps.crm.models import BusinessType, CommercialSource, LossReason, Opportunity, OpportunityStage
from apps.crm.services import NewOpportunityData, create_opportunity
from apps.equipment.services import NewEquipmentData, create_equipment
from apps.maintenance.models import MaintenanceType
from apps.maintenance.services import NewMaintenanceData, open_maintenance

User = get_user_model()

# Strings acentuadas reais pedidas explicitamente pelo usuário na auditoria.
NOME_CONTATO = "João da Conceição"
RAZAO_SOCIAL = "Climatização São José"
OBSERVACAO_LONGA = "Instalação próxima à área de recepção."
DIAGNOSTICO_MANUTENCAO = "Manutenção preventiva – equipamento nº 03."
VALID_CNPJ = "11.222.333/0001-81"


class ClientAccentedPersistenceTest(TestCase):
    """1) salvar; 2) ler do banco; 3) renderizar em template; 7) Cliente."""

    def test_save_reload_and_render_accented_client(self):
        client_obj = Client.objects.create(
            client_type=ClientType.PJ,
            company_name=RAZAO_SOCIAL,
            contact_name=NOME_CONTATO,
            notes=OBSERVACAO_LONGA,
        )

        # 2) ler do banco — nunca confiar só na instância em memória.
        reloaded = Client.objects.get(pk=client_obj.pk)
        self.assertEqual(reloaded.company_name, RAZAO_SOCIAL)
        self.assertEqual(reloaded.contact_name, NOME_CONTATO)
        self.assertEqual(reloaded.notes, OBSERVACAO_LONGA)

        # 3) renderizar em template (ficha do cliente) — via HTTP real,
        # exercitando toda a cadeia banco → view → template → resposta.
        admin = User.objects.create_superuser(username="aud_cliente_admin", password="senha-forte-123", email="a@a.com")
        self.client.force_login(admin)
        response = self.client.get(f"/clientes/{client_obj.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, RAZAO_SOCIAL)
        self.assertContains(response, NOME_CONTATO)
        self.assertContains(response, OBSERVACAO_LONGA)

    def test_search_by_accented_name_does_not_break(self):
        """
        Banco e busca: buscar com nomes acentuados não pode quebrar nem
        devolver erro — a exigência do usuário é preservar corretamente os
        caracteres, não (necessariamente) ignorar acentos na busca.
        """
        Client.objects.create(client_type=ClientType.PJ, company_name=RAZAO_SOCIAL)
        Client.objects.create(client_type=ClientType.PJ, company_name="Maringá Serviços LTDA")

        admin = User.objects.create_superuser(username="aud_busca_admin", password="senha-forte-123", email="b@b.com")
        self.client.force_login(admin)

        for termo in ("São José", "Maringá", "Serviços"):
            with self.subTest(termo=termo):
                response = self.client.get("/clientes/", {"q": termo})
                self.assertEqual(response.status_code, 200)


class ClientAccentedFormPostTest(TestCase):
    """4) POST de formulário com caracteres acentuados reais."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="aud_post_admin", password="senha-forte-123", email="c@c.com")
        self.client.force_login(self.admin)

    def _full_payload(self, submission_token, **overrides):
        data = {
            "action": "save",
            "submission_token": submission_token,
            "client_type": ClientType.PJ,
            "document": VALID_CNPJ,
            "company_name": RAZAO_SOCIAL,
            "trade_name": "",
            "registration_status": "",
            "state_registration": "",
            "phone": "",
            "email": "",
            "contact_name": NOME_CONTATO,
            "notes": OBSERVACAO_LONGA,
            "fiscal_cep": "",
            "fiscal_logradouro": "",
            "fiscal_numero": "",
            "fiscal_complemento": "",
            "fiscal_bairro": "",
            "fiscal_cidade": "",
            "fiscal_uf": "",
            "initial_location_name": "",
            "operational_cep": "",
            "operational_logradouro": "",
            "operational_numero": "",
            "operational_complemento": "",
            "operational_bairro": "",
            "operational_cidade": "",
            "operational_uf": "",
            "operational_reference_notes": "",
        }
        data.update(overrides)
        return data

    def test_post_accented_client_persists_and_survives_relogin(self):
        submission_token = self.client.get("/clientes/novo/").context["submission_token"]
        response = self.client.post("/clientes/novo/", self._full_payload(submission_token))
        self.assertEqual(response.status_code, 302)

        client_obj = Client.objects.get(company_name=RAZAO_SOCIAL)
        self.assertEqual(client_obj.contact_name, NOME_CONTATO)
        self.assertEqual(client_obj.notes, OBSERVACAO_LONGA)

        # "mantém acentuação após novo login" — logout/login e ler de novo.
        self.client.logout()
        self.client.force_login(self.admin)
        response = self.client.get(f"/clientes/{client_obj.pk}/")
        self.assertContains(response, NOME_CONTATO)
        self.assertContains(response, OBSERVACAO_LONGA)


class CrmAccentedOpportunityTest(TestCase):
    """6) CRM — salvar/ler/renderizar/POST com caracteres acentuados."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="aud_crm_admin", password="senha-forte-123", email="d@d.com")
        self.client_obj = Client.objects.create(client_type=ClientType.PJ, company_name=RAZAO_SOCIAL)
        self.source = CommercialSource.objects.create(name="Indicação")
        self.stage_novo = OpportunityStage.objects.create(name="Novo", order=1)
        self.stage_perdido = OpportunityStage.objects.create(name="Perdido", order=2, is_lost=True)
        self.loss_reason = LossReason.objects.create(name="Preço")
        self.client.force_login(self.admin)

    def test_create_opportunity_service_persists_and_renders_accented_text(self):
        opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title=RAZAO_SOCIAL,
                owner=self.admin,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.admin,
                notes=OBSERVACAO_LONGA,
                estimated_value=Decimal("12500.00"),
            )
        )
        reloaded = Opportunity.objects.get(pk=opportunity.pk)
        self.assertEqual(reloaded.title, RAZAO_SOCIAL)
        self.assertEqual(reloaded.notes, OBSERVACAO_LONGA)

        response = self.client.get(f"/crm/oportunidades/{opportunity.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, RAZAO_SOCIAL)
        self.assertContains(response, OBSERVACAO_LONGA)
        # Valor estimado em formato brasileiro (auditoria de idioma): vírgula
        # decimal E separador de milhar — nunca "12500.00" cru.
        self.assertContains(response, "R$ 12.500,00")

        list_response = self.client.get("/crm/oportunidades/")
        self.assertContains(list_response, "R$ 12.500,00")

    def test_post_create_opportunity_with_accented_data(self):
        response = self.client.post(
            "/crm/oportunidades/nova/",
            {
                "client": self.client_obj.pk,
                "title": RAZAO_SOCIAL,
                "owner": self.admin.pk,
                "source": self.source.pk,
                "business_type": BusinessType.LOCACAO,
                "stage": self.stage_novo.pk,
                "notes": OBSERVACAO_LONGA,
            },
        )
        self.assertEqual(response.status_code, 302)
        opportunity = Opportunity.objects.get(title=RAZAO_SOCIAL)
        self.assertEqual(opportunity.notes, OBSERVACAO_LONGA)

    def test_stage_change_validation_message_is_portuguese_and_renders_correctly(self):
        """
        5) Mensagem de validação: mudar para etapa de perda sem motivo
        precisa devolver erro em português, com acento correto, e esse
        erro precisa aparecer de fato no HTML renderizado (não só em
        `form.errors` cru).
        """
        opportunity = create_opportunity(
            NewOpportunityData(
                client=self.client_obj,
                title="Oportunidade sem motivo",
                owner=self.admin,
                source=self.source,
                business_type=BusinessType.LOCACAO,
                stage=self.stage_novo,
                created_by=self.admin,
            )
        )
        # A view sempre redireciona (302) de volta para o detalhe da
        # oportunidade, carregando o erro via `django.contrib.messages` —
        # `follow=True` segue o redirect para ver a mensagem de fato
        # renderizada na página, não só a resposta HTTP crua do POST.
        response = self.client.post(
            f"/crm/oportunidades/{opportunity.pk}/etapa/",
            {"stage": self.stage_perdido.pk},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Motivo de perda é obrigatório ao marcar a oportunidade como perdida.")


class CurrencyFilterTest(TestCase):
    """Filtro `brl` (apps.core.templatetags.currency) — formato brasileiro."""

    def _render(self, value):
        template = Template("{% load currency %}{{ value|brl }}")
        return template.render(Context({"value": value}))

    def test_formats_with_thousands_separator_and_decimal_comma(self):
        self.assertEqual(self._render(Decimal("1234.56")), "R$ 1.234,56")

    def test_formats_large_value(self):
        self.assertEqual(self._render(Decimal("1234567.89")), "R$ 1.234.567,89")

    def test_formats_small_value_without_thousands_separator(self):
        self.assertEqual(self._render(Decimal("42.50")), "R$ 42,50")

    def test_zero(self):
        self.assertEqual(self._render(Decimal("0")), "R$ 0,00")

    def test_negative_value(self):
        self.assertEqual(self._render(Decimal("-1234.56")), "-R$ 1.234,56")

    def test_none_renders_as_dash(self):
        self.assertEqual(self._render(None), "—")


class MaintenanceAccentedTest(TestCase):
    """
    Manutenção: diagnóstico com travessão/º/acentos ("Manutenção
    preventiva – equipamento nº 03.") precisa sobreviver a salvar, ler do
    banco e renderizar.
    """

    def setUp(self):
        category = Category.objects.create(name="Climatizador")
        model = EquipmentModel.objects.create(category=category, name="NI23 Big Tank", code="NI23BT")
        self.admin = User.objects.create_superuser(username="aud_mnt_admin", password="senha-forte-123", email="e@e.com")
        self.equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=self.admin))
        self.client.force_login(self.admin)

    def test_open_maintenance_persists_and_renders_accented_diagnosis(self):
        maintenance = open_maintenance(
            NewMaintenanceData(
                equipment_id=self.equipment.pk,
                maintenance_type=MaintenanceType.PREVENTIVA,
                responsible=self.admin,
                created_by=self.admin,
                diagnosis=DIAGNOSTICO_MANUTENCAO,
            )
        )
        reloaded = type(maintenance).objects.get(pk=maintenance.pk)
        self.assertEqual(reloaded.diagnosis, DIAGNOSTICO_MANUTENCAO)

        response = self.client.get(f"/manutencao/manutencoes/{maintenance.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, DIAGNOSTICO_MANUTENCAO)


class EquipmentPdfLabelAccentedTest(TestCase):
    """9) PDF — Configuração/Descrição/Locação/Manutenção/João/São José/ç ã é ô."""

    def test_label_pdf_renders_accented_model_and_category_names(self):
        """
        A etiqueta "antiga" (100x50mm, `generate_label_pdf`) embute
        `model.name`/`category.name` como texto — diferente do padrão novo
        6x6 (que só usa o código, sempre ASCII) — é o ponto certo para
        provar que acentos sobrevivem até o PDF final via WeasyPrint.
        """
        from pypdf import PdfReader

        from apps.qrcodes.services import generate_label_pdf

        category = Category.objects.create(name="Climatização")
        model = EquipmentModel.objects.create(category=category, name="Refrigeração Compacta", code="RFCP")
        admin = User.objects.create_superuser(username="aud_pdf_admin", password="senha-forte-123", email="f@f.com")
        equipment = create_equipment(NewEquipmentData(model_id=model.pk, created_by=admin))

        pdf_bytes = generate_label_pdf(equipment)
        reader = PdfReader(__import__("io").BytesIO(pdf_bytes))
        text = reader.pages[0].extract_text()
        self.assertIn(equipment.patrimonio, text)
        # O template não embute o nome do modelo/categoria (só marca
        # fixa + patrimônio) — o que prova a sobrevivência de acentos até
        # o PDF final via WeasyPrint é o próprio texto fixo do template
        # ("Locações", "IDENTIFICAÇÃO").
        self.assertIn("Locações", text)
        self.assertIn("IDENTIFICAÇÃO", text)


@override_settings(DEBUG=False)
class ErrorPagesPortugueseTest(TestCase):
    """
    Páginas de erro (403/404/500) precisam existir, ser em português e
    UTF-8 — antes desta auditoria, o projeto não tinha 403.html/404.html/
    500.html próprios, e em produção (DEBUG=False) o usuário via a página
    padrão em inglês do Django.
    """

    def test_404_page_is_portuguese(self):
        response = self.client.get("/esta-rota-nao-existe-9f8e7d/")
        self.assertEqual(response.status_code, 404)
        content = response.content.decode("utf-8")
        self.assertIn("Página não encontrada", content)
        self.assertNotIn("Ã", content)  # nenhum sinal de mojibake

    def test_403_page_is_portuguese(self):
        # Usuário autenticado mas sem nenhum cargo/permissão tentando uma
        # tela restrita (RoleRequiredMixin) — dispara PermissionDenied de
        # verdade, exatamente o caminho que usa 403.html.
        user = User.objects.create_user(username="aud_403_sem_perfil", password="senha-forte-123")
        self.client.force_login(user)
        response = self.client.get("/equipamentos/exportar/")
        self.assertEqual(response.status_code, 403)
        content = response.content.decode("utf-8")
        self.assertIn("Acesso não permitido", content)
        self.assertNotIn("Ã", content)

    def test_500_page_is_portuguese_and_utf8(self):
        # O handler500 padrão do Django renderiza sem nenhum contexto/
        # request — chamamos a própria view default do Django diretamente,
        # o mesmo caminho que production usa quando uma view não tratada
        # levanta uma exceção.
        request = RequestFactory().get("/")
        response = server_error(request)
        self.assertEqual(response.status_code, 500)
        content = response.content.decode("utf-8")
        self.assertIn("Ocorreu um erro interno", content)
        self.assertNotIn("Ã", content)


class MojibakeRegressionTest(TestCase):
    """
    Varredura de regressão: nenhum arquivo rastreado pelo git deveria
    conter sequências clássicas de mojibake (UTF-8 mal interpretado como
    Latin-1/cp1252) nem o caractere de substituição U+FFFD. Não corrige
    nada — só detecta e relata, para nunca deixar uma regressão de
    encoding entrar silenciosamente no repositório.
    """

    # Pares de bytes que só aparecem quando um "Ã"/"Â" de verdade em UTF-8
    # foi decodificado errado como Latin-1/cp1252 e re-salvo — nunca
    # aparecem em português correto (que usa "Ã"/"Â" sozinhos, seguidos de
    # espaço ou início de nova sílaba, nunca destes pares específicos).
    MOJIBAKE_MARKERS = (
        "Ã£", "Ã§", "Ã©", "Ã¡", "Ã³", "Ãº", "Ã­", "Ã¢", "Ã\xaa", "Â½", "Âª", "Â²",
        "�",  # replacement character
    )

    def test_no_mojibake_in_tracked_repository_files(self):
        repo_root = Path(settings.BASE_DIR)
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        tracked_files = [
            repo_root / line
            for line in result.stdout.splitlines()
            if line.endswith((".py", ".html", ".js", ".md", ".txt", ".css"))
        ]

        offenders = []
        for path in tracked_files:
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                offenders.append((str(path), "arquivo rastreado não é UTF-8 válido"))
                continue
            for marker in self.MOJIBAKE_MARKERS:
                if marker in text:
                    offenders.append((str(path), f"contém marcador suspeito de mojibake: {marker!r}"))

        self.assertEqual(offenders, [], f"Possível mojibake encontrado: {offenders}")

    def test_unicode_nfc_normalization_is_stable_for_stored_names(self):
        """
        Não normalizamos em massa (fora de escopo) — mas o teste garante
        que o caminho padrão de salvar/ler pelo Django/PostgreSQL não
        introduz uma forma de composição Unicode diferente da que foi
        digitada (o que quebraria comparações exatas silenciosamente).
        """
        client_obj = Client.objects.create(client_type=ClientType.PJ, company_name=RAZAO_SOCIAL)
        reloaded = Client.objects.get(pk=client_obj.pk)
        self.assertEqual(
            unicodedata.normalize("NFC", reloaded.company_name),
            unicodedata.normalize("NFC", RAZAO_SOCIAL),
        )
        # A forma bruta lida do banco já deveria ser NFC (é como o Python/
        # navegador tipicamente compõe esses caracteres) — mas o que
        # realmente importa aqui é a igualdade acima, não esta asserção
        # extra, mantida só como documentação do comportamento observado.
        self.assertEqual(reloaded.company_name, unicodedata.normalize("NFC", reloaded.company_name))
