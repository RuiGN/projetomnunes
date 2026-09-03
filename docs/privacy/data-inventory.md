# MVP data inventory

Version: 1.1
Owner: Privacy and Security
Review cycle: every release or every six months, whichever occurs first
Approval status: engineering review complete; controller and legal/regulatory approval pending

This inventory defines the minimum categories authorized for the MVP. A field that does not map to a category below must not be collected until the processing register and privacy review are updated.

| Category ID | Category | Examples | Sensitive personal data | Default access | System of record |
|---|---|---|---|---|---|
| `identity_registration` | Identity and registration data | UUID, legal/display/social name, birth date, account status | Sometimes (minor status) | Data subject and authorized tenant administrators | PostgreSQL |
| `professional_profile` | Professional data | professional category, declared specialty, council identifier and jurisdiction | No by default | Professional and authorized tenant administrators | PostgreSQL |
| `professional_regulatory` | Professional regulatory evidence | CFP/CRP council, registration number, jurisdiction, registration status, validity, verification source and timestamp | May reveal professional disciplinary or financial regularity | Professional, authorized compliance roles and competent Psychology Council when legally required | PostgreSQL plus protected verification evidence |
| `clinic_regulatory` | Clinic regulatory evidence | legal-entity registration, technical supervisor, CRP certificate, validity, inspection and renewal evidence | May link professionals and health-service operations | Authorized clinic/compliance roles and competent Psychology Council | PostgreSQL plus protected evidence objects |
| `tdic_service_agreement` | TDIC service agreement evidence | agreement version, service characteristics, rights and duties, technologies used, confidentiality resources, forum, organization and acceptance timestamp | May reveal a psychological-service relationship | Service user, responsible professional and specifically authorized compliance roles | PostgreSQL append-only history and protected document object |
| `psychological_record` | Psychological record data | subject identification, demand and objectives, concise evolution, scientific procedures, referral or closure and issued-document references | Yes | Data subject as legally applicable and explicitly authorized responsible psychologist or care relationship | Encrypted PostgreSQL/objects |
| `restricted_assessment_material` | Restricted psychological assessment material | psychological instruments, application material, answers, scoring, technical basis and resulting documents | Yes; professionally restricted | Responsible psychologist and another expressly authorized psychologist when regulation permits | Segregated encrypted PostgreSQL/objects |
| `emergency_protection_action` | Emergency and protection action data | assessed context, minimum necessary disclosure, referral, notification, protection-network articulation, responsible professional and rationale | Yes | Responsible professional and strictly necessary protection-network recipients | Encrypted PostgreSQL/objects with minimized audit metadata |
| `contact` | Contact data | e-mail, telephone, address, locale, timezone | No by default | Data subject and authorized operational roles | PostgreSQL |
| `consent_evidence` | Consent evidence | document version, decision, purpose, actor, represented subject, timestamp | May reveal health relationship | Data subject, privacy role and authorized auditors | PostgreSQL append-only history |
| `usage_security` | Usage and security data | request ID, pseudonymous actor ID, authentication event, device class, truncated network origin | No by default | Security and specifically authorized auditors | Protected logs and PostgreSQL audit store |
| `declared_clinical` | Declared clinical data | journal, check-in, goals, exercises, messages and care context supplied by the person | Yes | Data subject and explicitly authorized care relationship | Encrypted PostgreSQL/objects |
| `accessibility_preferences` | Accessibility preferences | contrast, motion, text size, assistive requirements | May reveal health/disability | Data subject and roles that need the preference | PostgreSQL |
| `appointment_operations` | Appointment operations | availability, booking status, unit, room and reminder preference | May reveal health service use | Data subject and authorized operational/care roles | PostgreSQL |
| `communication_content` | Communication content | typed channel, message and protected attachment metadata | Usually yes for clinical channel | Active participants authorized for that channel | Encrypted PostgreSQL/objects |
| `financial_operations` | Financial operations | service price, charge, due date, payment state, refund and receipt metadata | No by default | Data subject and authorized finance roles | Segregated financial ledger |
| `learning_activity` | Learning activity data | lesson favorites, private notes, playback events, lesson progress, quiz attempts, course enrollment and certificates | No by default (may reveal engagement) | Data subject and authorized care/operational roles | PostgreSQL |

## Classification rules

- Sensitive personal data includes health, disability, religious belief, biometrics and any category protected by LGPD article 5 when applicable.
- Free-text fields are treated as sensitive because a person can disclose protected information unexpectedly.
- Passwords, recovery codes, payment card PAN/CVV and provider secrets are credentials, not product data; plaintext persistence is prohibited.
- Logs use pseudonymous identifiers and never include clinical text, authentication tokens, document contents or secrets.
- Synthetic data is mandatory outside authorized environments.
- A generic `therapist` role is not proof of eligibility to perform acts reserved to Psychology. Authorization for regulated capabilities must use verified `professional_regulatory` evidence and the applicable jurisdiction.
- Psychological records and `restricted_assessment_material` are separate categories. A general clinical-data permission never grants access to professionally restricted assessment material.
- Regulatory evidence is collected only to demonstrate eligibility, accountability, inspection readiness or a documented legal/regulatory obligation; it must not be reused for ranking, advertising or unrelated profiling.

## Regulatory references for this revision

- CFP Resolution 01/2009 — psychological records, minimum content, restricted assessment material, access, confidentiality and minimum retention: https://site.cfp.org.br/wp-content/uploads/2009/04/resolucao2009_01.pdf
- CFP Professional Code of Ethics — confidentiality, minors, recording methods, confidential-file destination and professional identification: https://site.cfp.org.br/wp-content/uploads/2012/07/codigo-de-etica-psicologia.pdf
- CFP Resolution 06/2019 — preparation, authorship, professional registration, custody and delivery of psychological documents: https://site.cfp.org.br/wp-content/uploads/2019/09/Resolu%C3%A7%C3%A3o-CFP-n-06-2019-comentada.pdf
- CFP Resolution 09/2024 — Psychology practice mediated by digital information and communication technologies: https://atosoficiais.com.br/cfp/resolucao-do-exercicio-profissional-n-9-2024-regulamenta-o-exercicio-profissional-da-psicologia-mediado-por-tecnologias-digitais-da-informacao-e-da-comunicacao-tdics-em
- CRP-02/PE legal-entity guidance — registration, technical supervisor, professional regularity and certificate renewal evidence: https://www.crppe.org.br/profissional/?id=17
