from app.ai.client import OpenAICompatibleClient
from app.ai.direct_providers import (
    DeepSeekClaimProvider,
    DeepSeekClassificationProvider,
    DeepSeekEvidenceProvider,
    KimiEvidenceProvider,
    QwenEmbeddingProvider,
)
from app.ai.providers import ModelProviders
from app.config import Settings


def build_model_providers(settings: Settings) -> ModelProviders:
    if settings.embedding_dimensions != 1024:
        raise ValueError(
            "This Phase 5 migration uses vector(1024); set EMBEDDING_DIMENSIONS=1024"
        )
    qwen_key = settings.dashscope_api_key
    deepseek_key = settings.deepseek_api_key
    if qwen_key is None or deepseek_key is None:
        raise ValueError("Qwen and DeepSeek API keys are required for Phase 5")
    qwen_client = OpenAICompatibleClient(
        api_key=qwen_key.get_secret_value(),
        base_url=settings.qwen_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    deepseek_client = OpenAICompatibleClient(
        api_key=deepseek_key.get_secret_value(),
        base_url=settings.deepseek_base_url,
        timeout_seconds=settings.http_timeout_seconds,
    )
    evidence_provider_name = settings.evidence_comparison_provider.casefold()
    if evidence_provider_name == "deepseek":
        evidence_provider = DeepSeekEvidenceProvider(
            deepseek_client,
            model=settings.evidence_comparison_model,
            max_tokens=settings.evidence_comparison_max_output_tokens,
            thinking=settings.evidence_comparison_thinking,
        )
    elif evidence_provider_name == "kimi":
        kimi_key = settings.moonshot_api_key
        if kimi_key is None:
            raise ValueError("MOONSHOT_API_KEY is required when evidence uses Kimi")
        kimi_client = OpenAICompatibleClient(
            api_key=kimi_key.get_secret_value(),
            base_url=settings.kimi_base_url,
            timeout_seconds=max(settings.http_timeout_seconds, 120),
        )
        evidence_provider = KimiEvidenceProvider(
            kimi_client,
            model=settings.evidence_comparison_model,
            max_tokens=settings.evidence_comparison_max_output_tokens,
            thinking=settings.evidence_comparison_thinking,
        )
    else:
        raise ValueError(
            "EVIDENCE_COMPARISON_PROVIDER must be 'deepseek' or 'kimi'"
        )
    return ModelProviders(
        classification=DeepSeekClassificationProvider(
            deepseek_client,
            model=settings.classification_model,
            max_tokens=settings.classification_max_output_tokens,
            thinking=settings.classification_thinking,
        ),
        embedding=QwenEmbeddingProvider(
            qwen_client,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        ),
        claim_extraction=DeepSeekClaimProvider(
            deepseek_client,
            model=settings.claim_extraction_model,
            max_tokens=settings.claim_extraction_max_output_tokens,
            thinking=settings.claim_extraction_thinking,
        ),
        evidence_comparison=evidence_provider,
    )
