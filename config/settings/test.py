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

import tempfile

from .dev import *  # noqa: F401,F403

AXES_ENABLED = False

# MEDIA_ROOT isolado por processo de teste (14/09/2026, ver docs/testing.md
# "Isolamento de MEDIA_ROOT nos testes"): sem isso, todo FileField salvo
# durante a suíte (hoje: apps.attachments, usado por apps.crm ao emitir
# Proposta/Contrato) grava no media/ real do projeto. Rodar a suíte mais de
# uma vez então encontra arquivo já existente com o mesmo nome e o
# Storage do Django o renomeia (sufixo aleatório) para não sobrescrever —
# quebrando de forma não-determinística qualquer teste que espera o nome
# original (ex.: `attachment.file.name.endswith("teste.pdf")`). Um
# diretório novo e descartável por execução elimina a poluição sem exigir
# nenhuma limpeza manual.
MEDIA_ROOT = tempfile.mkdtemp(prefix="locus_test_media_")
