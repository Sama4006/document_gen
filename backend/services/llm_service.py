"""LLM service: all OpenAI API calls (chat + embeddings)."""

import json
import logging
import re
from typing import Dict, List, Optional

from backend.config import settings

logger = logging.getLogger("docgen.llm")

# Errors after which the next fallback model is tried.
_RETRY_WITH_NEXT_MODEL = {
    "NotFoundError",          # model unknown / not available to this key
    "RateLimitError",         # 429: quota or rate limit
    "InternalServerError",    # 5xx: overloaded or unavailable
    "APITimeoutError",
    "APIConnectionError",
}

SYSTEM_PROMPT = (
    "You are a professional document generation assistant. Write clear, "
    "well-structured content suitable for a Word document. Use plain text: "
    "no Markdown syntax such as #, ** or backticks. If context is supplied, "
    "base factual statements on it and do not invent figures or names."
)

FILL_SYSTEM_PROMPT = (
    "You fill in Word document templates. You receive a request, optional "
    "context, and a list of placeholder names. Return ONE JSON object whose "
    "keys are exactly the placeholder names and whose values are plain-text "
    "strings (no Markdown). Keep short fields short (names, dates, titles); "
    "write full paragraphs for long fields (summaries, analysis, body text). "
    "Use '\\n' for line breaks and '- ' for list items. If the context does "
    "not contain a fact a field needs, write a sensible neutral value rather "
    "than inventing specifics."
)


class LLMNotConfigured(RuntimeError):
    """Raised when an LLM call is attempted without an API key."""


class LLMModelNotFound(RuntimeError):
    """Raised when the API does not know the configured model name."""


class LLMUnavailable(RuntimeError):
    """Raised when every configured chat model failed."""


def _model_not_found(setting: str, model: str) -> LLMModelNotFound:
    return LLMModelNotFound(
        f"The model '{model}' is not available for this API key. "
        f"Set {setting} in .env to a model your key can use "
        "(GET /models lists them)."
    )


