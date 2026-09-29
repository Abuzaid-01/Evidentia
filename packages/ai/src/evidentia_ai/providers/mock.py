"""Deterministic provider for tests and offline development.

Only used when AI_VISION_PROVIDERS explicitly includes "mock". Its observations are labelled with
provider "mock" everywhere, so fake output can never pass as real evidence.
"""

from __future__ import annotations

import hashlib

from evidentia_ai.prompts import AnalysisContext
from evidentia_ai.providers.base import ImageInput, ProviderResult
from evidentia_ai.schemas import (
    ActivityCandidate,
    ConditionFinding,
    ObjectFinding,
    VisionExtraction,
)


class MockVisionProvider:
    name = "mock"
    model = "mock-vision-1"

    def extract(self, image: ImageInput, ctx: AnalysisContext, prompt: str) -> ProviderResult:
        digest = hashlib.sha256(image.data).digest()
        keys = [a.key for a in ctx.activities]
        activity = (
            ctx.declared_activity if ctx.declared_activity in keys else keys[digest[0] % len(keys)]
        )
        confidence = round(0.55 + (digest[1] / 255) * 0.4, 3)
        extraction = VisionExtraction(
            caption=f"[mock] Field {ctx.media_kind} that appears to show {activity.replace('_', ' ')}.",
            scene_type="construction_site",
            activities=[
                ActivityCandidate(
                    activity=activity,
                    confidence=confidence,
                    rationale="[mock] deterministic output",
                )
            ],
            objects=[ObjectFinding(name="structure", count=1, confidence=0.7)],
            conditions=[ConditionFinding(subject="structure", condition="visible", confidence=0.7)],
            people_present=bool(digest[2] % 2),
            uncertainty=["[mock] no real model was used"],
        )
        return ProviderResult(
            extraction=extraction,
            provider=self.name,
            model=self.model,
            model_version="1",
            raw={"mock": True},
            latency_ms=1,
        )
