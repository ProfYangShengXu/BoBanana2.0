"""LLM factory.

Builds OpenAI-compatible chat models. Temperature is layered per agent role to
reduce fixation (a single low temperature made the executor repeat the same
exploration script); the reviewer and directive gate stay at 0 to keep review
strict and deterministic.
"""

from __future__ import annotations

from typing import Type, TypeVar

from pydantic import BaseModel

from .config import Settings

T = TypeVar("T", bound=BaseModel)


# Per-role temperatures. Strict critics at 0; the executor runs hotter so retries
# actually change approach instead of replaying the same failing commands.
ROLE_TEMPERATURES: dict[str, float] = {
    "planner": 0.3,
    "executor": 0.45,
    "reviewer": 0.0,
    "directive_gate": 0.0,
    "finalize": 0.3,
    "intent": 0.2,
}


def resolve_structured_output_method(settings: Settings) -> str:
    mode = (settings.structured_output_method or "auto").lower()
    if mode != "auto":
        return mode
    base = (settings.base_url or "").lower()
    if any(h in base for h in ("deepseek", "moonshot", "dashscope", "qwen")):
        return "function_calling"
    return "json_schema"


def normalize_chat_model(model: str, base_url: str | None) -> str:
    """DeepSeek thinking/reasoner models reject tool_choice used by structured output."""
    if not base_url or "deepseek" not in base_url.lower():
        return model
    if model == "deepseek-chat":
        return model
    thinking_like = ("v4-flash", "reasoner", "r1", "thinking")
    if any(t in model.lower() for t in thinking_like):
        return "deepseek-chat"
    return model


def wrap_structured_output(llm, schema: Type[T], settings: Settings):
    """Bind a Pydantic schema using a provider-compatible structured-output method."""
    method = resolve_structured_output_method(settings)
    return llm.with_structured_output(schema, method=method)


def build_chat_model(settings: Settings, temperature: float | None = None,
                     callbacks: list | None = None):
    """Create a chat LLM. Raises a clear error if no API key is configured.

    ``temperature`` overrides the global default when provided (used for the
    per-role temperature tiers).
    """
    if not settings.api_key:
        raise RuntimeError(
            "No LLM configured. Set OPENAI_API_KEY (and optionally OPENAI_BASE_URL) "
            "in your environment or .env file."
        )
    from langchain_openai import ChatOpenAI

    chat_model = normalize_chat_model(settings.model, settings.base_url)
    kwargs = {
        "model": chat_model,
        "temperature": settings.temperature if temperature is None else temperature,
        "api_key": settings.api_key,
    }
    # Per-call timeout bounds each graph node so a stuck call can't hang the whole
    # task past its wall-clock budget (checked at node boundaries).
    if getattr(settings, "llm_timeout", 0):
        kwargs["timeout"] = settings.llm_timeout
    if settings.base_url:
        kwargs["base_url"] = settings.base_url
    if callbacks:
        kwargs["callbacks"] = callbacks
    return ChatOpenAI(**kwargs)


def role_temperature(settings: Settings, role: str) -> float:
    return ROLE_TEMPERATURES.get(role, settings.temperature)


def build_role_models(settings: Settings, callbacks: list | None = None) -> dict:
    """Build one chat model per agent role with its layered temperature."""
    return {role: build_chat_model(settings, temperature=temp, callbacks=callbacks)
            for role, temp in ROLE_TEMPERATURES.items()}
