"""Aprovals API for GitHub access at NOAA GSL

This API allows users to submit agreements for GitH# Set database URL based on environment
if IS_DEVELOPMENT:
    DATABASE_URL = "sqlite:///./agreement.db"  # Local development database
else:
    DATABASE_URL = "sqlite:////data/agreement.db"  # Production database pathb access, get approvals from stakeholders, and manage user agreements.
It uses FastAPI for the web framework, SQLAlchemy for database interactions, and APScheduler for background tasks.
It also includes basic authentication and email notifications for approvals and disapprovals.

Dependencies:
- FastAPI
- SQLAlchemy
- APScheduler
- smtplib (for sending emails)
- pandas (for exporting agreements to CSV)

Configuration:
- The API uses environment variables to manage sensitive information like database URLs and email credentials.
- The database is set up using SQLAlchemy with a SQLite backend.
- Email notifications are sent using Gmail's SMTP server with SSL.

Endpoints:
- GET /: Displays the agreement form.
- POST /submit_agreement/: Submits a new user agreement.
- GET /approve_user/{email}/{approver_id}: Approves a user agreement.
- GET /refuse_user/{email}/{approver_id}: Refuses a user agreement.
- GET /browse_agreements: Displays all agreements in a table format.
- GET /status: Displays the status of user agreements.
- GET /dashboard: Displays a lightweight dashboard summarizing agreements.
- GET /progress/{email}: Displays the progress page for a specific user.
- POST /api/progress/{email}/generate: Triggers GIF generation for a user.
- GET /api/progress/{email}/status: Checks the status of GIF generation for a user.
- GET /download-agreements/: Downloads all agreements as a CSV file.
- GET /api/lab_sponsors: Retrieves the list of labs and their sponsors.
- GET /renew/{email}: Renews a user's agreement.
- PUT /api/agreements/{email}: Updates an existing agreement.
- DELETE /api/agreements/{email}: Deletes an existing agreement.
author: Renn Valo
date: 03/1/2025
Version: 5.0
"""
from fastapi import Depends, FastAPI, Form, HTTPException, Request, BackgroundTasks, status
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timedelta
import uvicorn
import uuid
import smtplib
import os
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from datetime import datetime
import logging
from pydantic import BaseModel
import pandas as pd
import threading
import time
from verification_progress_gif import create_progress_gif

# Configure logging
logging.basicConfig(level=logging.INFO)

# Updated get_stakeholders to use lab and .env
# Load environment variables
load_dotenv('/data/.env')

def get_stakeholders(lab, sponsor):
    env_var = f"STAKEHOLDERS_{lab.upper()}"
    stakeholders_str = os.getenv(env_var)
    if not stakeholders_str:
        raise ValueError(f"No stakeholders defined for lab: {lab}")
    stakeholders = [email.strip() for email in stakeholders_str.split(",") if email.strip()]
    # Add sponsor and admin email as before
    stakeholders.append(sponsor)
    stakeholders.append("renn.valo@noaa.gov")
    return stakeholders
    # 1st stakeholder is the GitHub System Owner 2nd is the GitHub Account Administrator 3rd is the GitHub Security Officer 4th is the sponsor, and 5th is the email of the person who will setup the github account.
    # for testing set all emails to one person like this... return ["renn.valo@noaa.gov", "renn.valo@noaa.gov", "renn.valo@noaa.gov", sponsor, "renn.valo@noaa.gov"]

# Check if we're in development or production mode
IS_DEVELOPMENT = os.getenv("ENVIRONMENT", "development").lower() == "development"

# Initialize FastAPI with root_path for production
if IS_DEVELOPMENT:
    app = FastAPI()  # Docs enabled in development
    logging.info("Running in DEVELOPMENT mode")
else:
    app = FastAPI(
        root_path="/githubapprovals",
        docs_url=None,
        redoc_url=None,
        openapi_url=None
    )  # Add root path in production, docs disabled
    logging.info("Running in PRODUCTION mode")

security = HTTPBasic() #adding security to endpoints that need it.

