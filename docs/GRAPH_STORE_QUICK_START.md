# GraphStore Entity Quick Start

How to create and update standalone Schema.org entities in the graph store
(`results/file_organization.db`) using `src/storage/entity_metadata.py`.

Standalone entities (residences, events, people) have no backing file: they
persist as `schema_metadata` rows keyed by their JSON-LD `@id`, with
`schema_type` mirroring `@type`. Run everything from the project root with the
venv active:

```bash
source venv/bin/activate
python  # or a script with: sys.path.insert(0, '<project root>')
```

## Setup

```python
from src.storage.entity_metadata import (
    EventEntity, ImageObjectEntity, LocalBusinessEntity, NGOEntity,
    OrganizationEntity, PersonEntity, PlaceEntity, ResidenceEntity,
    SchemaOrgEntity,
)
from src.storage.graph_store import GraphStore

store = GraphStore()  # defaults to results/file_organization.db
```

Available concrete types (all two-liner subclasses of `SchemaOrgEntity`):

- `PlaceEntity` -> `ResidenceEntity`
- `EventEntity`, `ImageObjectEntity`, `PersonEntity`
- `OrganizationEntity` -> `CorporationEntity`, `EducationalOrganizationEntity`,
  `GovernmentOrganizationEntity`, `NGOEntity`, `PerformingGroupEntity`,
  `SportsOrganizationEntity`, `NewsMediaOrganizationEntity`,
  `PoliticalPartyEntity`, and `LocalBusinessEntity`
- `LocalBusinessEntity` -> all 30 schema.org direct subtypes
  (`DentistEntity`, `FoodEstablishmentEntity`, `StoreEntity`, ...)

## Create an entity

```python
residence = ResidenceEntity("residence-casa-azul", name="Casa Azul")
residence.set_address("1115 Kinney Avenue, #3", "Austin", "TX", "78704")
residence.geocode()          # Nominatim forward-geocode address -> geo (True on success)
residence.set_geo(30.27, -97.68)  # or set coordinates directly
residence.save(store)        # upsert by @id
```

`geocode()` strips trailing unit/suite designators (`#3`, `Suite 108`,
`Apt 2B`, ...) from the lookup — Nominatim can't resolve them — while the
stored `address` keeps the full street.

Any type works via the base class or a two-line subclass:

```python
class LandmarkEntity(SchemaOrgEntity):
    entity_type = "Landmark"

event = EventEntity("event-burning-flipside-2026", name="Burning Flipside")
event.set_property("startDate", "2026-04-23")
event.set_property("endDate", "2026-04-27")
event.set_property("location", {"@type": "Place", "name": "City of Pyropolis"})
event.save(store)
```

## Update an entity

`load` -> mutate -> `save` round-trips the same row (no duplicates):

```python
residence = ResidenceEntity.load(store, "residence-casa-azul")
residence.add_same_as("https://example.com/listing")
residence.add_main_entity_of_page("https://travis.prodigycad.com/property-detail/198226/2026")
residence.set_property("photo", [...])   # arbitrary schema.org properties
residence.save(store)
```

`add_same_as` / `add_main_entity_of_page` keep a single URL scalar, grow to a
deduplicated list on further additions.

To retype an entity (e.g. Organization -> its Corporation subtype), load it
through the target subclass and save — properties carry over, `@type` and the
indexed `schema_type` column update in place:

```python
from src.storage.entity_metadata import CorporationEntity

org = CorporationEntity.load(store, "org-integrity-studio")
org.save(store)   # row now has @type/schema_type "Corporation"
```

## Organizations and businesses

```python
org = OrganizationEntity("org-integrity-studio", name="Integrity Studio")
org.set_property("url", "https://integritystudio.ai")
org.set_property("founder", {"@type": "Person", "@id": alyshia.entity_id, "name": alyshia.name})
org.add_same_as("https://www.linkedin.com/company/integrity-studio-ai")
org.add_same_as("https://github.com/integritystudio")   # sameAs grows to a list
org.save(store)

ngo = NGOEntity("ngo-capital-city-village", name="Capital City Village")
ngo.set_property("taxID", "27-0539952")
ngo.set_property("nonprofitStatus", "Nonprofit501c3")
ngo.set_property("areaServed", {"@type": "City", "name": "Austin"})
ngo.save(store)

biz = LocalBusinessEntity("business-inspired-movement", name="Inspired Movement")
biz.set_property("telephone", "+1 512 920 2182")
biz.set_property("address", {"@type": "PostalAddress", "streetAddress": "4201 S Congress Ave Suite 108", ...})
biz.save(store)
```

