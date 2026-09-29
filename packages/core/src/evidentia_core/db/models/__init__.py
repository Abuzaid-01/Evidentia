from evidentia_core.db.models.assets import Asset, Derivative
from evidentia_core.db.models.audit import AuditEvent
from evidentia_core.db.models.campaigns import Campaign, ShareLink
from evidentia_core.db.models.claims import (
    ActivityEvent,
    Claim,
    ClaimMetric,
    EvidenceLink,
    Metric,
    ObservationReview,
)
from evidentia_core.db.models.comparisons import BeforeAfterPair
from evidentia_core.db.models.evidence import Observation
from evidentia_core.db.models.pipeline import AnalysisRun, Job, WebhookEvent
from evidentia_core.db.models.projects import Project, Site, Taxonomy
from evidentia_core.db.models.reports import Report, ReportSnapshot
from evidentia_core.db.models.search import Embedding, SearchFeedback, SearchQuery
from evidentia_core.db.models.tenancy import Membership, Organization, User

__all__ = [
    "ActivityEvent",
    "AnalysisRun",
    "Asset",
    "AuditEvent",
    "BeforeAfterPair",
    "Campaign",
    "Claim",
    "ClaimMetric",
    "Derivative",
    "Embedding",
    "EvidenceLink",
    "Job",
    "Membership",
    "Metric",
    "Observation",
    "ObservationReview",
    "Organization",
    "Project",
    "Report",
    "ReportSnapshot",
    "SearchFeedback",
    "SearchQuery",
    "ShareLink",
    "Site",
    "Taxonomy",
    "User",
    "WebhookEvent",
]

# Tables protected by row-level security (organization_id = current tenant).
TENANT_TABLES: tuple[str, ...] = (
    "projects",
    "sites",
    "taxonomies",
    "assets",
    "derivatives",
    "jobs",
    "analysis_runs",
    "observations",
    "audit_events",
    "embeddings",
    "search_queries",
    "search_feedback",
    "observation_reviews",
    "metrics",
    "claims",
    "claim_metrics",
    "activity_events",
    "evidence_links",
    "reports",
    "report_snapshots",
    "before_after_pairs",
    "campaigns",
    "share_links",
)
