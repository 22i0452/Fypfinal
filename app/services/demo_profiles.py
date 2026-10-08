"""Idempotent fictional demo profiles. Never overwrite saved patient changes."""
from medflow.domain.models import Patient

DOCTORS = [
    ('DOC-DEV-002', 'Dr. Ayesha Khan', 'ayesha@demo.medflow.invalid'),
    ('DOC-DEV-003', 'Dr. Bilal Ahmed', 'bilal@demo.medflow.invalid'),
    ('DOC-DEV-004', 'Dr. Sara Malik', 'sara@demo.medflow.invalid'),
]
PATIENTS = [
    ('001', 'Demo Patient - Hamza', '28 years', 'Headache and fever', 'No history reported', 'DOC-DEV-002'),
    ('002', 'Demo Patient - Maryam', '46 years', 'Follow-up visit', 'Previously reported hypertension', 'DOC-DEV-003'),
    ('003', 'Demo Patient - Ali', '8 years', 'Cough; accompanied by mother', 'No history reported', 'DOC-DEV-004'),
]


def seed_demo_profiles(container):
    # Coordinated writes share the DB transaction. PostgreSQL serializes startup
    # so two application processes cannot seed duplicate doctors or profiles.
    with container.database.transaction():
        for practitioner, name, email in DOCTORS:
            user = container.auth_repository.get_by_email(email)
            if user is None:
                user = container.auth_repository.create_doctor(name, email, container.settings.demo_access_password)
                with container.database.connection() as db:
                    db.execute('DELETE FROM practitioner_profiles WHERE doctor_user_id=? AND practitioner_id<>?',
                               (user.user_id, practitioner))
                    db.execute('UPDATE practitioner_profiles SET doctor_user_id=? WHERE practitioner_id=? AND doctor_user_id IS NULL',
                               (user.user_id, practitioner))
        for suffix, name, age, complaint, history, practitioner in PATIENTS:
            identifier = 'PT-DEMO-SYNTHETIC-' + suffix
            if container.patient_repository.get(identifier) is None:
                container.patient_repository.save(Patient(patient_id=identifier, name=name,
                    age_text=age, current_complaint=complaint, past_medical_history=history,
                    first_visit='Yes', phone_number='03000000' + suffix))
            container.auth_repository.assign_patient(practitioner, identifier)

