"""Per-request provider metadata. Context propagation prevents cross-patient leakage."""
from contextlib import contextmanager
from contextvars import ContextVar
import time

_events = ContextVar('medflow_provider_events', default=None)
_listener = ContextVar('medflow_provider_listener', default=None)
_deadline = ContextVar('medflow_provider_deadline', default=None)


@contextmanager
def collect_provider_events(on_event=None, timeout_seconds=90):
    events = []
    token = _events.set(events)
    listener_token = _listener.set(on_event)
    previous = _deadline.get()
    deadline = time.perf_counter() + timeout_seconds
    deadline_token = _deadline.set(min(previous, deadline) if previous else deadline)
    try:
        yield events
    finally:
        _events.reset(token)
        _listener.reset(listener_token)
        _deadline.reset(deadline_token)


def remaining_budget(timeout_seconds):
    deadline = _deadline.get()
    return min(timeout_seconds, deadline-time.perf_counter()) if deadline else timeout_seconds


def provider_event(task, provider, model, status, fallback=False, duration_ms=None):
    event = {'task':task,'provider':provider,'model':model,'status':status,'fallback':fallback}
    if duration_ms is not None:
        event['duration_ms'] = max(0, round(duration_ms, 2))
    events = _events.get()
    if events is not None and status != 'running':
        events.append(event)
    listener = _listener.get()
    if listener:
        # Observability must never invalidate a clinical result on disconnect.
        try:
            listener(event, list(events or []))
        except Exception:
            pass