# List of allowed origins (single domain)
origins = [
    "https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/",
    "https://apps-prod.gsd.esrl.noaa.gov/githubapprovals/",
    "http://localhost:8000/",
]

# Add CORS middleware to the FastAPI application
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow requests from this origin
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# Set database URL based on environment
if IS_DEVELOPMENT:
    DATABASE_URL = "sqlite:///./agreement.db"  # Local development database
else:
    DATABASE_URL = "sqlite:////data/agreement.db"  # Production database path
# DATABASE_URL = "sqlite:///./agreement.db"  # Local development database

logging.info(f"Using database URL: {DATABASE_URL}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

templates = Jinja2Templates(directory="templates")

# Serve static files from the /images directory (absolute path)
app.mount("/images", StaticFiles(directory="/images"), name="images")

# Constants
ORG_NAME = "NOAA-GSL"  # Replace with your organization name
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # get token so you can use API
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
TOTAL_LICENSES = 97  # Replace with your organization's total  -static value for now
PREFIX_APP = "apps-prod.gsd.esrl.noaa.gov"

# Database models
class UserAgreement(Base):
    __tablename__ = "user_agreements"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    esrl_lab = Column(String, nullable=False)
    role = Column(String, nullable=False)
    agreed = Column(Boolean, default=False)
    sponsor = Column(String, nullable=False)  # GitHub sponsor
    systemowner = Column(String, nullable=True) #GitHub Federal System Owner 
    accountadmin = Column(String, nullable=True) #Github Federal Account Administrator
    isso = Column(String, nullable=True) # GitHub Federal Security Officer
    sponsorid = Column(String, nullable=True)  # GitHub Federal sponsor
    dissystemowner = Column(String, nullable=True) #GitHub Federal System Owner
    disaccountadmin = Column(String, nullable=True) #Github Federal Account Administrator
    disisso = Column(String, nullable=True) # GitHub Federal Security Officer
    dissponsor = Column(String, nullable=True)  # GitHub Federal sponsor
    timestamp = Column(DateTime, default=func.now())
    approval_timestamp1 = Column(DateTime)
    approval_timestamp2 = Column(DateTime)
    approval_timestamp3 = Column(DateTime)
    approval_timestamp4 = Column(DateTime)
    final_approval_timestamp = Column(DateTime)
    approval_token1 = Column(Text, unique=True)
    approval_token2 = Column(Text, unique=True)
    approval_token3 = Column(Text, unique=True)
    approval_token4 = Column(Text, unique=True)
    last_renewal_date = Column(DateTime, default=func.now())  
    approver_email1 = Column(String)  
    approver_email2 = Column(String)  
    approver_email3 = Column(String)  
    approver_email4 = Column(String)  
    disapprover_email1 = Column(String)  
    disapprover_email2 = Column(String)  
    disapprover_email3 = Column(String)  
    disapprover_email4 = Column(String)  

Base.metadata.create_all(bind=engine)

scheduler = BackgroundScheduler()
scheduler.start()

# Function to check for users who need to renew and send reminder emails
def check_for_renewals():
    session = SessionLocal()
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] check_for_renewals() called")
    
    # Fetch users who need renewal
    users_to_renew = session.query(UserAgreement).filter(
        UserAgreement.last_renewal_date <= datetime.utcnow() - timedelta(days=365)
    ).all()
    print(f"Users to renew: {len(users_to_renew)}")

    for user in users_to_renew:
        print(f"Checking email for: {user.email}")
        print(f"Sending email to: {user.email}")
        print(f"Last renewal date: {user.last_renewal_date}")

        # Generate the renewal link and message
        renewal_link = f"https://{PREFIX_APP}/githubapprovals/renew/{user.email}"
        message = f"""
        Dear {user.first_name},

        NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

        It has been over a year since your last review of GSL's GitHub Usage Policy Agreement. 

            To continue as a GSL GitHub contributor you will need to:
            Read and understand the roles and responsibilities for being a GSL GitHub {user.role}.  
            The latest updates to GSL's GitHub Usage Policy can be found here:
            https://docs.google.com/document/d/1myfENqhtMSvlcrqBAAACSF0rYLPWhXRh/
           
        Agree to follow the roles and responsibilities for being a GSL team member by clicking the link below:
        {renewal_link}

        NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.
        
        Thank you,
        Your GSL ITS Team
        """
            
        # Send email to the user
        send_email(user.email, "Agreement Renewal Reminder", message)
        print(f"Email sent to: {user.email}")

    session.close()



