#!/usr/bin/env python3
"""
Schema.org REST API endpoints.

Provides JSON-LD representations of entities in schema.org format.
Supports single entity retrieval and bulk export with filtering.
"""

from typing import Dict, Any, Iterator, cast
from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session, selectinload, joinedload

# Routes keep an explicit response_model=Dict[str, Any]; deleting it would
# make these return annotations the OpenAPI/serialization schema.
from src.schema_types import GraphDocument, SchemaMapping

from storage.models import (
    File, Category, Company, Person, Location
)
from storage.models import get_session
from storage.schema_org_exporter import SchemaOrgExporter
from storage.schema_org_context import get_context_document
from api.schema_org_models import (
    FileFilterParams, CategoryFilterParams, CompanyFilterParams,
    PersonFilterParams, LocationFilterParams, BulkExportParams,
    ErrorResponse
)


# Create FastAPI app
app = FastAPI(
    title="Schema.org API",
    description="JSON-LD representations of file system entities",
    version="2.1.0",
    responses={
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
    }
)


# Dependency for database session
def get_db() -> Iterator[Session]:
    """Get database session."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


# File Endpoints
@app.get("/api/files/{file_id}/schema-org", response_model=Dict[str, Any])
async def get_file_schema_org(
    file_id: str,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get File as schema.org JSON-LD.

    Returns:
        File entity as schema.org JSON-LD with @context, @type, @id
    """
    file = db.query(File).filter(File.id == file_id).first()
    if not file:
        raise HTTPException(status_code=404, detail=f"File {file_id} not found")

    return cast(SchemaMapping, file.to_schema_org())


