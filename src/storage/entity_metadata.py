"""
Class-based standalone schema.org entities backed by the graph store.

Standalone entities (e.g. a Residence, an Event venue) have no backing file,
so they persist as ``SchemaMetadata`` rows keyed by their JSON-LD ``@id``.

``SchemaOrgEntity`` is the generic base: subclass it and set ``entity_type``
(and optionally type-specific helpers) to model more specific schema.org
types — see ``PlaceEntity``/``ResidenceEntity``/``PersonEntity``.
"""

import json
import re
from pathlib import Path
from typing import Any, ClassVar, Dict, Iterable, List, Optional, Type, TypeVar, Union

from sqlalchemy.orm import Session

from .graph_store import GraphStore
from .models import SchemaMetadata

SCHEMA_ORG_CONTEXT = "https://schema.org"
SCHEMA_ORG_TYPE_URL = "https://schema.org/{type_name}"

_JSONLD_CONTEXT = "@context"
_JSONLD_ID = "@id"
_JSONLD_TYPE = "@type"
_RESERVED_KEYS = (_JSONLD_CONTEXT, _JSONLD_TYPE, _JSONLD_ID, "name", "additionalType")

# Unit/suite suffixes confuse Nominatim ("1115 Kinney Avenue, #3" resolves,
# "4201 S Congress Ave Suite 108" doesn't) — strip them from geocode queries.
_UNIT_SUFFIX_RE = re.compile(
    r"\s*(?:,\s*)?(?:#|(?:suite|ste|unit|apt|apartment|bldg|building|fl|floor|rm|room)\.?\s+)"
    r"[\w-]+\s*$",
    re.IGNORECASE,
)

# Nominatim usage policy: <=1 req/s (matches src/analyzers/image_metadata.py).
_GEOCODE_USER_AGENT = "schema-org-file-system/2.1.0"
_GEOCODE_TIMEOUT_SEC = 5
_GEOCODE_MIN_DELAY_SEC = 1.0
_GEOCODE_MAX_RETRIES = 2

E = TypeVar("E", bound="SchemaOrgEntity")


def _strip_unit_suffix(street: str) -> str:
    """Drop a trailing unit/suite/apartment designator from a street address."""
    return _UNIT_SUFFIX_RE.sub("", street).rstrip(" ,")


