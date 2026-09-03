"""Journal persistence owned by the journal domain."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from core.persistence import UUIDTimestampedModel

CONTEXT_MAX_LENGTH = 4000
DETAIL_MAX_LENGTH = 2000


class JournalEntryQuerySet(models.QuerySet["JournalEntry"]):
    """Journal entries retaining explicit tenant scope."""

    def for_clinic(self, clinic_id: UUID) -> JournalEntryQuerySet:
        return self.filter(clinic_id=clinic_id)


class JournalEntryManager(models.Manager["JournalEntry"]):
    """Refuse accidental global access to journal entries."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("JournalEntry queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> JournalEntryQuerySet:
        return JournalEntryQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureJournalEntryManager(models.Manager["JournalEntry"]):
    """Unrestricted journal access reserved for transactional services."""

    def get_queryset(self) -> JournalEntryQuerySet:
        return JournalEntryQuerySet(self.model, using=self._db)


class JournalEntry(UUIDTimestampedModel):
    """One patient-authored emotional diary record with per-item privacy."""

    class Mood(models.IntegerChoices):
        VERY_LOW = 1, "Muito mal"
        LOW = 2, "Mal"
        NEUTRAL = 3, "Neutro"
        GOOD = 4, "Bem"
        VERY_GOOD = 5, "Muito bem"

    class Emotion(models.TextChoices):
        ANXIETY = "anxiety", "Ansiedade"
        SADNESS = "sadness", "Tristeza"
        ANGER = "anger", "Raiva"
        JOY = "joy", "Alegria"
        FEAR = "fear", "Medo"
        CALM = "calm", "Calma"
        FRUSTRATION = "frustration", "Frustração"
        HOPE = "hope", "Esperança"

    class Visibility(models.TextChoices):
        SHAREABLE = "shareable", "Verde"
        CONFIRMATION_REQUIRED = "confirmation_required", "Amarelo"
        PRIVATE = "private", "Vermelho"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="journal_entries",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="journal_entries",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="journal_entries",
    )
    mood = models.IntegerField(choices=Mood.choices)
    emotions = models.JSONField(default=list, blank=True)
    intensity = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    context = models.TextField(max_length=CONTEXT_MAX_LENGTH)
    triggers = models.TextField(max_length=DETAIL_MAX_LENGTH, blank=True)
    reactions = models.TextField(max_length=DETAIL_MAX_LENGTH, blank=True)
    strategies = models.TextField(max_length=DETAIL_MAX_LENGTH, blank=True)
    visibility = models.CharField(
        max_length=24, choices=Visibility.choices, default=Visibility.PRIVATE
    )

    objects = JournalEntryManager()
    infrastructure_objects = InfrastructureJournalEntryManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "created_at"),
                name="journal_patient_created_idx",
            ),
            models.Index(
                fields=("clinic", "visibility"),
                name="journal_clinic_visibility_idx",
            ),
        ]


class JournalAccessRequestQuerySet(models.QuerySet["JournalAccessRequest"]):
    """Scoped query set for granular journal entry access requests."""

    def for_clinic(self, clinic_id: UUID) -> JournalAccessRequestQuerySet:
        return self.filter(clinic_id=clinic_id)

    def active(self) -> JournalAccessRequestQuerySet:
        now = timezone.now()
        return self.filter(
            status=JournalAccessRequest.Status.GRANTED,
            revoked_at__isnull=True,
        ).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gte=now))


class JournalAccessRequestManager(models.Manager["JournalAccessRequest"]):
    """Refuse global queries on access requests."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "JournalAccessRequest queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> JournalAccessRequestQuerySet:
        return JournalAccessRequestQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureJournalAccessRequestManager(models.Manager["JournalAccessRequest"]):
    """Internal infrastructure access manager."""

    def get_queryset(self) -> JournalAccessRequestQuerySet:
        return JournalAccessRequestQuerySet(self.model, using=self._db)


class JournalAccessRequest(UUIDTimestampedModel):
    """Granular access request or consent for yellow diary records."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        GRANTED = "granted", "Autorizado"
        REJECTED = "rejected", "Recusado"
        REVOKED = "revoked", "Revogado"
        EXPIRED = "expired", "Expirado"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="journal_access_requests",
    )
    journal_entry = models.ForeignKey(
        "journal.JournalEntry",
        on_delete=models.CASCADE,
        related_name="access_requests",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="journal_access_requests",
    )
    therapist = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="journal_access_requests",
    )
    purpose = models.CharField(max_length=255)
    consent_version = models.CharField(max_length=32, default="v1.0")
    status = models.CharField(
        max_length=24, choices=Status.choices, default=Status.PENDING
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.CharField(max_length=255, blank=True)

    objects = JournalAccessRequestManager()
    infrastructure_objects = InfrastructureJournalAccessRequestManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "journal_entry", "therapist", "status"),
                name="journal_req_entry_status_idx",
            ),
            models.Index(
                fields=("clinic", "patient_profile", "status"),
                name="journal_req_patient_status_idx",
            ),
        ]


