FROM amazoncorretto:21

# Install system dependencies
RUN yum update -y && \
    yum install -y \
    python3 \
    python3-pip \
    python3-devel \
    curl \
    unzip \
    shadow-utils \
    procps-ng \
    gcc \
    && yum clean all \
    && ln -sf python3 /usr/bin/python

# Create non-root user
RUN groupadd -g 1001 exomiser && \
    useradd -r -u 1001 -g exomiser -s /bin/bash -d /home/exomiser exomiser && \
    mkdir -p /home/exomiser && \
    chown exomiser:exomiser /home/exomiser

# Set environment variables
ENV EXOMISER_VERSION=14.1.0
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Download and install Exomiser CLI
WORKDIR /tmp
RUN curl -L -o "exomiser-cli-${EXOMISER_VERSION}-distribution.zip" \
    "https://github.com/exomiser/Exomiser/releases/download/${EXOMISER_VERSION}/exomiser-cli-${EXOMISER_VERSION}-distribution.zip" && \
    unzip exomiser-cli-${EXOMISER_VERSION}-distribution.zip && \
    rm exomiser-cli-${EXOMISER_VERSION}-distribution.zip && \
    mv exomiser-cli-${EXOMISER_VERSION} /opt/exomiser && \
    chown -R exomiser:exomiser /opt/exomiser

# Create application directories
RUN mkdir -p /opt/app /opt/instance /opt/exomiser/data /opt/exomiser/results && \
    chown -R exomiser:exomiser /opt/app /opt/instance /opt/exomiser

# Copy requirements first for better layer caching
COPY --chown=exomiser:exomiser requirements.txt /opt/app/requirements.txt

# Install Python dependencies
RUN pip3 install --no-cache-dir --upgrade pip setuptools wheel && \
    pip3 install --no-cache-dir -r /opt/app/requirements.txt

# Copy application code
COPY --chown=exomiser:exomiser ./app /opt/app

# Switch to non-root user
USER exomiser

# Set working directory
WORKDIR /opt/app

# Add healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# Expose port
EXPOSE 8000

# Run Gunicorn with optimized settings
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "120", \
     "--keep-alive", "2", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "main:app"]
