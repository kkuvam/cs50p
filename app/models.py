# File: app/models.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from enum import Enum

# Export the db object so app can init it (db.init_app(app))
db = SQLAlchemy()

class SexType(Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"

class TaskStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class GenomeAssembly(Enum):
    hg19 = "hg19"
    hg38 = "hg38"

class User(UserMixin, db.Model):
    """
    General-purpose user model. Extend by adding columns (profile, last_login, etc).
    Password is stored hashed in password_hash.
    """
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)   # flask-login uses is_active
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships - track what users created and updated
    created_individuals = db.relationship('Individual', foreign_keys='Individual.created_by', backref='creator', lazy=True)
    updated_individuals = db.relationship('Individual', foreign_keys='Individual.updated_by', backref='last_updater', lazy=True)
    created_analyses = db.relationship('Analysis', foreign_keys='Analysis.created_by', backref='creator', lazy=True)
    updated_analyses = db.relationship('Analysis', foreign_keys='Analysis.updated_by', backref='last_updater', lazy=True)

    def __repr__(self):
        return f"<User {self.email}>"

    # --- password helpers (use these; do not store plain text) ---
    def set_password(self, password: str) -> None:
        """Hash & store password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return check_password_hash(self.password_hash, password)

    # flask-login expect methods provided by UserMixin (is_authenticated, get_id, etc)


class Individual(db.Model):
    """
    Individual model based on phenopacket form fields.
    Stores individual information and phenotype data for genomic analysis.
    """
    __tablename__ = "individuals"

    id = db.Column(db.Integer, primary_key=True)
    identity = db.Column(db.String(50), nullable=False, index=True)  # e.g. P0001
    full_name = db.Column(db.String(120), nullable=False)
    sex = db.Column(db.Enum(SexType), nullable=False, default=SexType.UNKNOWN)
    age_years = db.Column(db.Integer, nullable=False)  # Age in years

    # Medical/Clinical information
    medical_history = db.Column(db.Text, nullable=True)  # Clinical notes
    diagnosis = db.Column(db.String(255), nullable=True)  # Primary diagnosis

    # HPO (Human Phenotype Ontology) phenotypes - stored as JSON array
    hpo_terms = db.Column(db.JSON, nullable=False)  # [{"id": "HP:0001250", "label": "Seizures"}, ...]

    # File storage paths
    vcf_filename = db.Column(db.String(255), nullable=True)  # Original VCF filename at upload
    vcf_file_path = db.Column(db.String(255), nullable=False)  # Path to uploaded VCF file in /opt/exomiser/ikdrc/vcf/
    phenopacket_yaml = db.Column(db.Text, nullable=True)  # Generated YAML phenopacket content (updated after creation)

    # Audit trail - track who created and last updated
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    # Analysis relationship
    analyses = db.relationship('Analysis', backref='individual', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Individual {self.identity}: {self.full_name or 'Unnamed'}>"

    @property
    def hpo_count(self):
        """Return count of HPO terms for this individual."""
        return len(self.hpo_terms) if self.hpo_terms else 0

    def generate_phenopacket_yaml(self, creator="Exomiser Web Interface"):
        """
        Generate phenopacket YAML content based on individual data.
        This method replicates the JavaScript logic from phenopacket.html
        """
        import yaml
        from datetime import datetime

        # Convert sex to phenopacket format
        sex_map = {
            "MALE": "MALE",
            "FEMALE": "FEMALE",
            "OTHER": "OTHER_SEX",
            "UNKNOWN": "UNKNOWN_SEX"
        }

        # Build phenotypic features from HPO terms
        phenotypic_features = []
        if self.hpo_terms and isinstance(self.hpo_terms, list):
            for term in self.hpo_terms:
                if isinstance(term, dict) and "id" in term:
                    phenotypic_features.append({
                        "type": {
                            "id": term["id"],
                            "label": term.get("label", "")
                        }
                    })

        # Build the phenopacket object
        phenopacket_obj = {
            "phenopacket": {
                "id": self.identity,
                "subject": {
                    "id": self.identity,
                    "sex": sex_map.get(self.sex.value if self.sex else "UNKNOWN", "UNKNOWN_SEX")
                },
                "phenotypicFeatures": phenotypic_features,
                "metaData": {
                    "created": datetime.utcnow().isoformat() + "Z",
                    "createdBy": creator,
                    "resources": [
                        {
                            "id": "hp",
                            "name": "human phenotype ontology",
                            "url": "http://purl.obolibrary.org/obo/hp.owl",
                            "version": "hp/releases/latest",
                            "namespacePrefix": "HP",
                            "iriPrefix": "http://purl.obolibrary.org/obo/HP_"
                        }
                    ],
                    "phenopacketSchemaVersion": "1.0"
                }
            }
        }

        # Add age if available
        if self.age_years:
            phenopacket_obj["phenopacket"]["subject"]["age"] = {
                "age": f"{self.age_years}Y"
            }

        # Add VCF file information if available
        if self.vcf_file_path:
            import os
            vcf_filename = os.path.basename(self.vcf_file_path)
            phenopacket_obj["phenopacket"]["htsFiles"] = [
                {
                    "uri": f"ikdrc/vcf/{vcf_filename}",
                    "htsFormat": "VCF",
                    "genomeAssembly": "hg19"
                }
            ]

        # Convert to YAML string
        return yaml.dump(phenopacket_obj, default_flow_style=False, sort_keys=False)

    def update_phenopacket_yaml(self, creator="Exomiser Web Interface"):
        """
        Generate and update the phenopacket_yaml field for this individual.
        """
        self.phenopacket_yaml = self.generate_phenopacket_yaml(creator)
        return self.phenopacket_yaml

    def to_dict(self):
        """Convert individual to dictionary for API responses."""
        return {
            'id': self.id,
            'identity': self.identity,
            'full_name': self.full_name,
            'sex': self.sex.value if self.sex else None,
            'age_years': self.age_years,
            'medical_history': self.medical_history,
            'diagnosis': self.diagnosis,
            'hpo_terms': self.hpo_terms,
            'hpo_count': self.hpo_count,
            'vcf_filename': self.vcf_filename,
            'vcf_file_path': self.vcf_file_path,
            'phenopacket_yaml': self.phenopacket_yaml,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class Analysis(db.Model):
    """
    Analysis model for genomic variant analysis workflows.
    Represents an Exomiser analysis job with VCF file and individual data.
    """
    __tablename__ = "analyses"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)  # User-friendly analysis name
    description = db.Column(db.Text, nullable=True)   # Analysis description

    # Analysis configuration
    vcf_filename = db.Column(db.String(255), nullable=False)  # Original VCF filename
    vcf_file_path = db.Column(db.String(500), nullable=True)  # Server file path
    genome_assembly = db.Column(db.Enum(GenomeAssembly), nullable=False, default=GenomeAssembly.hg19)

    # Analysis parameters
    analysis_mode = db.Column(db.String(50), default='PASS_ONLY')  # PASS_ONLY, FULL, etc.
    frequency_threshold = db.Column(db.Float, default=1.0)  # Max allele frequency
    pathogenicity_threshold = db.Column(db.Float, default=0.5)  # Min pathogenicity score

    # Analysis execution
    status = db.Column(db.Enum(TaskStatus), nullable=False, default=TaskStatus.PENDING)
    progress_percent = db.Column(db.Integer, default=0)  # 0-100

    # Results and outputs
    results_directory = db.Column(db.String(500), nullable=True)  # Path to results folder
    output_html = db.Column(db.String(500), nullable=True)  # HTML report path
    output_tsv = db.Column(db.String(500), nullable=True)   # TSV results path
    output_vcf = db.Column(db.String(500), nullable=True)   # Filtered VCF path
    phenopacket_path = db.Column(db.String(500), nullable=True)  # Generated phenopacket YAML

    # Execution details
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)  # Error details if failed
    log_file_path = db.Column(db.String(500), nullable=True)  # Execution log path

    # Relationships
    individual_id = db.Column(db.Integer, db.ForeignKey('individuals.id'), nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Analysis {self.name}: {self.status.value}>"

    @property
    def duration(self):
        """Calculate analysis execution duration."""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return datetime.utcnow() - self.started_at
        return None

    @property
    def is_running(self):
        """Check if analysis is currently running."""
        return self.status == TaskStatus.RUNNING

    @property
    def is_completed(self):
        """Check if analysis completed successfully."""
        return self.status == TaskStatus.COMPLETED

    @property
    def is_failed(self):
        """Check if analysis failed."""
        return self.status == TaskStatus.FAILED

    def to_dict(self):
        """Convert analysis to dictionary for API responses."""
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'vcf_filename': self.vcf_filename,
            'genome_assembly': self.genome_assembly.value if self.genome_assembly else None,
            'status': self.status.value,
            'progress_percent': self.progress_percent,
            'individual_id': self.individual_id,
            'individual_name': self.individual.full_name if self.individual else None,
            'individual_identity': self.individual.identity if self.individual else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration': str(self.duration) if self.duration else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