class CheckInQuestionnaireQuerySet(models.QuerySet["CheckInQuestionnaire"]):
    """Scoped query set for check-in questionnaires."""

    def for_clinic(self, clinic_id: UUID) -> CheckInQuestionnaireQuerySet:
        return self.filter(clinic_id=clinic_id)


class CheckInQuestionnaireManager(models.Manager["CheckInQuestionnaire"]):
    """Refuse accidental global access to questionnaires."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError(
            "CheckInQuestionnaire queries require .for_clinic(clinic_id)."
        )

    def for_clinic(self, clinic_id: UUID) -> CheckInQuestionnaireQuerySet:
        return CheckInQuestionnaireQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureCheckInQuestionnaireManager(models.Manager["CheckInQuestionnaire"]):
    def get_queryset(self) -> CheckInQuestionnaireQuerySet:
        return CheckInQuestionnaireQuerySet(self.model, using=self._db)


DEFAULT_CHECKIN_QUESTIONS = [
    {
        "key": "general_state",
        "label": "Como você avalia seu estado geral hoje?",
        "type": "scale_1_5",
        "required": True,
        "order": 1,
    },
    {
        "key": "anxiety",
        "label": "Nível de ansiedade hoje",
        "type": "scale_1_5",
        "required": True,
        "order": 2,
    },
    {
        "key": "sadness",
        "label": "Sentimento de tristeza ou desânimo",
        "type": "scale_1_5",
        "required": True,
        "order": 3,
    },
    {
        "key": "irritability",
        "label": "Nível de irritabilidade ou impaciência",
        "type": "scale_1_5",
        "required": True,
        "order": 4,
    },
    {
        "key": "energy",
        "label": "Nível de disposição e energia",
        "type": "scale_1_5",
        "required": True,
        "order": 5,
    },
    {
        "key": "sleep_quality",
        "label": "Qualidade do seu sono na última noite",
        "type": "scale_1_5",
        "required": True,
        "order": 6,
    },
    {
        "key": "motivation",
        "label": "Nível de motivação para o seu dia",
        "type": "scale_1_5",
        "required": True,
        "order": 7,
    },
    {
        "key": "notes",
        "label": "Observações (opcional)",
        "type": "text",
        "required": False,
        "order": 8,
    },
]


class CheckInQuestionnaire(UUIDTimestampedModel):
    """Versioned check-in questionnaire configured per clinic."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="checkin_questionnaires",
    )
    title = models.CharField(max_length=255, default="Check-in Diário")
    version = models.CharField(max_length=32, default="v1.0")
    is_active = models.BooleanField(default=True)
    questions = models.JSONField(default=list)

    objects = CheckInQuestionnaireManager()
    infrastructure_objects = InfrastructureCheckInQuestionnaireManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "version"),
                name="unique_checkin_questionnaire_version_per_clinic",
            )
        ]


class DailyCheckInQuerySet(models.QuerySet["DailyCheckIn"]):
    """Scoped query set for daily check-in responses."""

    def for_clinic(self, clinic_id: UUID) -> DailyCheckInQuerySet:
        return self.filter(clinic_id=clinic_id)


class DailyCheckInManager(models.Manager["DailyCheckIn"]):
    """Refuse global queries on daily check-ins."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("DailyCheckIn queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> DailyCheckInQuerySet:
        return DailyCheckInQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureDailyCheckInManager(models.Manager["DailyCheckIn"]):
    def get_queryset(self) -> DailyCheckInQuerySet:
        return DailyCheckInQuerySet(self.model, using=self._db)


class DailyCheckIn(UUIDTimestampedModel):
    """Patient-completed daily state check-in record."""

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="daily_checkins",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="daily_checkins",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="daily_checkins",
    )
    questionnaire = models.ForeignKey(
        CheckInQuestionnaire,
        on_delete=models.PROTECT,
        related_name="checkin_responses",
    )
    questionnaire_version = models.CharField(max_length=32)
    date = models.DateField()
    period = models.CharField(max_length=16, default="daily")
    answers = models.JSONField(default=dict)
    visibility = models.CharField(
        max_length=24,
        choices=JournalEntry.Visibility.choices,
        default=JournalEntry.Visibility.PRIVATE,
    )
    is_draft = models.BooleanField(default=False)
    idempotency_key = models.CharField(max_length=128, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    previous_version_answers = models.JSONField(null=True, blank=True)

    objects = DailyCheckInManager()
    infrastructure_objects = InfrastructureDailyCheckInManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("clinic", "patient_profile", "date", "period"),
                name="unique_patient_checkin_per_date_period",
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "patient_profile", "date"),
                name="checkin_patient_date_idx",
            ),
        ]


class ClinicalSignalRuleQuerySet(models.QuerySet["ClinicalSignalRule"]):
    """Scoped query set for clinic-configured clinical signal rules."""

    def for_clinic(self, clinic_id: UUID) -> ClinicalSignalRuleQuerySet:
        return self.filter(clinic_id=clinic_id)

    def active(self) -> ClinicalSignalRuleQuerySet:
        return self.filter(is_active=True)


class ClinicalSignalRuleManager(models.Manager["ClinicalSignalRule"]):
    """Refuse global queries on clinical signal rules."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("ClinicalSignalRule queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> ClinicalSignalRuleQuerySet:
        return ClinicalSignalRuleQuerySet(self.model, using=self._db).for_clinic(
            clinic_id
        )


