"""
Каталог прав и ролей MiniSED (ТЗ п.8.4, 15.3, 15.4).

Используется сид-миграцией (0002) и кодом. При добавлении права/роли —
правьте здесь и добавляйте data-миграцию, синхронизирующую БД.
"""

# --- Права -----------------------------------------------------------------
# (code, name, category)
SYSTEM_PERMISSIONS = [
    ("manage_users", "Управление пользователями", "system"),
    ("manage_roles", "Управление ролями", "system"),
    ("manage_directories", "Управление справочниками", "system"),
    ("manage_routes", "Управление маршрутами", "system"),
    ("view_logs", "Просмотр журналов", "system"),
    ("manage_integrations", "Настройка интеграций", "system"),
    ("view_audit", "Просмотр аудита", "system"),
    ("manage_security", "Управление безопасностью", "system"),
]

PROCESS_PERMISSIONS = [
    ("request_create", "Создание заявки", "process"),
    ("request_edit", "Редактирование заявки", "process"),
    ("approve", "Согласование заявки", "process"),
    ("return_for_revision", "Возврат на доработку", "process"),
    ("reject", "Отклонение", "process"),
    ("close", "Закрытие", "process"),
    ("assign_responsible", "Назначение ответственного", "process"),
    ("change_deadline", "Изменение сроков", "process"),
    ("document_upload", "Загрузка документов", "process"),
    ("document_download", "Скачивание документов", "process"),
    ("version_history_view", "Просмотр истории версий", "process"),
    ("route_change", "Изменение маршрута согласования", "process"),
    ("approval_sheet_generate", "Формирование листа согласования", "process"),
    ("legal_view", "Просмотр юридических дел", "process"),
    ("legal_manage", "Управление юридическими делами", "process"),
    ("confidential_view", "Просмотр конфиденциальных вложений", "process"),
]

ALL_PERMISSIONS = SYSTEM_PERMISSIONS + PROCESS_PERMISSIONS

_SYSTEM_CODES = [c for c, _, _ in SYSTEM_PERMISSIONS]

# --- Роли ------------------------------------------------------------------
# code -> (name, kind, [permission codes])
SYSTEM_ROLES = {
    "sys_admin": ("Системный администратор", "system", _SYSTEM_CODES),
    "dict_admin": ("Администратор справочников", "system", ["manage_directories"]),
    "user_admin": ("Администратор пользователей", "system", ["manage_users", "manage_roles"]),
    "route_admin": ("Администратор маршрутов", "system", ["manage_routes"]),
    "auditor": ("Аудитор", "system", ["view_audit", "view_logs"]),
}

_BASE_APPROVER = [
    "approve", "return_for_revision", "reject",
    "document_download", "version_history_view",
]

PROCESS_ROLES = {
    "initiator": (
        "Инициатор", "process",
        ["request_create", "request_edit", "document_upload", "document_download"],
    ),
    "approver": ("Согласующий", "process", _BASE_APPROVER),
    "internal_participant": ("Внутренний участник", "process", ["document_download"]),
    "observer": ("Наблюдатель", "process", ["document_download"]),
    "lawyer": (
        "Юрист", "process",
        _BASE_APPROVER + ["legal_view", "legal_manage", "confidential_view", "document_upload"],
    ),
    "legal_head": (
        "Руководитель юридической службы", "process",
        _BASE_APPROVER + ["legal_view", "legal_manage", "confidential_view",
                          "assign_responsible", "route_change"],
    ),
    "ops_director": (
        "Операционный директор", "process",
        _BASE_APPROVER + ["assign_responsible"],
    ),
    "cfo_head": ("Руководитель ЦФО", "process", _BASE_APPROVER),
    "finance_director": ("Финансовый директор", "process", _BASE_APPROVER),
    "general_director": (
        "Генеральный директор", "process",
        _BASE_APPROVER + ["close", "approval_sheet_generate"],
    ),
    "final_signer": (
        "Финальный подписант", "process",
        ["approve", "reject", "approval_sheet_generate", "document_download"],
    ),
    "responsible_executor": (
        "Ответственный исполнитель", "process",
        ["close", "change_deadline", "document_upload", "document_download"],
    ),
}

ALL_ROLES = {**SYSTEM_ROLES, **PROCESS_ROLES}