class SchemaOrgEntity:
    """A standalone schema.org entity persisted as a ``SchemaMetadata`` row.

    Subclass and override ``entity_type`` to model a specific schema.org
    type; add helper methods that call ``set_property`` for type-specific
    vocabulary.
    """

    entity_type: ClassVar[str] = "Thing"

    def __init__(
        self,
        entity_id: str,
        name: Optional[str] = None,
        additional_type: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            entity_id: JSON-LD ``@id`` (persistence key).
            name: schema.org ``name``.
            additional_type: bare type name (e.g. ``"Accommodation"``),
                emitted as a full ``additionalType`` URL.
            properties: further schema.org properties (e.g. ``address``).
        """
        self.entity_id = entity_id
        self.name = name
        self.additional_type = additional_type
        self.properties: Dict[str, Any] = dict(properties or {})

    def set_property(self, name: str, value: Any) -> None:
        """Set an arbitrary schema.org property."""
        self.properties[name] = value

    def get_property(self, name: str) -> Any:
        """Get a schema.org property (``None`` if unset)."""
        return self.properties.get(name)

    def add_same_as(self, url: str) -> None:
        """Add a ``sameAs`` reference URL (see ``_append_url_property``)."""
        self._append_url_property("sameAs", url)

    def add_main_entity_of_page(self, url: str) -> None:
        """Add a ``mainEntityOfPage`` URL (see ``_append_url_property``)."""
        self._append_url_property("mainEntityOfPage", url)

    def _append_url_property(self, name: str, url: str) -> None:
        """Append a URL to a property.

        A single value stays a scalar (schema.org convention); further
        additions grow it into a list. Duplicate URLs are ignored.
        """
        existing = self.properties.get(name)
        if existing is None:
            self.properties[name] = url
            return
        urls = existing if isinstance(existing, list) else [existing]
        if url not in urls:
            urls.append(url)
        self.properties[name] = urls[0] if len(urls) == 1 else urls

    def to_jsonld(self) -> Dict[str, Any]:
        """Serialize to a schema.org JSON-LD document."""
        jsonld: Dict[str, Any] = {
            _JSONLD_CONTEXT: SCHEMA_ORG_CONTEXT,
            _JSONLD_TYPE: self.entity_type,
            _JSONLD_ID: self.entity_id,
        }
        if self.name is not None:
            jsonld["name"] = self.name
        if self.additional_type:
            jsonld["additionalType"] = SCHEMA_ORG_TYPE_URL.format(type_name=self.additional_type)
        jsonld.update(self.properties)
        return jsonld

    @classmethod
    def from_jsonld(cls: Type[E], jsonld: Dict[str, Any]) -> E:
        """Rebuild an entity from a JSON-LD document."""
        additional = jsonld.get("additionalType")
        if additional and additional.startswith(SCHEMA_ORG_CONTEXT):
            additional = additional.rsplit("/", 1)[-1]
        entity = cls(
            entity_id=jsonld[_JSONLD_ID],
            name=jsonld.get("name"),
            additional_type=additional,
            properties={k: v for k, v in jsonld.items() if k not in _RESERVED_KEYS},
        )
        return entity

    def save(self, store: GraphStore, session: Optional[Session] = None) -> SchemaMetadata:
        """Insert or update this entity's ``SchemaMetadata`` row by ``@id``.

        ``schema_type`` is kept in sync with the JSON-LD ``@type``;
        standalone rows have no ``file_id``.
        """
        jsonld = self.to_jsonld()
        close_session = session is None
        session = session or store.get_session()
        try:
            row = self._query_row(session, self.entity_id)
            if row is None:
                row = SchemaMetadata(schema_json=jsonld, is_valid=True)
                session.add(row)
            else:
                row.schema_json = jsonld
            row.schema_type = self.entity_type
            if close_session:
                session.commit()
                # Reload attributes so the returned row is usable after close
                # (sessions expire attributes on commit).
                session.refresh(row)
                session.expunge(row)
            else:
                session.flush()
            return row
        finally:
            if close_session:
                session.close()

    @classmethod
    def load(
        cls: Type[E],
        store: GraphStore,
        entity_id: str,
        session: Optional[Session] = None,
    ) -> Optional[E]:
        """Load an entity by ``@id`` (``None`` if absent)."""
        close_session = session is None
        session = session or store.get_session()
        try:
            row = cls._query_row(session, entity_id)
            return cls.from_jsonld(row.schema_json) if row else None
        finally:
            if close_session:
                session.close()

    @staticmethod
    def _query_row(session: Session, entity_id: str) -> Optional[SchemaMetadata]:
        return (
            session.query(SchemaMetadata)
            .filter(SchemaMetadata.file_id.is_(None))
            .filter(SchemaMetadata.schema_json[_JSONLD_ID].as_string() == entity_id)
            .first()
        )

    @staticmethod
    def export(entities: Iterable["SchemaOrgEntity"], file_path: Union[str, Path]) -> Path:
        """Write entities to a JSON file (list of JSON-LD documents)."""
        path = Path(file_path)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([e.to_jsonld() for e in entities], f, indent=2, ensure_ascii=False)
        return path


class PlaceEntity(SchemaOrgEntity):
    """schema.org Place: adds address/geo helpers."""

    entity_type: ClassVar[str] = "Place"

    def set_address(
        self,
        street: str,
        locality: str,
        region: str,
        postal_code: str,
        country: str = "US",
    ) -> None:
        """Set a schema.org PostalAddress ``address`` property."""
        self.set_property(
            "address",
            {
                _JSONLD_TYPE: "PostalAddress",
                "streetAddress": street,
                "addressLocality": locality,
                "addressRegion": region,
                "postalCode": postal_code,
                "addressCountry": country,
            },
        )

    def set_geo(self, latitude: float, longitude: float) -> None:
        """Set a schema.org GeoCoordinates ``geo`` property."""
        self.set_property(
            "geo",
            {
                _JSONLD_TYPE: "GeoCoordinates",
                "latitude": latitude,
                "longitude": longitude,
            },
        )

    def geocode(self) -> bool:
        """Forward-geocode ``address`` into ``geo`` via Nominatim.

        Rate-limited per OSM policy. Unit/suite suffixes are stripped from
        the street for the lookup (Nominatim can't resolve them); the stored
        ``address`` keeps the full street. Returns ``False`` (leaving ``geo``
        unset) when geopy is unavailable, no address is set, the lookup
        fails, or the address does not resolve.
        """
        address = self.get_property("address")
        if not address:
            return False
        try:
            from geopy.extra.rate_limiter import RateLimiter
            from geopy.geocoders import Nominatim
        except ImportError:
            return False

        street = address.get("streetAddress")
        query = {
            "street": _strip_unit_suffix(street) if street else None,
            "city": address.get("addressLocality"),
            "state": address.get("addressRegion"),
            "postalcode": address.get("postalCode"),
            "country": address.get("addressCountry"),
        }
        try:
            geocoder = Nominatim(user_agent=_GEOCODE_USER_AGENT, timeout=_GEOCODE_TIMEOUT_SEC)
            forward_geocode = RateLimiter(
                geocoder.geocode,
                min_delay_seconds=_GEOCODE_MIN_DELAY_SEC,
                max_retries=_GEOCODE_MAX_RETRIES,
                swallow_exceptions=False,
            )
            location = forward_geocode({k: v for k, v in query.items() if v})
        except Exception:
            return False
        if location is None:
            return False
        self.set_geo(location.latitude, location.longitude)
        return True


class ResidenceEntity(PlaceEntity):
    """schema.org Residence (Place subtype)."""

    entity_type: ClassVar[str] = "Residence"


class EventEntity(SchemaOrgEntity):
    """schema.org Event."""

    entity_type: ClassVar[str] = "Event"


class OrganizationEntity(SchemaOrgEntity):
    """schema.org Organization."""

    entity_type: ClassVar[str] = "Organization"


class CorporationEntity(OrganizationEntity):
    """schema.org Corporation (Organization subtype)."""

    entity_type: ClassVar[str] = "Corporation"


class LocalBusinessEntity(OrganizationEntity):
    """schema.org LocalBusiness (Organization subtype; also a Place)."""

    entity_type: ClassVar[str] = "LocalBusiness"


class AnimalShelterEntity(LocalBusinessEntity):
    """schema.org AnimalShelter (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "AnimalShelter"


class ArchiveOrganizationEntity(LocalBusinessEntity):
    """schema.org ArchiveOrganization (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "ArchiveOrganization"


class AutomotiveBusinessEntity(LocalBusinessEntity):
    """schema.org AutomotiveBusiness (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "AutomotiveBusiness"


class ChildCareEntity(LocalBusinessEntity):
    """schema.org ChildCare (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "ChildCare"


class DentistEntity(LocalBusinessEntity):
    """schema.org Dentist (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "Dentist"


class DryCleaningOrLaundryEntity(LocalBusinessEntity):
    """schema.org DryCleaningOrLaundry (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "DryCleaningOrLaundry"


class EmergencyServiceEntity(LocalBusinessEntity):
    """schema.org EmergencyService (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "EmergencyService"


class EmploymentAgencyEntity(LocalBusinessEntity):
    """schema.org EmploymentAgency (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "EmploymentAgency"


class EntertainmentBusinessEntity(LocalBusinessEntity):
    """schema.org EntertainmentBusiness (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "EntertainmentBusiness"


class FinancialServiceEntity(LocalBusinessEntity):
    """schema.org FinancialService (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "FinancialService"


class FoodEstablishmentEntity(LocalBusinessEntity):
    """schema.org FoodEstablishment (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "FoodEstablishment"


class GovernmentOfficeEntity(LocalBusinessEntity):
    """schema.org GovernmentOffice (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "GovernmentOffice"


class HealthAndBeautyBusinessEntity(LocalBusinessEntity):
    """schema.org HealthAndBeautyBusiness (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "HealthAndBeautyBusiness"


class HomeAndConstructionBusinessEntity(LocalBusinessEntity):
    """schema.org HomeAndConstructionBusiness (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "HomeAndConstructionBusiness"


class InternetCafeEntity(LocalBusinessEntity):
    """schema.org InternetCafe (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "InternetCafe"


class LegalServiceEntity(LocalBusinessEntity):
    """schema.org LegalService (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "LegalService"


class LibraryEntity(LocalBusinessEntity):
    """schema.org Library (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "Library"


class LodgingBusinessEntity(LocalBusinessEntity):
    """schema.org LodgingBusiness (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "LodgingBusiness"


class MedicalBusinessEntity(LocalBusinessEntity):
    """schema.org MedicalBusiness (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "MedicalBusiness"


class ProfessionalServiceEntity(LocalBusinessEntity):
    """schema.org ProfessionalService (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "ProfessionalService"


class RadioStationEntity(LocalBusinessEntity):
    """schema.org RadioStation (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "RadioStation"


class RealEstateAgentEntity(LocalBusinessEntity):
    """schema.org RealEstateAgent (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "RealEstateAgent"


class RecyclingCenterEntity(LocalBusinessEntity):
    """schema.org RecyclingCenter (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "RecyclingCenter"


class SelfStorageEntity(LocalBusinessEntity):
    """schema.org SelfStorage (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "SelfStorage"


class ShoppingCenterEntity(LocalBusinessEntity):
    """schema.org ShoppingCenter (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "ShoppingCenter"


class SportsActivityLocationEntity(LocalBusinessEntity):
    """schema.org SportsActivityLocation (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "SportsActivityLocation"


class StoreEntity(LocalBusinessEntity):
    """schema.org Store (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "Store"


class TelevisionStationEntity(LocalBusinessEntity):
    """schema.org TelevisionStation (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "TelevisionStation"


class TouristInformationCenterEntity(LocalBusinessEntity):
    """schema.org TouristInformationCenter (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "TouristInformationCenter"


class TravelAgencyEntity(LocalBusinessEntity):
    """schema.org TravelAgency (LocalBusiness subtype)."""

    entity_type: ClassVar[str] = "TravelAgency"


class EducationalOrganizationEntity(OrganizationEntity):
    """schema.org EducationalOrganization (Organization subtype)."""

    entity_type: ClassVar[str] = "EducationalOrganization"


class GovernmentOrganizationEntity(OrganizationEntity):
    """schema.org GovernmentOrganization (Organization subtype)."""

    entity_type: ClassVar[str] = "GovernmentOrganization"


class NGOEntity(OrganizationEntity):
    """schema.org NGO (Organization subtype)."""

    entity_type: ClassVar[str] = "NGO"


class PerformingGroupEntity(OrganizationEntity):
    """schema.org PerformingGroup (Organization subtype)."""

    entity_type: ClassVar[str] = "PerformingGroup"


class SportsOrganizationEntity(OrganizationEntity):
    """schema.org SportsOrganization (Organization subtype)."""

    entity_type: ClassVar[str] = "SportsOrganization"


class NewsMediaOrganizationEntity(OrganizationEntity):
    """schema.org NewsMediaOrganization (Organization subtype)."""

    entity_type: ClassVar[str] = "NewsMediaOrganization"


class PoliticalPartyEntity(OrganizationEntity):
    """schema.org PoliticalParty (Organization subtype)."""

    entity_type: ClassVar[str] = "PoliticalParty"


class MedicalEntityEntity(SchemaOrgEntity):
    """schema.org MedicalEntity (Thing subtype; root of the medical vocabulary).

    The doubled name is the mechanical ``{TypeName}Entity`` naming convention
    applied to a schema.org type literally named ``MedicalEntity``.
    """

    entity_type: ClassVar[str] = "MedicalEntity"


class MedicalTestEntity(MedicalEntityEntity):
    """schema.org MedicalTest (MedicalEntity subtype)."""

    entity_type: ClassVar[str] = "MedicalTest"


class BloodTestEntity(MedicalTestEntity):
    """schema.org BloodTest (Thing > MedicalEntity > MedicalTest > BloodTest)."""

    entity_type: ClassVar[str] = "BloodTest"


class PathologyTestEntity(MedicalTestEntity):
    """schema.org PathologyTest (MedicalTest subtype, BloodTest sibling)."""

    entity_type: ClassVar[str] = "PathologyTest"


class ImageObjectEntity(SchemaOrgEntity):
    """schema.org ImageObject."""

    entity_type: ClassVar[str] = "ImageObject"


class PersonEntity(SchemaOrgEntity):
    """schema.org Person: adds ``owns`` links and graph-store identity."""

    entity_type: ClassVar[str] = "Person"

    def owns(self, *entity_ids: str) -> None:
        """Set (replace) ``owns`` references to other entities' ``@id``s."""
        refs: List[Dict[str, str]] = [{_JSONLD_ID: eid} for eid in entity_ids]
        self.set_property("owns", refs[0] if len(refs) == 1 else refs)

    def add_owns(self, *entity_ids: str) -> None:
        """Append ``owns`` references, preserving existing ones.

        A single reference stays a scalar dict (schema.org convention);
        further additions grow it into a list. Duplicate ``@id``s are ignored.
        """
        existing = self.get_property("owns")
        refs: List[Dict[str, str]] = (
            [] if existing is None else existing if isinstance(existing, list) else [existing]
        )
        seen = {ref.get(_JSONLD_ID) for ref in refs}
        for eid in entity_ids:
            if eid not in seen:
                seen.add(eid)
                refs.append({_JSONLD_ID: eid})
        self.set_property("owns", refs[0] if len(refs) == 1 else refs)

    @classmethod
    def from_graph_person(
        cls,
        store: GraphStore,
        person_name: str,
        session: Optional[Session] = None,
    ) -> Optional["PersonEntity"]:
        """Build a PersonEntity whose ``@id`` is the graph-store canonical id.

        The person is resolved (or created) through the graph store's
        validation gate; returns ``None`` when the name is rejected.
        """
        close_session = session is None
        session = session or store.get_session()
        try:
            person = store.get_or_create_person(person_name, session=session)
            if person is None:
                return None
            # canonical_id is nullable at the column level but always set by
            # get_or_create_person; regenerate deterministically if absent.
            canonical_id = person.canonical_id or person.generate_canonical_id(person.name)
            entity = cls(entity_id=canonical_id, name=person.name)
            if close_session:
                session.commit()
            return entity
        finally:
            if close_session:
                session.close()
