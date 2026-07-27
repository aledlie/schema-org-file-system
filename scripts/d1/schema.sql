-- D1 Schema for File Organization System
-- Auto-generated from src/storage/models.py — do not hand-edit.
-- Regenerate: python scripts/d1/generate_schema.py

-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- categories

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER NOT NULL, 
  canonical_id VARCHAR(36), 
  source_ids JSON, 
  merged_into_id INTEGER, 
  name VARCHAR(100) NOT NULL, 
  parent_id INTEGER, 
  description TEXT, 
  icon VARCHAR(50), 
  color VARCHAR(20), 
  level INTEGER, 
  full_path VARCHAR(255), 
  created_at DATETIME, 
  updated_at DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(merged_into_id) REFERENCES categories (id), 
  FOREIGN KEY(parent_id) REFERENCES categories (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_categories_canonical_id ON categories (canonical_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_categories_full_path ON categories (full_path);
CREATE INDEX IF NOT EXISTS ix_categories_name ON categories (name);
CREATE INDEX IF NOT EXISTS ix_categories_parent_id ON categories (parent_id);

-- companies

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER NOT NULL, 
  canonical_id VARCHAR(36), 
  source_ids JSON, 
  merged_into_id INTEGER, 
  name VARCHAR(255) NOT NULL, 
  normalized_name VARCHAR(255), 
  domain VARCHAR(255), 
  industry VARCHAR(100), 
  first_seen DATETIME, 
  last_seen DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(merged_into_id) REFERENCES companies (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_canonical_id ON companies (canonical_id);
CREATE INDEX IF NOT EXISTS ix_companies_name ON companies (name);
CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_normalized_name ON companies (normalized_name);

-- locations

CREATE TABLE IF NOT EXISTS locations (
  id INTEGER NOT NULL, 
  canonical_id VARCHAR(36), 
  source_ids JSON, 
  merged_into_id INTEGER, 
  name VARCHAR(255) NOT NULL, 
  city VARCHAR(100), 
  state VARCHAR(100), 
  country VARCHAR(100), 
  latitude FLOAT, 
  longitude FLOAT, 
  geohash VARCHAR(12), 
  created_at DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(merged_into_id) REFERENCES locations (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_locations_canonical_id ON locations (canonical_id);
CREATE INDEX IF NOT EXISTS ix_locations_city_state ON locations (city, state);
CREATE INDEX IF NOT EXISTS ix_locations_geo ON locations (latitude, longitude);
CREATE INDEX IF NOT EXISTS ix_locations_geohash ON locations (geohash);
CREATE INDEX IF NOT EXISTS ix_locations_name ON locations (name);

-- merge_events

CREATE TABLE IF NOT EXISTS merge_events (
  id VARCHAR(36) NOT NULL, 
  target_entity_type VARCHAR(8) NOT NULL, 
  target_entity_id INTEGER NOT NULL, 
  target_canonical_id VARCHAR(36), 
  source_entity_ids JSON NOT NULL, 
  source_canonical_ids JSON, 
  merge_reason TEXT, 
  confidence FLOAT, 
  performed_by VARCHAR(100), 
  performed_at DATETIME, 
  jsonld JSON, 
  is_rolled_back BOOLEAN, 
  rolled_back_at DATETIME, 
  rolled_back_by VARCHAR(100), 
  PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_merge_entity_type ON merge_events (target_entity_type);
CREATE INDEX IF NOT EXISTS ix_merge_performed_at ON merge_events (performed_at);

-- organization_sessions

CREATE TABLE IF NOT EXISTS organization_sessions (
  id VARCHAR(64) NOT NULL, 
  started_at DATETIME, 
  completed_at DATETIME, 
  dry_run BOOLEAN, 
  source_directories JSON, 
  base_path VARCHAR(500), 
  file_limit INTEGER, 
  total_files INTEGER, 
  organized_count INTEGER, 
  skipped_count INTEGER, 
  error_count INTEGER, 
  total_cost FLOAT, 
  total_processing_time_sec FLOAT, 
  PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_organization_sessions_started_at ON organization_sessions (started_at);

-- people

CREATE TABLE IF NOT EXISTS people (
  id INTEGER NOT NULL, 
  canonical_id VARCHAR(36), 
  source_ids JSON, 
  merged_into_id INTEGER, 
  name VARCHAR(255) NOT NULL, 
  normalized_name VARCHAR(255), 
  email VARCHAR(255), 
  role VARCHAR(100), 
  review_status VARCHAR(20) DEFAULT 'auto_accepted', 
  detection_confidence FLOAT, 
  validation_scores JSON DEFAULT '{}', 
  validated_at DATETIME, 
  first_seen DATETIME, 
  last_seen DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(merged_into_id) REFERENCES people (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_people_canonical_id ON people (canonical_id);
CREATE INDEX IF NOT EXISTS ix_people_name ON people (name);
CREATE UNIQUE INDEX IF NOT EXISTS ix_people_normalized_name ON people (normalized_name);
CREATE INDEX IF NOT EXISTS ix_people_review_status ON people (review_status);

-- files

CREATE TABLE IF NOT EXISTS files (
  id VARCHAR(64) NOT NULL, 
  canonical_id VARCHAR(100), 
  source_ids JSON, 
  filename VARCHAR(255) NOT NULL, 
  original_path TEXT NOT NULL, 
  current_path TEXT, 
  file_extension VARCHAR(20), 
  mime_type VARCHAR(100), 
  file_size INTEGER, 
  content_hash VARCHAR(64), 
  created_at DATETIME, 
  modified_at DATETIME, 
  organized_at DATETIME, 
  status VARCHAR(17), 
  organization_reason TEXT, 
  extracted_text TEXT, 
  extracted_text_length INTEGER, 
  ocr_confidence FLOAT, 
  detected_language VARCHAR(10), 
  schema_type VARCHAR(50), 
  schema_data JSON, 
  kie_fields JSON, 
  image_width INTEGER, 
  image_height INTEGER, 
  has_faces BOOLEAN, 
  face_count INTEGER, 
  image_classification JSON, 
  exif_datetime DATETIME, 
  gps_latitude FLOAT, 
  gps_longitude FLOAT, 
  processing_time_sec FLOAT, 
  session_id VARCHAR(64), 
  db_created_at DATETIME, 
  db_updated_at DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(session_id) REFERENCES organization_sessions (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_files_canonical_id ON files (canonical_id);
CREATE INDEX IF NOT EXISTS ix_files_content_hash ON files (content_hash);
CREATE INDEX IF NOT EXISTS ix_files_file_extension ON files (file_extension);
CREATE INDEX IF NOT EXISTS ix_files_filename ON files (filename);
CREATE INDEX IF NOT EXISTS ix_files_organized_at ON files (organized_at);
CREATE INDEX IF NOT EXISTS ix_files_session_id ON files (session_id);
CREATE INDEX IF NOT EXISTS ix_files_status ON files (status);

-- cost_records

CREATE TABLE IF NOT EXISTS cost_records (
  id INTEGER NOT NULL, 
  session_id VARCHAR(64), 
  file_id VARCHAR(64), 
  feature_name VARCHAR(50) NOT NULL, 
  processing_time_sec FLOAT NOT NULL, 
  cost FLOAT, 
  success BOOLEAN, 
  error_message TEXT, 
  created_at DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(session_id) REFERENCES organization_sessions (id), 
  FOREIGN KEY(file_id) REFERENCES files (id)
);
CREATE INDEX IF NOT EXISTS ix_cost_feature_date ON cost_records (feature_name, created_at);
CREATE INDEX IF NOT EXISTS ix_cost_records_created_at ON cost_records (created_at);
CREATE INDEX IF NOT EXISTS ix_cost_records_feature_name ON cost_records (feature_name);
CREATE INDEX IF NOT EXISTS ix_cost_records_file_id ON cost_records (file_id);
CREATE INDEX IF NOT EXISTS ix_cost_records_session_id ON cost_records (session_id);

-- file_categories

CREATE TABLE IF NOT EXISTS file_categories (
  file_id VARCHAR(64) NOT NULL, 
  category_id INTEGER NOT NULL, 
  confidence FLOAT, 
  signal_evidence JSON, 
  created_at DATETIME, 
  PRIMARY KEY (file_id, category_id), 
  FOREIGN KEY(file_id) REFERENCES files (id), 
  FOREIGN KEY(category_id) REFERENCES categories (id)
);
CREATE INDEX IF NOT EXISTS ix_file_categories_category_id ON file_categories (category_id);

-- file_companies

CREATE TABLE IF NOT EXISTS file_companies (
  file_id VARCHAR(64) NOT NULL, 
  company_id INTEGER NOT NULL, 
  confidence FLOAT, 
  context VARCHAR(255), 
  created_at DATETIME, 
  PRIMARY KEY (file_id, company_id), 
  FOREIGN KEY(file_id) REFERENCES files (id), 
  FOREIGN KEY(company_id) REFERENCES companies (id)
);
CREATE INDEX IF NOT EXISTS ix_file_companies_company_id ON file_companies (company_id);

-- file_locations

CREATE TABLE IF NOT EXISTS file_locations (
  file_id VARCHAR(64) NOT NULL, 
  location_id INTEGER NOT NULL, 
  location_type VARCHAR(50), 
  confidence FLOAT, 
  created_at DATETIME, 
  PRIMARY KEY (file_id, location_id), 
  FOREIGN KEY(file_id) REFERENCES files (id), 
  FOREIGN KEY(location_id) REFERENCES locations (id)
);
CREATE INDEX IF NOT EXISTS ix_file_locations_location_id ON file_locations (location_id);

-- file_people

CREATE TABLE IF NOT EXISTS file_people (
  file_id VARCHAR(64) NOT NULL, 
  person_id INTEGER NOT NULL, 
  role VARCHAR(50), 
  confidence FLOAT, 
  created_at DATETIME, 
  PRIMARY KEY (file_id, person_id), 
  FOREIGN KEY(file_id) REFERENCES files (id), 
  FOREIGN KEY(person_id) REFERENCES people (id)
);
CREATE INDEX IF NOT EXISTS ix_file_people_person_id ON file_people (person_id);

-- file_relationships

CREATE TABLE IF NOT EXISTS file_relationships (
  id INTEGER NOT NULL, 
  source_file_id VARCHAR(64) NOT NULL, 
  target_file_id VARCHAR(64) NOT NULL, 
  relationship_type VARCHAR(12) NOT NULL, 
  confidence FLOAT, 
  extra_data JSON, 
  created_at DATETIME, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_file_relationship UNIQUE (source_file_id, target_file_id, relationship_type), 
  FOREIGN KEY(source_file_id) REFERENCES files (id), 
  FOREIGN KEY(target_file_id) REFERENCES files (id)
);
CREATE INDEX IF NOT EXISTS ix_file_relationships_relationship_type ON file_relationships (relationship_type);
CREATE INDEX IF NOT EXISTS ix_file_relationships_source_file_id ON file_relationships (source_file_id);
CREATE INDEX IF NOT EXISTS ix_file_relationships_target_file_id ON file_relationships (target_file_id);

-- key_value_store

CREATE TABLE IF NOT EXISTS key_value_store (
  id INTEGER NOT NULL, 
  namespace VARCHAR(50) NOT NULL, 
  "key" VARCHAR(255) NOT NULL, 
  value JSON, 
  value_type VARCHAR(20), 
  file_id VARCHAR(64), 
  expires_at DATETIME, 
  created_at DATETIME, 
  updated_at DATETIME, 
  PRIMARY KEY (id), 
  CONSTRAINT uq_namespace_key UNIQUE (namespace, "key"), 
  FOREIGN KEY(file_id) REFERENCES files (id)
);
CREATE INDEX IF NOT EXISTS ix_key_value_store_file_id ON key_value_store (file_id);
CREATE INDEX IF NOT EXISTS ix_key_value_store_namespace ON key_value_store (namespace);
CREATE INDEX IF NOT EXISTS ix_kv_expires ON key_value_store (expires_at);
CREATE INDEX IF NOT EXISTS ix_kv_namespace_key ON key_value_store (namespace, "key");

-- schema_metadata

CREATE TABLE IF NOT EXISTS schema_metadata (
  id INTEGER NOT NULL, 
  file_id VARCHAR(64), 
  schema_type VARCHAR(50), 
  schema_context VARCHAR(255), 
  schema_json JSON NOT NULL, 
  is_valid BOOLEAN, 
  validation_errors JSON, 
  created_at DATETIME, 
  updated_at DATETIME, 
  PRIMARY KEY (id), 
  FOREIGN KEY(file_id) REFERENCES files (id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_schema_metadata_file_id ON schema_metadata (file_id);
CREATE INDEX IF NOT EXISTS ix_schema_metadata_schema_type ON schema_metadata (schema_type);

