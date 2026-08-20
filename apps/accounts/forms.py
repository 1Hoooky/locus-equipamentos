"""
Formulários de gestão de usuários — especificação, seção 12 (tela
"Gestão de usuários": criar usuário, definir perfil, ativar/desativar),
restrita a Administrador (seção 11).
"""

from django import forms
from django.contrib.auth.forms import UserCreationForm

from apps.accounts.models import User

TEXT_INPUT_CLASS = "border border-gray-300 rounded-md px-3 py-1.5 text-sm w-full"


class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)


class UserUpdateForm(forms.ModelForm):
    """
    Edição de um usuário existente: perfil e ativo/inativo (desligamento
    de acesso sem apagar o registro nem seu histórico de autoria — a
    mesma lógica de soft delete do resto do sistema, especificação
    seção 5). Troca de senha continua pelo fluxo de "esqueci minha senha"
    (apps/accounts/urls.py), não por aqui.
    """

    class Meta:
        model = User
        fields = ("first_name", "last_name", "email", "role", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != "is_active":
                field.widget.attrs.setdefault("class", TEXT_INPUT_CLASS)
