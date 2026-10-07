"""Record observed BookingFlow transitions without changing its decisions."""
from copy import deepcopy
from app.services.evidence_checks import check


def record_transition(flow, before, extraction):
    raw = flow._caller_text[:800]
    source_id = f"R{flow.evidence_turn:04d}"
    method = extraction.get("_process_metadata") or {}
    current = {**flow.prefill, **flow.values}
    if flow.pending:
        current[flow.pending["key"]] = {key: value for key, value in flow.pending.items() if key != "key"}
    for key, value in current.items():
        previous = before["values"].get(key) or before["prefill"].get(key)
        if before["pending"] and before["pending"].get("key") == key:
            previous = {k: v for k, v in before["pending"].items() if k != "key"}
        changed = previous != value
        old = flow.field_evidence.get(key)
        if changed:
            # Early collected fields keep their original turn when promoted from prefill.
            if not old or old.get("interpretation", {}).get("en") != value.get("en"):
                revisions = (old.get("revisions", []) + [{"raw": old.get("raw", "")[:280], "interpretation": old.get("interpretation"), "source_turn_id": old.get("source_turn_id")}])[-2:] if old else []
                rule = {"name": "Name text format", "age": "Age range (1–120)", "phone": "Phone digit format", "department": "Known department", "time": "Day and time resolved", "first_visit": "Visit answer normalized"}.get(key, "Text collected")
                detail = {"name": "Text accepted; patient identity is not verified here.", "age": "A numeric age within the supported range was accepted.", "phone": "Digit length/prefix rules passed; ownership has not been verified.", "department": "An alias matched a configured booking department.", "time": "An exact requested day and clock time were resolved. Availability is checked on save."}.get(key, "BookingFlow accepted this value. No clinical truth check was performed.")
                flow.field_evidence[key] = {"field": key, "raw": raw, "interpretation": deepcopy(value), "source_turn_id": source_id,
                    "method": method, "checks": [check("field_rule", rule, "passed", detail)], "revisions": revisions,
                    "confirmation": None}
                old = flow.field_evidence[key]
        if not old:
            continue  # Older states have no observed source provenance; never backfill a claim.
        if key in flow.values and before["pending"] and before["pending"].get("key") == key and not changed:
            old["confirmation"] = {"type": "readback", "source_turn_id": source_id, "raw": raw}
        if flow.done and not before["done"]:
            old["confirmation"] = {"type": "final_summary", "source_turn_id": source_id, "raw": raw}
        old["status"] = "checked" if old.get("confirmation") else "review" if flow.pending and flow.pending.get("key") == key else "received"
        old["label"] = "Patient confirmed" if old.get("confirmation") else "Awaiting confirmation" if old["status"] == "review" else "Collected"
    # Remove stale evidence if a correction explicitly removed a field.
    flow.field_evidence = {key: value for key, value in flow.field_evidence.items() if key in current}
    flow.last_answer = {"source_turn_id": source_id, "raw": raw, "status": "received", "method": method,
                        "checks": [check("turn_processed", "Booking turn processed", "passed", "This answer was processed by the state machine; only accepted values advance.")]}
    for key, outcome in flow._field_outcomes.items():
        if not isinstance(outcome, dict):
            flow.last_answer["status"] = "review"
            flow.last_answer["checks"].append(check("field_rule", f"{key.replace('_', ' ').title()} input", "failed", str(outcome or "Value could not be normalized.")))


def before_transition(flow):
    return deepcopy({"values": flow.values, "prefill": flow.prefill, "pending": flow.pending, "done": flow.done})
