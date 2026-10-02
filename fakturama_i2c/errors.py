"""Exceptions that stop the flow. All of them fail closed: nothing is retried blindly."""

from __future__ import annotations


class AutomationError(Exception):
    """Base class for every error raised by this package."""


class ExtractionError(AutomationError):
    """The source image could not be turned into a trustworthy OrderExtraction."""

    def __init__(self, message: str, issues: list[str] | None = None):
        self.issues = issues or []
        detail = "\n  - ".join([message, *self.issues])
        super().__init__(detail)


class ManualReviewRequired(AutomationError):
    """The PDF says 'stop for manual review' - ambiguous match, conflicting master data, etc."""

    def __init__(self, step: str, reason: str, evidence: dict | None = None):
        self.step = step
        self.reason = reason
        self.evidence = evidence or {}
        super().__init__(f"[{step}] manual review required: {reason}")


class VerificationFailed(AutomationError):
    """An action was performed but reading the UI back did not show the expected value."""

    def __init__(self, step: str, what: str, expected: object, actual: object):
        self.step = step
        self.what = what
        self.expected = expected
        self.actual = actual
        super().__init__(f"[{step}] {what}: expected {expected!r}, got {actual!r}")


class ControlNotFound(AutomationError):
    """A UI control could not be located within the timeout."""


class FollowUpExists(ManualReviewRequired):
    """Fakturama reports the Order already has a follow-up Invoice; we answered 'No'."""

    def __init__(self, number: str, message: str):
        self.number = number
        super().__init__("4.6", f"the Order already has a follow-up Invoice {number}", {"fakturama": message})