@app.get("/api/files/schema-org/bulk", response_model=Dict[str, Any])
async def get_files_schema_org_bulk(
    params: FileFilterParams = Depends(),
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Get multiple Files as schema.org JSON-LD.

    Args:
        params: Pagination and filter parameters

    Returns:
        JSON-LD document with @context and @graph containing matching File entities
    """
    query = db.query(File)

    if params.mime_type:
        query = query.filter(File.mime_type == params.mime_type)

    files = query.options(
        selectinload(File.categories),
        selectinload(File.companies),
        selectinload(File.people),
        selectinload(File.locations),
    ).offset(params.skip).limit(params.limit).all()
    return {
        "@context": get_context_document()["@context"],
        "@graph": [file.to_schema_org() for file in files],
    }


# Category Endpoints
@app.get("/api/categories/{category_id}/schema-org", response_model=Dict[str, Any])
async def get_category_schema_org(
    category_id: int,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Category as schema.org JSON-LD (DefinedTerm).

    Returns:
        Category entity as schema.org JSON-LD
    """
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")

    return cast(SchemaMapping, category.to_schema_org())


@app.get("/api/categories/schema-org/bulk", response_model=Dict[str, Any])
async def get_categories_schema_org_bulk(
    params: CategoryFilterParams = Depends(),
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Get multiple Categories as schema.org JSON-LD.

    Args:
        params: Pagination and filter parameters

    Returns:
        JSON-LD document with @context and @graph containing matching Category entities
    """
    query = db.query(Category)

    if params.level is not None:
        query = query.filter(Category.level == params.level)

    categories = query.options(
        selectinload(Category.files),
        joinedload(Category.parent),
        selectinload(Category.subcategories),
    ).offset(params.skip).limit(params.limit).all()
    return {
        "@context": get_context_document()["@context"],
        "@graph": [category.to_schema_org() for category in categories],
    }


# Company Endpoints
@app.get("/api/companies/{company_id}/schema-org", response_model=Dict[str, Any])
async def get_company_schema_org(
    company_id: int,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Company as schema.org JSON-LD (Organization).

    Returns:
        Company entity as schema.org JSON-LD
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company {company_id} not found")

    return cast(SchemaMapping, company.to_schema_org())


@app.get("/api/companies/schema-org/by-name/{name}", response_model=Dict[str, Any])
async def get_company_by_name_schema_org(
    name: str,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Company by name as schema.org JSON-LD.

    Args:
        name: Company name

    Returns:
        Company entity as schema.org JSON-LD
    """
    company = db.query(Company).filter(Company.normalized_name == name.lower().strip()).first()
    if not company:
        raise HTTPException(status_code=404, detail=f"Company '{name}' not found")

    return cast(SchemaMapping, company.to_schema_org())


@app.get("/api/companies/schema-org/bulk", response_model=Dict[str, Any])
async def get_companies_schema_org_bulk(
    params: CompanyFilterParams = Depends(),
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Get multiple Companies as schema.org JSON-LD.

    Args:
        params: Pagination and filter parameters

    Returns:
        JSON-LD document with @context and @graph containing matching Company entities
    """
    query = db.query(Company)

    if params.industry:
        query = query.filter(Company.industry == params.industry)

    companies = query.options(
        selectinload(Company.files),
    ).offset(params.skip).limit(params.limit).all()
    return {
        "@context": get_context_document()["@context"],
        "@graph": [company.to_schema_org() for company in companies],
    }


# Person Endpoints
@app.get("/api/people/{person_id}/schema-org", response_model=Dict[str, Any])
async def get_person_schema_org(
    person_id: int,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Person as schema.org JSON-LD.

    Returns:
        Person entity as schema.org JSON-LD
    """
    person = db.query(Person).filter(Person.id == person_id).first()
    if not person:
        raise HTTPException(status_code=404, detail=f"Person {person_id} not found")

    return cast(SchemaMapping, person.to_schema_org())


@app.get("/api/people/schema-org/by-name/{name}", response_model=Dict[str, Any])
async def get_person_by_name_schema_org(
    name: str,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Person by name as schema.org JSON-LD.

    Args:
        name: Person name

    Returns:
        Person entity as schema.org JSON-LD
    """
    person = db.query(Person).filter(Person.normalized_name == name.lower().strip()).first()
    if not person:
        raise HTTPException(status_code=404, detail=f"Person '{name}' not found")

    return cast(SchemaMapping, person.to_schema_org())


@app.get("/api/people/schema-org/bulk", response_model=Dict[str, Any])
async def get_people_schema_org_bulk(
    params: PersonFilterParams = Depends(),
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Get multiple People as schema.org JSON-LD.

    Args:
        params: Pagination and filter parameters

    Returns:
        JSON-LD document with @context and @graph containing matching Person entities
    """
    query = db.query(Person)

    if params.role:
        query = query.filter(Person.role == params.role)

    people = query.options(
        selectinload(Person.files),
    ).offset(params.skip).limit(params.limit).all()
    return {
        "@context": get_context_document()["@context"],
        "@graph": [person.to_schema_org() for person in people],
    }


# Location Endpoints
@app.get("/api/locations/{location_id}/schema-org", response_model=Dict[str, Any])
async def get_location_schema_org(
    location_id: int,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Location as schema.org JSON-LD (Place).

    Returns:
        Location entity as schema.org JSON-LD
    """
    location = db.query(Location).filter(Location.id == location_id).first()
    if not location:
        raise HTTPException(status_code=404, detail=f"Location {location_id} not found")

    return cast(SchemaMapping, location.to_schema_org())


@app.get("/api/locations/schema-org/by-name/{name}", response_model=Dict[str, Any])
async def get_location_by_name_schema_org(
    name: str,
    db: Session = Depends(get_db)
) -> SchemaMapping:
    """
    Get Location by name as schema.org JSON-LD.

    Args:
        name: Location name

    Returns:
        Location entity as schema.org JSON-LD
    """
    location = db.query(Location).filter(Location.name == name).first()
    if not location:
        raise HTTPException(status_code=404, detail=f"Location '{name}' not found")

    return cast(SchemaMapping, location.to_schema_org())


@app.get("/api/locations/schema-org/bulk", response_model=Dict[str, Any])
async def get_locations_schema_org_bulk(
    params: LocationFilterParams = Depends(),
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Get multiple Locations as schema.org JSON-LD.

    Args:
        params: Pagination and filter parameters

    Returns:
        JSON-LD document with @context and @graph containing matching Location entities
    """
    query = db.query(Location)

    if params.country:
        query = query.filter(Location.country == params.country)

    locations = query.options(
        selectinload(Location.files),
    ).offset(params.skip).limit(params.limit).all()
    return {
        "@context": get_context_document()["@context"],
        "@graph": [location.to_schema_org() for location in locations],
    }


# Bulk Export Endpoint
@app.get("/api/schema-org/export", response_model=Dict[str, Any])
async def export_all_entities_schema_org(
    params: BulkExportParams = Depends(),
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Export all entities as schema.org JSON-LD @graph document.

    Args:
        params: Export parameters (entity_types)

    Returns:
        JSON-LD document with @context and @graph keys containing all matching entities
    """
    entity_types_list = [t.strip().lower() for t in params.entity_types.split(",")]

    entity_classes = []
    if "all" in entity_types_list or "file" in entity_types_list:
        entity_classes.append(File)
    if "all" in entity_types_list or "category" in entity_types_list:
        entity_classes.append(Category)
    if "all" in entity_types_list or "company" in entity_types_list:
        entity_classes.append(Company)
    if "all" in entity_types_list or "person" in entity_types_list:
        entity_classes.append(Person)
    if "all" in entity_types_list or "location" in entity_types_list:
        entity_classes.append(Location)

    exporter = SchemaOrgExporter(db)
    return cast(GraphDocument, exporter.get_graph_document(entity_classes=entity_classes or None))


# Graph Export Endpoint
@app.get("/api/schema-org/graph", response_model=Dict[str, Any])
async def get_full_graph_document(
    db: Session = Depends(get_db)
) -> GraphDocument:
    """
    Return a full JSON-LD @graph document for all entity types.

    Returns:
        JSON-LD document with @context and @graph containing all entities
    """
    exporter = SchemaOrgExporter(db)
    return cast(GraphDocument, exporter.get_graph_document())


# Context Endpoint
@app.get("/schema/context", response_model=Dict[str, Any])
async def get_schema_context() -> SchemaMapping:
    """
    Return the JSON-LD @context document for this API.

    Returns:
        Standalone JSON-LD context document mapping all schema.org and custom terms
    """
    return cast(SchemaMapping, get_context_document())


# Health Check
@app.get("/health")
async def health_check() -> Dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
