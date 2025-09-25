import asyncio
import os
import subprocess
import uuid
from datetime import datetime
from fastapi import FastAPI, File, UploadFile, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import shutil
import httpx

app = FastAPI()

# Mount static files for resources
app.mount("/static", StaticFiles(directory="/opt/exomiser/app/static"), name="static")
# Mount results files for results
app.mount("/browse", StaticFiles(directory="/opt/exomiser/tasks"), name="tasks")

# Set up templates
templates = Jinja2Templates(directory="/opt/exomiser/app/templates")
# Add datetime filter for templates
def datetime_filter(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
templates.env.filters['datetime'] = datetime_filter
# Add dirname filter for parent directory navigation
def dirname_filter(path):
    if not path:
        return ""
    return os.path.dirname(path).replace(os.sep, "/")
templates.env.filters['dirname'] = dirname_filter

# Dictionary to track task status
tasks = {}

# Maximum number of concurrent tasks
MAX_CONCURRENT_TASKS = 1

# Semaphore to control concurrency
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

@app.get("/", response_class=HTMLResponse)
async def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request})

@app.post("/upload")
async def upload_files(
    task_id: str = Form(None),
    vcf: UploadFile = File(...),
    phenopacket: UploadFile = File(...),
    request: Request = None
):
    # Generate unique task ID
    task_id = str(task_id) or str(uuid.uuid4())
    tasks[task_id] = {"status": "queued", "result_file": None, "error": None}

    # Create task-specific directory
    task_dir = f"/opt/exomiser/tasks/{task_id}"
    os.makedirs(task_dir, exist_ok=True)

    # Save uploaded files
    vcf_path = f"{task_dir}/{vcf.filename}"
    phenopacket_path = f"{task_dir}/{phenopacket.filename}"
    with open(vcf_path, "wb") as f:
        shutil.copyfileobj(vcf.file, f)
    with open(phenopacket_path, "wb") as f:
        shutil.copyfileobj(phenopacket.file, f)

    # Store file paths in tasks for use in run_exomiser endpoint
    tasks[task_id]["vcf_path"] = vcf_path
    tasks[task_id]["phenopacket_path"] = phenopacket_path

    # async with httpx.AsyncClient() as client:
    #     await client.post(f"http://localhost:0000/run/{task_id}")

    # Redirect to status page
    return templates.TemplateResponse(
        "status.html",
        {"request": request, "task_id": task_id}
    )

@app.post("/run/{task_id}")
async def run(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_dir = f"/opt/exomiser/tasks/{task_id}"
    vcf_path = task["vcf_path"]
    phenopacket_path = task["phenopacket_path"]
    output_prefix = f"{task_dir}"

    async with semaphore:  # Limit concurrent tasks
        try:
            tasks[task_id]["status"] = "queued"
            cmd = [
                "java",
                "-Xms1g",
                "-Xmx2g",
                "-jar",
                "/opt/exomiser/exomiser-cli-14.1.0.jar",
                "--sample",
                phenopacket_path,
                "--output-prefix",
                output_prefix,
                "--spring.config.location=/opt/exomiser/application.properties"
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            tasks[task_id]["status"] = "completed"
            tasks[task_id]["result_file"] = f"{output_prefix}_exomiser.html"
        except subprocess.CalledProcessError as e:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e.stderr)
        except Exception as e:
            tasks[task_id]["status"] = "failed"
            tasks[task_id]["error"] = str(e)

    return {"status": tasks[task_id]["status"], "task_id": task_id}

@app.get("/status/{task_id}", response_class=HTMLResponse)
async def check_status(task_id: str, request: Request):
    task = tasks.get(task_id)
    if not task:
        return templates.TemplateResponse(
            "status.html",
            {
                "request": request,
                "task_id": task_id,
                "status": "not_found",
                "error": "Task not found"
            }
        )

    if task["status"] == "running":
        return templates.TemplateResponse(
            "status.html",
            {"request": request, "task_id": task_id}
        )
    elif task["status"] == "completed":
        return FileResponse(task["result_file"], media_type="text/html")
    else:
        raise HTTPException(status_code=500, detail=f"Task failed: {task.get('error', 'Unknown error')}")

@app.get("/tasks", response_class=HTMLResponse)
async def list_tasks(request: Request):
    # Convert tasks dictionary to a list for template rendering
    task_list = [
        {"task_id": task_id, "status": details["status"]}
        for task_id, details in tasks.items()
    ]
    # Sort tasks by task_id
    task_list.sort(key=lambda x: x["task_id"])
    return templates.TemplateResponse(
        "tasks.html",
        {
            "request": request,
            "tasks": task_list
        }
    )

@app.get("/browse", response_class=HTMLResponse)
async def list_tasks_directory(request: Request, path: str = ""):
    tasks_dir = "/opt/exomiser/tasks"
    path = path.strip("/")  # Remove leading/trailing slashes
    # Construct the full path, preventing directory traversal
    full_path = os.path.normpath(os.path.join(tasks_dir, path)).rstrip("/")
    if not full_path.startswith(tasks_dir):
        return templates.TemplateResponse(
            "browse.html",
            {
                "request": request,
                "files": [],
                "directory": tasks_dir,
                "current_path": path,
                "error": "Invalid path"
            },
            status_code=400
        )

    try:
        # List directory contents, excluding .vcf files
        files = []
        for entry in os.scandir(full_path):
            if entry.is_file() and entry.name.lower().endswith('.vcf'):
                continue  # Skip .vcf files
            files.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0,
                "modified": entry.stat().st_mtime
            })
        # Sort files by name
        files.sort(key=lambda x: x["name"])
        return templates.TemplateResponse(
            "browse.html",
            {
                "request": request,
                "files": files,
                "directory": tasks_dir,
                "current_path": path
            }
        )
    except FileNotFoundError:
        return templates.TemplateResponse(
            "browse.html",
            {
                "request": request,
                "files": [],
                "directory": tasks_dir,
                "current_path": path,
                "error": f"Directory {full_path} not found"
            },
            status_code=404
        )
    except PermissionError:
        return templates.TemplateResponse(
            "browse.html",
            {
                "request": request,
                "files": [],
                "directory": tasks_dir,
                "current_path": path,
                "error": f"Permission denied accessing {full_path}"
            },
            status_code=403
        )
