FROM amazoncorretto:21

RUN yum install -y procps-ng shadow-utils which curl unzip python3 python3-pip

ENV EXOMISER_VERSION=14.1.0
WORKDIR /tmp
RUN curl -L -o "exomiser-cli-${EXOMISER_VERSION}-distribution.zip" "https://github.com/exomiser/Exomiser/releases/download/${EXOMISER_VERSION}/exomiser-cli-${EXOMISER_VERSION}-distribution.zip" && \
    unzip exomiser-cli-${EXOMISER_VERSION}-distribution.zip && \
    rm exomiser-cli-${EXOMISER_VERSION}-distribution.zip && \
    mv exomiser-cli-${EXOMISER_VERSION} /opt/exomiser

# Install Python dependencies
RUN pip3 install --no-cache-dir fastapi uvicorn jinja2 python-multipart httpx

WORKDIR /opt/exomiser

COPY ./compose/production/exomiser/application.properties /opt/exomiser/application.properties
COPY ./compose/production/exomiser/app /opt/exomiser/app

# Expose port for FastAPI
EXPOSE 9000

# Command to run FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