def send_email(recipient, subject, message):
    print(f"Preparing to send email to {recipient} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    sender_email = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    if not sender_email or not password:
        raise HTTPException(status_code=500, detail="Email configuration is missing")
    
    #specify the alternative "from" email address
    from_email = "github.gsl@noaa.gov" #Alaternative email address authorized in Gmail account

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = recipient
    msg["Subject"] = subject

    body = MIMEText(message, "plain")
    msg.attach(body)

    context = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, recipient, msg.as_string())
            print(f"Email sent to: {recipient}")    
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=500, detail="Failed to send email due to authentication error. Please check your email credentials.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")
    
def send_approval_emails(user_email):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.approval_token1 = str(uuid.uuid4())
    user.approval_token2 = str(uuid.uuid4())
    user.approval_token3 = str(uuid.uuid4())
    user.approval_token4 = str(uuid.uuid4())
    session.commit()

    # Extract first and last name from sponsor email
    sponsor_name = user.sponsor.split('@')[0].replace('.', ' ').title()

    # Send approval email to the sponsor first
    approval_link = f"https://{PREFIX_APP}/githubapprovals/approve_user/{user_email}/1?token={user.approval_token1}"
    refusal_link = f"https://{PREFIX_APP}/githubapprovals/refuse_user/{user_email}/1?token={user.approval_token1}"
    message = f"""
    Dear {sponsor_name},

    NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

    You have sponsored {user_email} to join GSL's GitHub.
    
    Do you approve or refuse {user_email}'s request to join GSL's GitHub?:
    - Approve: 
    {approval_link}

    - Refuse: 
    {refusal_link}

    Thank you for your prompt attention to this matter.

    NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.

    Best regards,
    Your Approval Team
    """
    send_email(user.sponsor, "User Agreement Approval Needed", message)

def send_stakeholder_approval_emails(user_email):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
    tokens = [user.approval_token2, user.approval_token3, user.approval_token4]

    # Extract first and last name from sponsor email
    sponsor_name = user.sponsor.split('@')[0].replace('.', ' ').title()

    # Get the number of active licenses from the database
    rowsindatabase = session.query(UserAgreement).count()
    available_licenses = 106 - rowsindatabase

    for idx, (stakeholder, token) in enumerate(zip(stakeholders[1:], tokens), start=2):
        approval_link = f"https://{PREFIX_APP}/githubapprovals/approve_user/{user_email}/{idx}?token={token}"
        refusal_link = f"https://{PREFIX_APP}/githubapprovals/refuse_user/{user_email}/{idx}?token={token}"

        message = f"""
        Dear GitHub Stakeholder,

        NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

        {sponsor_name} has sponsored {user_email} to join GSL's GitHub.

        We currently have {rowsindatabase} active licenses with {available_licenses} licenses available for new members.

        Do you approve or refuse {user_email}'s request to join GSL's GitHub?:
        - Approve: 
        {approval_link}

        - Refuse: 
        {refusal_link}

        Thank you for your prompt attention to this matter.

        NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.

        Best regards,
        Your Approval Team
        """
        send_email(stakeholder, "User Agreement Approval Needed", message)

    scheduler.add_job(send_reminder_emails, 'interval', hours=48, args=[user_email])

def send_reminder_emails(user_email):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()
    if not user or (user.systemowner and user.accountadmin and user.isso and user.sponsorid):
        return

    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
    for idx, stakeholder in enumerate(stakeholders, start=1):
        if not getattr(user, f"approved{idx}"):
            approval_link = f"https://{PREFIX_APP}/githubapprovals/{user_email}/{idx}"
            message = f"Reminder: Please approve the new user agreement from {user_email}. Click to approve: or ignore if you've already responded {approval_link}"
            send_email(stakeholder, "Reminder: User Agreement Approval Needed", message)

