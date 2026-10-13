"""
Регламентные заявки (ТЗ п.9): ЭЦП, МЧД, доверенности и будущие типы.

Общая карточка с type-специфичными полями в JSON (data). Согласование
идёт через универсальный движок approvalflow (Approval, привязанный к заявке
generic-связью). Документы — через приложение documents.
"""

from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from core.models import CFO, Facility, Organization
from . import constants


class PowerTemplate(models.Model):
    """
    Справочник шаблонов доверенностей (матрица полномочий, УПР1/ФНС1/…).
    Используется в анкете заявки на доверенность для выбора полномочий.
    """

    code = models.CharField("Код", max_length=32, unique=True)
    name = models.CharField("Наименование", max_length=255)
    powers = models.TextField("Полномочия", blank=True)
    is_active = models.BooleanField("Активен", default=True)
    # Порядок в форме — как в утверждённой матрице, а не по алфавиту.
    sort_order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name = "Шаблон доверенности"
        verbose_name_plural = "Шаблоны доверенностей (матрица)"

    def __str__(self):
        return f"{self.code} — {self.name}"


class RoleAssignment(models.Model):
    """
    Кто исполняет маршрутную роль в заданном контексте (организация/ЦФО/объект).

    Используется движком построения маршрута: для каждой роли-слота ищем самое
    специфичное назначение. Если не найдено — инициатору предлагается ручной
    выбор (что фиксируется в истории заявки).
    """

    ROLE_CHOICES = [(code, name) for code, name in constants.ROLE_NAMES.items()]

    role_code = models.CharField("Роль", max_length=32, choices=ROLE_CHOICES)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, null=True, blank=True,
        related_name="role_assignments", verbose_name="Организация",
    )
    cfo = models.ForeignKey(
        CFO, on_delete=models.CASCADE, null=True, blank=True,
        related_name="role_assignments", verbose_name="ЦФО",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.CASCADE, null=True, blank=True,
        related_name="role_assignments", verbose_name="Объект",
    )
    user_b24_id = models.IntegerField("Сотрудник (ID Б24)")
    user_name = models.CharField("ФИО", max_length=255, blank=True)
    is_active = models.BooleanField("Активно", default=True)

    class Meta:
        verbose_name = "Назначение роли"
        verbose_name_plural = "Назначения ролей (маршрут)"
        indexes = [models.Index(fields=["role_code"])]

    def __str__(self):
        return f"{self.get_role_code_display()} → USER#{self.user_b24_id}"