class InfrastructureClinicalSignalRuleManager(models.Manager["ClinicalSignalRule"]):
    def get_queryset(self) -> ClinicalSignalRuleQuerySet:
        return ClinicalSignalRuleQuerySet(self.model, using=self._db)


class ClinicalSignalRule(UUIDTimestampedModel):
    """Deterministic configured rule that flags check-in answers for human review.

    The rule NEVER diagnoses, never escalates automatically and never treats
    platform messages as emergencies. It only creates a human triage item.
    """

    class Operator(models.TextChoices):
        GREATER_OR_EQUAL = "gte", "Maior ou igual a"
        LESS_OR_EQUAL = "less_or_equal", "Menor ou igual a"
        EQUAL = "equal", "Igual a"

    class MonitoringWindow(models.TextChoices):
        BUSINESS_HOURS = "business_hours", "Horário comercial"
        EXTENDED = "extended", "Horário estendido"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="clinical_signal_rules",
    )
    name = models.CharField(max_length=255)
    question_key = models.CharField(max_length=64)
    operator = models.CharField(max_length=24, choices=Operator.choices)
    threshold = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)
    monitoring_window = models.CharField(
        max_length=24,
        choices=MonitoringWindow.choices,
        default=MonitoringWindow.BUSINESS_HOURS,
    )
    responsible_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="clinical_signal_rules",
        blank=True,
    )
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clinical_signal_rules_authorized",
        null=True,
        blank=True,
    )

    objects = ClinicalSignalRuleManager()
    infrastructure_objects = InfrastructureClinicalSignalRuleManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        indexes = [
            models.Index(
                fields=("clinic", "question_key", "is_active"),
                name="signal_rule_clinic_key_idx",
            ),
        ]


class HumanTriageItemQuerySet(models.QuerySet["HumanTriageItem"]):
    """Scoped query set for human triage review items."""

    def for_clinic(self, clinic_id: UUID) -> HumanTriageItemQuerySet:
        return self.filter(clinic_id=clinic_id)

    def pending(self) -> HumanTriageItemQuerySet:
        return self.filter(status=HumanTriageItem.Status.PENDING)


class HumanTriageItemManager(models.Manager["HumanTriageItem"]):
    """Refuse global queries on triage items."""

    def get_queryset(self) -> NoReturn:
        raise RuntimeError("HumanTriageItem queries require .for_clinic(clinic_id).")

    def for_clinic(self, clinic_id: UUID) -> HumanTriageItemQuerySet:
        return HumanTriageItemQuerySet(self.model, using=self._db).for_clinic(clinic_id)


class InfrastructureHumanTriageItemManager(models.Manager["HumanTriageItem"]):
    def get_queryset(self) -> HumanTriageItemQuerySet:
        return HumanTriageItemQuerySet(self.model, using=self._db)


class HumanTriageItem(UUIDTimestampedModel):
    """One human-review triage item generated from a configured signal rule."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        IN_REVIEW = "in_review", "Em revisão"
        CLOSED = "closed", "Encerrado"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="human_triage_items",
    )
    checkin = models.ForeignKey(
        DailyCheckIn,
        on_delete=models.CASCADE,
        related_name="triage_items",
        null=True,
        blank=True,
    )
    rule = models.ForeignKey(
        ClinicalSignalRule,
        on_delete=models.PROTECT,
        related_name="triage_items",
    )
    patient_profile = models.ForeignKey(
        "people.PatientProfile",
        on_delete=models.CASCADE,
        related_name="human_triage_items",
    )
    reason = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviewed_triage_items",
        null=True,
        blank=True,
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_decision = models.CharField(max_length=255, blank=True)
    is_emergency = models.BooleanField(default=False)

    objects = HumanTriageItemManager()
    infrastructure_objects = InfrastructureHumanTriageItemManager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "infrastructure_objects"
        constraints = [
            models.UniqueConstraint(
                fields=("checkin", "rule"),
                name="unique_triage_item_per_checkin_rule",
            )
        ]
        indexes = [
            models.Index(
                fields=("clinic", "status", "created_at"),
                name="triage_clinic_status_idx",
            ),
        ]
