"""
Teste do django-axes (força bruta no login) — especificação, seção 11:
"django-axes contra força bruta". Reativa `AXES_ENABLED` (desligado por
padrão em config/settings/test.py — ver o docstring de lá para o motivo)
e usa requisições HTTP reais para /contas/login/, porque é a view (via
`AuthenticationForm`) quem passa `request` para `authenticate()` —
`self.client.login()` não passa, e por isso não serve para testar o
próprio axes.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

User = get_user_model()

LOGIN_URL = "/contas/login/"


@override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3, AXES_LOCKOUT_PARAMETERS=["username", "ip_address"])
class AxesLockoutTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alvo_bruteforce", password="senha-correta-123")

    def _attempt(self, password):
        return self.client.post(LOGIN_URL, {"username": "alvo_bruteforce", "password": password})

    def test_wrong_password_below_limit_just_fails_normally(self):
        for _ in range(2):  # abaixo do limite de 3
            response = self._attempt("senha-errada")
            self.assertEqual(response.status_code, 200)  # re-renderiza o form de login, sem bloqueio

        # ainda dá pra logar certo, porque o limite não foi atingido
        response = self._attempt("senha-correta-123")
        self.assertEqual(response.status_code, 302)

    def test_exceeding_failure_limit_locks_out_even_correct_password(self):
        for _ in range(3):  # atinge o AXES_FAILURE_LIMIT=3
            self._attempt("senha-errada")

        # a partir daqui, até a credencial CERTA é recusada — a conta está bloqueada
        response = self._attempt("senha-correta-123")
        self.assertEqual(response.status_code, 429)

    def test_successful_login_resets_the_failure_counter(self):
        """AXES_RESET_ON_SUCCESS=True (config/settings/base.py) — 2 falhas + 1 acerto não deve travar depois."""
        self.client.post(LOGIN_URL, {"username": "alvo_bruteforce", "password": "senha-errada"})
        self.client.post(LOGIN_URL, {"username": "alvo_bruteforce", "password": "senha-errada"})
        self.client.logout()
        ok = self._attempt("senha-correta-123")
        self.assertEqual(ok.status_code, 302)
        self.client.logout()

        # duas falhas de novo — se o contador tivesse acumulado das 2 primeiras
        # + essas 2, teria batido no limite de 3; como resetou, ainda não trava.
        self._attempt("senha-errada")
        response = self._attempt("senha-errada")
        self.assertEqual(response.status_code, 200)

    def test_lockout_does_not_affect_a_different_account_from_a_different_ip(self):
        """
        AXES_LOCKOUT_PARAMETERS=["username", "ip_address"] (lista simples,
        não aninhada) bloqueia se QUALQUER uma das duas dimensões bater no
        limite — usuário específico OU IP específico, o que vier primeiro.
        Por isso o isolamento real de "outro_usuario" só se confirma vindo
        de um IP diferente: um `outro_usuario` no MESMO IP também seria
        bloqueado (a dimensão IP sozinha já bateu o limite), o que é o
        comportamento pretendido, não um bug.
        """
        User.objects.create_user(username="outro_usuario", password="outra-senha-123")

        for _ in range(3):
            self._attempt("senha-errada")

        response = self.client.post(
            LOGIN_URL,
            {"username": "outro_usuario", "password": "outra-senha-123"},
            REMOTE_ADDR="10.0.0.99",
        )
        self.assertEqual(response.status_code, 302)
