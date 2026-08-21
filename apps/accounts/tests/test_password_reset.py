"""
Teste de integração HTTP do fluxo completo de recuperação de senha —
especificação, seção 12 ("Recuperação de senha") e seção 11 ("redefinição
por e-mail"). Era a única das 13 telas da seção 12 sem teste dedicado
(auditoria de arquitetura, docs/auditoria-arquitetura-fase1.md).

Escrever este teste revelou um bug real e objetivo, não apenas uma
lacuna de cobertura: o template padrão de e-mail do Django
(`registration/password_reset_email.html`) monta o link de redefinição
com `{% url 'password_reset_confirm' %}` (nome de rota SEM namespace),
mas este projeto só registra a rota com namespace
(`accounts:password_reset_confirm`, ver apps/accounts/urls.py) — então
o envio do e-mail quebrava com `NoReverseMatch` assim que alguém de
fato solicitasse a redefinição. Corrigido com um template próprio em
`templates/registration/password_reset_email.html`, que só troca o
nome da rota usada no link; nenhum outro comportamento foi alterado.

O teste usa requisições HTTP reais (não chama as views/forms
diretamente), do pedido inicial até o login com a senha nova, para que
o bug acima (que só aparece na renderização real do e-mail) seja
efetivamente coberto.
"""

import re

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

User = get_user_model()

RESET_URL = "/contas/senha/redefinir/"
DONE_URL = "/contas/senha/redefinir/enviado/"
COMPLETE_URL = "/contas/senha/redefinir/concluido/"
LOGIN_URL = "/contas/login/"

# Extrai o link de redefinição de dentro do corpo do e-mail enviado —
# não reconstruímos o link "de fora" (isso testaria nossa suposição
# sobre o formato, não o que o sistema realmente envia).
RESET_LINK_RE = re.compile(r"http://\S+?(/contas/senha/redefinir/confirmar/\S+?/\S+?)/\s")


class PasswordResetFlowTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="usuaria_esqueceu",
            email="usuaria@locuslocacoes.com.br",
            password="senha-antiga-123",
        )

    def test_password_reset_page_renders(self):
        response = self.client.get(RESET_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_reset.html")

    def test_full_reset_flow_lets_user_login_with_new_password(self):
        # 1. Solicita a redefinição.
        response = self.client.post(RESET_URL, {"email": self.user.email})
        self.assertRedirects(response, DONE_URL)

        # 2. Um e-mail real foi "enviado" (backend de teste do Django,
        #    independente do console backend usado em dev).
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertIn(self.user.email, sent.to)

        match = RESET_LINK_RE.search(sent.body)
        self.assertIsNotNone(match, f"Link de redefinição não encontrado no e-mail:\n{sent.body}")
        confirm_path = match.group(1) + "/"

        # 3. Abre o link recebido por e-mail.
        response = self.client.get(confirm_path, follow=True)
        self.assertEqual(response.status_code, 200)
        # Django troca o token da URL por "set-password" na sessão e
        # redireciona para a mesma view sem o token no path — ainda é a
        # tela de definir nova senha, só que com o link já "consumido".
        self.assertTemplateUsed(response, "accounts/password_reset_confirm.html")
        self.assertContains(response, "Defina sua nova senha")
        final_confirm_url = response.redirect_chain[-1][0] if response.redirect_chain else confirm_path

        # 4. Define a senha nova.
        response = self.client.post(
            final_confirm_url,
            {"new_password1": "senha-nova-muito-forte-456", "new_password2": "senha-nova-muito-forte-456"},
        )
        self.assertRedirects(response, COMPLETE_URL)

        response = self.client.get(COMPLETE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "accounts/password_reset_complete.html")

        # 5. A senha antiga não funciona mais; a nova funciona.
        self.assertFalse(self.client.login(username="usuaria_esqueceu", password="senha-antiga-123"))
        self.assertTrue(self.client.login(username="usuaria_esqueceu", password="senha-nova-muito-forte-456"))

    def test_unknown_email_still_redirects_without_revealing_whether_it_exists(self):
        """
        Comportamento padrão (e correto) do Django: não vaza se o e-mail
        existe ou não na base — sempre redireciona para a tela de
        "enviado", só que sem de fato enviar nada.
        """
        response = self.client.post(RESET_URL, {"email": "nao-existe@locuslocacoes.com.br"})
        self.assertRedirects(response, DONE_URL)
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_with_tampered_token_is_rejected(self):
        response = self.client.post(RESET_URL, {"email": self.user.email})
        self.assertEqual(len(mail.outbox), 1)

        match = RESET_LINK_RE.search(mail.outbox[0].body)
        self.assertIsNotNone(match)
        confirm_path = match.group(1) + "/"
        tampered_path = confirm_path[:-2] + "xx/"

        response = self.client.get(tampered_path, follow=True)
        self.assertContains(response, "Este link de redefinição não é mais válido.")

        # E, coerentemente, não é possível usar o link viciado pra logar.
        self.assertFalse(self.client.login(username="usuaria_esqueceu", password="qualquer-coisa"))
