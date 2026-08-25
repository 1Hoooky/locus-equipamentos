"""
Teste de concorrência REAL do double-submit — 3º reteste manual: mesmo
com o `SubmissionGuard` de sessão, Enter pressionado rapidamente em "Nova
unidade" ainda criou 2 registros. Causa raiz: dois POSTs quase
simultâneos carregam a MESMA sessão no início de cada request; ambos veem
o token na própria cópia em memória; ambos passavam na checagem antes de
qualquer um persistir a remoção (a sessão só é salva no fim do request).
Sessão Django não dá read-modify-write atômico entre requests.

A propriedade exigida — "um token de submissão válido produz no máximo
UMA Location, mesmo com duas requisições concorrentes" — agora é
garantida pelo banco: consumir o token é inserir em
`ConsumedSubmissionToken` (apps.core.models), e o índice UNIQUE decide a
corrida (PostgreSQL serializa inserts conflitantes no índice; o perdedor
recebe IntegrityError e é tratado como reenvio).

`TransactionTestCase` + threads + PostgreSQL de verdade — mesmo padrão de
`test_movement_concurrency.py`. Cada thread usa um `Client` de teste
próprio (o test client não é thread-safe), mas os dois compartilham o
MESMO cookie de sessão e o MESMO token, reproduzindo exatamente o Enter
repetido numa única aba.
"""

import threading

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client as HttpClient
from django.test import TransactionTestCase

from apps.core.models import ConsumedSubmissionToken
from apps.operations.models import Location, LocationType

User = get_user_model()


class LocationCreateConcurrentDoubleSubmitTest(TransactionTestCase):
    def setUp(self):
        User.objects.create_user(username="corrida_unidade", password="senha-forte-123", role="ADMINISTRATIVO")

    def _post_data(self, token):
        return {
            "submission_token": token,
            "name": "Unidade Corrida",
            "type": LocationType.ESTOQUE,
            "client": "",
            "cep": "",
            "logradouro": "",
            "numero": "",
            "complemento": "",
            "bairro": "",
            "cidade": "",
            "uf": "",
            "reference_notes": "",
        }

    def test_two_concurrent_posts_with_same_token_create_exactly_one_location(self):
        # Sessão + token obtidos uma única vez (a "aba" aberta)...
        browser = HttpClient()
        browser.login(username="corrida_unidade", password="senha-forte-123")
        token = browser.get("/operacao/unidades/novo/").context["submission_token"]
        session_cookie = browser.cookies

        # ...e compartilhados pelos dois POSTs (os dois Enters).
        data = self._post_data(token)
        barrier = threading.Barrier(2)
        statuses: dict[str, int] = {}
        errors: dict[str, Exception] = {}
        lock = threading.Lock()

        def worker(label):
            try:
                client = HttpClient()
                client.cookies = session_cookie.copy()
                barrier.wait()  # os dois POSTs largam juntos
                response = client.post("/operacao/unidades/novo/", data)
                with lock:
                    statuses[label] = response.status_code
            except Exception as exc:  # pragma: no cover - diagnóstico
                with lock:
                    errors[label] = exc
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(label,)) for label in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, {}, f"Nenhuma das requisições deveria estourar exceção: {errors}")
        # As duas terminam com redirect (uma para o detalhe da unidade
        # criada, a outra para a lista com a mensagem de reenvio) — mas o
        # RESULTADO exigido é um só:
        self.assertEqual(set(statuses.values()), {302})
        self.assertEqual(
            Location.objects.filter(name="Unidade Corrida").count(),
            1,
            "2 POSTs concorrentes com o MESMO token têm que produzir exatamente 1 Location.",
        )
        # E o token consta como consumido exatamente uma vez.
        self.assertEqual(ConsumedSubmissionToken.objects.filter(token=token).count(), 1)

    def test_five_concurrent_posts_with_same_token_still_create_exactly_one(self):
        """Versão mais agressiva do mesmo cenário — N Enters, não só 2."""
        browser = HttpClient()
        browser.login(username="corrida_unidade", password="senha-forte-123")
        token = browser.get("/operacao/unidades/novo/").context["submission_token"]
        session_cookie = browser.cookies

        data = self._post_data(token)
        data["name"] = "Unidade Corrida x5"
        barrier = threading.Barrier(5)
        lock = threading.Lock()
        statuses: list[int] = []

        def worker():
            try:
                client = HttpClient()
                client.cookies = session_cookie.copy()
                barrier.wait()
                response = client.post("/operacao/unidades/novo/", data)
                with lock:
                    statuses.append(response.status_code)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(len(statuses), 5)
        self.assertEqual(Location.objects.filter(name="Unidade Corrida x5").count(), 1)
