"""Errors shown to people are in Russian and say what to do; everything else is logged with a traceback."""
import os
import re


class UserError(Exception):
    """An error whose message is meant for the user as is."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise UserError(f"На сервере не задан {name}. Добавьте его в .env и перезапустите API.", status=503)
    return value


_RATE = {"RateLimitError", "GoogleRateLimitError", "ModelRateLimitError", "ResourceExhausted", "TooManyRequests"}
_AUTH = {"AuthenticationError", "GoogleAuthenticationError", "ModelAuthenticationError", "PermissionDeniedError",
         "GooglePermissionDeniedError", "ModelPermissionDeniedError", "Unauthenticated"}
_TIMEOUT = {"APITimeoutError", "TimeoutError", "ReadTimeout", "ConnectTimeout", "Timeout", "DeadlineExceeded"}
_CONTEXT = {"ContextOverflowError", "GoogleContextOverflowError"}
_CONNECTION = {"APIConnectionError", "ConnectionError", "ConnectError", "ServiceUnavailable"}


def _status(exc: BaseException) -> int | None:
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def humanize(exc: BaseException) -> str:
    """Turn any exception into a short Russian message that is safe to show."""
    if isinstance(exc, UserError):
        return exc.message
    names = {cls.__name__ for cls in type(exc).__mro__}
    text = str(exc)
    status = _status(exc)
    lowered = text.lower()
    if names & _RATE or status == 429 or re.search(r"\b429\b|resource.exhausted|rate.limit|quota", lowered):
        return "Сервис ИИ сейчас перегружен или исчерпан лимит запросов. Попробуйте через минуту."
    if status in (500, 502, 503, 504) or re.search(r"\b50[0234]\b|unavailable|high demand|overloaded", lowered):
        return "Модель Gemini сейчас перегружена. Нажмите «Попробовать ещё раз» через минуту: обработка продолжится с того же шага."
    if names & _AUTH or status in (401, 403):
        return "Внешний сервис отклонил API-ключ. Проверьте ключи в .env."
    if names & _CONTEXT:
        return "Видео слишком длинное, чтобы обработать его целиком."
    if names & _TIMEOUT or "timed out" in lowered:
        return "Внешний сервис не ответил вовремя. Попробуйте ещё раз."
    if names & _CONNECTION:
        return "Нет связи с внешним сервисом. Проверьте подключение к интернету и попробуйте ещё раз."
    return "Что-то пошло не так. Попробуйте ещё раз, а если ошибка повторится, загляните в логи API."
