import os
import json
from urllib.parse import urlparse
from rest_framework import serializers
from .models import (
    Agreement,
    AgreementDocument,
    Participant,
    DecisionLog,
    ApprovalTemplate,
    ApprovalTemplateParticipant,
    ApprovalTemplateAccess,
)


def normalize_crm_link_value(raw: str, request=None) -> str:
    """
    Приводим crm_link к кликабельному URL.

    Поддерживаем:
    - Уже готовый http(s) URL → возвращаем как есть.
    - Формат "deal: { ... JSON ... }" (то, что сейчас приходит с фронта).
    - Если ничего распарсить не удалось — возвращаем исходную строку.
    """
    if not raw:
        return ""

    raw = str(raw).strip()

    # Уже нормальный URL
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw

    json_str = None

    # Наш текущий формат: "deal: {\"deal\":{...},\"lead\":{...},...}"
    if ":" in raw:
        _, rest = raw.split(":", 1)
        rest = rest.strip()
        if rest.startswith("{") or rest.startswith("["):
            json_str = rest

    if not json_str:
        return raw

    try:
        data = json.loads(json_str)
    except Exception:
        return raw

    # Пытаемся вытащить url из deal/lead/contact/company
    for key in ("deal", "lead", "contact", "company"):
        bucket = data.get(key)
        if not bucket:
            continue

        first = None
        if isinstance(bucket, dict):
            if not bucket:
                continue
            # берём первый элемент словаря: {"0": {...}}
            first = next(iter(bucket.values()))
        elif isinstance(bucket, list):
            if not bucket:
                continue
            first = bucket[0]
        else:
            continue

        if not isinstance(first, dict):
            continue

        url_path = first.get("url")
        if not url_path:
            continue

        url_path = str(url_path)

        # Если вдруг Bitrix отдал полный URL
        if url_path.startswith("http://") or url_path.startswith("https://"):
            return url_path

        # Дотягиваем домен портала из Origin (https://hotelvedensky.bitrix24.ru)
        domain = None
        if request is not None:
            origin = request.headers.get("Origin") or ""
            try:
                parsed = urlparse(origin)
                domain = parsed.hostname
            except Exception:
                domain = None

        if domain:
            return f"https://{domain}{url_path}"

        # На худой конец вернём относительный путь
        return url_path

    # Если пройтись по всем не получилось — оставляем как есть
    return raw


class AgreementDocumentSerializer(serializers.ModelSerializer):
    # виртуальное поле для красивого имени файла
    name = serializers.SerializerMethodField()

    class Meta:
        model = AgreementDocument
        fields = ["id", "type", "file", "url", "name"]

    def get_name(self, obj):
        if obj.file:
            return os.path.basename(obj.file.name)
        if obj.url:
            return obj.url
        return "Документ"


class ParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participant
        fields = [
            "id",
            "type",
            "b24_user_id",
            "email",
            "name",
            "status",
            "comment",
            "decided_at",
            "order_index",
            "prev_status",
            "prev_comment",
        ]
        read_only_fields = [
            "status",
            "comment",
            "decided_at",
            "prev_status",
            "prev_comment",
        ]


class DecisionLogSerializer(serializers.ModelSerializer):
    participant = ParticipantSerializer()

    class Meta:
        model = DecisionLog
        fields = ["id", "participant", "status", "comment", "decided_at"]


