import io
import os
import json
import requests
from django.db import transaction
from django.http import FileResponse, HttpResponse
from django.shortcuts import render
from datetime import datetime
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, parser_classes
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from django.utils import timezone
from .models import (
    Agreement,
    AgreementDocument,
    Participant,
    DecisionLog,
    ApprovalTemplate,
    B24Identity,
    B24UserEmail,
    RoundNote,
)
from .models import (
    Agreement as AgreementModel,
)
from .serializers import (
    AgreementSerializer,
    ApprovalTemplateSerializer,
)
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import F, Q
from core.services import log_action
from core.auth import can_view_all, get_current_profile, is_lawyer, lawyer_b24_ids
from urllib.parse import urlencode


def _store_bitrix_portal_token(domain, member_id, token_data):
    """Сохраняет портал и его токены (для Bitrix Connector)."""
    if not domain or not token_data.get("access_token"):
        return
    try:
        from bitrix.views import _upsert_portal
        from bitrix.client import store_token

        portal = _upsert_portal(domain, member_id)
        store_token(portal, token_data)
    except Exception as e:
        print("[Bitrix] portal token store error:", e)


def _deep_link_route(request) -> str:
    """Маршрут SPA из параметра `to` — куда открыть приложение.

    Так работают ссылки из уведомлений («Перейти к согласованию»): человек
    попадает сразу в карточку, а не на главную. Берём и из query, и из тела:
    Битрикс открывает обработчик POST-ом, query при этом сохраняется, но
    подстраховываемся. Пускаем только внутренние пути (/...), без «//» —
    иначе параметром можно было бы увести на чужой домен."""
    raw = (request.GET.get("to") or request.POST.get("to") or "").strip()
    if not raw.startswith("/") or raw.startswith("//"):
        return ""
    return raw[:200]


def _serve_spa(request, boot_token=None):
    """Отдаёт собранный Vue SPA (frontend/dist/index.html).

    Приложение открывается из Битрикс24 (обработчик /app). Если Битрикс
    прислал токены (POST с AUTH_ID), пользователь уже авторизован на сервере,
    и мы вкладываем токен MiniSED прямо в HTML (window.__MINISED_BOOT__) —
    SPA входит сразу, без зависимости от BX24 SDK и тайминга в iframe.
    Если сборки ещё нет — отдаём старый шаблон как запасной вариант."""
    dist_index = settings.BASE_DIR / "frontend" / "dist" / "index.html"
    if not dist_index.exists():
        return render(
            request,
            "approvals/app.html",
            {"session_b24_id": request.session.get("b24_user_id")},
        )
    html = dist_index.read_text(encoding="utf-8")
    boot_data = {}
    if boot_token:
        boot_data["token"] = boot_token
    route = _deep_link_route(request)
    if route:
        boot_data["route"] = route
    if boot_data:
        boot = "<script>window.__MINISED_BOOT__=%s;</script>" % json.dumps(boot_data)
        html = html.replace("</head>", boot + "</head>", 1)
    resp = HttpResponse(html, content_type="text/html; charset=utf-8")
    # Не кэшировать оболочку SPA, иначе iframe Битрикса держит старый билд.
    resp["Cache-Control"] = "no-store, must-revalidate"
    return resp


