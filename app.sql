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
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on email for faster lookups
CREATE UNIQUE INDEX ix_users_email ON users (email);

-- Patients table
CREATE TABLE patients (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    individual_id VARCHAR(50) NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    sex VARCHAR(10) NOT NULL DEFAULT 'UNKNOWN', -- MALE, FEMALE, OTHER, UNKNOWN
    age_years INTEGER NOT NULL,
    medical_history TEXT,
    diagnosis VARCHAR(255),
    hpo_terms TEXT NOT NULL, -- JSON array stored as TEXT
    vcf_file_path VARCHAR(255) NOT NULL,
    phenopacket_yaml TEXT,
    created_by INTEGER NOT NULL,
    updated_by INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key constraints
    FOREIGN KEY(created_by) REFERENCES users (id),
    FOREIGN KEY(updated_by) REFERENCES users (id)
);

-- Create index on individual_id for faster patient lookups
CREATE INDEX ix_patients_individual_id ON patients (individual_id);

-- Tasks table
CREATE TABLE tasks (
    id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(120) NOT NULL,
    description TEXT,
    vcf_filename VARCHAR(255) NOT NULL,
    vcf_file_path VARCHAR(500),
    genome_assembly VARCHAR(10) NOT NULL DEFAULT 'hg19', -- hg19, hg38
    analysis_mode VARCHAR(50) DEFAULT 'PASS_ONLY',
    frequency_threshold REAL DEFAULT 1.0,
    pathogenicity_threshold REAL DEFAULT 0.5,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING', -- PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    progress_percent INTEGER DEFAULT 0,
    results_directory VARCHAR(500),
    output_html VARCHAR(500),
    output_tsv VARCHAR(500),
    output_vcf VARCHAR(500),
    phenopacket_path VARCHAR(500),
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT,
    log_file_path VARCHAR(500),
    patient_id INTEGER NOT NULL,
    created_by INTEGER NOT NULL,
    updated_by INTEGER NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key constraints
    FOREIGN KEY(patient_id) REFERENCES patients (id),
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
    'scrypt:32768:8:1$dcjsNCnF7R7g8sW7$381723960c119fb9aa564a38ddec6ed4ca04d77982c40bdf5d75ae3efc30d66b102d2b6a15eec41997b40ec33f03128080b3d0e618e5be44477ddf3f8bc31a66',
    'System Administrator',
    1,
    1,
    datetime('now'),
    datetime('now')
);

-- Create triggers to automatically update the updated_at timestamp

-- Trigger for users table
CREATE TRIGGER update_users_updated_at
    AFTER UPDATE ON users
    FOR EACH ROW
BEGIN
    UPDATE users SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Trigger for patients table
CREATE TRIGGER update_patients_updated_at
    AFTER UPDATE ON patients
    FOR EACH ROW
BEGIN
    UPDATE patients SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Trigger for tasks table
CREATE TRIGGER update_tasks_updated_at
    AFTER UPDATE ON tasks
    FOR EACH ROW
BEGIN
    UPDATE tasks SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Sample data (optional - remove if not needed)

-- Insert a sample patient (created by admin user)
INSERT INTO patients (
    individual_id,
    full_name,
    sex,
    age_years,
    medical_history,
    diagnosis,
    hpo_terms,
    vcf_file_path,
    created_by,
    updated_by,
    created_at,
    updated_at
) VALUES (
    'P0001',
    'John Doe',
    'MALE',
    35,
    'Patient with seizure disorder',
    'Epilepsy',
    '[{"id": "HP:0001250", "label": "Seizures"}]',
    '/opt/exomiser/ikdrc/vcf/P0001_sample.vcf',
    1,  -- created by admin
    1,  -- updated by admin
    datetime('now'),
    datetime('now')
);

-- Insert a sample task (created by admin user)
INSERT INTO tasks (
    name,
    description,
    vcf_filename,
    genome_assembly,
    analysis_mode,
    frequency_threshold,
    pathogenicity_threshold,
    status,
    progress_percent,
    patient_id,
    created_by,
    updated_by,
    created_at,
    updated_at
) VALUES (
    'P0001 Epilepsy Analysis',
    'Genomic analysis for epilepsy patient P0001',
    'P0001_sample.vcf',
    'hg38',
    'PASS_ONLY',
    0.01,
    0.7,
    'PENDING',
    0,
    1,  -- patient P0001
    1,  -- created by admin
    1,  -- updated by admin
    datetime('now'),
    datetime('now')
);
