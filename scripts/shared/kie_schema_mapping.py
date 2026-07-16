"""KIE field class names and Schema.org property mappings."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shared.kie_utils import KIEResult


# ---------------------------------------------------------------------------
# Field class names used during KIE training and inference
# ---------------------------------------------------------------------------

KIE_FIELD_CLASSES: list[str] = [
    "vendor_name",
    "customer_name",
    "invoice_number",
    "invoice_date",
    "total_amount",
    "currency",
    "line_item",
    "receipt_date",
    "store_name",
    "receipt_total",
]

# ---------------------------------------------------------------------------
# Schema.org mapping per KIE field class
#
# Each entry maps a KIE class name to a Schema.org property path on the
# Invoice type.  Nested types (Organization, Person, MonetaryAmount) are
# expressed as ``nested_type`` + ``nested_prop``.
# ---------------------------------------------------------------------------

KIE_FIELD_TO_SCHEMA: dict[str, dict[str, str]] = {
    # Invoice fields
    "vendor_name": {
        "schema_type": "Invoice",
        "property": "provider",
        "nested_type": "Organization",
        "nested_prop": "name",
    },
    "customer_name": {
        "schema_type": "Invoice",
        "property": "customer",
        "nested_type": "Person",
        "nested_prop": "name",
    },
    "invoice_number": {
        "schema_type": "Invoice",
        "property": "confirmationNumber",
    },
    "invoice_date": {
        "schema_type": "Invoice",
        "property": "paymentDueDate",
    },
    "total_amount": {
        "schema_type": "Invoice",
        "property": "totalPaymentDue",
        "nested_type": "MonetaryAmount",
        "nested_prop": "value",
    },
    "currency": {
        "schema_type": "Invoice",
        "property": "totalPaymentDue",
        "nested_type": "MonetaryAmount",
        "nested_prop": "currency",
    },
    "line_item": {
        "schema_type": "Invoice",
        "property": "referencesOrder",
        "nested_type": "Order",
        "nested_prop": "description",
    },
    # Receipt fields (mapped to Invoice — no Receipt schema.org type)
    "receipt_date": {
        "schema_type": "Invoice",
        "property": "paymentDueDate",
    },
    "store_name": {
        "schema_type": "Invoice",
        "property": "provider",
        "nested_type": "Organization",
        "nested_prop": "name",
    },
    "receipt_total": {
        "schema_type": "Invoice",
        "property": "totalPaymentDue",
        "nested_type": "MonetaryAmount",
        "nested_prop": "value",
    },
}

# ---------------------------------------------------------------------------
# Shared confidence threshold and classification field groups
#
# Both kie_result_to_schema_org (below) and ContentClassifier.classify_with_kie
# (src/classifiers/content_classifier.py) use the same 0.5 gate and the same
# field-class groupings. Single-sourcing them here eliminates the silent-drift
# risk that previously existed when the two private copies could diverge.
# ---------------------------------------------------------------------------

# Public constant; content_classifier.py imports this instead of maintaining
# its own private copy.
KIE_MIN_CONFIDENCE: float = 0.5

# Field-class groups for classification. content_classifier.py imports these
# so the tuples are defined in one place alongside KIE_FIELD_CLASSES above.
KIE_VENDOR_CLASSES: tuple[str, ...] = ("vendor_name", "store_name")
KIE_AMOUNT_CLASSES: tuple[str, ...] = ("total_amount", "receipt_total")
KIE_DATE_CLASSES: tuple[str, ...] = ("invoice_date", "receipt_date")


def kie_result_to_schema_org(kie_result: KIEResult) -> dict:
    """Convert a KIEResult into a Schema.org JSON-LD fragment.

    Returns a dict suitable for merging into an existing ``schema_data`` JSON
    blob.  Only fields whose best prediction exceeds ``KIE_MIN_CONFIDENCE``
    are included.
    """
    schema: dict = {
        "@type": "Invoice",
    }

    for class_name, fields in kie_result.fields.items():
        if not fields:
            continue

        mapping = KIE_FIELD_TO_SCHEMA.get(class_name)
        if mapping is None:
            continue

        # Pick the highest-confidence prediction for this class.
        best = max(fields, key=lambda f: f.confidence)
        if best.confidence < KIE_MIN_CONFIDENCE:
            continue

        prop = mapping["property"]
        nested_type = mapping.get("nested_type")
        nested_prop = mapping.get("nested_prop")

        if nested_type and nested_prop:
            # Merge into existing nested object if the property is already set
            # (e.g. totalPaymentDue.value and totalPaymentDue.currency).
            existing = schema.get(prop)
            if isinstance(existing, dict):
                existing[nested_prop] = best.value
            else:
                schema[prop] = {
                    "@type": nested_type,
                    nested_prop: best.value,
                }
        else:
            schema[prop] = best.value

    return schema
