-- SQL Schema for Exomiser Application
-- Generated from Flask-SQLAlchemy models
-- Date: 29 September 2025

-- Users table
CREATE TABLE users (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL,
    full_name VARCHAR(120),
    is_active BOOLEAN NOT NULL DEFAULT 1,
    is_admin BOOLEAN NOT NULL DEFAULT 0,
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    deleted_at DATETIME,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on email for faster lookups
CREATE UNIQUE INDEX ix_users_email ON users (email);

-- Individuals table
CREATE TABLE individuals (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    identity VARCHAR(50) NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    sex VARCHAR(10) NOT NULL DEFAULT 'UNKNOWN', -- MALE, FEMALE, OTHER, UNKNOWN
    age_years INTEGER NOT NULL,
    age_months INTEGER NOT NULL DEFAULT 0,      -- Additional months (0-11)
    medical_history TEXT,
    diagnosis VARCHAR(255),
    vcf_file_path VARCHAR(255) NOT NULL,
    vcf_filename VARCHAR(255), -- Original filename at upload time
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    deleted_at DATETIME,
    created_by INTEGER NOT NULL,
    updated_by INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key constraints
    FOREIGN KEY(created_by) REFERENCES users (id),
    FOREIGN KEY(updated_by) REFERENCES users (id)
);

-- Create index on identity for faster individual lookups
CREATE INDEX ix_individuals_identity ON individuals (identity);

-- Analyses table
CREATE TABLE analyses (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    individual_id INTEGER NOT NULL,
    hpo_terms TEXT,            -- JSON array: [{"id":"HP:0001250","label":"Seizures"},...]
    phenopacket_yaml TEXT,     -- Generated GA4GH Phenopacket v1.0 YAML
    name VARCHAR(120) NOT NULL,
    description TEXT,
    genome_assembly VARCHAR(10) NOT NULL DEFAULT 'hg19', -- hg19, hg38
    analysis_mode VARCHAR(50) DEFAULT 'PASS_ONLY',
    frequency_threshold REAL DEFAULT 1.0,
    pathogenicity_threshold REAL DEFAULT 0.5,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    output_html VARCHAR(500),
    output_vcf VARCHAR(500),
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT,
    log TEXT,                  -- Complete process output log for debugging
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    deleted_at DATETIME,
    created_by INTEGER NOT NULL,
    updated_by INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key constraints
    FOREIGN KEY(individual_id) REFERENCES individuals (id),
    FOREIGN KEY(created_by) REFERENCES users (id),
    FOREIGN KEY(updated_by) REFERENCES users (id)
);

-- Create a default admin user (password is 'admin123')
-- Password hash generated with werkzeug.security.generate_password_hash('admin123')
INSERT INTO users (
    email,
    password_hash,
    full_name,
    is_active,
    is_admin,
    created_at,
    updated_at
) VALUES (
    'admin@exomiser.local',
    'pbkdf2:sha256:1000000$SUVqCFHToYApqo3F$c86388c7f66826a42738a0382b1580d75dc314e1c18772081c1e1da82cf91f2b',
    'System Administrator',
    1,
    1,
    datetime('now'),
    datetime('now')
);

-- ── History tables ───────────────────────────────────────────────────────
-- Full row snapshot on every INSERT, UPDATE, DELETE.
-- log and phenopacket_yaml excluded from analyses_history (large fields).

CREATE TABLE users_history (
    history_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    operation     VARCHAR(10) NOT NULL,   -- INSERT, UPDATE, DELETE
    changed_at    DATETIME    NOT NULL,
    id            INTEGER     NOT NULL,
    email         VARCHAR(120),
    password_hash VARCHAR(256),
    full_name     VARCHAR(120),
    is_active     BOOLEAN,
    is_admin      BOOLEAN,
    is_deleted    BOOLEAN,
    deleted_at    DATETIME,
    created_at    DATETIME,
    updated_at    DATETIME
);
CREATE INDEX ix_users_history_id ON users_history (id);

CREATE TABLE individuals_history (
    history_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    operation       VARCHAR(10) NOT NULL,
    changed_at      DATETIME    NOT NULL,
    id              INTEGER     NOT NULL,
    identity        VARCHAR(50),
    full_name       VARCHAR(120),
    sex             VARCHAR(10),
    age_years       INTEGER,
    age_months      INTEGER,
    medical_history TEXT,
    diagnosis       VARCHAR(255),
    vcf_filename    VARCHAR(255),
    vcf_file_path   VARCHAR(255),
    is_deleted      BOOLEAN,
    deleted_at      DATETIME,
    created_by      INTEGER,
    updated_by      INTEGER,
    created_at      DATETIME,
    updated_at      DATETIME
);
CREATE INDEX ix_individuals_history_id ON individuals_history (id);

CREATE TABLE analyses_history (
    history_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    operation               VARCHAR(10) NOT NULL,
    changed_at              DATETIME    NOT NULL,
    id                      INTEGER     NOT NULL,
    individual_id           INTEGER,
    hpo_terms               TEXT,
    name                    VARCHAR(120),
    description             TEXT,
    genome_assembly         VARCHAR(10),
    analysis_mode           VARCHAR(50),
    frequency_threshold     REAL,
    pathogenicity_threshold REAL,
    status                  VARCHAR(20),
    output_html             VARCHAR(500),
    output_vcf              VARCHAR(500),
    started_at              DATETIME,
    completed_at            DATETIME,
    error_message           TEXT,
    -- log excluded (large debug output)
    -- phenopacket_yaml excluded (large YAML document)
    is_deleted              BOOLEAN,
    deleted_at              DATETIME,
    created_by              INTEGER,
    updated_by              INTEGER,
    created_at              DATETIME,
    updated_at              DATETIME
);
CREATE INDEX ix_analyses_history_id ON analyses_history (id);

-- ── History triggers ─────────────────────────────────────────────────────
-- Note: updated_at triggers removed — SQLAlchemy handles updated_at via
-- onupdate=datetime.utcnow. Keeping them would cause updated_at
-- discrepancies in history rows.

-- users
CREATE TRIGGER users_history_insert AFTER INSERT ON users FOR EACH ROW
BEGIN INSERT INTO users_history (operation, changed_at, id, email, password_hash, full_name, is_active, is_admin, is_deleted, deleted_at, created_at, updated_at) VALUES ('INSERT', datetime('now'), NEW.id, NEW.email, NEW.password_hash, NEW.full_name, NEW.is_active, NEW.is_admin, NEW.is_deleted, NEW.deleted_at, NEW.created_at, NEW.updated_at); END;

CREATE TRIGGER users_history_update AFTER UPDATE ON users FOR EACH ROW
BEGIN INSERT INTO users_history (operation, changed_at, id, email, password_hash, full_name, is_active, is_admin, is_deleted, deleted_at, created_at, updated_at) VALUES ('UPDATE', datetime('now'), NEW.id, NEW.email, NEW.password_hash, NEW.full_name, NEW.is_active, NEW.is_admin, NEW.is_deleted, NEW.deleted_at, NEW.created_at, NEW.updated_at); END;

CREATE TRIGGER users_history_delete AFTER DELETE ON users FOR EACH ROW
BEGIN INSERT INTO users_history (operation, changed_at, id, email, password_hash, full_name, is_active, is_admin, is_deleted, deleted_at, created_at, updated_at) VALUES ('DELETE', datetime('now'), OLD.id, OLD.email, OLD.password_hash, OLD.full_name, OLD.is_active, OLD.is_admin, OLD.is_deleted, OLD.deleted_at, OLD.created_at, OLD.updated_at); END;

-- individuals
CREATE TRIGGER individuals_history_insert AFTER INSERT ON individuals FOR EACH ROW
BEGIN INSERT INTO individuals_history (operation, changed_at, id, identity, full_name, sex, age_years, age_months, medical_history, diagnosis, vcf_filename, vcf_file_path, is_deleted, deleted_at, created_by, updated_by, created_at, updated_at) VALUES ('INSERT', datetime('now'), NEW.id, NEW.identity, NEW.full_name, NEW.sex, NEW.age_years, NEW.age_months, NEW.medical_history, NEW.diagnosis, NEW.vcf_filename, NEW.vcf_file_path, NEW.is_deleted, NEW.deleted_at, NEW.created_by, NEW.updated_by, NEW.created_at, NEW.updated_at); END;

CREATE TRIGGER individuals_history_update AFTER UPDATE ON individuals FOR EACH ROW
BEGIN INSERT INTO individuals_history (operation, changed_at, id, identity, full_name, sex, age_years, age_months, medical_history, diagnosis, vcf_filename, vcf_file_path, is_deleted, deleted_at, created_by, updated_by, created_at, updated_at) VALUES ('UPDATE', datetime('now'), NEW.id, NEW.identity, NEW.full_name, NEW.sex, NEW.age_years, NEW.age_months, NEW.medical_history, NEW.diagnosis, NEW.vcf_filename, NEW.vcf_file_path, NEW.is_deleted, NEW.deleted_at, NEW.created_by, NEW.updated_by, NEW.created_at, NEW.updated_at); END;

CREATE TRIGGER individuals_history_delete AFTER DELETE ON individuals FOR EACH ROW
BEGIN INSERT INTO individuals_history (operation, changed_at, id, identity, full_name, sex, age_years, age_months, medical_history, diagnosis, vcf_filename, vcf_file_path, is_deleted, deleted_at, created_by, updated_by, created_at, updated_at) VALUES ('DELETE', datetime('now'), OLD.id, OLD.identity, OLD.full_name, OLD.sex, OLD.age_years, OLD.age_months, OLD.medical_history, OLD.diagnosis, OLD.vcf_filename, OLD.vcf_file_path, OLD.is_deleted, OLD.deleted_at, OLD.created_by, OLD.updated_by, OLD.created_at, OLD.updated_at); END;

-- analyses
CREATE TRIGGER analyses_history_insert AFTER INSERT ON analyses FOR EACH ROW
BEGIN INSERT INTO analyses_history (operation, changed_at, id, individual_id, hpo_terms, name, description, genome_assembly, analysis_mode, frequency_threshold, pathogenicity_threshold, status, output_html, output_vcf, started_at, completed_at, error_message, is_deleted, deleted_at, created_by, updated_by, created_at, updated_at) VALUES ('INSERT', datetime('now'), NEW.id, NEW.individual_id, NEW.hpo_terms, NEW.name, NEW.description, NEW.genome_assembly, NEW.analysis_mode, NEW.frequency_threshold, NEW.pathogenicity_threshold, NEW.status, NEW.output_html, NEW.output_vcf, NEW.started_at, NEW.completed_at, NEW.error_message, NEW.is_deleted, NEW.deleted_at, NEW.created_by, NEW.updated_by, NEW.created_at, NEW.updated_at); END;

CREATE TRIGGER analyses_history_update AFTER UPDATE ON analyses FOR EACH ROW
BEGIN INSERT INTO analyses_history (operation, changed_at, id, individual_id, hpo_terms, name, description, genome_assembly, analysis_mode, frequency_threshold, pathogenicity_threshold, status, output_html, output_vcf, started_at, completed_at, error_message, is_deleted, deleted_at, created_by, updated_by, created_at, updated_at) VALUES ('UPDATE', datetime('now'), NEW.id, NEW.individual_id, NEW.hpo_terms, NEW.name, NEW.description, NEW.genome_assembly, NEW.analysis_mode, NEW.frequency_threshold, NEW.pathogenicity_threshold, NEW.status, NEW.output_html, NEW.output_vcf, NEW.started_at, NEW.completed_at, NEW.error_message, NEW.is_deleted, NEW.deleted_at, NEW.created_by, NEW.updated_by, NEW.created_at, NEW.updated_at); END;

CREATE TRIGGER analyses_history_delete AFTER DELETE ON analyses FOR EACH ROW
BEGIN INSERT INTO analyses_history (operation, changed_at, id, individual_id, hpo_terms, name, description, genome_assembly, analysis_mode, frequency_threshold, pathogenicity_threshold, status, output_html, output_vcf, started_at, completed_at, error_message, is_deleted, deleted_at, created_by, updated_by, created_at, updated_at) VALUES ('DELETE', datetime('now'), OLD.id, OLD.individual_id, OLD.hpo_terms, OLD.name, OLD.description, OLD.genome_assembly, OLD.analysis_mode, OLD.frequency_threshold, OLD.pathogenicity_threshold, OLD.status, OLD.output_html, OLD.output_vcf, OLD.started_at, OLD.completed_at, OLD.error_message, OLD.is_deleted, OLD.deleted_at, OLD.created_by, OLD.updated_by, OLD.created_at, OLD.updated_at); END;

-- Sample data (optional - remove if not needed)

-- Insert a sample individual (created by admin user)
INSERT INTO individuals (
    identity,
    full_name,
    sex,
    age_years,
    age_months,
    medical_history,
    diagnosis,
    vcf_file_path,
    vcf_filename,
    created_by,
    updated_by,
    created_at,
    updated_at
) VALUES (
    'P0001',
    'John Doe',
    'MALE',
    35,
    0,
    'Individual with seizure disorder',
    'Epilepsy',
    '/opt/exomiser/ikdrc/vcf/P0001_sample.vcf',
    'P0001_sample.vcf',
    1,  -- created by admin
    1,  -- updated by admin
    datetime('now'),
    datetime('now')
);

-- Insert a sample analysis (created by admin user)
INSERT INTO analyses (
    name,
    description,
    genome_assembly,
    analysis_mode,
    frequency_threshold,
    pathogenicity_threshold,
    hpo_terms,
    status,
    individual_id,
    created_by,
    updated_by,
    created_at,
    updated_at
) VALUES (
    'P0001 Epilepsy Analysis',
    'Genomic analysis for epilepsy individual P0001',
    'hg38',
    'PASS_ONLY',
    0.01,
    0.7,
    '[{"id": "HP:0001250", "label": "Seizures"}]',
    'PENDING',
    1,  -- individual P0001
    1,  -- created by admin
    1,  -- updated by admin
    datetime('now'),
    datetime('now')
);
