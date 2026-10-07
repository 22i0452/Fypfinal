# Essential Guardrail Report

PASS: 12
FAIL: 0
TOTAL: 12

| Test | Status | Name |
| --- | --- | --- |
| SEC-01 | PASS | Direct provider bypass |
| SEC-02 | PASS | PHI removed from outbound payload |
| SEC-03 | PASS | Unapproved STT route blocked |
| SEC-04 | PASS | Cross-patient access denied |
| SEC-05 | PASS | Agent tool restriction |
| SEC-06 | PASS | Transcript prompt injection contained |
| SEC-07 | PASS | Malformed SOAP rejected |
| SEC-08 | PASS | Unsupported clinical fact flagged |
| SEC-09 | PASS | Doctor approval required |
| SEC-10 | PASS | Logs contain no PHI/secrets |
| SEC-11 | PASS | Audio cleanup succeeds |
| SEC-12 | PASS | Existing MedFlowAI workflow still works |

All checks use synthetic data and a mock provider. This report does not claim HIPAA compliance or complete security.
Design document: C:\Users\blossom\OneDrive\Documents\New project 2\FYP_Repo\docs\security\essential-guardrails.md
JSON evidence: C:\Users\blossom\OneDrive\Documents\New project 2\FYP_Repo\artifacts\security\guardrail-results.json
