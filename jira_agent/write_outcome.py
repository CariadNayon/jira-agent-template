"""Observe Jira mutation attempts within one tool call, without recording request data."""
from contextlib import contextmanager
from contextvars import ContextVar


class InputValidationError(ValueError):
    """Validation rejected an operation before issuing its external mutation."""


_writes: ContextVar[list[str] | None] = ContextVar('jira_write_outcomes', default=None)


@contextmanager
def observe_writes():
    outcomes: list[str] = []
    token = _writes.set(outcomes)
    try:
        yield outcomes
    finally:
        _writes.reset(token)


def begin_write(method: str):
    outcomes = _writes.get()
    if outcomes is None or method.upper() in ('GET', 'HEAD', 'OPTIONS'):
        return None
    outcomes.append('unknown')
    return outcomes, len(outcomes) - 1


def finish_write(attempt, *, rejected: bool):
    if attempt is not None:
        outcomes, index = attempt
        outcomes[index] = 'rejected' if rejected else 'may_have_applied'
