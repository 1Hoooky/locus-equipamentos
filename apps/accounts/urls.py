from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from apps.accounts import views

app_name = "accounts"

# As views genéricas de auth do Django (PasswordResetView,
# PasswordResetConfirmView) têm `success_url` padrão apontando para nomes
# de rota SEM namespace (ex.: reverse_lazy("password_reset_done")). Como
# este app registra tudo sob o namespace "accounts", esse padrão nunca
# resolve aqui — precisa ser sobrescrito explicitamente com o nome
# namespaced, senão a view quebra com NoReverseMatch assim que alguém
# de fato usa o fluxo (só apareceu ao escrever o teste de integração
# HTTP completo do fluxo, que nenhum teste anterior cobria).
urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="accounts/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("usuarios/", views.UserListView.as_view(), name="user_list"),
    path("usuarios/novo/", views.UserCreateView.as_view(), name="user_create"),
    path("usuarios/<int:pk>/editar/", views.UserUpdateView.as_view(), name="user_update"),
    path(
        "senha/redefinir/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/password_reset.html",
            success_url=reverse_lazy("accounts:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "senha/redefinir/enviado/",
        auth_views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "senha/redefinir/confirmar/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/password_reset_confirm.html",
            success_url=reverse_lazy("accounts:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "senha/redefinir/concluido/",
        auth_views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"),
        name="password_reset_complete",
    ),
]
