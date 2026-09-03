"""Forms for the editorial content HTTP layer."""

from __future__ import annotations

import json
from typing import Any

from django import forms

from .models import ContentKind

_BLOCK_MAX_CHARS = 20000
_BLOCK_TYPES = frozenset({"heading", "paragraph", "list_item"})


class HiddenValueList(forms.HiddenInput):
    """Hidden widget that reads repeated query values as a list."""

    def value_from_datadict(self, data: Any, files: Any, name: str) -> list[str] | None:
        if hasattr(data, "getlist"):
            values = [str(value) for value in data.getlist(name)]
            return values or None
        value = data.get(name)
        if value in (None, ""):
            return None
        return [str(value)]


class ValueListField(forms.Field):
    """Text field that preserves repeated posted values as an ordered list."""

    widget = HiddenValueList

    def __init__(
        self, *args: Any, max_length: int | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.max_length = max_length

    def to_python(self, value: object) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return [str(value)]
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple)):
            return [str(item) for item in value]
        return [str(value)]

    def validate(self, value: object) -> None:
        super().validate(value)
        items = value if isinstance(value, list) else []
        if not self.max_length or not items:
            return
        for item in items:
            if len(item) > self.max_length:
                raise forms.ValidationError(
                    "Cada bloco deve ter no máximo %(max)d caracteres.",
                    params={"max": self.max_length},
                    code="max_length",
                )


HiddenMultipleChoice = HiddenValueList


class ContentSearchForm(forms.Form):
    """Query published content by free text and managed category."""

    query = forms.CharField(required=False, max_length=200)
    category = forms.CharField(required=False, max_length=64)


