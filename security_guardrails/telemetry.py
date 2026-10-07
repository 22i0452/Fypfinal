"""Per-request provider metadata. Context propagation prevents cross-patient leakage."""
from contextlib import contextmanager
from contextvars import ContextVar

_events = ContextVar('medflow_provider_events', default=None)


@contextmanager
def collect_provider_events():
    events = []
    token = _events.set(events)
    try:
        yield events
    finally:
        _events.reset(token)


def provider_event(task, provider, model, status, fallback=False):
    events = _events.get()
    if events is not None:
        events.append({'task':task,'provider':provider,'model':model,'status':status,'fallback':fallback})