@app.get("/", response_class=HTMLResponse)
async def get_agreement_form(request: Request):
    return templates.TemplateResponse("agreement_form.html", {"request": request})

def _gif_fs_and_url_for_user_id(uid: int):
    fs_path = os.path.join("images", f"progress_{uid}.gif")
    url = f"{get_base_path()}images/progress_{uid}.gif"
    return fs_path, url

@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    logging.info("Status page requested")
    session = SessionLocal()
    try:
        agreements = session.query(UserAgreement).all()
        users = []
        for ag in agreements:
            status_dict = build_status_from_agreement(ag)
            stages = list(status_dict.values())
            denied = any(s["status"] == "denied" for s in stages)
            approved_count = sum(1 for s in stages if s["status"] == "validated")
            if approved_count == 4:
                continue
            if denied:
                approval_status = "Denied"
            else:
                approval_status = "Waiting"
            if approval_status == "Waiting":
                pending_roles = [s["role"] for s in stages if s["status"] != "validated"]
                if pending_roles:
                    approval_status = f"Waiting ({', '.join(pending_roles)})"
            fs_path, gif_url = _gif_fs_and_url_for_user_id(ag.id)
            gif_ready = os.path.exists(fs_path)  # Check if the GIF file exists
            users.append({
                "full_name": f"{ag.first_name} {ag.last_name}".strip(),
                "email": ag.email,
                "status": approval_status,
                "gif_url": gif_url if gif_ready else None,
            })
        return templates.TemplateResponse("status.html", 
                                          {"request": request, 
                                           "users": users, 
                                           "base_path": get_base_path()})
    finally:
        session.close()


@app.get("/browse_agreements", response_class=HTMLResponse)
async def browse_agreements(request: Request):
    session = SessionLocal()
    try:
        agreements = session.query(UserAgreement).all()
        logging.info(f"Found {len(agreements)} agreements in the database")
        #print(f"Found {len(agreements)} agreements in the database")
        return templates.TemplateResponse("browse_agreements.html", {"request": request, "agreements": agreements})
    except Exception as e:
        logging.error(f"Error in browse_agreements: {str(e)}")
        #print(f"Error in browse_agreements: {str(e)}")
        raise
    finally:
        session.close()

