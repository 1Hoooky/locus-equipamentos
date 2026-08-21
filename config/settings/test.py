"""
Configurações usadas pela suíte de testes (pytest.ini aponta para cá).

Herda tudo de dev.py, com uma única diferença: `AXES_ENABLED = False`.

Motivo: `axes.backends.AxesStandaloneBackend.authenticate()` exige um
`request` real como argumento — e o atalho `self.client.login(...)` do
Django (usado em quase todo teste só para autenticar rapidamente antes de
testar OUTRA coisa) não passa `request` para `authenticate()`, então
quebraria a suíte inteira. A forma correta de testar o próprio
django-axes é com requisições HTTP reais para a view de login (que passa
`request` corretamente via `AuthenticationForm`) — é exatamente o que
`apps/accounts/tests/test_axes_lockout.py` faz, reativando
`AXES_ENABLED=True` só ali via `override_settings`.
"""

from .dev import *  # noqa: F401,F403

AXES_ENABLED = False
