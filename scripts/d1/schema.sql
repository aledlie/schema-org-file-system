-- D1 Schema for File Organization System
-- Generated from SQLAlchemy models

-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- Enums as string columns with constraints
-- FileStatus: pending, organized, skipped, error, already_organized
-- RelationshipType: duplicate, similar, version, derived, related, parent_child, references

-- Files table (central node)
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  canonical_id TEXT UNIQUE NOT NULL,
  source_ids JSON,
  filename TEXT NOT NULL,
  original_path TEXT NOT NULL,
  current_path TEXT,
  file_extension TEXT,
  mime_type TEXT,
  file_size INTEGER,
  content_hash TEXT,
  created_at DATETIME,
  modified_at DATETIME,
  organized_at DATETIME,
  status TEXT DEFAULT 'pending',
  organization_reason TEXT,
  extracted_text TEXT,
  extracted_text_length INTEGER DEFAULT 0,
  schema_type TEXT,
  schema_data JSON,
  image_width INTEGER,
  image_height INTEGER,
  has_faces BOOLEAN,
  face_count INTEGER,
  image_classification JSON,
  exif_datetime DATETIME,
  gps_latitude REAL,
  gps_longitude REAL,
  processing_time_sec REAL,
  session_id TEXT,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_files_canonical_id ON files(canonical_id);
CREATE INDEX IF NOT EXISTS ix_files_filename ON files(filename);
CREATE INDEX IF NOT EXISTS ix_files_file_extension ON files(file_extension);
CREATE INDEX IF NOT EXISTS ix_files_content_hash ON files(content_hash);
CREATE INDEX IF NOT EXISTS ix_files_status ON files(status);
CREATE INDEX IF NOT EXISTS ix_files_organized_at ON files(organized_at);
CREATE INDEX IF NOT EXISTS ix_files_session_id ON files(session_id);

-- Categories table (hierarchical)
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT UNIQUE NOT NULL,
  source_ids JSON,
  merged_into_id INTEGER,
  name TEXT UNIQUE NOT NULL,
  parent_id INTEGER,
  description TEXT,
  icon TEXT,
  color TEXT,
  level INTEGER DEFAULT 0,
  file_count INTEGER DEFAULT 0,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (parent_id) REFERENCES categories(id),
  FOREIGN KEY (merged_into_id) REFERENCES categories(id)
);

CREATE INDEX IF NOT EXISTS ix_categories_canonical_id ON categories(canonical_id);
CREATE INDEX IF NOT EXISTS ix_categories_name ON categories(name);
CREATE INDEX IF NOT EXISTS ix_categories_parent_id ON categories(parent_id);

-- Companies table
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT UNIQUE NOT NULL,
  source_ids JSON,
  name TEXT NOT NULL,
  normalized_name TEXT UNIQUE NOT NULL,
  website TEXT,
  industry TEXT,
  file_count INTEGER DEFAULT 0,
  last_seen DATETIME,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_companies_canonical_id ON companies(canonical_id);
CREATE INDEX IF NOT EXISTS ix_companies_normalized_name ON companies(normalized_name);

