from __future__ import annotations

import uuid

from evidentia_core.domain.enums import SearchFeedbackAction
from evidentia_core.domain.search_plan import SearchFilters, SearchPlan
from pydantic import Field

from evidentia_api.schemas.assets import AssetSummary
from evidentia_api.schemas.common import ApiModel


class SearchRequest(ApiModel):
    project_id: uuid.UUID
    query: str = Field(default="", max_length=500)
    # Explicit filters (from UI controls) are merged with, and win over, filters parsed from text.
    filters: SearchFilters | None = None
    limit: int = Field(default=24, ge=1, le=100)
    use_llm_planner: bool = True


class MatchedObservation(ApiModel):
    id: uuid.UUID
    ontology_type: str
    subject: str
    predicate: str
    confidence: float | None
    status: str


class VideoSpan(ApiModel):
    start_ms: int
    end_ms: int
    label: str


class SearchResult(ApiModel):
    asset: AssetSummary
    score: float
    reasons: list[str]
    contributions: dict[str, dict[str, object]]
    matched_observations: list[MatchedObservation]
    video_span: VideoSpan | None = None
    missing_terms: list[str] = Field(
        default_factory=list, description="Query words this asset's description does not contain"
    )


class SearchResponse(ApiModel):
    query_id: uuid.UUID
    plan: SearchPlan
    results: list[SearchResult]
    retrievers: dict[str, dict[str, object]]
    took_ms: int
    query_terms: list[str] = Field(default_factory=list, description="Content words of the query")
    complete_matches: int = Field(0, description="Results that contain every query word")


class SimilarRequest(ApiModel):
    asset_id: uuid.UUID
    limit: int = Field(default=12, ge=1, le=50)
    same_project: bool = True


class SimilarResult(ApiModel):
    asset: AssetSummary
    similarity: float


class FeedbackRequest(ApiModel):
    asset_id: uuid.UUID
    action: SearchFeedbackAction
    rank: int | None = None
