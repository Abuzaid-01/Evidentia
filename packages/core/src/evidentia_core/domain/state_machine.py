"""Asset lifecycle state machine.

The pipeline is resumable: every step checks the current state, does its work, and advances the
state. A retried worker therefore continues from the last completed step instead of redoing work.
"""

from __future__ import annotations

from evidentia_core.domain.enums import AssetState as S

PIPELINE_ORDER: tuple[S, ...] = (
    S.UPLOADED,
    S.REGISTERED,
    S.METADATA_READY,
    S.DEDUP_CHECKED,
    S.ANALYZING,
    S.INDEXED,
)
TERMINAL_OK: frozenset[S] = frozenset({S.REVIEW_REQUIRED, S.READY})
FAILURES: frozenset[S] = frozenset({S.FAILED_RETRYABLE, S.FAILED_PERMANENT})

_TRANSITIONS: dict[S, frozenset[S]] = {
    S.AWAITING_UPLOAD: frozenset({S.UPLOADED, S.EXPIRED}),
    S.UPLOADED: frozenset({S.REGISTERED}),
    S.REGISTERED: frozenset({S.METADATA_READY}),
    S.METADATA_READY: frozenset({S.DEDUP_CHECKED}),
    S.DEDUP_CHECKED: frozenset({S.ANALYZING}),
    S.ANALYZING: frozenset({S.INDEXED}),
    S.INDEXED: frozenset({S.REVIEW_REQUIRED, S.READY}),
    # re-analysis restarts enrichment; review decisions can move between the two end states
    S.REVIEW_REQUIRED: frozenset({S.READY, S.DEDUP_CHECKED}),
    S.READY: frozenset({S.REVIEW_REQUIRED, S.DEDUP_CHECKED}),
    S.EXPIRED: frozenset(),
    # a retryable failure resumes at whichever pipeline step it failed in
    S.FAILED_RETRYABLE: frozenset(PIPELINE_ORDER),
    # permanent failures can only be restarted deliberately (manual re-analysis)
    S.FAILED_PERMANENT: frozenset({S.DEDUP_CHECKED}),
}

# Only in-flight states can fail. Finished assets never "fail"; they get re-analysed instead.
_CAN_FAIL: frozenset[S] = frozenset(PIPELINE_ORDER) | {S.FAILED_RETRYABLE}


class InvalidTransition(ValueError):
    def __init__(self, current: S, target: S) -> None:
        super().__init__(f"asset cannot move from {current.value} to {target.value}")
        self.current = current
        self.target = target


def can_transition(current: S, target: S) -> bool:
    if target == S.FAILED_RETRYABLE:
        return current in _CAN_FAIL
    if target == S.FAILED_PERMANENT:
        return current in _CAN_FAIL or current == S.AWAITING_UPLOAD
    return target in _TRANSITIONS.get(current, frozenset())


def assert_transition(current: S, target: S) -> None:
    if not can_transition(current, target):
        raise InvalidTransition(current, target)


def is_processing(state: S) -> bool:
    return state in PIPELINE_ORDER or state == S.FAILED_RETRYABLE