class RegulatoryRequest(models.Model):
    number = models.CharField("Номер", max_length=32, blank=True, db_index=True)
    request_type = models.CharField(
        "Тип заявки", max_length=32, choices=constants.TYPE_CHOICES
    )

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="reg_requests",
        verbose_name="Организация",
    )
    facility = models.ForeignKey(
        Facility, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reg_requests", verbose_name="Объект",
    )
    cfo = models.ForeignKey(
        CFO, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="reg_requests", verbose_name="ЦФО",
    )

    initiator_b24_id = models.IntegerField("Инициатор (ID Б24)", null=True, blank=True)

    # Заявка на отзыв ссылается на карточку отзываемой доверенности/МЧД.
    # Необязательная: бумажную доверенность, выданную до MiniSED, карточкой не
    # опишешь — её реквизиты инициатор вводит руками (data["source"]).
    # SET_NULL, а не CASCADE: отзыв — самостоятельный юридический факт и должен
    # пережить удаление карточки-первоисточника.
    source_request = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="revocations", verbose_name="Отзываемая доверенность",
    )

    # сотрудник, на которого оформляется ЭЦП/МЧД/доверенность
    subject_name = models.CharField("ФИО сотрудника", max_length=255, blank=True)
    subject_b24_id = models.IntegerField("Сотрудник (ID Б24)", null=True, blank=True)
    position = models.CharField("Должность", max_length=255, blank=True)
    department = models.CharField("Подразделение", max_length=255, blank=True)

    basis = models.TextField("Основание оформления", blank=True)
    valid_from = models.DateField("Действует с", null=True, blank=True)
    valid_until = models.DateField("Действует по", null=True, blank=True)
    comment = models.TextField("Комментарий", blank=True)

    status = models.CharField(
        "Статус", max_length=20, choices=constants.STATUS_CHOICES,
        default=constants.STATUS_DRAFT,
    )

    # исполнение юридическим отделом
    delivery_method = models.CharField(
        "Способ передачи", max_length=20, choices=constants.DELIVERY_CHOICES, blank=True
    )
    delivery_comment = models.CharField("Комментарий к передаче", max_length=500, blank=True)
    # Кто исполнил заявку. Для ЭЦП это ИТ-специалист объекта, взявший её в
    # работу (у доверенностей исполнителем выступает юротдел как группа).
    executor_b24_id = models.IntegerField("Исполнитель (ID Б24)", null=True, blank=True)
    # Когда исполнитель взял заявку в работу — строка хронологии в карточке
    # проверки лица («дата и время принятия в работу»).
    taken_at = models.DateTimeField("Взята в работу", null=True, blank=True)
    executed_at = models.DateTimeField("Исполнена", null=True, blank=True)
    received_at = models.DateTimeField("Получено инициатором", null=True, blank=True)

    # Итог проверки лица службой безопасности: решение и комментарий к нему.
    check_result = models.CharField(
        "Решение по проверке", max_length=20, choices=constants.CHECK_RESULTS, blank=True
    )
    check_comment = models.TextField("Комментарий к проверке", blank=True)

    # type-специфичные поля (доверитель, полномочия, нотариат, тип ЭЦП и т.д.)
    data = models.JSONField("Доп. поля", default=dict, blank=True)

    external_1c_id = models.CharField("Внешний ID в 1С", max_length=64, blank=True)
    external_diadoc_id = models.CharField("Внешний ID Диадока", max_length=64, blank=True)

    documents = GenericRelation(
        "documents.Document", content_type_field="content_type",
        object_id_field="object_id", related_query_name="reg_request",
    )

    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-id"]
        verbose_name = "Регламентная заявка"
        verbose_name_plural = "Регламентные заявки"
        indexes = [models.Index(fields=["request_type", "status"])]

    def __str__(self):
        return f"{self.number or f'#{self.pk}'} {self.get_request_type_display()}"

    def status_label(self) -> str:
        return self.get_status_display()


class PoaNumbering(models.Model):
    """Маска и счётчик номеров доверенностей юрлица (ТЗ «Форма маски номера»).

    Порядковый номер ХХ идёт сквозной по доверенностям И МЧД юрлица в пределах
    календарного года (так в реестрах заказчика) и обнуляется с новым годом.
    Строка заводится сама при первой выдаче — с маской по умолчанию из
    constants.POA_NUMBER_MASKS; юристы правят маску и последний номер в
    разделе реестра (например, чтобы продолжить нумерацию, начатую в Excel).
    """

    organization = models.OneToOneField(
        Organization, on_delete=models.CASCADE, related_name="poa_numbering",
        verbose_name="Организация",
    )
    mask = models.CharField(
        "Маска номера", max_length=64,
        help_text="{ХХ} — порядковый номер в году, {ГГГГ} — год, {ГГ} — две цифры года, {ММ} — месяц.",
    )
    year = models.PositiveIntegerField("Год счётчика", default=0)
    last_seq = models.PositiveIntegerField("Последний выданный номер", default=0)

    class Meta:
        verbose_name = "Нумерация доверенностей"
        verbose_name_plural = "Нумерация доверенностей (маски)"

    def __str__(self):
        return f"{self.organization} — {self.mask}"


