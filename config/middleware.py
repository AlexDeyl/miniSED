from django.conf import settings


class FrameAncestorsMiddleware:
    """
    Управляет встраиванием приложения в iframe.

    Заменяет небезопасный X-Frame-Options: ALLOWALL (который фактически
    отключает защиту) на Content-Security-Policy: frame-ancestors,
    где перечислены только доверенные домены (сам сайт + порталы Битрикс24).

    Список источников берётся из settings.FRAME_ANCESTORS.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        sources = getattr(settings, "FRAME_ANCESTORS", ["'self'"])
        self.header_value = "frame-ancestors " + " ".join(sources)

    def __call__(self, request):
        response = self.get_response(request)

        # Убираем X-Frame-Options, чтобы он не конфликтовал с CSP:
        # современные браузеры при наличии frame-ancestors игнорируют
        # X-Frame-Options, но убрать его — чище и предсказуемее.
        response.headers.pop("X-Frame-Options", None)

        existing = response.headers.get("Content-Security-Policy")
        if existing:
            response.headers["Content-Security-Policy"] = (
                f"{existing}; {self.header_value}"
            )
        else:
            response.headers["Content-Security-Policy"] = self.header_value

        return response
