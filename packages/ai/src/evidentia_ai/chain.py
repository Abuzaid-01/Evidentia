"""Run the provider chain: first provider that returns a valid extraction wins."""

from __future__ import annotations

from dataclasses import dataclass, field

from evidentia_ai.prompts import AnalysisContext
from evidentia_ai.providers.base import (
    ImageInput,
    ProviderPermanentError,
    ProviderResult,
    ProviderRetryableError,
    VisionProvider,
)


@dataclass
class ProviderAttempt:
    provider: str
    model: str
    error: str
    retryable: bool


@dataclass
class ChainOutcome:
    result: ProviderResult | None
    attempts: list[ProviderAttempt] = field(default_factory=list)

    @property
    def only_transient_failures(self) -> bool:
        """True when every failure was transient: worth retrying the whole step later."""
        return bool(self.attempts) and all(a.retryable for a in self.attempts)


def run_chain(
    providers: list[VisionProvider], image: ImageInput, ctx: AnalysisContext, prompt: str
) -> ChainOutcome:
    outcome = ChainOutcome(result=None)
    for provider in providers:
        try:
            outcome.result = provider.extract(image, ctx, prompt)
            return outcome
        except ProviderRetryableError as exc:
            outcome.attempts.append(ProviderAttempt(provider.name, provider.model, str(exc), True))
        except ProviderPermanentError as exc:
            outcome.attempts.append(ProviderAttempt(provider.name, provider.model, str(exc), False))
    return outcome