-- People table
CREATE TABLE IF NOT EXISTS people (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT UNIQUE NOT NULL,
  source_ids JSON,
  name TEXT NOT NULL,
  normalized_name TEXT UNIQUE NOT NULL,
  email TEXT,
  role TEXT,
  file_count INTEGER DEFAULT 0,
  last_seen DATETIME,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_people_canonical_id ON people(canonical_id);
CREATE INDEX IF NOT EXISTS ix_people_normalized_name ON people(normalized_name);

-- Locations table
CREATE TABLE IF NOT EXISTS locations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  canonical_id TEXT UNIQUE NOT NULL,
  source_ids JSON,
  name TEXT NOT NULL,
  latitude REAL,
  longitude REAL,
  city TEXT,
  state TEXT,
  country TEXT,
  file_count INTEGER DEFAULT 0,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_locations_canonical_id ON locations(canonical_id);
CREATE INDEX IF NOT EXISTS ix_locations_name ON locations(name);

-- Many-to-many: Files <-> Categories
CREATE TABLE IF NOT EXISTS file_categories (
  file_id TEXT NOT NULL,
  category_id INTEGER NOT NULL,
  confidence REAL DEFAULT 1.0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (file_id, category_id),
  FOREIGN KEY (file_id) REFERENCES files(id),
  FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE INDEX IF NOT EXISTS ix_file_categories_category_id ON file_categories(category_id);

-- Many-to-many: Files <-> Companies
CREATE TABLE IF NOT EXISTS file_companies (
  file_id TEXT NOT NULL,
  company_id INTEGER NOT NULL,
  confidence REAL DEFAULT 1.0,
  context TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (file_id, company_id),
  FOREIGN KEY (file_id) REFERENCES files(id),
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS ix_file_companies_company_id ON file_companies(company_id);

-- Many-to-many: Files <-> People
CREATE TABLE IF NOT EXISTS file_people (
  file_id TEXT NOT NULL,
  person_id INTEGER NOT NULL,
  role TEXT,
  confidence REAL DEFAULT 1.0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (file_id, person_id),
  FOREIGN KEY (file_id) REFERENCES files(id),
  FOREIGN KEY (person_id) REFERENCES people(id)
);

CREATE INDEX IF NOT EXISTS ix_file_people_person_id ON file_people(person_id);

-- Many-to-many: Files <-> Locations
CREATE TABLE IF NOT EXISTS file_locations (
  file_id TEXT NOT NULL,
  location_id INTEGER NOT NULL,
  location_type TEXT,
  confidence REAL DEFAULT 1.0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (file_id, location_id),
  FOREIGN KEY (file_id) REFERENCES files(id),
  FOREIGN KEY (location_id) REFERENCES locations(id)
);

CREATE INDEX IF NOT EXISTS ix_file_locations_location_id ON file_locations(location_id);

-- File relationships (graph edges)
CREATE TABLE IF NOT EXISTS file_relationships (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_file_id TEXT NOT NULL,
  target_file_id TEXT NOT NULL,
  relationship_type TEXT NOT NULL,
  confidence REAL DEFAULT 1.0,
  metadata JSON,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (source_file_id) REFERENCES files(id),
  FOREIGN KEY (target_file_id) REFERENCES files(id),
  UNIQUE (source_file_id, target_file_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS ix_file_relationships_source ON file_relationships(source_file_id);
CREATE INDEX IF NOT EXISTS ix_file_relationships_target ON file_relationships(target_file_id);
CREATE INDEX IF NOT EXISTS ix_file_relationships_type ON file_relationships(relationship_type);

-- Organization sessions
CREATE TABLE IF NOT EXISTS organization_sessions (
  id TEXT PRIMARY KEY,
  source_directories JSON,
  base_path TEXT NOT NULL,
  dry_run BOOLEAN DEFAULT 0,
  file_limit INTEGER,
  total_files INTEGER DEFAULT 0,
  organized_count INTEGER DEFAULT 0,
  skipped_count INTEGER DEFAULT 0,
  error_count INTEGER DEFAULT 0,
  total_cost REAL DEFAULT 0.0,
  total_processing_time_sec REAL DEFAULT 0.0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME
);

CREATE INDEX IF NOT EXISTS ix_organization_sessions_created_at ON organization_sessions(created_at);

-- Cost records
CREATE TABLE IF NOT EXISTS cost_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT,
  file_id TEXT,
  feature_name TEXT NOT NULL,
  cost REAL NOT NULL,
  processing_time_sec REAL DEFAULT 0.0,
  success BOOLEAN DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (session_id) REFERENCES organization_sessions(id),
  FOREIGN KEY (file_id) REFERENCES files(id)
);

CREATE INDEX IF NOT EXISTS ix_cost_records_session_id ON cost_records(session_id);
CREATE INDEX IF NOT EXISTS ix_cost_records_feature_name ON cost_records(feature_name);
CREATE INDEX IF NOT EXISTS ix_cost_records_created_at ON cost_records(created_at);

-- Schema metadata
CREATE TABLE IF NOT EXISTS schema_metadata (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id TEXT UNIQUE NOT NULL,
  schema_version TEXT,
  schema_context JSON,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (file_id) REFERENCES files(id)
);

-- Key-value store for flexible metadata
CREATE TABLE IF NOT EXISTS key_value_store (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  key TEXT UNIQUE NOT NULL,
  value JSON,
  db_created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  db_updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