class LLMService:
    def __init__(self):
        self._client = None

    @property
    def configured(self) -> bool:
        key = settings.openai_api_key
        return bool(key) and not key.startswith("sk-your-")

    @property
    def client(self):
        if not self.configured:
            raise LLMNotConfigured(
                "OPENAI_API_KEY is not set. Add it to .env and restart the server."
            )
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url or None,
                timeout=settings.openai_timeout,
                max_retries=1,
            )
        return self._client

    # ------------------------------------------------------------------ chat
    def _chat(self, system: str, user: str, json_mode: bool = False) -> str:
        """Call the main model, falling back to OPENAI_FALLBACK_MODELS in order
        when a model is busy, rate-limited or unavailable."""
        models = settings.chat_models
        failures = []
        for index, model in enumerate(models):
            try:
                return self._chat_once(system, user, json_mode, model)
            except Exception as exc:
                kind = type(exc).__name__
                if kind not in _RETRY_WITH_NEXT_MODEL:
                    raise
                failures.append((model, kind, exc))
                if index + 1 < len(models):
                    logger.warning("%s failed (%s); trying %s", model, kind, models[index + 1])
                    continue
                if len(models) == 1 and kind == "NotFoundError":
                    raise _model_not_found("OPENAI_MODEL", model) from exc
                if len(models) == 1:
                    raise
                summary = "; ".join(f"{m}: {k}" for m, k, _ in failures)
                raise LLMUnavailable(
                    f"All configured models failed ({summary}). The provider may be "
                    "busy or your quota used up; try again shortly, or change "
                    "OPENAI_MODEL / OPENAI_FALLBACK_MODELS in .env."
                ) from exc
        raise LLMUnavailable("No chat model is configured (OPENAI_MODEL).")

    def _chat_once(self, system: str, user: str, json_mode: bool, model: str) -> str:
        from openai import BadRequestError

        params = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": settings.max_output_tokens,
        }
        if settings.openai_temperature is not None:
            params["temperature"] = settings.openai_temperature
        if json_mode:
            params["response_format"] = {"type": "json_object"}

        try:
            response = self.client.chat.completions.create(**params)
        except BadRequestError as exc:
            # Model families disagree on a few parameters (older models want
            # `max_tokens`, some reject `temperature` or `response_format`).
            # Retry once with the parameter the API complained about adjusted.
            message = str(exc)
            if "max_completion_tokens" in message:
                params["max_tokens"] = params.pop("max_completion_tokens")
            elif "temperature" in message:
                params.pop("temperature", None)
            elif "response_format" in message:
                params.pop("response_format", None)
            else:
                raise
            response = self.client.chat.completions.create(**params)

        return (response.choices[0].message.content or "").strip()

    @staticmethod
    def _with_context(prompt: str, context: Optional[str]) -> str:
        if not context:
            return prompt
        return (
            f"Context information:\n{context}\n\n"
            f"Request:\n{prompt}\n\n"
            "Write the content using the context above."
        )

    def generate_content(self, prompt: str, context: Optional[str] = None) -> str:
        return self._chat(SYSTEM_PROMPT, self._with_context(prompt, context))

    def generate_placeholder_values(
        self,
        prompt: str,
        placeholders: List[str],
        context: Optional[str] = None,
        known_values: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        """Return a value for every placeholder, as structured JSON output."""
        known = {k: v for k, v in (known_values or {}).items() if v and k in placeholders}
        todo = [p for p in placeholders if p not in known]
        if not todo:
            return {p: known[p] for p in placeholders}

        parts = [self._with_context(prompt, context)]
        if known:
            parts.append(
                "Already decided values (stay consistent with them):\n"
                + json.dumps(known, ensure_ascii=False, indent=2)
            )
        parts.append("Placeholders to fill (JSON keys):\n" + json.dumps(todo))
        raw = self._chat(FILL_SYSTEM_PROMPT, "\n\n".join(parts), json_mode=True)

        data = self._parse_json_object(raw)
        values = {}
        for name in placeholders:
            if name in known:
                values[name] = known[name]
            else:
                values[name] = self._to_text(data.get(name, ""))
        return values

    @staticmethod
    def _parse_json_object(raw: str) -> dict:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                raise ValueError("The model did not return JSON for the placeholders.")
            data = json.loads(match.group(0))
        if not isinstance(data, dict):
            raise ValueError("The model did not return a JSON object.")
        return data

    @staticmethod
    def _to_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "\n".join(f"- {LLMService._to_text(v)}" for v in value)
        if isinstance(value, dict):
            return "\n".join(f"{k}: {LLMService._to_text(v)}" for k, v in value.items())
        return str(value)

    # ------------------------------------------------------------ embeddings
    def get_embeddings(
        self, texts: List[str], dimensions: Optional[int] = None
    ) -> List[List[float]]:
        """Embed texts. `dimensions` asks the model for shorter vectors; models
        that do not accept the option return full-length ones."""
        from openai import BadRequestError

        vectors: List[List[float]] = []
        for start in range(0, len(texts), 96):
            batch = texts[start : start + 96]
            params = {"model": settings.openai_embedding_model, "input": batch}
            if dimensions:
                params["dimensions"] = dimensions
            try:
                try:
                    response = self.client.embeddings.create(**params)
                except BadRequestError as exc:
                    if "dimensions" not in params or "dimension" not in str(exc).lower():
                        raise
                    params.pop("dimensions")  # caller shortens the vectors instead
                    response = self.client.embeddings.create(**params)
            except Exception as exc:
                if type(exc).__name__ == "NotFoundError":
                    raise _model_not_found(
                        "OPENAI_EMBEDDING_MODEL", settings.openai_embedding_model
                    ) from exc
                raise
            vectors.extend(item.embedding for item in response.data)
        return vectors

    def get_embedding(self, text: str) -> List[float]:
        return self.get_embeddings([text])[0]

    def list_models(self) -> List[str]:
        return sorted(model.id for model in self.client.models.list())


llm_service = LLMService()
