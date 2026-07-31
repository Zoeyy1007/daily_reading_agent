import json

from app.ai.client import OpenAICompatibleClient
from app.ai.providers import EmbeddingResult, ProviderResult
from app.ai.schemas import (
    ClaimExtractionResult,
    ClassificationResult,
    EvidenceComparisonResult,
    EvidencePairInput,
    SupplementDraft,
    SupplementPlan,
    SupplementVerification,
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
                "Classify a reading article using only the supplied text. content_type MUST "
                "be exactly one of these five lowercase values: news, analysis, opinion, "
                "tutorial, other. Apply them in this decision order: tutorial for primarily "
                "instructional step-by-step content; opinion for primarily argumentative or "
                "editorial content; analysis for interpretation or explanation beyond direct "
                "reporting; news for factual reporting about events or developments; other "
                "ONLY when none of the previous four categories applies. Subject areas such "
                "as politics, technology, crime, business, science, and health belong in the "
                "topics array and MUST NOT be used as content_type. Return concise JSON "
                "matching the required schema and no commentary."
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


class DeepSeekSupplementProvider:
    provider_name = "deepseek"

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

    def plan(
        self,
        *,
        article_title: str,
        article_content: str,
        cluster_event: str | None,
        evidence: list[dict[str, object]],
        tool_history: list[dict[str, object]],
        available_tools: list[dict[str, object]],
        coverage_targets: dict[str, dict[str, object]],
    ) -> ProviderResult[SupplementPlan]:
        payload = {
            "article_title": article_title,
            "article_content": article_content[:24000],
            "cluster_event": cluster_event,
            "saved_evidence": evidence,
            "tool_history": tool_history,
            "available_tools": available_tools,
            "coverage_targets": coverage_targets,
        }
        return self.client.structured_chat(
            model=self.model,
            system_prompt=(
                "You are a bounded research planner. First assess exactly four coverage areas: "
                "earlier events/timeline, affected people/effects, missing information from "
                "other reporting, and disagreement/uncertainty. Do not assess official basis or "
                "latest developments as separate gaps. Return strict structured output. If no "
                "supplement is needed, set supplement_needed=false and next_step=stop. For a "
                "coverage decision, evidence_ids may contain at most three distinct IDs from "
                "saved_evidence that directly address that area. Treat coverage_targets as the "
                "application-owned research ledger: do not search areas marked satisfied or "
                "max_target_reached, and focus queries on areas marked search_needed. A single "
                "strong source may satisfy an area before it reaches three items. For a "
                "tool step, return exactly two calls: one available search tool followed by "
                "collect_chunk whose source_call_id references the search call. Prefer "
                "search_local before external search. Search arguments are a structured research "
                "request, not a free-form query: purpose must be one currently search-needed "
                "coverage area; event must identify the concrete event in this article; entities "
                "and keywords must be derived from this article and that gap. Use null dates when "
                "a date boundary is not justified. preferred_domains may only narrow the domains "
                "shown by the selected tool and must be empty for search_local. Request only the "
                "number of results reasonably needed. Every search argument field is mandatory. "
                "After tool results, choose another tool step, compose, or stop. You are not a "
                "factual source and must never provide missing facts yourself."
            ),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_model=SupplementPlan,
            max_tokens=min(self.max_tokens, 2500),
            thinking=self.thinking,
            strict_schema=False,
        )

    def compose(
        self,
        *,
        article_title: str,
        gaps: list[str],
        evidence: list[dict[str, object]],
        word_budget: int,
    ) -> ProviderResult[SupplementDraft]:
        payload = {
            "article_title": article_title,
            "gaps": gaps,
            "word_budget": word_budget,
            "evidence": evidence,
        }
        return self.client.structured_chat(
            model=self.model,
            system_prompt=(
                "Write concise supplemental cards using only the supplied evidence excerpts. "
                "Every statement must cite one or more evidence_ids that directly support the "
                "entire statement. Do not add general knowledge, causal speculation, or bridge "
                "facts. Consequences are allowed only when an excerpt explicitly attributes "
                "that prediction or analysis; preserve that attribution. Stay within the total "
                "word budget. Return no cards when the evidence is insufficient."
            ),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_model=SupplementDraft,
            max_tokens=self.max_tokens,
            thinking=self.thinking,
            strict_schema=False,
        )

    def verify(
        self,
        *,
        draft: SupplementDraft,
        evidence: list[dict[str, object]],
        validation_feedback: str | None = None,
    ) -> ProviderResult[SupplementVerification]:
        payload = {
            "draft": draft.model_dump(),
            "evidence": evidence,
            "previous_validation_error": validation_feedback,
        }
        return self.client.structured_chat(
            model=self.model,
            system_prompt=(
                "Act as a strict citation verifier. Mark a statement supported only when its "
                "cited excerpts directly support every factual part of it. Reject added causal "
                "claims, unattributed predictions, synthesis not stated by a source, invalid "
                "evidence IDs, and partial support. Return exactly one entry for every draft "
                "statement using its zero-based card_index and statement_index. Every requested "
                "field is mandatory and must use the exact JSON data type in the schema. A "
                "supported statement requires one or more valid evidence_ids; an unsupported "
                "statement must use an empty evidence_ids array. If a previous validation error "
                "is supplied, correct it in the new response."
            ),
            user_prompt=json.dumps(payload, ensure_ascii=False),
            output_model=SupplementVerification,
            max_tokens=self.max_tokens,
            thinking=self.thinking,
            strict_schema=False,
        )