`LocalBusinessEntity` extends `OrganizationEntity` (schema.org dual-parents it
with Place; Python forces a pick) — `set_address`/`geocode` are `PlaceEntity`
methods, so on a business either set `address` via `set_property` and borrow a
throwaway `PlaceEntity` for geocoding, or set `geo` directly.

## People and associations

People go through the graph store's name-validation gate so the JSON-LD `@id`
is the person's canonical id (also creating/reusing their `people`-table row):

```python
person = PersonEntity.from_graph_person(store, "Amy Diane Morrow")  # None if rejected
person = PersonEntity.load(store, person.entity_id) or person       # reuse saved row
person.owns("residence-casa-azul")   # ownership lives on Person.owns (schema.org)
person.add_owns("business-inspired-movement")  # append, preserving existing owns
person.add_main_entity_of_page("https://www.linkedin.com/in/amydianemorrow/")
person.set_property("image", {"@id": "image-profile"})  # profile photo (ImageObject @id)
person.save(store)
```

`owns(*ids)` replaces; `add_owns(*ids)` appends with `@id` dedup — use it when
the person already owns something.

Cross-entity links are `{"@id": ...}` references — e.g. an event attendee:

```python
event.set_property("attendee", {"@type": "Person", "@id": person.entity_id, "name": person.name})
```

## Standalone images

For an image file with no `files`-table row (never indexed by
`organize-files content`):

```python
from urllib.parse import quote

image = ImageObjectEntity("image-profile", name="profile.png")
image.set_property("contentUrl", "file://" + quote(str(path)))
image.set_property("encodingFormat", "image/png")
image.set_property("width", 532)   # from PIL Image.open(path).size
image.set_property("height", 684)
image.save(store)
```

For files that ARE indexed, key the entity by the file's canonical id so
references line up: `ImageObjectEntity(file.schema_data["@id"], ...)` —
`save()` is an upsert, so bulk backfills are idempotent.

## Associate indexed images (photo property)

Files indexed by `organize-files content` have `files`-table rows whose
`schema_data` carries a canonical `urn:uuid` `@id`. Reference those ids when
attaching photos so the entity points at graph file identities:

```python
from src.storage.models import File

session = store.get_session()
rows = session.query(File).filter(File.current_path.like("%/Casa Azul/%")).all()
residence.set_property("photo", [
    {
        "@type": "ImageObject",
        "@id": (f.schema_data or {}).get("@id"),
        "name": f.filename,
        "contentUrl": "file://" + f.current_path,
        "encodingFormat": f.mime_type,
    }
    for f in rows
])
residence.save(store)
session.close()
```

If files moved on disk after indexing, repoint rows first with
`store.update_file_status(file_id, FileStatus.ORGANIZED, destination=new_path, ...)`
(and rewrite `schema_data["filePath"]`/`["url"]`, flagging the JSON column
modified with `sqlalchemy.orm.attributes.flag_modified`).

## Export / dashboard

```python
SchemaOrgEntity.export([residence, event], "results/entities.json")
```

The dashboard gallery (`_site/residence_gallery.html`) renders
`_site/residence_gallery.json` — a list of all Residence entities. Refresh it
after entity changes:

```python
import json
from src.storage.models import SchemaMetadata

session = store.get_session()
rows = (session.query(SchemaMetadata)
        .filter(SchemaMetadata.file_id.is_(None))
        .filter(SchemaMetadata.schema_type == "Residence")
        .order_by(SchemaMetadata.id).all())
with open("_site/residence_gallery.json", "w", encoding="utf-8") as f:
    json.dump([r.schema_json for r in rows], f, indent=2, ensure_ascii=False)
session.close()
```

(Dump the stored `schema_json` directly — `from_jsonld` on a *subclass* keeps
the type, but on base `SchemaOrgEntity` it would re-serialize as `Thing`.)

Open the page directly from disk (`open _site/residence_gallery.html`) —
photos use `file://` URLs, which browsers block on http-served pages.

## Inspect

```bash
sqlite3 results/file_organization.db \
  "select id, schema_type, json_extract(schema_json,'\$.\"@id\"'), json_extract(schema_json,'\$.name')
   from schema_metadata where file_id is null;"
```

Tests: `pytest tests/unit/test_entity_metadata.py`
