# Exomiser App — CS50P Final Project

Video Demo: https://youtu.be/8JFphQ4I_9w

**Exomiser App** is a browser-based platform for running *Exomiser*-powered variant interpretation on VCF (Variant Call Format) files. It’s designed to make genomic analysis accessible to anyone — students, lab technicians, or researchers — without the need for complex local installations or command-line setup. By combining a clean web interface with containerized backend services, Exomiser App provides a seamless workflow: upload your file, run the analysis, and explore your annotated variants in seconds.

## Key Features

- Upload VCF files directly through the browser for Exomiser-based interpretation.  
- No local dependencies — all services run in Docker containers orchestrated by Compose.  
- Simple, intuitive frontend for navigating variant results and their clinical significance.  
- Modular backend that handles uploads, analysis execution, and database operations cleanly.  
- Fully reproducible environment suitable for both learning and real-world testing.

## Files in This Repository

### `app/` — Core Web Application

The `app/` folder contains the full logic and interface for Exomiser App — both the frontend and backend layers that turn genomic data into interpretable output.

#### **Frontend**

The frontend uses **HTML, CSS, and JavaScript** to build a lightweight and responsive user interface. It’s designed for clarity and usability, even for users unfamiliar with bioinformatics tools.

Core UI components include:

- **Upload Form** – Lets users select `.vcf` files and submit them to the backend for processing. Basic client-side validation checks file size and format before upload.  
- **Job Progress Display** – Dynamically updates the analysis status using asynchronous requests or polling. Users can see when their job is queued, running, or complete.  
- **Results Table / Viewer** – Once Exomiser finishes processing, results are displayed in a sortable, searchable table. Each entry shows key metrics such as gene name, variant score, pathogenicity prediction, and phenotype relevance.  
- **Error Handling and Notifications** – The interface communicates clearly when something goes wrong, whether it’s a missing environment variable, an invalid upload, or a backend error.  

The design philosophy is minimalism — let users focus on their data rather than the machinery underneath.

#### **Backend**

The backend is written in **Python**, using a lightweight web framework such as Flask to handle routing and data flow. It serves as the bridge between user input and the Exomiser analysis engine.

Backend functionality includes:

- Receiving uploaded VCF files and validating their structure.  
- Saving temporary copies of input files to a controlled directory.  
- Writing job details into a database (schema defined in `app.sql`).  
- Calling the Exomiser engine (inside its container) through subprocess commands.  
- Monitoring each analysis job and reporting progress back to the frontend.  
- Formatting final results into JSON or tabular form for display.  

Additionally, the backend provides utility scripts to maintain the system:

- **Database Checks:** Validates that the database service is reachable (`check_db.py`).  
- **Job Monitoring:** Tracks running analyses and logs progress.  
- **Cleanup Tasks:** Removes temporary files and resets states after completion.  

Together, the frontend and backend in `app/` form a cohesive, interactive system that transforms command-line bioinformatics into a user-friendly, reproducible web experience.

---

### `compose/` — Container Orchestration

Houses Docker Compose configuration fragments that define how each container interacts — the web server, Exomiser worker, and database.  
This ensures every environment (local or cloud) runs consistently, without manual setup of dependencies or paths.

---


### `docker-compose.yml`

The central Compose file that brings everything together. Running  
```bash
docker compose up --build
```  
spins up all services — web app, Exomiser engine, and database — in one reproducible command. It’s the easiest way to launch Exomiser App locally.

---

### `app.sql`

Defines the relational database schema used by the backend. It creates tables for job metadata, file paths, result entries, and timestamps, enabling persistent tracking of analyses.

---

### `check_db.py`

A diagnostic Python script that ensures the backend can reach and query the database. Useful during setup or when debugging connection issues.

---

### `monitor_analysis.sh`

A Bash script that allows users or developers to monitor the progress of ongoing Exomiser analyses from the command line. It can be used alongside the web interface to confirm that background jobs are running correctly.

---

### `requirements.txt`

Lists the Python dependencies needed by the backend. Installing them with  
```bash
pip install -r requirements.txt
```  
allows you to test or modify the app locally without running containers.

---

### `LICENSE`

The project is distributed under the MIT License, allowing free use, modification, and redistribution.

---

## Quick Start


1. **Install Docker and Docker Compose**

   Make sure both are installed and running on your system.

2. **Build and launch the app**
   ```bash
   docker compose up --build
   ```

3. **Open the web interface**

   Navigate to `http://localhost:5000` (or the port defined in your `.env` file).

4. **Run an analysis**

   Upload a `.vcf` file, start the Exomiser analysis, and follow its progress on the dashboard.  
   Once complete, results will be displayed interactively in the browser.