@csrf_exempt
def app_view(request):
    # Установка/открытие приложения из Битрикс24: обработчик получает
    # токены прямо в POST (AUTH_ID/REFRESH_ID/member_id/DOMAIN). Сохраняем их,
    # чтобы сервер (Bitrix Connector) мог сам вызывать REST портала.
    if request.method == "POST" and request.POST.get("AUTH_ID"):
        # Битрикс24 при открытии/установке кладёт AUTH_ID/REFRESH_ID/member_id
        # в тело POST, а DOMAIN — в query-строку (/app/?DOMAIN=...). Поэтому
        # читаем и из тела, и из query (иначе domain=None → токен не сохраняется
        # и вызов user.current уходит на https://none/...).
        domain = request.POST.get("DOMAIN") or request.GET.get("DOMAIN")
        member_id = request.POST.get("member_id") or request.GET.get("member_id")
        access_token = request.POST.get("AUTH_ID")
        _store_bitrix_portal_token(
            domain,
            member_id,
            {
                "access_token": access_token,
                "refresh_token": request.POST.get("REFRESH_ID", ""),
                "expires_in": request.POST.get("AUTH_EXPIRES"),
            },
        )
        # Авторизуем на сервере по токену портала и вкладываем токен MiniSED
        # в HTML, чтобы SPA вошёл сразу (тот же аккаунт по bitrix_id/почте).
        boot_token = None
        try:
            from core.auth_views import _issue_for_bitrix

            _, token = _issue_for_bitrix(access_token, domain)
            if token:
                boot_token = token.key
        except Exception as e:
            print("[Bitrix] issue MiniSED token on /app POST error:", e)
        return _serve_spa(request, boot_token)

    code = request.GET.get("code")
    domain = request.GET.get("domain")
    server_domain = request.GET.get("server_domain")

    if code and domain and server_domain:
        # OAuth-код вернулся на обработчик /app. Обмениваем на токен, СРАЗУ
        # выпускаем токен MiniSED и отдаём SPA с вложенным токеном — без
        # редиректа и без опоры на cookie сессии (в iframe она третьесторонняя
        # и часто не доходит, из-за чего был цикл на /login).
        boot_token = None
        try:
            token_resp = requests.get(
                f"https://{server_domain}/oauth/token/",
                params={
                    "grant_type": "authorization_code",
                    "client_id": settings.BITRIX_CLIENT_ID,
                    "client_secret": settings.BITRIX_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": request.build_absolute_uri(request.path),
                },
                timeout=10,
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")

            _store_bitrix_portal_token(domain, token_data.get("member_id"), token_data)

            if access_token:
                from core.auth_views import _issue_for_bitrix

                _, token = _issue_for_bitrix(access_token, domain)
                if token:
                    boot_token = token.key
        except Exception as e:
            print(f"[Bitrix OAuth] token exchange error: {e}")
        return _serve_spa(request, boot_token)
    return _serve_spa(request)


def bitrix_auth_callback(request):
    """
    Callback после логина в Bitrix.
    Сохраняем b24_user_id + email в сессии и в таблице B24Identity,
    затем возвращаем пользователя на нужную страницу.
    """
    code = request.GET.get("code")
    if not code:
        return redirect("/approvals/app")

    redirect_uri = request.build_absolute_uri(settings.BITRIX_OAUTH_REDIRECT_PATH)

    data = {
        "grant_type": "authorization_code",
        "client_id": settings.BITRIX_CLIENT_ID,
        "client_secret": settings.BITRIX_CLIENT_SECRET,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    resp = requests.post(settings.BITRIX_OAUTH_TOKEN_URL, data=data, timeout=10)
    token_data = resp.json()

    access_token = token_data.get("access_token")
    domain = token_data.get("domain")
    if not access_token or not domain:
        return redirect("/approvals/app")

    # 🔹 Сохраняем токены портала, чтобы сервер мог сам вызывать REST Битрикса
    # (в т.ч. при прямом открытии MiniSED с домена). Ранее токен терялся.
    try:
        from bitrix.views import _upsert_portal
        from bitrix.client import store_token

        portal = _upsert_portal(domain, token_data.get("member_id"))
        store_token(portal, token_data)
    except Exception as e:
        print("[Bitrix OAuth] token store error:", e)

    user_resp = requests.get(
        f"https://{domain}/rest/user.current",
        params={"auth": access_token},
        timeout=10,
    )
    user_info = user_resp.json().get("result", {}) or {}
    b24_id = user_info.get("ID")
    raw_email = user_info.get("EMAIL") or user_info.get("WORK_EMAIL")

    if b24_id:
        request.session["b24_user_id"] = int(b24_id)

    if raw_email:
        email = raw_email.strip().lower()
        request.session["b24_email"] = email
        try:
            B24Identity.objects.update_or_create(
                b24_user_id=int(b24_id),
                defaults={"email": email},
            )
        except Exception as e:
            print("[Bitrix OAuth] B24Identity save error:", e)

    next_url = request.session.pop("auth_next", "/approvals/app")
    return redirect(next_url)


def bitrix_auth_start(request):
    """
    Старт OAuth-авторизации через Bitrix24.
    """
    next_url = request.GET.get("next") or "/approvals/app"
    request.session["auth_next"] = next_url

    redirect_uri = request.build_absolute_uri(settings.BITRIX_OAUTH_REDIRECT_PATH)

    params = {
        "client_id": settings.BITRIX_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
    }
    url = f"{settings.BITRIX_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return redirect(url)


def get_current_b24_id(request):
    """
    Определяет личность пользователя:
    0) авторизованный пользователь MiniSED (вход по email+пароль) — по профилю;
    1) запуск внутри портала — ID из заголовка X-B24-User;
    2) вход извне через OAuth — ID из сессии (b24_user_id).
    """
    # 0) авторизация MiniSED (email+пароль) — UserProfile.bitrix_id
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        profile = getattr(user, "minised_profile", None)
        if profile is not None and profile.bitrix_id:
            return profile.bitrix_id

    header = request.META.get("HTTP_X_B24_USER")
    if header:
        try:
            return int(header)
        except ValueError:
            pass

    session_id = request.session.get("b24_user_id")
    if session_id:
        try:
            return int(session_id)
        except ValueError:
            pass

    return None


def user_emails(b24_id) -> list[str]:
    """Все известные адреса сотрудника: привязки B24UserEmail + email профиля.

    По ним сотрудник опознаётся среди ВНЕШНИХ участников. Один адрес можно
    привязать к нескольким сотрудникам — так работает общий ящик (например
    почта юротдела): согласование, ушедшее на него, видят все, к кому он
    привязан."""
    if not b24_id:
        return []
    from core.models import UserProfile

    emails = set(
        B24UserEmail.objects.filter(b24_user_id=b24_id).values_list("email", flat=True)
    )
    profile_email = (
        UserProfile.objects.filter(bitrix_id=b24_id)
        .values_list("email", flat=True)
        .first()
    )
    if profile_email:
        emails.add(profile_email)
    return sorted({e.strip().lower() for e in emails if e and e.strip()})


def _external_email_q(emails) -> Q:
    """Внешний участник по любому из адресов, без учёта регистра.

    Регистр важен: в перенесённых данных рядом живут «Isa@…» и «isa@…», а
    привязки B24UserEmail всегда в нижнем регистре — точное сравнение их
    теряло."""
    q = Q()
    for email in emails:
        q |= Q(
            participants__type=Participant.TYPE_EXTERNAL,
            participants__email__iexact=email,
        )
    return q


def _legal_team_q() -> Q:
    """Согласования с участием юротдела — их видит любой сотрудник отдела.

    Участие юротдела = внутренний участник-юрист либо внешний участник на любом
    из адресов юристов, включая общий ящик отдела (один email, привязанный к
    нескольким юристам). Раньше согласование с общего ящика видел только тот
    юрист, кому этот адрес был привязан вручную, и в архив к остальным оно не
    попадало. Согласования БЕЗ юристов в маршруте отделу по-прежнему не видны."""
    from core.models import UserProfile

    ids = lawyer_b24_ids()
    if not ids:
        return Q(pk__in=[])
    emails = set(
        B24UserEmail.objects.filter(b24_user_id__in=ids).values_list("email", flat=True)
    )
    emails.update(
        UserProfile.objects.filter(bitrix_id__in=ids)
        .exclude(email="")
        .values_list("email", flat=True)
    )
    emails = {e.strip().lower() for e in emails if e and e.strip()}
    return Q(
        participants__type=Participant.TYPE_INTERNAL,
        participants__b24_user_id__in=ids,
    ) | _external_email_q(emails)


@method_decorator(csrf_exempt, name="dispatch")
class AgreementViewSet(viewsets.ModelViewSet):
    """
    /api/agreements/        -> все согласования (без фильтрации, без пагинации)
    /api/agreements/my/     -> только созданные текущим пользователем
    /api/agreements/todo/   -> где текущий пользователь ждёт решения
    """

    queryset = (
        Agreement.objects.all()
        .order_by("-created_at")
        .prefetch_related("participants", "documents", "decision_logs")
    )
    serializer_class = AgreementSerializer
    pagination_class = None
    permission_classes = [AllowAny]

    def get_queryset(self):
        """Базовый queryset: согласования, к которым текущий пользователь
        имеет отношение:
        - инициатор;
        - внутренний участник (по b24_user_id);
        - внешний участник (по email, привязанному к его профилю);
        - сотруднику юротдела — все согласования с участием юротдела
          (см. _legal_team_q).
        """
        base_qs = super().get_queryset()
        request = getattr(self, "request", None)
        if request is None:
            return base_qs.none()

        user_id = get_current_b24_id(request)
        if not user_id:
            return base_qs.none()

        # Сквозной просмотр (системный администратор) — видит всё, без отбора.
        if can_view_all(user_id):
            status_all = (
                request.query_params.get("status")
                if getattr(self, "action", None) == "list" else None
            )
            return base_qs.filter(status=status_all) if status_all else base_qs

        emails = getattr(self, "b24_emails", None)
        if emails is None:
            emails = user_emails(user_id)

        base_q = Q(author_b24_id=user_id) | Q(
            participants__type=Participant.TYPE_INTERNAL,
            participants__b24_user_id=user_id,
        )

        if emails:
            base_q |= _external_email_q(emails)

        if is_lawyer(user_id):
            base_q |= _legal_team_q()

        qs = base_qs.filter(base_q).distinct()
        # Вкладки списка («В работе»/«Отклонённые»/«Завершённые») фильтруют по
        # статусу на сервере — иначе на каждой пришлось бы гонять весь архив.
        status_f = (
            request.query_params.get("status")
            if getattr(self, "action", None) == "list" else None
        )
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    def perform_create(self, serializer):
        agreement = serializer.save()

        try:
            req = getattr(self, "request", None)
            if req is not None:
                raw_crm = (req.data.get("crm_link") or "").strip()
                if raw_crm and agreement.crm_link != raw_crm:
                    agreement.crm_link = raw_crm
                    agreement.save(update_fields=["crm_link"])
        except Exception as e:
            print("CRM UPDATE ERROR in perform_create:", e)

        if agreement.flow_type == Agreement.FLOW_SEQUENTIAL:
            first_waiting = self._get_next_waiting(agreement)
            if first_waiting:
                self._notify_participant(agreement, first_waiting)
        else:
            for p in agreement.participants.filter(status=Participant.STATUS_WAITING):
                self._notify_participant(agreement, p)

    def initial(self, request, *args, **kwargs):
        self.b24_id = get_current_b24_id(request)
        if not self.b24_id:
            raise AuthenticationFailed("Откройте приложение «Мини-СЭД» из Битрикс24.")

        self.b24_emails = user_emails(self.b24_id)

        return super().initial(request, *args, **kwargs)

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["current_b24_id"] = getattr(self, "b24_id", None)
        return ctx

    def _round_qs(self, agreement: Agreement):
        """Участники текущего круга (ТЗ п.7.4 — несколько кругов)."""
        return agreement.participants.filter(round_number=agreement.current_round)

    def _get_next_waiting(self, agreement: Agreement):
        """
        Первый по порядку (order_index) участник текущего круга со статусом waiting.
        Нужен, чтобы понять, кому отправлять уведомление дальше.
        """
        return (
            self._round_qs(agreement)
            .filter(status=Participant.STATUS_WAITING)
            .order_by("order_index")
            .first()
        )

    def _is_participant_turn(
        self, agreement: Agreement, participant: Participant
    ) -> bool:
        """
        Сейчас ли очередь этого участника?
        Он может голосовать только если:
        - сам в статусе waiting
        - перед ним (с меньшим order_index) в этом круге НЕТ участников waiting
        """
        if agreement.flow_type == Agreement.FLOW_PARALLEL:
            return participant.status == Participant.STATUS_WAITING

        if participant.status != Participant.STATUS_WAITING:
            return False

        return not self._round_qs(agreement).filter(   # type: ignore
            order_index__lt=participant.order_index,
            status=Participant.STATUS_WAITING,
        ).exists()

    def _recompute_status(self, agreement: Agreement):
        """Пересчёт статуса по участникам ТЕКУЩЕГО круга."""
        parts = self._round_qs(agreement)
        if parts.filter(status=Participant.STATUS_REJECTED).exists():
            agreement.status = Agreement.STATUS_REJECTED
        elif parts.filter(status=Participant.STATUS_WAITING).exists():
            agreement.status = Agreement.STATUS_IN_PROGRESS
        else:
            agreement.status = Agreement.STATUS_COMPLETED
        agreement.save(update_fields=["status"])

    def _notify_participant(self, agreement: Agreement,
                            participant: Participant):
        """
        Уведомление участнику — и внутреннему, и внешнему (единая логика,
        см. approvals.notifications): письмо со ссылкой-токеном на страницу
        согласования + Битрикс-колокольчик, если участник есть в Битриксе.
        """
        from . import notifications

        try:
            base_url = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/") \
                or self.request.build_absolute_uri("/")
            notifications.notify_participant(agreement, participant, base_url)
        except Exception as e:
            print("NOTIFY ERROR for participant", participant.id, e)

    @action(detail=False, methods=["get"])
    def my(self, request):
        qs = self.get_queryset().filter(author_b24_id=self.b24_id)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def badge_counts(self, request):
        """Счётчики для вкладок светофора (мои согласования):
        отклонённые/завершённые — сколько я ЕЩЁ НЕ просмотрел после смены статуса."""
        from core import services as core_services

        my_qs = Agreement.objects.filter(author_b24_id=self.b24_id)
        rejected = my_qs.filter(status=Agreement.STATUS_REJECTED)
        completed = my_qs.filter(status=Agreement.STATUS_COMPLETED)
        return Response({
            "rejected_unseen": len(core_services.unseen_pks(self.b24_id, rejected)),
            "completed_unseen": len(core_services.unseen_pks(self.b24_id, completed)),
            "in_progress": my_qs.filter(status=Agreement.STATUS_IN_PROGRESS).count(),
        })

    @action(detail=False, methods=["get"])
    def todo(self, request):
        """
        Согласования, где текущему пользователю нужно принять решение:
        - как внутреннему участнику (по b24_user_id),
        - как внешнему участнику (по email из B24Identity).
        """
        emails = getattr(self, "b24_emails", [])

        cond_internal = Q(
            participants__type=Participant.TYPE_INTERNAL,
            participants__b24_user_id=self.b24_id,
            participants__status=Participant.STATUS_WAITING,
            participants__round_number=F("current_round"),
        )

        cond_external = Q()
        for email in emails:
            # регистр адреса в старых данных не нормализован — сравниваем iexact
            cond_external |= Q(
                participants__type=Participant.TYPE_EXTERNAL,
                participants__email__iexact=email,
                participants__status=Participant.STATUS_WAITING,
                participants__round_number=F("current_round"),
            )

        qs = (
            self.get_queryset()
            .filter(
                Q(status=Agreement.STATUS_IN_PROGRESS) & (cond_internal | cond_external)
            )
            .distinct()
        )
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        """
        Решение участника (через API внутри Б24).
        В body: {participant_id, decision, comment}

        Если flow_type = sequential — голосовать может только тот,
        чей черёд (order_index) и у кого статус waiting.
        Если flow_type = parallel — любой участник со статусом waiting.
        """
        b24_id = get_current_b24_id(request)
        if not b24_id:
            raise AuthenticationFailed("Откройте приложение «Мини-СЭД» из Битрикс24.")

        agreement = self.get_object()

        participant_id = request.data.get("participant_id")
        decision = request.data.get("decision")
        comment = (request.data.get("comment") or "").strip()

        try:
            participant = agreement.participants.get(id=participant_id)
        except Participant.DoesNotExist:
            return Response(
                {"detail": "Участник не найден"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if agreement.status == Agreement.STATUS_CANCELED:
            return Response(
                {"detail": "Согласование отменено, изменить решение нельзя."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if agreement.status == Agreement.STATUS_COMPLETED:
            return Response(
                {"detail": "Согласование уже завершено."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if participant.type == Participant.TYPE_INTERNAL:
            if str(participant.b24_user_id) != str(b24_id):
                return Response(
                    {"detail": "Недостаточно прав"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        else:
            # Внешний участник (по email): решать может только владелец этой
            # почты — из B24UserEmail или email профиля MiniSED.
            my_emails = {e.lower() for e in getattr(self, "b24_emails", [])}
            profile = get_current_profile(request)
            if profile and profile.email:
                my_emails.add(profile.email.lower())
            if (participant.email or "").lower() not in my_emails:
                return Response(
                    {"detail": "Недостаточно прав"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        if participant.status != Participant.STATUS_WAITING:
            return Response(
                {"detail": "Вы уже приняли решение по этому документу."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if agreement.flow_type == AgreementModel.FLOW_SEQUENTIAL:

            if not self._is_participant_turn(agreement, participant):
                return Response(
                    {
                        "detail": "Сначала должны принять решение участники выше по списку."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if decision == "reject" and not comment:
            return Response(
                {"detail": "Комментарий обязателен при отклонении документа."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        now = timezone.now()

        if decision == "approve":
            participant.status = Participant.STATUS_APPROVED
        elif decision == "reject":
            participant.status = Participant.STATUS_REJECTED
        else:
            return Response(
                {"detail": "Некорректное решение"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        participant.comment = comment
        participant.decided_at = now
        participant.save(update_fields=["status", "comment", "decided_at"])

        DecisionLog.objects.create(
            agreement=agreement,
            participant=participant,
            status=participant.status,
            comment=participant.comment,
            round_number=agreement.current_round,
            decided_at=participant.decided_at,
        )

        self._recompute_status(agreement)

        if (
            agreement.flow_type == AgreementModel.FLOW_SEQUENTIAL
            and agreement.status == Agreement.STATUS_IN_PROGRESS
        ):
            next_p = self._get_next_waiting(agreement)
            if next_p:
                self._notify_participant(agreement, next_p)

        # Инициатору — итог: согласовано (все приняли) или отклонено.
        try:
            from core.models import UserProfile
            from . import notifications

            if agreement.status == Agreement.STATUS_COMPLETED:
                notifications.notify_author_result(agreement, approved=True)
            elif agreement.status == Agreement.STATUS_REJECTED:
                by_name = ""
                if participant.b24_user_id:
                    prof = UserProfile.objects.filter(bitrix_id=participant.b24_user_id).first()
                    by_name = prof.fio if prof else ""
                notifications.notify_author_result(
                    agreement, approved=False, by_name=by_name, comment=comment
                )
        except Exception as e:
            print("NOTIFY author result error:", e)

        return Response({"status": participant.status})

    @action(detail=True, methods=["post"])
    def restart(self, request, pk=None):
        """
        Перезапуск согласования:
        - только те участники, у кого статус REJECTED,
        переводятся обратно в WAITING
        - у них сохраняем prev_status/prev_comment
        - возвращаем список внутренних участников,
        которых нужно уведомить во фронте
        """
        agreement = self.get_object()

        if agreement.status not in [
            Agreement.STATUS_REJECTED,
            Agreement.STATUS_IN_PROGRESS,
        ]:
            return Response(
                {
                    "detail": "Перезапуск доступен только для отклонённых или незавершённых согласований."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        internal_to_notify: list[int] = []

        with transaction.atomic():
            # только отклонившие участники ТЕКУЩЕГО круга
            rejected_participants = self._round_qs(agreement).filter(
                status=Participant.STATUS_REJECTED
            )

            for p in rejected_participants:
                p.prev_status = p.status
                p.prev_comment = p.comment
                p.status = Participant.STATUS_WAITING
                p.comment = ""
                p.decided_at = None
                p.save()

                if p.type == Participant.TYPE_INTERNAL and p.b24_user_id:
                    internal_to_notify.append(p.b24_user_id)
                else:
                    self._notify_participant(agreement, p)

            self._recompute_status(agreement)

        data = self.get_serializer(agreement).data
        data["internal_to_notify"] = internal_to_notify
        return Response(data)

    def _create_participants(self, agreement, specs, round_number):
        created = []
        for idx, s in enumerate(specs):
            if not isinstance(s, dict):
                continue
            p = Participant.objects.create(
                agreement=agreement,
                type=s.get("type", Participant.TYPE_INTERNAL),
                b24_user_id=s.get("b24_user_id"),
                email=s.get("email", "") or "",
                name=s.get("name", "") or "",
                order_index=s.get("order_index", idx),
                round_number=round_number,
            )
            created.append(p)
        return created

    def _route_snapshot(self, agreement, round_number):
        return [
            {"type": p.type, "b24_user_id": p.b24_user_id, "email": p.email, "order_index": p.order_index}
            for p in agreement.participants.filter(round_number=round_number).order_by("order_index")
        ]

    @action(detail=True, methods=["post"])
    def resubmit(self, request, pk=None):
        """
        Повторное согласование новым кругом (ТЗ п.7.4, 7.5).
        Автор после доработки отправляет заново: создаётся новый круг с
        (возможно изменённым) маршрутом; история прошлых кругов сохраняется.
        Body (опц.): participants=[{type,b24_user_id,email,order_index}],
        comment — пояснение согласующим, что изменилось после доработки.
        """
        b24_id = get_current_b24_id(request)
        agreement = self.get_object()
        if agreement.author_b24_id != b24_id:
            return Response({"detail": "Только автор может отправить на повторное согласование."}, status=403)
        # Завершённое согласование закрыто; повторно — только отклонённое или отменённое.
        if agreement.status not in (Agreement.STATUS_REJECTED, Agreement.STATUS_CANCELED):
            return Response({"detail": "Повторно отправить можно отклонённое или отменённое согласование."}, status=400)

        specs = request.data.get("participants")
        if not isinstance(specs, list) or not specs:
            # копируем маршрут предыдущего круга
            specs = self._route_snapshot(agreement, agreement.current_round)
        if not specs:
            return Response({"detail": "Маршрут пуст — некого назначить."}, status=400)

        comment = (request.data.get("comment") or "").strip()

        internal_to_notify: list[int] = []
        with transaction.atomic():
            new_round = agreement.current_round + 1
            new_parts = self._create_participants(agreement, specs, new_round)
            agreement.current_round = new_round
            agreement.status = Agreement.STATUS_IN_PROGRESS
            agreement.save(update_fields=["current_round", "status"])
            # Пояснение инициатора живёт на круге: согласующие увидят его в
            # истории и получат в письме вместе с приглашением согласовать.
            if comment:
                RoundNote.objects.create(
                    agreement=agreement, round_number=new_round,
                    author_b24_id=b24_id, comment=comment,
                )

            # Уведомляем ВСЕХ, кому предстоит решать в новом круге, — и внешних,
            # и внутренних. Раньше внутренним не уходило ничего: их id лишь
            # возвращались фронту в internal_to_notify, а фронт их не использует.
            # Список в ответе оставлен для совместимости.
            if agreement.flow_type == Agreement.FLOW_SEQUENTIAL:
                to_notify = [p for p in [self._get_next_waiting(agreement)] if p]
            else:
                to_notify = list(new_parts)
            for p in to_notify:
                if p.type == Participant.TYPE_INTERNAL and p.b24_user_id:
                    internal_to_notify.append(p.b24_user_id)
                self._notify_participant(agreement, p)

        try:
            log_action("agreement_resubmitted", target=agreement,
                       new_value={"round": agreement.current_round}, request=request)
        except Exception:
            pass

        data = self.get_serializer(agreement).data
        data["internal_to_notify"] = internal_to_notify
        return Response(data)

    @action(detail=True, methods=["post"], url_path="set_route")
    def set_route(self, request, pk=None):
        """
        Изменение согласующих текущего круга при направлении (ТЗ п.7.6).
        Разрешено, пока в текущем круге никто ещё не проголосовал.
        Body: participants=[{type,b24_user_id,email,order_index}].
        """
        b24_id = get_current_b24_id(request)
        agreement = self.get_object()
        if agreement.author_b24_id != b24_id:
            return Response({"detail": "Только автор может менять маршрут."}, status=403)
        if agreement.status != Agreement.STATUS_IN_PROGRESS:
            return Response(
                {"detail": "Менять маршрут текущего круга можно только у активного согласования."},
                status=400,
            )

        cur = self._round_qs(agreement)
        if cur.exclude(status=Participant.STATUS_WAITING).exists():
            return Response(
                {"detail": "Маршрут можно менять до первых решений. Для изменений после — используйте повторное согласование."},
                status=400,
            )

        specs = request.data.get("participants")
        if not isinstance(specs, list) or not specs:
            return Response({"detail": "Передайте список участников."}, status=400)

        old = self._route_snapshot(agreement, agreement.current_round)
        with transaction.atomic():
            cur.delete()
            self._create_participants(agreement, specs, agreement.current_round)
            self._recompute_status(agreement)

        try:
            log_action("agreement_route_changed", target=agreement,
                       old_value=old, new_value=self._route_snapshot(agreement, agreement.current_round),
                       request=request)
        except Exception:
            pass

        return Response(self.get_serializer(agreement).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        """
        Отменить согласование.
        Только автор, нельзя отменить уже завершённое/отменённое.
        """
        b24_id = get_current_b24_id(request)
        if not b24_id:
            raise AuthenticationFailed("Откройте приложение «Мини-СЭД» из Битрикс24.")
        agreement = self.get_object()

        if agreement.author_b24_id != b24_id:
            return Response(
                {"detail": "Недостаточно прав для отмены согласования."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if agreement.status in (
            Agreement.STATUS_COMPLETED,
            Agreement.STATUS_CANCELED,
        ):
            return Response(
                {
                    "detail": "Нельзя отменить уже завершённое или отменённое согласование."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        agreement.status = Agreement.STATUS_CANCELED
        agreement.save()

        serializer = self.get_serializer(agreement)
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        """
        Удалить согласование.
        Только автор. При удалении удаляются
        документы и участники (через CASCADE).
        """
        b24_id = get_current_b24_id(request)
        if not b24_id:
            raise AuthenticationFailed("Откройте приложение «Мини-СЭД» из Битрикс24.")
        agreement = self.get_object()

        if agreement.author_b24_id != b24_id:
            return Response(
                {"detail": "Недостаточно прав для удаления согласования."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return super().destroy(request, *args, **kwargs)

    @action(
        detail=True,
        methods=["post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def update_document(self, request, pk=None):
        b24_id = get_current_b24_id(request)
        if not b24_id:
            raise AuthenticationFailed("Откройте приложение «Мини-СЭД» из Битрикс24.")
        agreement = self.get_object()

        if agreement.author_b24_id != b24_id:
            return Response(
                {"detail": "Недостаточно прав для обновления документа."},
                status=status.HTTP_403_FORBIDDEN,
            )

        files = request.FILES.getlist("files")
        single = request.FILES.get("file")

        if single and not files:
            files = [single]

        if not files:
            return Response(
                {"detail": "Файлы не переданы."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        AgreementDocument.objects.filter(
            agreement=agreement,
            type=AgreementDocument.TYPE_FILE,
        ).delete()

        for f in files:
            AgreementDocument.objects.create(
                agreement=agreement,
                type=AgreementDocument.TYPE_FILE,
                file=f,
            )

        serializer = self.get_serializer(agreement)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def participated(self, request):
        """
        Согласования, где пользователь участвовал:
        - как внутренний участник (по b24_user_id)
        - как внешний участник (по email, привязанному к его Б24-профилю)
        """
        b24_id = get_current_b24_id(request)
        if not b24_id:
            raise AuthenticationFailed("Откройте приложение «Мини-СЭД» из Битрикс24.")

        emails = user_emails(b24_id)

        base_q = Q(
            participants__type=Participant.TYPE_INTERNAL,
            participants__b24_user_id=b24_id,
        )
        if emails:
            base_q |= _external_email_q(emails)

        qs = self.get_queryset().filter(base_q).distinct()
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="sheet_pdf")
    def sheet_pdf(self, request, pk=None):
        """Лист согласования в PDF (ТЗ п.7.7), формируется на лету."""
        agreement = self.get_object()
        from .sheet import render_pdf

        pdf = render_pdf(agreement)
        return FileResponse(
            io.BytesIO(pdf), content_type="application/pdf",
            filename=f"list_soglasovaniya_{agreement.id}.pdf",
        )


@csrf_exempt
@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
def simple_create_agreement(request):
    """
    Упрощённое создание согласования.
    Ожидает поля:
      - title
      - description (опц.)
      - amount (опц.)
      - deadline (опц., YYYY-MM-DD)
      - crm_link (опц.)
      - files (один или несколько файлов договора/приложений)
      - internal_users: строка "12,34,56" (ID пользователей Б24)
      - external_emails: строка "mail1@x.ru,mail2@y.ru"
    """

    b24_id = get_current_b24_id(request)
    if not b24_id:
        return Response(
            {"detail": "Требуется авторизация Битрикс24."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    title = request.data.get("title", "").strip()
    if not title:
        return Response({"detail": "Не заполнено название"}, status=400)

    description = request.data.get("description", "").strip()
    amount = request.data.get("amount")
    deadline = request.data.get("deadline")
    crm_link = request.data.get("crm_link", "").strip()

    try:
        amount_val = (
            float(amount)
            if amount
            not in (
                None,
                "",
            )
            else None
        )
    except ValueError:
        return Response({"detail": "Некорректная сумма"}, status=400)

    deadline_val = None
    if deadline:
        try:
            deadline_val = datetime.strptime(deadline, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Некорректный формат дедлайна (нужно YYYY-MM-DD)"},
                status=400,
            )

    flow_type = request.data.get("flow_type") or Agreement.FLOW_PARALLEL
    if flow_type not in dict(Agreement.FLOW_CHOICES):
        flow_type = Agreement.FLOW_PARALLEL

    agreement = Agreement.objects.create(
        title=title,
        description=description,
        amount=amount_val,
        deadline=deadline_val,
        crm_link=crm_link,
        author_b24_id=b24_id,
        status=Agreement.STATUS_IN_PROGRESS,
        flow_type=flow_type,
    )

    files = request.FILES.getlist("files")
    single = request.FILES.get("file")

    if single and not files:
        files = [single]

    for f in files:
        AgreementDocument.objects.create(
            agreement=agreement,
            type=AgreementDocument.TYPE_FILE,
            file=f,
        )
    internal = request.data.get("internal_users", "")
    for idx, user_id_str in enumerate(
        filter(None, [x.strip() for x in internal.split(",")])
    ):
        try:
            uid = int(user_id_str)
        except ValueError:
            continue
        Participant.objects.create(
            agreement=agreement,
            type=Participant.TYPE_INTERNAL,
            b24_user_id=uid,
            order_index=idx,
        )
    external_raw = request.data.get("external_emails", "") or ""
    external_list = [x.strip() for x in external_raw.split(",") if x.strip()]
    for idx, email in enumerate(external_list, start=100):
        Participant.objects.create(
            agreement=agreement,
            type=Participant.TYPE_EXTERNAL,
            email=email,
            order_index=idx,
        )

    # Уведомления при создании — И внутренним, И внешним участникам, единым
    # богатым письмом (название, описание, сумма, CRM + ссылка-токен на страницу
    # согласования без авторизации). Для последовательного маршрута шлём только
    # первому (остальным — по мере наступления их очереди в decide).
    from . import notifications

    base_url = (getattr(settings, "PUBLIC_BASE_URL", "") or "").rstrip("/") \
        or request.build_absolute_uri("/")
    parts = list(agreement.participants.order_by("order_index"))
    if agreement.flow_type == Agreement.FLOW_SEQUENTIAL:
        parts = parts[:1]
    for p in parts:
        try:
            notifications.notify_participant(agreement, p, base_url)
        except Exception as e:
            print("NOTIFY create error:", e)

    serializer = AgreementSerializer(agreement)
    return Response(serializer.data, status=201)


@api_view(["POST"])
def register_b24_identity(request):
    """
    Регистрирует связку b24_user_id ↔ email.
    Вызывается из фронта после BX24.user.current().
    """
    user_id = get_current_b24_id(request)
    if not user_id:
        return Response(
            {"detail": "Требуется авторизация Битрикс24."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    email = (request.data.get("email") or "").strip().lower()
    if not email:
        return Response(
            {"detail": "Не передан email"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    identity, created = B24Identity.objects.update_or_create(
        b24_user_id=user_id,
        defaults={"email": email},
    )
    return Response(
        {"b24_user_id": identity.b24_user_id, "email": identity.email},
        status=status.HTTP_200_OK,
    )


@csrf_exempt
def external_approve_view(request, token):
    try:
        # По токену согласуют и внешние, и внутренние участники (внутренним
        # теперь тоже уходит письмо со ссылкой), поэтому по типу не фильтруем.
        participant = Participant.objects.select_related("agreement").get(
            external_token=token,
        )
    except Participant.DoesNotExist:
        return render(
            request,
            "approvals/external_not_found.html",
            status=404,
        )

    agreement = participant.agreement
    documents = []
    for d in agreement.documents.all():  # type: ignore
        url = None
        name = None

        if d.file:
            url = d.file.url
            name = os.path.basename(d.file.name)
        elif d.url:
            url = d.url
            name = d.url

        if not url:
            continue

        documents.append(
            {
                "url": url,
                "name": name or "Документ",
            }
        )
    file_url = documents[0]["url"] if documents else None

    if request.method == "POST":
        decision = request.POST.get("decision")
        comment = request.POST.get("comment", "").strip()
        if participant.status != Participant.STATUS_WAITING:
            return render(
                request,
                "approvals/external_result.html",
                {"agreement": agreement, "participant": participant},
            )
        if decision == "reject" and not comment:
            return render(
                request,
                "approvals/external_approve.html",
                {
                    "agreement": agreement,
                    "participant": participant,
                    "documents": documents,
                    "file_url": file_url,
                    "deadline": agreement.deadline,
                    "already_decided": False,
                    "error": "При отклонении документа необходимо указать комментарий.",
                    "force_comment": True,
                    "comment_value": "",
                },
            )

        if decision == "approve":
            participant.status = Participant.STATUS_APPROVED
        elif decision == "reject":
            participant.status = Participant.STATUS_REJECTED
        else:
            return render(
                request,
                "approvals/external_approve.html",
                {
                    "agreement": agreement,
                    "participant": participant,
                    "documents": documents,
                    "file_url": file_url,
                    "deadline": agreement.deadline,
                    "already_decided": False,
                    "error": None,
                    "force_comment": False,
                    "comment_value": comment,
                },
            )

        now = timezone.now()
        participant.comment = comment
        participant.decided_at = now
        participant.save(update_fields=["status", "comment", "decided_at"])

        # 🔹 пишем в историю решений
        DecisionLog.objects.create(
            agreement=agreement,
            participant=participant,
            status=participant.status,
            comment=participant.comment,
            round_number=agreement.current_round,
            decided_at=participant.decided_at,
        )

        # пересчитываем статус по участникам текущего круга
        cur = agreement.participants.filter(round_number=agreement.current_round)
        if cur.filter(status=Participant.STATUS_REJECTED).exists():
            agreement.status = Agreement.STATUS_REJECTED
        elif not cur.filter(status=Participant.STATUS_WAITING).exists():
            agreement.status = Agreement.STATUS_COMPLETED
        else:
            agreement.status = Agreement.STATUS_IN_PROGRESS
        agreement.save(update_fields=["status"])

        # Последовательный флоу: после решения уведомляем следующего по очереди
        # (раньше это делал только API-endpoint; теперь и согласование по ссылке).
        if (
            participant.status == Participant.STATUS_APPROVED
            and agreement.flow_type == Agreement.FLOW_SEQUENTIAL
            and agreement.status == Agreement.STATUS_IN_PROGRESS
        ):
            nxt = (
                agreement.participants.filter(
                    round_number=agreement.current_round,
                    status=Participant.STATUS_WAITING,
                )
                .order_by("order_index")
                .first()
            )
            if nxt:
                try:
                    from . import notifications

                    notifications.notify_participant(
                        agreement, nxt, request.build_absolute_uri("/")
                    )
                except Exception as e:
                    print("NOTIFY next ERROR:", e)

        return render(
            request,
            "approvals/external_result.html",
            {"agreement": agreement, "participant": participant},
        )

    already = participant.status != Participant.STATUS_WAITING
    return render(
        request,
        "approvals/external_approve.html",
        {
            "agreement": agreement,
            "participant": participant,
            "documents": documents,
            "file_url": file_url,
            "deadline": agreement.deadline,
            "already_decided": already,
            "error": None,
            "force_comment": False,
            "comment_value": "",
        },
    )


class ApprovalTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = ApprovalTemplateSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        user_id = get_current_b24_id(self.request)
        qs = ApprovalTemplate.objects.all()

        if not user_id:
            return qs.none()

        return qs.filter(
            Q(scope=ApprovalTemplate.SCOPE_PUBLIC)
            | Q(scope=ApprovalTemplate.SCOPE_PRIVATE, author_b24_id=user_id)
            | Q(
                scope=ApprovalTemplate.SCOPE_GROUP,
                accesses__b24_user_id=user_id,
            )
        ).distinct()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["current_b24_id"] = get_current_b24_id(self.request)
        return ctx
