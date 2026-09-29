"""Cloudinary AI Vision (Analyze API `ai_vision_general`) as a structured-extraction provider.

The image never leaves Cloudinary: we pass the signed URL of the `ev_ai` rendition as the source.
The JSON schema is fenced into the prompt, which is Cloudinary's documented structured-output format.
"""

from __future__ import annotations

from evidentia_cloudinary.analyze import (
    AnalyzeClient,
    general_responses,
    source_uri,
    structured_prompt,
)
from evidentia_cloudinary.errors import CloudinaryPermanentError, CloudinaryRetryableError

from evidentia_ai.parsing import ExtractionInvalid, parse_extraction
from evidentia_ai.prompts import AnalysisContext, extraction_instruction
from evidentia_ai.providers.base import (
    ImageInput,
    ProviderPermanentError,
    ProviderResult,
    ProviderRetryableError,
)
from evidentia_ai.schemas import json_schema


class CloudinaryVisionProvider:
    name = "cloudinary"
    model = "ai_vision_general"

    def __init__(self, client: AnalyzeClient) -> None:
        self._client = client

    def extract(self, image: ImageInput, ctx: AnalysisContext, prompt: str) -> ProviderResult:
        if not image.cloudinary_url:
            raise ProviderPermanentError("cloudinary: no Cloudinary source URL for this image")
        cld_prompt = structured_prompt(extraction_instruction(ctx), json_schema())
        try:
            result = self._client.ai_vision_general(source_uri(image.cloudinary_url), [cld_prompt])
        except CloudinaryRetryableError as exc:
            raise ProviderRetryableError(str(exc)) from exc
        except CloudinaryPermanentError as exc:
            raise ProviderPermanentError(str(exc)) from exc

        responses = general_responses(result)
        if not responses or not responses[0]:
            raise ProviderPermanentError("cloudinary: empty ai_vision_general response")
        try:
            extraction = parse_extraction(responses[0], {a.key for a in ctx.activities})
        except ExtractionInvalid as exc:
            raise ProviderPermanentError(f"cloudinary: {exc}") from exc
        return ProviderResult(
            extraction=extraction,
            provider=self.name,
            model=self.model,
            model_version=result.model_version,
            raw={"value": responses[0], "request_id": result.request_id},
            latency_ms=result.latency_ms,
            usage={"quota": result.quota},
        )
