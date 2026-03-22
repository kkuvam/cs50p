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
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
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
    age_years = db.Column(db.Integer, nullable=False)   # Age in complete years
    age_months = db.Column(db.Integer, nullable=False, default=0)  # Additional months (0–11)

    # Medical/Clinical information
    medical_history = db.Column(db.Text, nullable=True)  # Clinical notes
    diagnosis = db.Column(db.String(255), nullable=True)  # Primary diagnosis

    # File storage paths
    vcf_filename = db.Column(db.String(255), nullable=True)  # Original VCF filename at upload
    vcf_file_path = db.Column(db.String(255), nullable=False)  # Path to uploaded VCF file in /opt/exomiser/ikdrc/vcf/

    # Soft delete
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Audit trail - track who created and last updated
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    analyses = db.relationship('Analysis', backref='individual', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Individual {self.identity}: {self.full_name or 'Unnamed'}>"

    @property
    def active_analyses(self):
        """Return non-deleted analyses for this individual."""
        return Analysis.query.filter_by(individual_id=self.id, is_deleted=False).all()

    @property
    def age_display(self):
        """Human-readable age string."""
        if self.age_years == 0 and self.age_months:
            return f"{self.age_months} month{'s' if self.age_months != 1 else ''}"
        if self.age_months:
            return f"{self.age_years}y {self.age_months}m"
        return f"{self.age_years} year{'s' if self.age_years != 1 else ''}"

    def to_dict(self):
        """Convert individual to dictionary for API responses."""
        return {
            'id': self.id,
            'identity': self.identity,
            'full_name': self.full_name,
            'sex': self.sex.value if self.sex else None,
            'age_years': self.age_years,
            'age_months': self.age_months,
            'medical_history': self.medical_history,
            'diagnosis': self.diagnosis,
            'vcf_filename': self.vcf_filename,
            'vcf_file_path': self.vcf_file_path,
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
    individual_id = db.Column(db.Integer, db.ForeignKey('individuals.id'), nullable=False)

    # HPO phenotypes for this specific analysis run
    hpo_terms = db.Column(db.JSON, nullable=True)  # [{"id": "HP:0001250", "label": "Seizures"}, ...]
    phenopacket_yaml = db.Column(db.Text, nullable=True)  # Generated YAML phenopacket content

    # Basic info
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Analysis configuration
    genome_assembly = db.Column(db.Enum(GenomeAssembly), nullable=False, default=GenomeAssembly.hg19)
    analysis_mode = db.Column(db.String(50), default='PASS_ONLY')  # PASS_ONLY, FULL, etc.
    frequency_threshold = db.Column(db.Float, default=1.0)  # Max allele frequency
    pathogenicity_threshold = db.Column(db.Float, default=0.5)  # Min pathogenicity score

    # Execution state
    status = db.Column(db.Enum(TaskStatus), nullable=False, default=TaskStatus.PENDING)
    output_html = db.Column(db.String(500), nullable=True)  # HTML report path
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    error_message = db.Column(db.Text, nullable=True)  # Error details if failed
    log = db.Column(db.Text, nullable=True)  # Complete process output log for debugging

    # Soft delete
    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)

    # Audit trail
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<Analysis {self.name}: {self.status.value}>"

    @property
    def hpo_count(self):
        """Return count of HPO terms for this analysis."""
        return len(self.hpo_terms) if self.hpo_terms else 0

    def generate_phenopacket_yaml(self, creator="Exomiser Web Interface"):
        """
        Generate GA4GH Phenopacket v1.0 YAML from this analysis and its linked individual.
        Age is encoded as ISO 8601 duration (e.g. P2Y6M).
        """
        import yaml
        from datetime import datetime as _dt

        individual = self.individual

        sex_map = {
            "MALE": "MALE",
            "FEMALE": "FEMALE",
            "OTHER": "OTHER_SEX",
            "UNKNOWN": "UNKNOWN_SEX",
        }

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

        phenopacket_obj = {
            "id": individual.identity,
            "subject": {
                "id": individual.identity,
                "sex": sex_map.get(
                    individual.sex.value if individual.sex else "UNKNOWN", "UNKNOWN_SEX"
                ),
            },
            "phenotypicFeatures": phenotypic_features,
            "metaData": {
                "created": _dt.utcnow().isoformat() + "Z",
                "createdBy": creator,
                "resources": [
                    {
                        "id": "hp",
                        "name": "human phenotype ontology",
                        "url": "http://purl.obolibrary.org/obo/hp.owl",
                        "version": "hp/releases/latest",
                        "namespacePrefix": "HP",
                        "iriPrefix": "http://purl.obolibrary.org/obo/HP_",
                    }
                ],
                "phenopacketSchemaVersion": "1.0",
            },
        }

        # ISO 8601 age duration (P{Y}Y{M}M)
        years = individual.age_years or 0
        months = individual.age_months or 0
        if years or months:
            if months:
                iso_age = f"P{years}Y{months}M"
            else:
                iso_age = f"P{years}Y"
            phenopacket_obj["subject"]["age"] = {"age": iso_age}

        if individual.vcf_file_path:
            phenopacket_obj["htsFiles"] = [
                {
                    "uri": individual.vcf_file_path,
                    "htsFormat": "VCF",
                    "genomeAssembly": self.genome_assembly.value if self.genome_assembly else "hg19",
                }
            ]

        return yaml.dump(phenopacket_obj, default_flow_style=False, sort_keys=False)

    def update_phenopacket_yaml(self, creator="Exomiser Web Interface"):
        """Generate and store phenopacket_yaml on this analysis."""
        self.phenopacket_yaml = self.generate_phenopacket_yaml(creator)
        return self.phenopacket_yaml

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
            'genome_assembly': self.genome_assembly.value if self.genome_assembly else None,
            'hpo_terms': self.hpo_terms,
            'hpo_count': self.hpo_count,
            'status': self.status.value,
            'progress_percent': self.progress_percent,
            'individual_id': self.individual_id,
            'individual_name': self.individual.full_name if self.individual else None,
            'individual_identity': self.individual.identity if self.individual else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'duration': str(self.duration) if self.duration else None,
            'error_message': self.error_message,
            'log': self.log,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