class AgreementSerializer(serializers.ModelSerializer):
    documents = AgreementDocumentSerializer(many=True, required=False)
    participants = ParticipantSerializer(many=True, required=False)
    decision_logs = DecisionLogSerializer(many=True, read_only=True)
    documents_v = serializers.SerializerMethodField()

    class Meta:
        model = Agreement
        fields = [
            "id",
            "title",
            "description",
            "amount",
            "author_b24_id",
            "deadline",
            "crm_link",
            "flow_type",
            "status",
            "created_at",
            "documents",
            "documents_v",
            "participants",
            "decision_logs",
        ]

    def get_documents_v(self, obj):
        """Версионируемые документы (ТЗ п.7.1-7.3) — через приложение documents."""
        from django.contrib.contenttypes.models import ContentType
        from documents.models import Document

        ct = ContentType.objects.get_for_model(Agreement)
        docs = Document.objects.filter(
            content_type=ct, object_id=obj.pk, deleted_at__isnull=True
        ).prefetch_related("versions")
        out = []
        for d in docs:
            versions = [
                {
                    "id": v.id,
                    "version_number": v.version_number,
                    "uploaded_at": v.uploaded_at,
                    "uploaded_by_b24_id": v.uploaded_by_b24_id,
                    "change_comment": v.change_comment,
                    "is_current": v.is_current,
                    "download_url": f"/api/documents/{d.id}/versions/{v.id}/download/",
                }
                for v in d.versions.all().order_by("version_number")
            ]
            out.append({
                "id": d.id,
                "title": d.title,
                "current_version_number": d.current_version.version_number if d.current_version else None,
                "versions": versions,
            })
        return out
        read_only_fields = ["status", "created_at", "author_b24_id"]

    def validate_crm_link(self, value):
        """
        На вход получаем то, что пришло из формы (в том числе "deal: { ... }"),
        а на выход — по возможности нормальный URL.
        """
        request = self.context.get("request")
        return normalize_crm_link_value(value, request)

    def create(self, validated_data):
        """
        Поддерживаем два варианта создания:

        1) Чистый DRF (JSON):
        {
            "title": "...",
            "documents": [...],
            "participants": [...]
        }

        2) Наш текущий фронт (multipart form-data):
        - files / file
        - participants: JSON-строка (массив участников)
        - internal_users: "12,34"                (fallback)
        - external_emails: "a@b.ru, c@d.ru"      (fallback)
        """
        request = self.context.get("request")
        current_b24_id = self.context.get("current_b24_id") or 0

        # то, что уже пришло как вложенные данные (если вообще пришло)
        docs_data = validated_data.pop("documents", [])
        participants_data = validated_data.pop("participants", [])

        # 1) Попробовать распарсить JSON из request.data["participants"],
        #    если participants ещё не пришли вложенно (типичный кейс для multipart)
        if request is not None and not participants_data:
            raw_participants = request.data.get("participants")
            if raw_participants:
                # Если пришла строка — это JSON из FormData
                if isinstance(raw_participants, str):
                    try:
                        parsed = json.loads(raw_participants)
                    except (TypeError, ValueError):
                        raise serializers.ValidationError(
                            {"participants": "Некорректный формат списка участников"}
                        )
                    if not isinstance(parsed, list):
                        raise serializers.ValidationError(
                            {"participants": "Список участников должен быть массивом"}
                        )
                    participants_data = parsed
                # Если это уже не строка (например, чистый JSON-запрос),
                # сюда мы, как правило, не попадём, потому что participants_data
                # уже будет заполнен из validated_data.

        # 2) Fallback для нашего HTML-фронта:
        #    - забираем файлы из request.FILES, если documents пуст
        #    - собираем участников из internal_users / external_emails,
        #      если всё ещё нет participants_data
        if request is not None:
            # 2.1 Документы из файлов, если не пришли вложенно
            if not docs_data:
                files = request.FILES.getlist("files") or request.FILES.getlist("file")
                for f in files:
                    docs_data.append(
                        {
                            "type": AgreementDocument.TYPE_FILE,
                            "file": f,
                        }
                    )

            # 2.2 Участники из internal_users / external_emails, если их всё ещё нет
            if not participants_data:
                internal_raw = (request.data.get("internal_users") or "").strip()
                external_raw = (request.data.get("external_emails") or "").strip()

                internal_ids = []
                if internal_raw:
                    for chunk in internal_raw.split(","):
                        chunk = chunk.strip()
                        if not chunk:
                            continue
                        try:
                            internal_ids.append(int(chunk))
                        except ValueError:
                            continue

                external_emails = []
                if external_raw:
                    for chunk in external_raw.split(","):
                        email = chunk.strip()
                        if email:
                            external_emails.append(email)

                idx = 0
                # сначала внутренние
                for uid in internal_ids:
                    participants_data.append(
                        {
                            "type": Participant.TYPE_INTERNAL,
                            "b24_user_id": uid,
                            "email": "",
                            "name": "",
                            "order_index": idx,
                        }
                    )
                    idx += 1
                # потом внешние
                for email in external_emails:
                    participants_data.append(
                        {
                            "type": Participant.TYPE_EXTERNAL,
                            "b24_user_id": None,
                            "email": email,
                            "name": "",
                            "order_index": idx,
                        }
                    )
                    idx += 1

            # 🔹 КРИТИЧНО: добираем crm_link из request.data, если он по какой-то причине
            # не попал в validated_data (частый кейс с multipart + кастомным фронтом)
            raw_crm = (request.data.get("crm_link") or "").strip()
            if raw_crm:
                validated_data["crm_link"] = raw_crm

        # --- создаём сам Agreement ---
        validated_data["author_b24_id"] = current_b24_id
        agreement = Agreement.objects.create(**validated_data)

        # --- документы ---
        for doc in docs_data:
            AgreementDocument.objects.create(agreement=agreement, **doc)

        # --- участники ---
        for i, p_data in enumerate(participants_data):
            # p_data может быть dict со всяким лишним — аккуратно чистим
            data = dict(p_data) if p_data is not None else {}
            order_index = data.pop("order_index", i)
            # убираем поля, которых нет в модели Participant
            data.pop("note", None)

            Participant.objects.create(
                agreement=agreement,
                order_index=order_index,
                **data,
            )

        return agreement


class ApprovalTemplateParticipantSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalTemplateParticipant
        fields = [
            "id",
            "type",
            "b24_user_id",
            "email",
            "name",
            "order_index",
            "note",
        ]


class ApprovalTemplateSerializer(serializers.ModelSerializer):
    participants = ApprovalTemplateParticipantSerializer(many=True)
    shared_with = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False,
    )
    shared_with_ids = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ApprovalTemplate
        fields = [
            "id",
            "name",
            "description",
            "scope",
            "author_b24_id",
            "created_at",
            "updated_at",
            "participants",
            "shared_with",
            "shared_with_ids",
        ]
        read_only_fields = ["author_b24_id", "created_at", "updated_at"]

    def get_shared_with_ids(self, obj):
        return list(obj.accesses.values_list("b24_user_id", flat=True))

    def create(self, validated_data):
        participants_data = validated_data.pop("participants", [])
        shared_with = validated_data.pop("shared_with", [])

        current_b24_id = self.context.get("current_b24_id")
        if not current_b24_id:
            raise serializers.ValidationError("Не удалось определить автора (ID Б24).")
        validated_data["author_b24_id"] = current_b24_id

        template = ApprovalTemplate.objects.create(**validated_data)

        # УБИРАЕМ order_index из p, чтобы не было дубля аргумента
        for i, p in enumerate(participants_data):
            p = dict(p)
            p.pop("order_index", None)
            ApprovalTemplateParticipant.objects.create(
                template=template,
                order_index=i,
                **p,
            )

        if template.scope == ApprovalTemplate.SCOPE_GROUP:
            for uid in shared_with:
                ApprovalTemplateAccess.objects.get_or_create(
                    template=template,
                    b24_user_id=uid,
                )
        return template

    def update(self, instance, validated_data):
        participants_data = validated_data.pop("participants", None)
        shared_with = validated_data.pop("shared_with", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if participants_data is not None:
            instance.participants.all().delete()
            for i, p in enumerate(participants_data):
                p = dict(p)
                p.pop("order_index", None)
                ApprovalTemplateParticipant.objects.create(
                    template=instance,
                    order_index=i,
                    **p,
                )

        if shared_with is not None:
            instance.accesses.all().delete()
            if instance.scope == ApprovalTemplate.SCOPE_GROUP:
                for uid in shared_with:
                    ApprovalTemplateAccess.objects.get_or_create(
                        template=instance,
                        b24_user_id=uid,
                    )

        return instance
