"""Domain enumerations. Stored as strings in Postgres (non-native enums) so they are easy to evolve."""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"
    REVIEWER = "reviewer"
    MANAGER = "manager"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def at_least(self, other: Role) -> bool:
        return self.rank >= other.rank


_ROLE_RANK = {
    Role.VIEWER: 0,
    Role.CONTRIBUTOR: 1,
    Role.REVIEWER: 2,
    Role.MANAGER: 3,
    Role.ADMIN: 4,
}


class ResourceType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"


class AssetState(StrEnum):
    AWAITING_UPLOAD = "awaiting_upload"  # upload signed, bytes not yet at Cloudinary
    UPLOADED = "uploaded"  # Cloudinary confirmed storage (confirm call or webhook)
    REGISTERED = "registered"  # registry filled from Cloudinary Admin API
    METADATA_READY = "metadata_ready"  # EXIF/provenance + SHA-256 extracted
    DEDUP_CHECKED = "dedup_checked"  # exact + perceptual duplicate check done
    ANALYZING = "analyzing"  # AI enrichment running
    INDEXED = "indexed"  # observations persisted (+ embeddings from Phase 3)
    REVIEW_REQUIRED = "review_required"  # needs human attention
    READY = "ready"  # searchable, nothing urgent to review
    EXPIRED = "expired"  # upload intent never completed
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_PERMANENT = "failed_permanent"


class ProvenanceSource(StrEnum):
    EXIF = "exif"
    DEVICE = "device"
    USER = "user"
    UPLOAD = "upload"
    SITE = "site"
    NONE = "none"


class OntologyType(StrEnum):
    SCENE = "scene"
    ACTIVITY = "activity"
    OBJECT = "object"
    CONDITION = "condition"
    PEOPLE = "people"
    DOCUMENT_TEXT = "document_text"
    QUALITY = "quality"
    SENSITIVE = "sensitive"


class ObservationStatus(StrEnum):
    PROPOSED = "proposed"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class SourceKind(StrEnum):
    AI = "ai"
    HUMAN = "human"
    SYSTEM = "system"


class AnalysisTask(StrEnum):
    CAPTION = "caption"
    QUALITY = "quality"
    TAGGING = "tagging"
    VISION_EXTRACT = "vision_extract"
    OCR = "ocr"
    AUTO_TAGGING = "auto_tagging"
    VIDEO_VISUAL = "video_visual"  # Cloudinary AI Video Analysis segments
    SPEECH = "speech"  # Cloudinary auto-transcription segments


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED_RETRYABLE = "failed_retryable"
    DEAD = "dead"


class ActorKind(StrEnum):
    USER = "user"
    SYSTEM = "system"
    WEBHOOK = "webhook"


# --- Phase 3: search -------------------------------------------------------------------------


class EmbeddingKind(StrEnum):
    IMAGE = "image"  # visual embedding of the model-input rendition (text->image, image->image)
    TEXT = "text"  # embedding of the asset's search document (caption + observations + OCR)
    SEGMENT = "segment"  # one vector per video time span, so search can return that span


class SearchFeedbackAction(StrEnum):
    CLICK = "click"
    ADD_TO_EVIDENCE = "add_to_evidence"
    DISMISS = "dismiss"


# --- Phase 4: verification & evidence graph ------------------------------------------------------


class ReviewDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class ClaimType(StrEnum):
    DESCRIPTIVE = "descriptive"  # what is visibly there ("a tank exists at Site B")
    PROGRESS = "progress"  # visible change over time ("progressed from foundation to structure")
    OUTCOME = "outcome"  # effect on people/environment: needs a measured metric
    METRIC = "metric"  # a number: needs a sourced metric


class ClaimStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    RETRACTED = "retracted"


class SupportLevel(StrEnum):
    UNSUPPORTED = "unsupported"  # rules not met
    PROPOSED = "proposed"  # rules met, not yet validated
    REVIEWED = "reviewed"  # rules met + validation did not reject
    VERIFIED = "verified"  # approved by a reviewer


class ValidationVerdict(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_SUPPORTED = "not_supported"
    NOT_CHECKED = "not_checked"  # no LLM available: only deterministic rules ran


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


class EvidenceTarget(StrEnum):
    CLAIM = "claim"
    EVENT = "event"


class MetricSource(StrEnum):
    FIELD_SURVEY = "field_survey"
    SENSOR = "sensor"
    OPERATIONAL_RECORD = "operational_record"
    THIRD_PARTY = "third_party"
    VISUAL_COUNT = "visual_count"  # counted from verified media: weakest source, still explicit


# --- Phase 5: reports & snapshots -----------------------------------------------------------------


class ReportStatus(StrEnum):
    DRAFT = "draft"  # never published
    PUBLISHED = "published"  # at least one immutable snapshot exists (drafting can continue)


class ReportAudience(StrEnum):
    INTERNAL = "internal"  # full renditions, links back into the app
    EXTERNAL = "external"  # face-redacted renditions only, no app links


class PdfStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"  # Cloudinary not configured: the HTML snapshot is still available


class CitationKind(StrEnum):
    CLAIM = "claim"
    METRIC = "metric"


# --- Phase 7: before/after comparisons ------------------------------------------------------------


class PairStatus(StrEnum):
    CANDIDATE = "candidate"  # proposed by site/time/SigLIP ranking; geometry not checked yet
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"  # geometry + visible change measured; waiting for a human
    FAILED = "failed"  # technical failure (media could not be fetched or decoded)
    CONFIRMED = "confirmed"  # a reviewer confirmed it shows the same place: usable as evidence
    REJECTED = "rejected"


class PairOrigin(StrEnum):
    SUGGESTED = "suggested"
    MANUAL = "manual"
