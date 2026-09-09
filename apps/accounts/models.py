"""
Usuário customizado com perfil (role) — especificação, seção 6 e 11.

Usamos um User próprio (em vez do padrão do Django) desde o primeiro
commit porque trocar o modelo de usuário depois que já existem migrations
aplicadas é doloroso. `AUTH_USER_MODEL = "accounts.User"` está configurado
em config/settings/base.py.

Arquitetura de Cargos/Permissões (aprovada em 09/09/2026): a partir desta
migração, `User.groups` (herdado de `PermissionsMixin` via `AbstractUser`,
já existente no schema desde o primeiro commit mas nunca usado) passa a
representar o "Cargo" do usuário — um `django.contrib.auth.models.Group`
com `Permission`s reais atribuídas. `Role`/`role` e os `CAN_*` de
`apps/accounts/permissions.py` NÃO são removidos nesta rodada — continuam
sendo a autorização de fato em toda view existente. Os dois sistemas
coexistem deliberadamente até a migração ser feita view por view (ver
relatório de aprovação da arquitetura). Ver `apps/accounts/services.py`
para o único caminho suportado de atribuir cargo a um usuário, e
`RoleProfile` abaixo para os metadados do cargo.
"""

from django.contrib.auth.models import AbstractUser, Group
from django.db import models

from apps.core.models import TimeStampedModel


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrador"
    ADMINISTRATIVO = "ADMINISTRATIVO", "Administrativo"
    OPERACIONAL = "OPERACIONAL", "Operacional/Técnico"
    CONSULTA = "CONSULTA", "Consulta"


class User(AbstractUser):
    """
    `is_active` já existe em AbstractUser (controla login), então não
    duplicamos SoftDeleteModel aqui — desativar um usuário é exatamente
    desmarcar esse campo, sem apagar o registro nem seu histórico de autoria.
    """

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CONSULTA)

    def has_role(self, *roles: str) -> bool:
        return self.role in roles

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def is_administrativo_ou_superior(self) -> bool:
        return self.role in (Role.ADMIN, Role.ADMINISTRATIVO)

    @property
    def is_operacional_ou_superior(self) -> bool:
        return self.role in (Role.ADMIN, Role.ADMINISTRATIVO, Role.OPERACIONAL)

    @property
    def cargo(self) -> Group | None:
        """
        O Cargo (Group) do usuário na nova arquitetura de Permissões.

        Assume a invariante de "um cargo por usuário" — garantida pelo
        único caminho de escrita suportado, `apps.accounts.services.
        set_user_cargo()`, nunca por uma constraint de banco (M2M nativo
        do Django não modela cardinalidade 1 sem duplicar toda a
        autenticação). Ver `apps/accounts/services.py` para o raciocínio
        completo.
        """
        return self.groups.first()

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    class Meta:
        # Permissões "reais" (django.contrib.auth.Permission) que
        # representam, uma a uma, as constantes CAN_* de
        # apps/accounts/permissions.py que fazem sentido lidas como ação
        # sobre um usuário. Ver apps/accounts/permission_catalog.py para o
        # catálogo completo (todos os apps) e o raciocínio de por que isto
        # existe em paralelo aos CAN_* nesta rodada.
        permissions = [
            ("manage_users", "Pode gerenciar usuários (criar, editar, ativar/desativar)"),
        ]


class RoleProfile(TimeStampedModel):
    """
    Metadados de um Cargo (`django.contrib.auth.models.Group`) — arquitetura
    de Cargos/Permissões aprovada em 09/09/2026.

    Decora `Group` em vez de substituí-lo: a autorização de fato continua
    sendo `Group` + `Permission` nativos do Django (`ModelBackend.
    has_perm()`); isto só guarda o que o Django não tem — uma descrição
    livre para a tela de gestão de cargos e a marca de "protegido".

    Segue o mesmo padrão de `Category` (apps/catalog/models.py): tabela de
    configuração simples, editável por Admin/superusuário, SEM
    `HistoricalRecords` — não é um registro de negócio com valor de
    auditoria por linha, é metadado de configuração do próprio sistema
    (mesmo raciocínio já usado para não dar histórico a `Category`).

    `is_protected=True` significa que o cargo não pode ser renomeado,
    editado (permissões) ou excluído pela tela de gestão de cargos — hoje
    isso vale só para "Administrador" (seção 11: a válvula de segurança do
    sistema não pode virar um cargo qualquer, editável por quem quer que
    tenha acesso à tela). A flag é genérica (não hardcoded comparando
    nome) para já suportar, sem mudança de schema, um eventual segundo
    cargo protegido no futuro. A checagem de fato mora em
    `apps.accounts.services` (único caminho suportado de editar/excluir
    cargo) — nunca só na interface.
    """

    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name="profile")
    description = models.TextField(blank=True, help_text="Descrição livre do cargo, exibida na tela de gestão de cargos.")
    is_protected = models.BooleanField(
        default=False,
        help_text="Cargo do sistema que não pode ser editado/excluído pela interface (ex.: Administrador).",
    )

    class Meta:
        verbose_name = "cargo"
        verbose_name_plural = "cargos"

    def __str__(self) -> str:
        return self.group.name
