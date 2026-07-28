import json
import logging
from copy import deepcopy
from time import perf_counter
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.ai.providers import EmbeddingResult, ProviderResult

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("daily_reading.ai")


class ProviderAPIError(RuntimeError):
    pass


class StructuredOutputError(ProviderAPIError):
    def __init__(
        self,
        *,
        model: str,
        output_model: str,
        validation_error: str,
        response_preview: str,
    ) -> None:
        self.model = model
        self.output_model = output_model
        self.validation_error = validation_error
        self.response_preview = response_preview
        super().__init__(
            f"Invalid {output_model} structured output from {model}: "
            f"{validation_error}"
        )


def _inline_json_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline local $defs references for providers with incomplete $ref support."""
    copied = deepcopy(schema)
    definitions = copied.pop("$defs", {})

    def resolve(value: Any) -> Any:
        if isinstance(value, list):
            return [resolve(item) for item in value]
        if not isinstance(value, dict):
            return value
        reference = value.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            name = reference.removeprefix("#/$defs/")
            target = definitions.get(name)
            if isinstance(target, dict):
                extras = {key: item for key, item in value.items() if key != "$ref"}
                return resolve({**deepcopy(target), **extras})
        return {key: resolve(item) for key, item in value.items()}

    return resolve(copied)


def _usage(payload: dict[str, object]) -> tuple[int | None, int | None]:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None, None
    input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    return (
        int(input_tokens) if isinstance(input_tokens, int | float) else None,
        int(output_tokens) if isinstance(output_tokens, int | float) else None,
    )


class OpenAICompatibleClient:
    def __init__(self, *, api_key: str, base_url: str, timeout_seconds: float) -> None:
        if not api_key:
            raise ValueError("Provider API key is missing")
        if not base_url:
            raise ValueError("Provider base URL is missing")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)

    def _post(self, path: str, payload: dict[str, object]) -> tuple[dict[str, object], float]:
        started = perf_counter()
        model = str(payload.get("model") or "n/a")
        logger.info("ai_call stage=request_start endpoint=%s model=%s", path, model)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ProviderAPIError("Provider returned a non-object response")
            elapsed_ms = (perf_counter() - started) * 1000
            logger.info(
                "ai_call stage=request_complete status=ok endpoint=%s model=%s "
                "elapsed_ms=%.2f request_id=%s",
                path,
                model,
                elapsed_ms,
                data.get("id"),
            )
            return data, elapsed_ms
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "ai_call stage=request_complete status=error endpoint=%s model=%s "
                "elapsed_ms=%.2f error=%s",
                path,
                model,
                (perf_counter() - started) * 1000,
                exc,
            )
            raise ProviderAPIError(f"Provider request failed: {exc}") from exc

    def structured_chat(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        output_model: type[T],
        max_tokens: int,
        thinking: bool,
        strict_schema: bool,
    ) -> ProviderResult[T]:
        schema = _inline_json_schema_refs(output_model.model_json_schema())
        response_format: dict[str, object]
        if strict_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": output_model.__name__.casefold(),
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
            user_prompt += "\nReturn JSON matching this schema exactly:\n" + json.dumps(schema)
        payload: dict[str, object] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": response_format,
            "max_tokens": max_tokens,
            "stream": False,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        data, elapsed_ms = self._post("chat/completions", payload)
        content = ""
        try:
            choices = data["choices"]
            content = choices[0]["message"]["content"]  # type: ignore[index]
            if not isinstance(content, str):
                raise TypeError("message content is not a string")
            value = output_model.model_validate_json(content)
        except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
            if isinstance(exc, ValidationError):
                validation_error = json.dumps(
                    exc.errors(include_url=False, include_input=False),
                    ensure_ascii=False,
                    default=str,
                )[:4000]
            else:
                validation_error = f"{type(exc).__name__}: {exc}"
            preview = " ".join(str(content).split())[:1500]
            logger.warning(
                "ai_call stage=structured_validation status=error model=%s "
                "output_model=%s validation_error=%s response_preview=%s",
                model,
                output_model.__name__,
                validation_error,
                preview,
            )
            raise StructuredOutputError(
                model=model,
                output_model=output_model.__name__,
                validation_error=validation_error,
                response_preview=preview,
            ) from exc
        input_tokens, output_tokens = _usage(data)
        request_id = data.get("id")
        logger.info(
            "ai_call stage=structured_validation status=ok model=%s output_model=%s "
            "input_tokens=%s output_tokens=%s",
            model,
            output_model.__name__,
            input_tokens,
            output_tokens,
        )
        return ProviderResult(
            value=value,
            request_id=str(request_id) if request_id else None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=elapsed_ms,
        )

    def embeddings(
        self, *, model: str, texts: list[str], dimensions: int
    ) -> EmbeddingResult:
        data, elapsed_ms = self._post(
            "embeddings",
            {"model": model, "input": texts, "dimensions": dimensions},
        )
        try:
            rows = sorted(data["data"], key=lambda row: row["index"])  # type: ignore[arg-type,index]
            vectors = [[float(value) for value in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderAPIError("Provider returned invalid embedding output") from exc
        if len(vectors) != len(texts) or any(len(vector) != dimensions for vector in vectors):
            raise ProviderAPIError("Embedding response has unexpected dimensions")
        input_tokens, _output_tokens = _usage(data)
        request_id = data.get("id")
        return EmbeddingResult(
            vectors=vectors,
            request_id=str(request_id) if request_id else None,
            input_tokens=input_tokens,
            elapsed_ms=elapsed_ms,
        )
