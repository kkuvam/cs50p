FROM amazoncorretto:21-alpine

# Install system dependencies
RUN apk add --no-cache \
    python3 \
    python3-dev \
    py3-pip \
    py3-wheel \
    curl \
    unzip \
    shadow \
    procps \
    gcc \
    musl-dev \
    libffi-dev \
    && ln -sf python3 /usr/bin/python

# Create non-root user
RUN addgroup -g 1001 exomiser && \
    adduser -D -s /bin/sh -u 1001 -G exomiser exomiser

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
RUN python3 -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python3 -m pip install --no-cache-dir -r /opt/app/requirements.txt

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
     "--keepalive", "2", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "100", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "main:app"]
