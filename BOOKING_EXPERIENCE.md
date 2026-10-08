# Reception choices and appointment attendance

Reception uses inline department and doctor cards, followed by a calendar of actual available times. These are visible beside the conversation on desktop, without a popup. The choices follow Samra's current question. Speaking and clicking use the same booking state and final confirmation; changing a department or doctor clears dependent selections. Manual intake uses the same cards/calendar instead of visible dropdowns.

Department descriptions explain services rather than recommending a clinical diagnosis. Doctor cards use active clinic profiles and show their next opening when available. Selecting “Any available doctor” resolves to a real practitioner. Slot dates and times use the clinic timezone. Availability is checked again by the booking service when saving; a displayed opening is not a reservation. Stale conversation selections are rejected, and late availability responses cannot replace a newer selection.

## Doctor workspace

Appointments now have their own calendar and date agenda, above the separate patient-record card. Reception requests are in the Requests tab, with their date/time and a Review intake action. Confirmed appointments appear on their selected calendar day. Counts and markers come from the assigned doctor's saved appointments. No synthetic appointments are added to the schedule.

For a new intake, **Review patient details** is the default: staff check the name and intake against the attending person, then confirm the review. The saved method is `MANUAL_STAFF_REVIEW`, with an audit record. This is not proof of phone ownership. **Use phone OTP instead** retains the existing challenge flow. Neither path establishes attendance confirmation.

## Attendance before the visit

Open **Attendance** on an appointment, then **Request confirmation**. This prepares a durable request, clearly labelled **No patient notification has been delivered**. No SMS, email, telephone or patient-portal message is sent by this feature.

Staff can record a response after the patient communicates it:

- **I'll attend:** saves attendance confirmation independently of clinic approval and identity review.
- **Change time:** opens an actual availability calendar. The original reservation remains until the replacement saves successfully.
- **Cancel appointment:** cancels the appointment and its active workflow, releasing the reserved time.

The saved response identifies its source as `STAFF_RECORDED`. Saving requires a staff acknowledgement that the patient communicated the response. **Preview patient response** is explicitly labelled Demo and makes no record changes; it cannot impersonate a patient confirmation.

A time, doctor or visit-type change makes the old attendance request stale. Clinic approval alone preserves it. Requests and responses have duplicate protection, ownership checks and audit records. Replacement/cancellation, receipts, workflow updates and response writes share one SQLite transaction, so a failure cannot leave half a change.

The patient dashboard and real notification delivery remain next-phase integration points. The present implementation separates request preparation, delivery and response source so a future portal can add authenticated patient responses without treating a staff action as a delivered notification.

## Update and test

Pull the latest `main` and restart the existing FastAPI process. No new provider key is required. The attendance table initializes automatically; existing patients, appointments and optional OTP settings remain in the configured database.

Synthetic repeatable checks:

```sh
python -m unittest tests.test_booking_experience -q
QA_CHROMIUM_PATH=/path/to/chromium node tests/test_booking_experience_browser.cjs
```

The browser script also needs Playwright and the application's Python dependencies. It uses an isolated fictional clinic on localhost:8765 and should run sequentially with other browser scripts using that port. Validation details are in [VALIDATION.md](VALIDATION.md).
