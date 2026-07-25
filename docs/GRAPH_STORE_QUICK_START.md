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
    EventEntity, PersonEntity, PlaceEntity, ResidenceEntity, SchemaOrgEntity,
)
from src.storage.graph_store import GraphStore

store = GraphStore()  # defaults to results/file_organization.db
```

## Create an entity

```python
residence = ResidenceEntity("residence-casa-azul", name="Casa Azul")
residence.set_address("1117 Delano St", "Austin", "TX", "78721-2101")
residence.geocode()          # Nominatim forward-geocode address -> geo (True on success)
residence.set_geo(30.27, -97.68)  # or set coordinates directly
residence.save(store)        # upsert by @id
```

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

## People and associations

People go through the graph store's name-validation gate so the JSON-LD `@id`
is the person's canonical id (also creating/reusing their `people`-table row):

```python
person = PersonEntity.from_graph_person(store, "Amy Diane Morrow")  # None if rejected
person = PersonEntity.load(store, person.entity_id) or person       # reuse saved row
person.owns("residence-casa-azul")   # ownership lives on Person.owns (schema.org)
person.add_main_entity_of_page("https://www.linkedin.com/in/amydianemorrow/")
person.save(store)
```

Cross-entity links are `{"@id": ...}` references — e.g. an event attendee:

```python
event.set_property("attendee", {"@type": "Person", "@id": person.entity_id, "name": person.name})
```

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