class PoaRegistryEntry(models.Model):
    """Строка реестра доверенностей и МЧД (раздел юристов).

    Создаётся в момент «Взять в работу» — тогда же присваивается номер. Графы
    по умолчанию переносятся из заявки, дальше юрист их уточняет (каждая
    правка пишется в PoaRegistryChange). Записи без заявки — доверенности,
    выданные до MiniSED или мимо него, их юрист вносит руками.
    """

    request = models.OneToOneField(
        RegulatoryRequest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registry_entry", verbose_name="Заявка",
    )
    kind = models.CharField("Вид", max_length=8, choices=constants.REGISTRY_KINDS)
    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name="poa_registry",
        verbose_name="Компания",
    )
    number = models.CharField("Номер доверенности", max_length=64, blank=True, db_index=True)
    # порядковый номер и год — по ним считается следующий номер; у записей,
    # внесённых руками, могут быть пусты
    seq = models.PositiveIntegerField("Порядковый номер", null=True, blank=True)
    seq_year = models.PositiveIntegerField("Год нумерации", null=True, blank=True)
    reg_number = models.CharField("Рег. № МЧД (ФНС)", max_length=64, blank=True)
    issue_date = models.DateField("Дата выдачи", null=True, blank=True)
    code = models.CharField("КОД", max_length=255, blank=True)
    representative = models.CharField("Представитель", max_length=500, blank=True)
    powers = models.TextField("Полномочия", blank=True)
    valid_until = models.DateField("Срок действия", null=True, blank=True)
    cert_valid_until = models.DateField("Срок сертификата", null=True, blank=True)
    revoked_at = models.DateField("Отозвана с", null=True, blank=True)
    comment = models.TextField("Примечание", blank=True)

    created_by_b24_id = models.IntegerField("Внёс (ID Б24)", null=True, blank=True)
    created_at = models.DateTimeField("Внесено", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        ordering = ["-issue_date", "-id"]
        verbose_name = "Запись реестра доверенностей"
        verbose_name_plural = "Реестр доверенностей и МЧД"
        indexes = [models.Index(fields=["organization", "seq_year", "seq"])]

    def __str__(self):
        return f"{self.number or f'#{self.pk}'} — {self.representative}"


class PoaRegistryChange(models.Model):
    """Правка графы реестра: кто, когда, что было и что стало.

    ТЗ: правки сохраняются; в интерфейсе их видит суперпользователь."""

    entry = models.ForeignKey(
        PoaRegistryEntry, on_delete=models.CASCADE, related_name="changes",
        verbose_name="Запись реестра",
    )
    field = models.CharField("Графа", max_length=32)
    old_value = models.TextField("Было", blank=True)
    new_value = models.TextField("Стало", blank=True)
    changed_by_b24_id = models.IntegerField("Кто правил (ID Б24)", null=True, blank=True)
    changed_at = models.DateTimeField("Когда", auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]
        verbose_name = "Правка реестра доверенностей"
        verbose_name_plural = "Правки реестра доверенностей"


class SecurityDelegation(models.Model):
    """Передача функций службы безопасности юридическому отделу.

    Пока СБ нет на месте (отпуск, больничный), любой юрист одной кнопкой
    берёт её раздел на себя, а потом возвращает. Строка — один период
    передачи: открыт, пока не проставлен ended_at. Кто и когда включал —
    остаётся в истории; кто исполнил конкретную заявку — в её executor_b24_id.
    """

    started_by_b24_id = models.IntegerField("Передал (ID Б24)")
    started_at = models.DateTimeField("Начало", auto_now_add=True)
    ended_by_b24_id = models.IntegerField("Вернул (ID Б24)", null=True, blank=True)
    ended_at = models.DateTimeField("Окончание", null=True, blank=True)
    comment = models.CharField("Причина", max_length=255, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Передача функций СБ юристам"
        verbose_name_plural = "Передача функций СБ юристам"

    def __str__(self):
        state = "действует" if self.ended_at is None else "завершена"
        return f"Передача СБ → юристам с {self.started_at:%d.%m.%Y} ({state})"

    @classmethod
    def active(cls):
        return cls.objects.filter(ended_at__isnull=True).first()
