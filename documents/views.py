"""
DRF API документов и версий. Файлы отдаются только через защищённый
endpoint с проверкой авторизации (ТЗ п.15.6) — не по прямой ссылке.
"""

import json

from django.contrib.contenttypes.models import ContentType
from django.http import FileResponse, Http404, JsonResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.auth import get_current_b24_id

from . import editing, services
from .models import Document, DocumentVersion, EditSession
from .serializers import DocumentSerializer


def _resolve_linked(data):
    """Опциональная привязка документа к карточке: linked_type + linked_id."""
    linked_type = data.get("linked_type")  # "app_label.model"
    linked_id = data.get("linked_id")
    if not linked_type or not linked_id:
        return None
    try:
        app_label, model = linked_type.split(".")
        ct = ContentType.objects.get(app_label=app_label, model=model)
    except (ValueError, ContentType.DoesNotExist):
        return None
    model_cls = ct.model_class()
    return model_cls.objects.filter(pk=linked_id).first()


@method_decorator(csrf_exempt, name="dispatch")
class DocumentViewSet(viewsets.ModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    parser_classes = [MultiPartParser, FormParser]

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Требуется авторизация Битрикс24.")
        return super().initial(request, *args, **kwargs)

    def get_queryset(self):
        return Document.objects.filter(deleted_at__isnull=True).prefetch_related(
            "versions"
        )

    def create(self, request, *args, **kwargs):
        title = (request.data.get("title") or "").strip()
        if not title:
            return Response({"detail": "Не указано название."}, status=400)

        doc = services.create_document(
            title=title,
            document_type=(request.data.get("document_type") or "").strip(),
            is_confidential=str(request.data.get("is_confidential")).lower()
            in ("1", "true", "yes", "on"),
            linked_object=_resolve_linked(request.data),
            created_by_b24_id=self.b24_id,
        )

        file = request.FILES.get("file")
        if file:
            services.add_version(
                doc, file, uploaded_by_b24_id=self.b24_id,
                change_comment=(request.data.get("change_comment") or "").strip(),
            )
        return Response(DocumentSerializer(doc).data, status=201)

    @action(detail=True, methods=["post"], url_path="versions")
    def add_version(self, request, pk=None):
        doc = self.get_object()
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "Файл не передан."}, status=400)
        services.add_version(
            doc, file, uploaded_by_b24_id=self.b24_id,
            change_comment=(request.data.get("change_comment") or "").strip(),
        )
        # свежий инстанс без устаревшего prefetch-кэша versions
        fresh = Document.objects.get(pk=doc.pk)
        return Response(DocumentSerializer(fresh).data)

    @action(
        detail=True,
        methods=["get"],
        url_path=r"versions/(?P<version_id>\d+)/download",
    )
    def download(self, request, pk=None, version_id=None):
        doc = self.get_object()
        version = DocumentVersion.objects.filter(id=version_id, document=doc).first()
        if version is None or not version.file:
            raise Http404("Версия не найдена.")
        return FileResponse(
            version.file.open("rb"),
            as_attachment=True,
            filename=version.original_filename or f"document_{doc.id}_v{version.version_number}",
        )

    @action(detail=True, methods=["get"], url_path="editor-config")
    def editor_config(self, request, pk=None):
        """
        Конфиг для онлайн-редактора (ТЗ п.7.2-7.3). Открывается редактор всегда
        по АКТУАЛЬНОЙ версии; результат вернётся отдельной версией через callback.
        """
        doc = self.get_object()
        if not editing.is_enabled():
            return Response({"detail": "Онлайн-редактор не подключён."}, status=409)
        if not editing.is_editable(doc.current_version):
            return Response(
                {"detail": "Этот документ нельзя редактировать онлайн."}, status=409
            )
        profile = getattr(request.user, "minised_profile", None)
        user_name = getattr(profile, "full_name", "") or ""
        return Response(
            editing.build_config(doc, b24_id=self.b24_id, user_name=user_name)
        )

    def destroy(self, request, *args, **kwargs):
        # мягкое удаление вместо физического (ТЗ п.15.6)
        doc = self.get_object()
        services.soft_delete(doc)
        return Response(status=204)


# --------------------------------------------------------------------------- #
# Эндпоинты сервер→сервер (сервер документов ходит без пользовательской сессии,
# авторизуется нашим одноразовым токеном в URL — в обход b24-гейта вьюсета).
# --------------------------------------------------------------------------- #
@csrf_exempt
def ds_download(request, pk, version_id):
    """Отдать файл версии серверу документов по подписанному токену `?t=`."""
    if not editing.is_enabled():
        raise Http404()
    payload = editing.jwt_decode(request.GET.get("t", ""))
    if not payload or payload.get("typ") != "dl" or str(payload.get("vid")) != str(version_id):
        raise Http404()
    version = DocumentVersion.objects.filter(id=version_id, document_id=pk).first()
    if version is None or not version.file:
        raise Http404()
    return FileResponse(version.file.open("rb"))


@csrf_exempt
def editor_callback(request, pk):
    """
    Приём результата редактирования от сервера документов. Отвечаем строго
    `{"error": 0}` при успехе — иначе сервер документов повторит доставку.
    """
    if not editing.is_enabled():
        return JsonResponse({"error": 1})
    payload = editing.jwt_decode(request.GET.get("t", ""))
    if not payload or payload.get("typ") != "cb":
        return JsonResponse({"error": 1})
    session = EditSession.objects.filter(id=payload.get("sid"), document_id=pk).first()
    if session is None:
        return JsonResponse({"error": 1})

    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, json.JSONDecodeError):
        return JsonResponse({"error": 1})

    # Если у сервера документов включён JWT — тело тоже подписано (поле `token`).
    if editing._jwt_secret():  # noqa: SLF001 — общий секрет модуля
        inner = editing.jwt_decode(body.get("token", ""))
        if inner is None:
            return JsonResponse({"error": 1})
        body = inner.get("payload", inner)

    return JsonResponse(editing.handle_callback(session, body))