class ContentRecommendForm(forms.Form):
    """Attribute one published content item to a patient (professional only)."""

    patient = forms.ChoiceField(label="Paciente")
    objective = forms.CharField(max_length=255, label="Objetivo")
    priority = forms.ChoiceField(
        choices=(("low", "Baixa"), ("normal", "Normal"), ("high", "Alta")),
        initial="normal",
        label="Prioridade",
    )
    context = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Contexto",
    )

    def __init__(
        self,
        *args: Any,
        patient_choices: list[tuple[str, str]],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        patient_field = self.fields["patient"]
        if isinstance(patient_field, forms.ChoiceField):
            patient_field.choices = patient_choices


def _blocks_from_raw(value: str) -> list[dict[str, str]]:
    """Parse the legacy raw-body fallback into heading/paragraph blocks."""
    blocks: list[dict[str, str]] = []
    for line in (value or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("<li>") and text.endswith("</li>"):
            blocks.append({"type": "list_item", "text": text[4:-5]})
        elif (text.startswith("<h2>") and text.endswith("</h2>")) or (
            text.startswith("<h3>") and text.endswith("</h3>")
        ):
            blocks.append({"type": "heading", "text": text[4:-5]})
        elif text.startswith("<p>") and text.endswith("</p>"):
            blocks.append({"type": "paragraph", "text": text[3:-4]})
        else:
            blocks.append({"type": "paragraph", "text": text})
    return blocks


def encode_blocks(blocks: list[dict[str, str]]) -> str:
    """Encode ordered typed blocks into the sanitized-safe stored markup."""
    rendered: list[str] = []
    for block in blocks:
        text = block.get("text", "")
        block_type = block.get("type", "paragraph")
        if block_type == "heading":
            rendered.append(f"<h2>{text}</h2>")
        elif block_type == "list_item":
            rendered.append(f"<li>{text}</li>")
        else:
            rendered.append(f"<p>{text}</p>")
    return "".join(rendered)


def blocks_body(fields: Any) -> str:
    """Resolve the ordered block body from typed fields or the raw fallback.

    The accessible block editor posts repeated ``block_type``/``block_text``
    pairs; the raw textarea remains as the no-JavaScript fallback and keeps the
    existing raw-body tests valid. ``fields`` may be a cleaned-data dict (one
    text per value) or a QueryDict with repeated ``block_text`` values.
    """

    types = fields.get("block_type") or []
    texts = fields.get("block_text") or []
    if isinstance(texts, str):
        texts = [texts]
    if types or texts:
        pairs = [
            (str(block_type).strip(), str(text).replace("\r\n", "\n"))
            for block_type, text in zip(types, texts, strict=False)
        ]
        blocks = [
            {"type": block_type, "text": text}
            for block_type, text in pairs
            if block_type in _BLOCK_TYPES and text.strip()
        ]
        if blocks:
            return encode_blocks(blocks)
    return _raw_body(fields)


def blocks_json(fields: dict[str, Any]) -> str:
    """Return the ordered blocks as JSON for the preview debug panel."""
    return json.dumps(blocks_from_fields(fields), ensure_ascii=False)


def blocks_from_fields(fields: dict[str, Any]) -> list[dict[str, str]]:
    """Return ordered typed blocks, falling back to the raw body."""
    body = blocks_body(fields)
    return _blocks_from_raw(body)


def _raw_body(fields: dict[str, Any]) -> str:
    value = fields.get("body")
    return value if isinstance(value, str) else ""


class EditorialContentForm(forms.Form):
    """Create a tenant-owned content item and its first accessible block body."""

    slug = forms.SlugField(max_length=160, label="Identificador")
    title = forms.CharField(max_length=255, label="Título")
    kind = forms.ChoiceField(choices=ContentKind.choices, label="Tipo")
    language_code = forms.CharField(max_length=10, initial="pt-BR", label="Idioma")
    audience = forms.ChoiceField(
        choices=(("patient", "Paciente"), ("professional", "Profissional")),
        label="Público",
    )
    categories = forms.CharField(required=False, max_length=200, label="Categorias")
    tags = forms.CharField(required=False, max_length=200, label="Tags")
    contraindications = forms.CharField(
        required=False,
        max_length=1000,
        label="Contraindicações",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    source_reference = forms.CharField(
        required=False, max_length=255, label="Referência da fonte"
    )
    valid_until = forms.DateField(
        required=False,
        label="Válido até",
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
    )
    body = forms.CharField(
        max_length=50000,
        required=False,
        label="Conteúdo em blocos",
        widget=forms.Textarea(
            attrs={"rows": 14, "aria-describedby": "editor-help", "spellcheck": "true"}
        ),
    )
    block_type = forms.MultipleChoiceField(
        required=False,
        choices=(
            ("heading", "Título"),
            ("paragraph", "Parágrafo"),
            ("list_item", "Item de lista"),
        ),
        widget=HiddenMultipleChoice,
        label="Tipo de bloco",
    )
    block_text = ValueListField(
        required=False,
        label="Texto do bloco",
    )

    def clean_categories(self) -> str:
        return _clean_taxonomy(self.cleaned_data.get("categories"))

    def clean_tags(self) -> str:
        return _clean_taxonomy(self.cleaned_data.get("tags"))

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        if not self.has_blocks() and not (cleaned.get("body") or "").strip():
            self.add_error("body", "Informe o conteúdo em blocos.")
        return cleaned

    def has_blocks(self) -> bool:
        types = self.cleaned_data.get("block_type") or []
        texts = self.data.getlist("block_text") if hasattr(self.data, "getlist") else []
        return bool([t for t in types if t in _BLOCK_TYPES]) and any(
            str(text).strip() for text in texts
        )

    def comma_list(self, field: str) -> list[str]:
        value = self.cleaned_data.get(field) or ""
        return [part.strip() for part in value.split(",") if part.strip()]


def _clean_taxonomy(value: object) -> str:
    """Validate one comma-separated taxonomy field against the model limits."""
    raw = value if isinstance(value, str) else ""
    terms = [part.strip() for part in raw.split(",") if part.strip()]
    oversized = [term for term in terms if len(term) > 64]
    if oversized:
        raise forms.ValidationError("Cada termo deve ter no máximo 64 caracteres.")
    return ",".join(terms)


class EditorialVersionForm(forms.Form):
    body = forms.CharField(
        max_length=50000,
        required=False,
        label="Conteúdo em blocos",
        widget=forms.Textarea(
            attrs={"rows": 14, "aria-describedby": "editor-help", "spellcheck": "true"}
        ),
    )
    block_type = forms.MultipleChoiceField(
        required=False,
        choices=(
            ("heading", "Título"),
            ("paragraph", "Parágrafo"),
            ("list_item", "Item de lista"),
        ),
        widget=HiddenMultipleChoice,
        label="Tipo de bloco",
    )
    block_text = ValueListField(
        required=False,
        label="Texto do bloco",
    )
    scheduled_for = forms.DateTimeField(required=False, label="Agendar publicação")

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean() or {}
        types = cleaned.get("block_type") or []
        data_texts = (
            self.data.getlist("block_text") if hasattr(self.data, "getlist") else []
        )
        has_typed = bool([t for t in types if t in _BLOCK_TYPES]) and any(
            str(text).strip() for text in data_texts
        )
        if not has_typed and not (cleaned.get("body") or "").strip():
            self.add_error("body", "Informe o conteúdo em blocos.")
        return cleaned


class EditorialMetadataForm(forms.Form):
    """Update clinical metadata of one content item (administration only)."""

    contraindications = forms.CharField(
        required=False,
        max_length=1000,
        label="Contraindicações",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    source_reference = forms.CharField(
        required=False, max_length=255, label="Referência da fonte"
    )
    valid_until = forms.DateField(
        required=False,
        label="Válido até",
        input_formats=["%Y-%m-%d", "%d/%m/%Y"],
    )


class EditorialCommentForm(forms.Form):
    body = forms.CharField(
        max_length=2000,
        label="Comentário editorial",
        widget=forms.Textarea(attrs={"rows": 3}),
    )


class EditorialApprovalForm(forms.Form):
    opinion = forms.CharField(
        max_length=2000, label="Parecer", widget=forms.Textarea(attrs={"rows": 4})
    )
    review_valid_days = forms.IntegerField(
        min_value=1, required=False, label="Validade da revisão em dias"
    )


class EditorialRollbackForm(forms.Form):
    target_version = forms.IntegerField(min_value=1, label="Versão de destino")


class EditorialMediaForm(forms.Form):
    file = forms.FileField(label="Arquivo de mídia")
