"""Deployment-specific model windows and an independent durable storage ceiling."""

from urllib.parse import urlsplit


def model_context_window(model: str, api_base: str | None, declared: int | None = None) -> int:
    if declared is not None:
        return declared
    host = urlsplit(api_base or "").hostname
    name = model.rsplit("/", 1)[-1]
    # Same official-deployment allowlist as NotaWorks. Custom proxies must declare capacity.
    if (host == "api.deepseek.com" and name in {"deepseek-flash", "deepseek-v4-flash"}) or (
        host == "dashscope.aliyuncs.com" and name == "deepseek-v4-flash-0731"
    ):
        return 1_000_000
    return 64_000


def checkpoint_byte_limit(window_tokens: int) -> int:
    return min(32 * 1024 * 1024, max(3 * 1024 * 1024, window_tokens * 16 + 256 * 1024))