def format_sponsor_name(sponsor):
    """Return sponsor name from email or as-is if already a name."""
    if sponsor and '@' in sponsor:
        return sponsor.split('@')[0].replace('.', ' ').title()
    return sponsor or ""

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Lightweight read-only dashboard summarizing agreements.

    Columns: User Name, Sponsor, Organization (lab), Role, Approval Status.
    Approval status format:
      - "Denied (n/4 approved)" if any stage denied
      - "n/4 approved" otherwise (n counts validated stages)
    """
    session = SessionLocal()
    try:
        agreements = session.query(UserAgreement).all()
        rows = []
        for ag in agreements:
            status_dict = build_status_from_agreement(ag)
            stages = list(status_dict.values())
            denied = any(s["status"] == "denied" for s in stages)
            approved_count = sum(1 for s in stages if s["status"] == "validated")
            if denied:
                approval_status = f"Denied ({approved_count}/4 approved)"
            else:
                approval_status = f"{approved_count}/4 approved"
            rows.append({
                "user_name": f"{ag.first_name} {ag.last_name}".strip(),
                "email": ag.email,
                "sponsor": format_sponsor_name(ag.sponsor),
                "organization": ag.esrl_lab,
                "role": ag.role,
                "approval_status": approval_status,
            })
        return templates.TemplateResponse("dashboard.html", {"request": request, "rows": rows})
    finally:
        session.close()

class UpdateAgreementRequest(BaseModel):
    first_name: str
    last_name: str
    esrl_lab: str
    role: str
    agreed: bool
    last_renewal_date: datetime  # New field for last renewal date

@app.put("/api/agreements/{email}")
async def update_agreement(
    email: str,
    request: UpdateAgreementRequest,
    credentials: HTTPBasicCredentials = Depends(security)
):
    # Use already loaded environment variables
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=403, detail="GITHUB_TOKEN missing in environment.")

    authenticate_user(credentials)

    session = SessionLocal()
    user_agreement = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user_agreement:
        raise HTTPException(status_code=404, detail="User not found")

    user_agreement.first_name = request.first_name
    user_agreement.last_name = request.last_name
    user_agreement.esrl_lab = request.esrl_lab
    user_agreement.role = request.role
    user_agreement.agreed = request.agreed
    user_agreement.last_renewal_date = request.last_renewal_date
    session.commit()
    return {"message": "Agreement updated successfully"}

def build_status_from_agreement(user_agreement: UserAgreement) -> dict:
    """Build a normalized status summary for each approval stage.

    A stage is considered:
      - "validated" if the corresponding approval field is non-empty
      - "denied"    if the corresponding disapproval field is non-empty (overrides approved)
      - "waiting"   otherwise

    Returns a dict shaped like:
    {
        "stage1": {"role": "sponsor",      "status": "validated|denied|waiting", "stamp": datetime|None},
        "stage2": {"role": "systemowner",  ...},
        "stage3": {"role": "accountadmin", ...},
        "stage4": {"role": "isso",         ...},
    }
    """

    stages = [
        ("sponsor",      user_agreement.sponsorid,     user_agreement.dissponsor,      user_agreement.approval_timestamp1),
        ("systemowner",  user_agreement.systemowner,   user_agreement.dissystemowner,  user_agreement.approval_timestamp2),
        ("accountadmin", user_agreement.accountadmin,  user_agreement.disaccountadmin, user_agreement.approval_timestamp3),
        ("isso",         user_agreement.isso,          user_agreement.disisso,         user_agreement.approval_timestamp4),
    ]

    def _is_flag_set(value) -> bool:
        """Treat None, empty string, numeric 0, and string '0' as NOT set."""
        return value not in (None, "", 0, "0")

    status_dict: dict[str, dict] = {}
    for idx, (role, approved_value, disapproved_value, stamp) in enumerate(stages, start=1):
        if _is_flag_set(disapproved_value):
            status = "denied"
        elif _is_flag_set(approved_value):
            status = "validated"
        else:
            status = "waiting"
        status_dict[f"stage{idx}"] = {"role": role, "status": status, "stamp": stamp}

    return status_dict

# ---------------- GIF Generation Async Support -----------------

# Set this to False to disable GIF animation generation
ENABLE_GIF_ANIMATION = False
GIF_JOBS = {}
GIF_JOBS_LOCK = threading.Lock()

def _start_gif_job(email: str):
    logging.info(f"Starting GIF job for {email}")
    with GIF_JOBS_LOCK:
        job = GIF_JOBS.get(email)
        if job and job.get("status") in ("running", "ready"):
            return
        GIF_JOBS[email] = {"status": "running", "gif_url": None, "error": None}

    def worker():
        logging.info(f"GIF worker started for {email}")
        session = SessionLocal()
        try:
            user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
            if not user:
                logging.error(f"User not found for email: {email}")
                with GIF_JOBS_LOCK:
                    GIF_JOBS[email]["status"] = "error"
                    GIF_JOBS[email]["error"] = "User not found"
                return
            status_dict = build_status_from_agreement(user)
            logging.info(f"Status dict built for {email}: {status_dict}")
            adapted = {k: {"status": v["status"], "timestamp": v["stamp"]} for k, v in status_dict.items()}
            if ENABLE_GIF_ANIMATION:
                gif_url = create_progress_gif(adapted, show_turtle=True, output_filename=f"/images/progress_{user.id}.gif")
                logging.info(f"GIF generated for {email}: {gif_url}")
                with GIF_JOBS_LOCK:
                    GIF_JOBS[email]["status"] = "ready"
                    GIF_JOBS[email]["gif_url"] = gif_url
            else:
                logging.info(f"GIF generation skipped for {email} (animation disabled)")
                with GIF_JOBS_LOCK:
                    GIF_JOBS[email]["status"] = "ready"
                    GIF_JOBS[email]["gif_url"] = None
        except Exception as e:
            logging.exception("GIF generation failed")
            with GIF_JOBS_LOCK:
                GIF_JOBS[email]["status"] = "error"
                GIF_JOBS[email]["error"] = str(e)
        finally:
            session.close()
    threading.Thread(target=worker, daemon=True).start()

def _compute_percent_complete(email: str) -> int:
    logging.info(f"Computing percent complete for {email}")
    session = SessionLocal()
    try:
        user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
        if not user:
            return 0
        status_dict = build_status_from_agreement(user)
        total = 4
        done = sum(1 for s in status_dict.values() if s["status"] in ("validated", "denied"))
        return int(done / total * 100)
    finally:
        session.close()

@app.post("/api/progress/{email}/generate")
async def api_trigger_gif(email: str):
    _start_gif_job(email)
    with GIF_JOBS_LOCK:
        return {"status": GIF_JOBS[email]["status"]}

@app.get("/api/progress/{email}/status")
async def api_progress_status(email: str, request: Request):
    with GIF_JOBS_LOCK:
        job = GIF_JOBS.get(email)
    percent = _compute_percent_complete(email)

    def _gif_fs_and_url_for_user_id(uid: int):
        fs_path = os.path.join("images", f"progress_{uid}.gif")
        url = request.url_for("images", path=f"progress_{uid}.gif")  # respects root_path
        return fs_path, str(url)

    # If no job, fall back to disk presence
    if not job:
        session = SessionLocal()
        try:
            user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
        finally:
            session.close()
        if user:
            fs_path, url = _gif_fs_and_url_for_user_id(user.id)
            logging.info(f"Fallback status check: {fs_path} exists={os.path.exists(fs_path)}")
            if os.path.exists(fs_path):
                return {"status": "ready", "percent": percent, "gif_url": url}
        return {"status": "not_started", "percent": percent}

    # If job exists, prefer disk check to ensure URL correctness/availability
    session = SessionLocal()
    try:
        user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    finally:
        session.close()
    if user:
        fs_path, url = _gif_fs_and_url_for_user_id(user.id)
        if os.path.exists(fs_path):
            return {"status": job["status"], "percent": percent, "gif_url": url}

    # Fallback to job payload if file not yet on disk
    resp = {"status": job["status"], "percent": percent}
    if job.get("gif_url"):
        resp["gif_url"] = job["gif_url"]
    if job.get("error"):
        resp["error"] = job["error"]
    return resp

def get_base_path() -> str:
    if IS_DEVELOPMENT:
        return "/"
    else:
        return "/githubapprovals/"

@app.get("/progress/{email}", response_class=HTMLResponse)
async def progress_page(email: str, request: Request):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        session.close()
        raise HTTPException(status_code=404, detail="User not found")
    full_name = f"{user.first_name} {user.last_name}".strip().title()
    session.close()
    cache_bust = int(datetime.utcnow().timestamp())
    # Trigger generation asynchronously (idempotent)
    _start_gif_job(email)
    return templates.TemplateResponse("submission_progress.html", {"request": request, "full_name": full_name, "gif_url": None, "cache_bust": cache_bust, "email": email, "base_path": get_base_path()})

@app.post("/submit_agreement/")
async def submit_agreement(
    email: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    esrl_lab: str = Form(...),
    role: str = Form(...),
    sponsor: str = Form(...),
    requirement1: bool = Form(...),
    requirement2: bool = Form(...),
    requirement3: bool = Form(...)
):
    logging.info(f"Received agreement submission: email={email}, first_name={first_name}, last_name={last_name}, esrl_lab={esrl_lab}, role={role}, requirement1={requirement1}, requirement2={requirement2}, requirement3={requirement3}")

    if not (requirement1 and requirement2 and requirement3):
        logging.error("All requirements must be agreed to for GSL GitHub access")
        raise HTTPException(status_code=400, detail="All requirements must be agreed to for GSL GitHub access.")

    session = SessionLocal()
    try:
        user_agreement = session.query(UserAgreement).filter(UserAgreement.email == email).first()
        if user_agreement:
            logging.error("Agreement already submitted for this email")
            return {"message":"Agreement already submitted for this email. The progress is being tracked."}

        # Create the user agreement in the database
        user_agreement = UserAgreement(
            email=email,
            first_name=first_name,
            last_name=last_name,
            esrl_lab=esrl_lab,
            role=role,
            sponsor=sponsor,
            agreed=True,
            last_renewal_date=datetime.utcnow() # Set the last renewal date to now
        )
        session.add(user_agreement)
        session.commit()

        # Attempt to send approval emails
        try:
            send_approval_emails(email)
        except HTTPException as e:
            logging.error(f"Failed to send approval emails: {e.detail}")
            session.rollback()
            raise e
        except Exception as e:
            logging.error(f"Error sending approval emails: {e}")
            session.rollback()
            raise HTTPException(status_code=500, detail="Failed to send approval emails")

        logging.info("Agreement submitted successfully")
        return {"message": "Agreement submitted. Awaiting approval."}
    except HTTPException as e:
        logging.error(f"HTTPException: {e.detail}")
        raise e
    except Exception as e:
        logging.error(f"Error submitting agreement: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        session.close()

@app.get("/approve_user/{email}/{approver_id}")
async def approve_user(email: str, approver_id: int, token: str):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
    
    # Check if the user has already been approved by all approvers
    if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
        raise HTTPException(status_code=400, detail="User has already been approved by all stakeholders.")

    if approver_id == 1 and user.approval_token1 != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 2 and user.approval_token2 != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 3 and user.approval_token3 != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 4 and user.approval_token4 != token:
        raise HTTPException(status_code=403, detail="Invalid token")

    if approver_id == 1:
        user.sponsorid = stakeholders[3] 
        user.approval_timestamp1 = datetime.utcnow()
        user.approver_email1 = stakeholders[3]
        session.commit()
        # Send approval emails to other stakeholders after sponsor approves
        send_stakeholder_approval_emails(email)
    elif approver_id == 2:
        user.systemowner = stakeholders[0] 
        user.approval_timestamp2 = datetime.utcnow()
        user.approver_email2 = stakeholders[0]
    elif approver_id == 3:
        user.accountadmin = stakeholders[1] 
        user.approval_timestamp3 = datetime.utcnow()
        user.approver_email3 = stakeholders[1]
    elif approver_id == 4:
        user.isso = stakeholders[2] 
        user.approval_timestamp4 = datetime.utcnow()
        user.approver_email4 = stakeholders[2]

    session.commit()

    if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
        user.final_approval_timestamp = datetime.utcnow()
        session.commit()
        send_final_confirmation_email(user.email, user.sponsor, user.esrl_lab)

    return {"message": "Your approval has been received and the request will now continue through the approval process. Once the candidate is either approved or denied, you'll receive an update via email with access status confirmation."}

@app.get("/refuse_user/{email}/{approver_id}")
async def refuse_user(email: str, approver_id: int, token: str):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)

    # Check if the user has already been approved by all approvers
    if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
        raise HTTPException(status_code=400, detail="User has already been approved by all stakeholders. Disapproval is not possible from the approvals API.  Please contact open a ticket by emailing help.ssg.gsl@noaa.gov")
    
    if approver_id == 1 and user.approval_token1 != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 2 and user.approval_token2 != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 3 and user.approval_token3 != token:
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 4 and user.approval_token4 != token:
        raise HTTPException(status_code=403, detail="Invalid token")

    if approver_id == 1:
        user.dissystemowner = stakeholders[0] 
        user.approval_timestamp1 = datetime.utcnow()
        user.disapprover_email1 = stakeholders[0]
    elif approver_id == 2:
        user.disaccountadmin = stakeholders[1] 
        user.approval_timestamp2 = datetime.utcnow()
        user.disapprover_email2= stakeholders[1]
    elif approver_id == 3:
        user.disisso = stakeholders[2] 
        user.approval_timestamp3 = datetime.utcnow()
        user.disapprover_email3 = stakeholders[2]
    elif approver_id == 4:
        user.dissponsor = stakeholders[3] 
        user.approval_timestamp3 = datetime.utcnow()
        user.disapprover_email4 = stakeholders[3]

    session.commit()

    send_email(user.email, "GitHub Access Request Disapproved", "Your request to join GitHub has been denied.  Email help@gsl.noaa.gov if you have any questions.")
    return {"message": "User disapproved"}

@app.get("/download-agreements/")
def download_agreements():
    db: Session = SessionLocal()
    agreements = db.query(UserAgreement).all()
    db.close()

    # Convert to DataFrame
    df = pd.DataFrame([{
        column.name: getattr(ag, column.name)
        for column in UserAgreement.__table__.columns
    } for ag in agreements])

    # Save to CSV
    file_path = "./data/agreements.csv"
    df.to_csv(file_path, index=False)

    return FileResponse(file_path, media_type='text/csv', filename="agreements.csv")

# new endpoint to get the list of labs and their sponsors
@app.get("/api/lab_sponsors")
async def get_lab_sponsors():
    logging.info("get_lab_sponsors endpoint called")
    try:
        # Try local development path first
        csv_path = "lab_sponsors.csv"
        logging.info(f"Trying local development path: {csv_path}")
        if not os.path.exists(csv_path):
            # If not found, try production path
            csv_path = "/lab_sponsors.csv"
            logging.info(f"Trying production path: {csv_path}")
            if not os.path.exists(csv_path):
                logging.error("Could not find lab_sponsors.csv in either path")
                raise FileNotFoundError(f"Could not find lab_sponsors.csv in either local or production paths")
        
        df = pd.read_csv(csv_path)
        sponsors_by_lab = {}
        for _, row in df.iterrows():
            lab = row['lab']
            sponsor = {"value": row['email'], "text": row['name']}
            sponsors_by_lab.setdefault(lab, []).append(sponsor)
        return sponsors_by_lab
    except Exception as e:
        logging.error(f"Error reading lab sponsors: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Could not load lab sponsors: {str(e)}")

# Add a new endpoint for users to renew their agreement
@app.get("/renew/{email}")
async def renew_agreement(email: str):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.last_renewal_date = datetime.utcnow()
    session.commit()
    session.close()

    return {"message": "Agreement renewed successfully"}

from dotenv import dotenv_values

@app.delete("/api/agreements/{email}")
async def delete_agreement(email: str, credentials: HTTPBasicCredentials = Depends(security)):
    # Use already loaded environment variables
    if not GITHUB_TOKEN:
        raise HTTPException(status_code=403, detail="GITHUB_TOKEN missing in environment.")

    authenticate_user(credentials)
    
    session = SessionLocal()
    user_agreement = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user_agreement:
        raise HTTPException(status_code=404, detail="User not found")

    session.delete(user_agreement)
    session.commit()
    session.close()
    return {"message": "User agreement deleted successfully"}

def authenticate_user(credentials: HTTPBasicCredentials):
    correct_username = os.getenv("EMAIL_ADDRESS")
    correct_password = os.getenv("EMAIL_PASSWORD")
    if not correct_username or not correct_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server authentication configuration is missing.",
        )
    if not (credentials.username == correct_username and credentials.password == correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )  

def send_final_confirmation_email(user_email, sponsor, lab):
    stakeholders = get_stakeholders(lab, sponsor)
    
    # Send access granted email with link to policy document
    granted_message = (
        "You have been granted an account on GitHub!\n\n"
        "Please review the GSL Onboarding Documents to get started:\n"
        "https://docs.google.com/document/d/1JuoRV9g2jOnbaGsy2EXJQ_8sPcSpYNEzqUqkvgghtp8/edit?tab=t.0\n\n"
        "If you have any questions, contact your sponsor or the GSL ITS Team."
    )
    send_email(user_email, "GitHub Access Granted", granted_message)
    
    for stakeholder in stakeholders:
        send_email(stakeholder, "User Approved", f"{user_email} has been granted an account on GitHub.")

#check_for_renewals()  # Initial check for renewals on launch of the server
scheduler.add_job(check_for_renewals, 'interval', days=3)  # Check every three days

