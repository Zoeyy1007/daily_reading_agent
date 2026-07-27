import json

from app.ai.client import OpenAICompatibleClient
from app.ai.providers import EmbeddingResult, ProviderResult
from app.ai.schemas import (
    ClaimExtractionResult,
    ClassificationResult,
    EvidenceComparisonResult,
    EvidencePairInput,
)


class QwenEmbeddingProvider:
    provider_name = "qwen"

    def __init__(self, client: OpenAICompatibleClient, *, model: str, dimensions: int) -> None:
        self.client = client
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> EmbeddingResult:
        return self.client.embeddings(
            model=self.model, texts=texts, dimensions=self.dimensions
        )


class DeepSeekClassificationProvider:
    provider_name = "deepseek"

    def __init__(self, client: OpenAICompatibleClient, *, model: str, max_tokens: int, thinking: bool) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.thinking = thinking

    def classify(self, *, title: str, content: str) -> ProviderResult[ClassificationResult]:
        return self.client.structured_chat(
            model=self.model,
            system_prompt=(
                "Classify a reading article. Use only information in the supplied text. "
                "Return concise JSON and no commentary."
            ),
            user_prompt=f"Title: {title}\n\nArticle:\n{content[:16000]}",
            output_model=ClassificationResult,
            max_tokens=self.max_tokens,
            thinking=self.thinking,
            strict_schema=False,
        )


class DeepSeekClaimProvider:
    provider_name = "deepseek"

    def __init__(self, client: OpenAICompatibleClient, *, model: str, max_tokens: int, thinking: bool) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.thinking = thinking

    def extract_claims(
        self, *, article_id: int, title: str, content: str
    ) -> ProviderResult[ClaimExtractionResult]:
        return self.client.structured_chat(
            model=self.model,
            system_prompt=(
                "Extract atomic claims from a news article. Every supporting_excerpt must "
                "be copied verbatim from the article. Do not infer missing facts. Return JSON only."
            ),
            user_prompt=f"Article ID: {article_id}\nTitle: {title}\n\nArticle:\n{content[:60000]}",
            output_model=ClaimExtractionResult,
            max_tokens=self.max_tokens,
            thinking=self.thinking,
            strict_schema=False,
        )


class StructuredEvidenceProvider:
    provider_name = ""
    strict_schema = False

    def __init__(
        self,
        client: OpenAICompatibleClient,
        *,
        model: str,
        max_tokens: int,
        thinking: bool,
    ) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens
        self.thinking = thinking

    def compare(
        self,
        *,
        article_titles: dict[int, str],
        pairs: list[EvidencePairInput],
    ) -> ProviderResult[EvidenceComparisonResult]:
        payload = {
            "articles": [
                {"article_id": article_id, "title": title}
                for article_id, title in article_titles.items()
            ],
            "pairs": [pair.model_dump() for pair in pairs],
        }
        return self.client.structured_chat(
            model=self.model,
            system_prompt=(
                "Classify only the supplied cross-source claim pairs. Return one link for every "
                "pair and do not compare claims outside that pair. Return JSON conforming exactly "
                "to the supplied schema. Every item in links must contain exactly left_claim_id, "
                "right_claim_id, relationship, confidence, and rationale. relationship must be "
                "one of equivalent, supports, contradicts, related, unrelated. Copy the numeric "
                "claim IDs from each pair; do not substitute article IDs or claim text. Keep the "
                "batch summary concise."
            ),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_model=EvidenceComparisonResult,
            max_tokens=self.max_tokens,
            thinking=self.thinking,
            strict_schema=self.strict_schema,
        )


class KimiEvidenceProvider(StructuredEvidenceProvider):
    provider_name = "kimi"
    strict_schema = True


class DeepSeekEvidenceProvider(StructuredEvidenceProvider):
    provider_name = "deepseek"
    strict_schema = False
