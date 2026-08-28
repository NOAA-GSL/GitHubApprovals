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
from typing import Optional
import pandas as pd
import threading
import time
from verification_progress_gif import create_progress_gif
import sqlite3

# Configure logging with file handler and structured format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Console output for supervisord
        logging.FileHandler(
            '/var/log/approvals.log' if os.path.exists('/var/log') else './approvals.log',
            mode='a'
        )
    ]
)
# Load environment variables
#load_dotenv()
load_dotenv('/data/.env')

# Updated get_stakeholders to use lab and .env
# Load environment variables
load_dotenv('/data/.env')

def get_stakeholders(lab, sponsor):
    logging.debug(f"[STAKEHOLDER] Resolving stakeholders for lab={lab}, sponsor={sponsor}")
    env_var = f"STAKEHOLDERS_{lab.upper()}"
    logging.debug(f"[STAKEHOLDER] Looking up environment variable: {env_var}")
    stakeholders_str = os.getenv(env_var)
    if not stakeholders_str:
        logging.error(f"[STAKEHOLDER] No stakeholders defined for lab: {lab} (env var: {env_var})")
        raise ValueError(f"No stakeholders defined for lab: {lab}")
    stakeholders = [email.strip() for email in stakeholders_str.split(",") if email.strip()]
    # Add sponsor and admin email as before
    stakeholders.append(sponsor)
    # Add all automation owners
    for owner in get_automation_owners():
        stakeholders.append(owner)
    logging.info(f"[STAKEHOLDER] Resolved stakeholders for lab={lab}: System Owner={stakeholders[0]}, Account Admin={stakeholders[1]}, ISSO={stakeholders[2]}, Sponsor={stakeholders[3]}, Automation Owners={stakeholders[4:]}")
    return stakeholders
    # 1st stakeholder is the GitHub System Owner 2nd is the GitHub Account Administrator 3rd is the GitHub Security Officer 4th is the sponsor, and 5th+ are the automation owner(s) who will setup the github account.
    # for testing set all emails to one person like this... return ["renn.valo@noaa.gov", "renn.valo@noaa.gov", "renn.valo@noaa.gov", sponsor, "renn.valo@noaa.gov"]

def get_automation_owners():
    """Parse AUTOMATION_OWNERS environment variable and return list of email addresses.
    
    Supports single email or comma-separated list of emails.
    Defaults to 'renn.valo@noaa.gov' if not set or empty.
    
    Returns:
        list: List of email addresses (at least one)
    """
    owners_str = os.getenv("AUTOMATION_OWNERS", "renn.valo@noaa.gov")
    owners = [email.strip() for email in owners_str.split(",") if email.strip()]
    # Ensure at least one owner is returned (fallback to default)
    if not owners:
        owners = ["renn.valo@noaa.gov"]
    return owners

# Check if we're in development or production mode
# treat anything other than explicit "production" as non-production
IS_DEVELOPMENT = os.getenv("ENVIRONMENT", "development").lower() != "production"

BASE_URL = os.getenv("BASE_URL", "https://localhost:8000")
# Path prefix where the app is mounted (e.g. /githubapprovals/ or /)
BASE_PATH = os.getenv("BASE_PATH", "/" if IS_DEVELOPMENT else "/githubapprovals/")
# Initialize FastAPI with root_path for production and disable auto docs endpoints
app = FastAPI(
    root_path=BASE_PATH.rstrip("/") if BASE_PATH != "/" else "",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
) 

security = HTTPBasic() #adding security to endpoints that need it.

# List of allowed origins (single domain)
origins = [
    "https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/",
    "https://apps-prod.gsd.esrl.noaa.gov/githubapprovals/",
    "https://gsl.noaa.gov/githubapprovals",
    "http://gsl.noaa.gov/githubapprovals",
    "https://githubapprovals.gsl.noaa.gov",
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

logging.info(f"Using database URL: {DATABASE_URL}")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

templates = Jinja2Templates(directory="templates")

# Serve static files from the /data directory 
app.mount("/images", StaticFiles(directory="images"), name="images")

# Constants
ORG_NAME = "NOAA-GSL"  # Replace with your organization name
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # get token so you can use API
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"}
TOTAL_LICENSES = 97  # Replace with your organization's total  -static value for now

# Database models
class UserAgreement(Base):
    __tablename__ = "user_agreements"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    github_username = Column(String, nullable=True, index=True)
    information_owner = Column(Boolean, default=False, index=True)
    welcome_email_sent = Column(Boolean, default=False)
    info_owner_date_added = Column(DateTime, nullable=True)
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
    last_reminder_sent = Column(DateTime, nullable=True)  # Track when last reminder was sent

Base.metadata.create_all(bind=engine)

def migrate_add_last_reminder_sent_column():
    """Add last_reminder_sent column to existing database if it doesn't exist.
    
    This migration is idempotent and safe to run multiple times.
    """
    
    # Determine database path
    if IS_DEVELOPMENT:
        db_path = "./agreement.db"
    else:
        db_path = "/data/agreement.db"
    
    # Check if database file exists
    if not os.path.exists(db_path):
        logging.info("[MIGRATION] Database not found, will be created by SQLAlchemy")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if column already exists
        cursor.execute("PRAGMA table_info(user_agreements)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "last_reminder_sent" not in columns:
            logging.info("[MIGRATION] Adding last_reminder_sent column to user_agreements table")
            cursor.execute("ALTER TABLE user_agreements ADD COLUMN last_reminder_sent TEXT")
            conn.commit()
            logging.info("[MIGRATION] Successfully added last_reminder_sent column")
        else:
            logging.info("[MIGRATION] last_reminder_sent column already exists, skipping")
        
        conn.close()
    except Exception as e:
        logging.error(f"[MIGRATION] Error adding last_reminder_sent column: {str(e)}")
        raise

# Run migration immediately after schema creation
migrate_add_last_reminder_sent_column()

scheduler = BackgroundScheduler()
scheduler.start()

# Track reminder jobs for each user email so we can cancel them later
REMINDER_JOBS = {}

# Function to check for users who need to renew and send reminder emails
def check_for_renewals():
    session = SessionLocal()
    logging.info(f"[RENEWAL] check_for_renewals() started at {datetime.utcnow().isoformat()}")
    
    # Fetch users who need renewal
    users_to_renew = session.query(UserAgreement).filter(
        UserAgreement.last_renewal_date <= datetime.utcnow() - timedelta(days=365)
    ).all()
    logging.info(f"[RENEWAL] Found {len(users_to_renew)} users needing renewal")

    for user in users_to_renew:
        logging.info(f"[RENEWAL] Processing renewal for user_email={user.email}, last_renewal_date={user.last_renewal_date}")

        # Generate renewal token and store it
        renewal_token = str(uuid.uuid4())
        user.approval_token1 = renewal_token
        session.commit()
        logging.debug(f"[RENEWAL] Generated renewal token for user_email={user.email}")

        # Generate the renewal link with token and message
        renewal_link = f"{BASE_URL}/renew/{user.email}?token={renewal_token}"
        logging.debug(f"[RENEWAL] Generated renewal link for user_email={user.email}: {renewal_link}")
        lab = user.esrl_lab.upper()
        policy_link = "https://docs.google.com/document/d/1lCFyaoes64q7x23uGICeY1gQNdnGJE0dAFwS0wBDi9k/"
        message = f"""Dear {user.first_name},

NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

It has been over a year since your last review of GSL's GitHub Usage Policy Agreement.

To continue as a member of NOAA's {lab} GitHub organization you will need to:
  - Read and understand the roles and responsibilities for being a GSL GitHub {user.role}.
  - The latest updates to GSL's GitHub Usage Policy can be found here: {policy_link}

Agree to follow the roles and responsibilities by clicking the link below:
{renewal_link}

NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.

Thank you,
Your GSL ITS Team"""
        html_body = _build_approval_html_email(
            title="Action Required: Annual Agreement Renewal",
            greeting=f"Dear {user.first_name},",
            intro_lines=[
                f"It has been over a year since your last review of GSL's GitHub Usage Policy Agreement.",
                f"To continue as a member of NOAA's <strong>{lab} GitHub organization</strong> as a <strong>{user.role}</strong>, you must renew your agreement.",
            ],
            details_rows=[
                ("Lab", f"NOAA's {lab} GitHub organization"),
                ("Your Role", user.role),
                ("Action Required", "Renew your GitHub Usage Policy agreement"),
            ],
            action_items=[
                f'Read the latest <a href="{policy_link}" style="color:#003087;">GSL GitHub Usage Policy</a>',
                "Click the <strong>Renew Agreement</strong> button below to confirm",
            ],
            action_link=renewal_link,
            action_label="Renew Agreement",
            footer_note="If you have any questions, please contact the GSL ITS Team.",
        )

        # Send email to the user
        send_email(user.email, "Agreement Renewal Reminder", message, html_body=html_body)
        logging.info(f"[EMAIL] Renewal reminder sent to user_email={user.email}")

    session.close()


def recover_pending_approval_reminders():
    """On server startup, find all pending approvals and schedule reminder jobs for them.
    
    This ensures that if the server restarts, pending approvals don't get stuck without reminders.
    """
    logging.info("[STARTUP] Checking for pending approvals to schedule reminder jobs...")
    session = SessionLocal()
    try:
        # Find all users where:
        # - Sponsor approved (sponsorid is set)
        # - Still waiting for at least one stakeholder (systemowner, accountadmin, or isso not set)
        # - Not denied (no disapproval fields set)
        pending_users = session.query(UserAgreement).filter(
            UserAgreement.sponsorid.isnot(None),
            UserAgreement.sponsorid != "",
            UserAgreement.sponsorid != "0"
        ).all()
        
        recovered_count = 0
        for user in pending_users:
            # Check if fully approved - skip if so
            if user.systemowner and user.accountadmin and user.isso:
                continue
            
            # Check if denied - skip if so
            if user.dissponsor or user.dissystemowner or user.disaccountadmin or user.disisso:
                continue
            
            # This user has pending approvals - schedule reminder job
            # Check if job already exists to prevent duplicates
            if user.email not in REMINDER_JOBS:
                logging.info(f"[STARTUP] Recovering reminder job for pending approval: user_email={user.email}")
                job = scheduler.add_job(send_reminder_emails, 'interval', hours=48, args=[user.email])
                REMINDER_JOBS[user.email] = job
                recovered_count += 1
            else:
                logging.debug(f"[STARTUP] Reminder job already exists for user_email={user.email}, skipping")
        
        logging.info(f"[STARTUP] Recovered {recovered_count} pending approval reminder jobs")
    except Exception as e:
        logging.error(f"[STARTUP] Error recovering pending approval reminders: {str(e)}")
    finally:
        session.close()


def send_email(recipient, subject, message, html_body=None):
    logging.debug(f"[EMAIL] Preparing to send email: recipient={recipient}, subject={subject}, from=github.gsl@noaa.gov")
    sender_email = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    if not sender_email or not password:
        logging.error(f"[EMAIL] Email configuration missing for recipient={recipient}")
        raise HTTPException(status_code=500, detail="Email configuration is missing")
    
    #specify the alternative "from" email address
    from_email = "github.gsl@noaa.gov" #Alaternative email address authorized in Gmail account

    msg = MIMEMultipart("alternative")
    msg["From"] = from_email
    msg["To"] = recipient
    msg["Subject"] = subject

    # Plain text part first (fallback for email clients that don't support HTML)
    body = MIMEText(message, "plain")
    msg.attach(body)

    # HTML part second — email clients prefer the last/best part
    if html_body:
        html_part = MIMEText(html_body, "html")
        msg.attach(html_part)

    context = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, recipient, msg.as_string())
            logging.info(f"[EMAIL] Successfully sent email: recipient={recipient}, subject={subject}, timestamp={datetime.utcnow().isoformat()}")    
    except smtplib.SMTPAuthenticationError as e:
        logging.error(f"[EMAIL] SMTP authentication error for recipient={recipient}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send email due to authentication error. Please check your email credentials.")
    except Exception as e:
        logging.error(f"[EMAIL] Failed to send email to recipient={recipient}, subject={subject}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")


def _build_approval_html_email(
    title: str,
    greeting: str,
    intro_lines: list,
    details_rows: list,
    action_items: list,
    approve_link: str = None,
    refuse_link: str = None,
    action_link: str = None,
    action_label: str = None,
    footer_note: str = None,
    is_reminder: bool = False,
) -> str:
    """Build a modern NOAA-GSL branded HTML email with inline CSS.

    Supports two button layouts:
    - approve_link + refuse_link: side-by-side Approve / Refuse buttons
    - action_link + action_label: single centered action button (e.g. renewal)
    """
    # Details table rows
    table_rows_html = ""
    for i, (label, value) in enumerate(details_rows):
        bg = "#f5f7fa" if i % 2 == 0 else "#ffffff"
        table_rows_html += (
            f'<tr style="background-color:{bg};">'
            f'<td style="padding:9px 14px;font-weight:600;color:#333;width:38%;border-bottom:1px solid #e0e0e0;">{label}</td>'
            f'<td style="padding:9px 14px;color:#555;border-bottom:1px solid #e0e0e0;">{value}</td>'
            f'</tr>'
        )

    details_table_html = (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="border:1px solid #e0e0e0;border-radius:6px;overflow:hidden;margin:20px 0;">'
        + table_rows_html +
        '</table>'
    ) if details_rows else ""

    # Buttons
    buttons_html = ""
    if approve_link and refuse_link:
        buttons_html = (
            '<div style="margin:28px 0;text-align:center;">'
            f'<a href="{approve_link}" style="display:inline-block;padding:14px 30px;background-color:#28a745;'
            'color:#ffffff;text-decoration:none;border-radius:6px;font-size:15px;font-weight:600;margin-right:14px;">&#10003;&nbsp;Approve</a>'
            f'<a href="{refuse_link}" style="display:inline-block;padding:14px 30px;background-color:#dc3545;'
            'color:#ffffff;text-decoration:none;border-radius:6px;font-size:15px;font-weight:600;">&#10007;&nbsp;Refuse</a>'
            '</div>'
        )
    elif action_link and action_label:
        buttons_html = (
            '<div style="margin:28px 0;text-align:center;">'
            f'<a href="{action_link}" style="display:inline-block;padding:14px 36px;background-color:#003087;'
            'color:#ffffff;text-decoration:none;border-radius:6px;font-size:15px;font-weight:600;">'
            f'{action_label} &rarr;</a>'
            '</div>'
        )

    # Intro paragraph(s)
    intro_html = "".join(
        f'<p style="margin:6px 0;color:#333;font-size:14px;">{line}</p>'
        for line in intro_lines
    )

    # Action items list
    action_items_html = "".join(
        f'<li style="margin:6px 0;color:#555;font-size:14px;">{item}</li>'
        for item in action_items
    )
    action_section = (
        '<div style="background:#f0f4ff;border-left:4px solid #003087;padding:14px 18px;margin:20px 0;border-radius:0 6px 6px 0;">'
        '<p style="margin:0 0 8px 0;font-weight:600;color:#003087;font-size:14px;">What to do next:</p>'
        f'<ul style="margin:0;padding-left:20px;">{action_items_html}</ul>'
        '</div>'
    ) if action_items else ""

    # VPN note — only shown when action links are present
    vpn_note = (
        '<div style="background:#fff8e1;border-left:4px solid #f9a825;padding:12px 16px;margin:18px 0;border-radius:0 6px 6px 0;">'
        '<p style="margin:0;color:#5d4037;font-size:13px;"><strong>Note:</strong> You must be on the wired '
        'network at NOAA or VPNed in to access the links in this email.</p>'
        '</div>'
    ) if (approve_link or refuse_link or action_link) else ""

    reminder_badge = (
        '<span style="display:inline-block;background:#e65100;color:#fff;font-size:11px;font-weight:700;'
        'padding:2px 10px;border-radius:12px;margin-left:12px;vertical-align:middle;">REMINDER</span>'
    ) if is_reminder else ""

    footer = f'<p style="margin:0 0 4px 0;font-size:12px;color:#666;">{footer_note}</p>' if footer_note else ""

    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '</head>'
        '<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f4;padding:24px 0;">'
        '<tr><td align="center">'
        '<table width="620" cellpadding="0" cellspacing="0" '
        'style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">'
        # Header
        '<tr><td style="background-color:#003087;padding:18px 28px;">'
        '<p style="margin:0;color:#ffffff;font-size:20px;font-weight:700;letter-spacing:1px;">NOAA-GSL</p>'
        '<p style="margin:4px 0 0 0;color:#a8c4e8;font-size:12px;">GitHub Access Management</p>'
        '</td></tr>'
        # Title bar
        f'<tr><td style="background-color:#0d47a1;padding:11px 28px;">'
        f'<p style="margin:0;color:#ffffff;font-size:14px;font-weight:600;">{title}{reminder_badge}</p>'
        '</td></tr>'
        # Body
        '<tr><td style="padding:24px 28px;">'
        f'<p style="margin:0 0 14px 0;color:#333;font-size:15px;">{greeting}</p>'
        f'{intro_html}'
        f'{vpn_note}'
        f'{details_table_html}'
        f'{buttons_html}'
        f'{action_section}'
        '</td></tr>'
        # Footer
        '<tr><td style="background-color:#f8f9fa;padding:14px 28px;border-top:1px solid #e0e0e0;">'
        f'{footer}'
        '<p style="margin:4px 0 0 0;font-size:11px;color:#aaa;">'
        'NOAA-GSL &middot; Automated GitHub Access System &middot; '
        'This is an automated message. Please do not reply to this email.</p>'
        '</td></tr>'
        '</table>'
        '</td></tr></table>'
        '</body></html>'
    )


def send_approval_emails(user_email):
    logging.info(f"[APPROVAL] Initiating sponsor approval email for user_email={user_email}")
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()

    if not user:
        logging.error(f"[APPROVAL] User not found for user_email={user_email}")
        raise HTTPException(status_code=404, detail="User not found")

    user.approval_token1 = str(uuid.uuid4())
    user.approval_token2 = str(uuid.uuid4())
    user.approval_token3 = str(uuid.uuid4())
    user.approval_token4 = str(uuid.uuid4())
    session.commit()
    logging.debug(f"[APPROVAL] Generated approval tokens for user_email={user_email}: token1={user.approval_token1[:8]}..., token2={user.approval_token2[:8]}..., token3={user.approval_token3[:8]}..., token4={user.approval_token4[:8]}...")

    # Extract first and last name from sponsor email
    sponsor_name = user.sponsor.split('@')[0].replace('.', ' ').title()
    lab = user.esrl_lab.upper()
    logging.info(f"[APPROVAL] Sponsor identified: sponsor_email={user.sponsor}, sponsor_name={sponsor_name}, lab={lab}")

    # Send approval email to the sponsor first
    approval_link = f"{BASE_URL}/approve_user/{user_email}/1?token={user.approval_token1}"
    refusal_link = f"{BASE_URL}/refuse_user/{user_email}/1?token={user.approval_token1}"
    message = f"""Dear {sponsor_name},

NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

You have sponsored {user_email} to join NOAA's {lab} GitHub organization.

Do you approve or refuse {user_email}'s request to join NOAA's {lab} GitHub organization?:
- Approve:
{approval_link}

- Refuse:
{refusal_link}

Thank you for your prompt attention to this matter.

NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.

Best regards,
Your Approval Team"""
    html_body = _build_approval_html_email(
        title="Action Required: GitHub Access Approval",
        greeting=f"Dear {sponsor_name},",
        intro_lines=[
            f"You have sponsored <strong>{user_email}</strong> to join NOAA's <strong>{lab} GitHub organization</strong>.",
            "Please review this request and indicate your approval or refusal below.",
        ],
        details_rows=[
            ("Applicant Email", user_email),
            ("Lab", f"NOAA's {lab} GitHub organization"),
            ("Your Role", "Sponsor"),
        ],
        action_items=[
            "Review the request details above",
            "Click <strong>Approve</strong> to approve or <strong>Refuse</strong> to deny access",
        ],
        approve_link=approval_link,
        refuse_link=refusal_link,
        footer_note="If you have any questions, please contact the GSL ITS Team.",
    )
    logging.info(f"[EMAIL] Sending sponsor approval request: recipient={user.sponsor}, user_email={user_email}, approval_link={approval_link}")
    send_email(user.sponsor, "User Agreement Approval Needed", message, html_body=html_body)
    logging.info(f"[APPROVAL] Sponsor approval email sent successfully to sponsor={user.sponsor} for user_email={user_email}")

def send_stakeholder_approval_emails(user_email):
    logging.info(f"[STAKEHOLDER] Initiating stakeholder approval emails for user_email={user_email}")
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()

    if not user:
        logging.error(f"[STAKEHOLDER] User not found for user_email={user_email}")
        raise HTTPException(status_code=404, detail="User not found")

    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
    tokens = [user.approval_token2, user.approval_token3, user.approval_token4]

    # Extract first and last name from sponsor email
    sponsor_name = user.sponsor.split('@')[0].replace('.', ' ').title()
    lab = user.esrl_lab.upper()
    logging.info(f"[STAKEHOLDER] Sponsor info: sponsor_name={sponsor_name}, sponsor_email={user.sponsor}, lab={lab}")

    # Get the number of active licenses from the database
    rowsindatabase = session.query(UserAgreement).count()
    available_licenses = 106 - rowsindatabase
    logging.debug(f"[STAKEHOLDER] License info: active_licenses={rowsindatabase}, available_licenses={available_licenses}")

    stakeholder_roles = ["System Owner", "Account Admin", "ISSO"]
    for idx, (stakeholder, token, role) in enumerate(zip(stakeholders[0:3], tokens, stakeholder_roles), start=2):
        approval_link = f"{BASE_URL}/approve_user/{user_email}/{idx}?token={token}"
        refusal_link = f"{BASE_URL}/refuse_user/{user_email}/{idx}?token={token}"
        logging.info(f"[EMAIL] Preparing stakeholder approval email: approver_id={idx}, role={role}, stakeholder={stakeholder}, user_email={user_email}")

        message = f"""Dear GitHub Stakeholder ({role}),

NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

{sponsor_name} has sponsored {user_email} to join NOAA's {lab} GitHub organization.

We currently have {rowsindatabase} active licenses with {available_licenses} licenses available for new members.

Do you approve or refuse {user_email}'s request to join NOAA's {lab} GitHub organization?:
- Approve:
{approval_link}

- Refuse:
{refusal_link}

Thank you for your prompt attention to this matter.

NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.

Best regards,
Your Approval Team"""
        html_body = _build_approval_html_email(
            title="Action Required: GitHub Access Approval",
            greeting="Dear GitHub Stakeholder,",
            intro_lines=[
                f"<strong>{sponsor_name}</strong> has sponsored <strong>{user_email}</strong> to join NOAA's <strong>{lab} GitHub organization</strong>.",
                f"As <strong>{role}</strong>, your approval is required to proceed.",
            ],
            details_rows=[
                ("Applicant Email", user_email),
                ("Lab", f"NOAA's {lab} GitHub organization"),
                ("Sponsor", sponsor_name),
                ("Your Role", role),
                ("Active Licenses", f"{rowsindatabase} in use, {available_licenses} available"),
            ],
            action_items=[
                "Review the request details above",
                "Click <strong>Approve</strong> to approve or <strong>Refuse</strong> to deny access",
            ],
            approve_link=approval_link,
            refuse_link=refusal_link,
            footer_note="If you have any questions, please contact the GSL ITS Team.",
        )
        send_email(stakeholder, "User Agreement Approval Needed", message, html_body=html_body)
        logging.info(f"[EMAIL] Stakeholder approval email sent: approver_id={idx}, role={role}, stakeholder={stakeholder}, user_email={user_email}")

    logging.info(f"[STAKEHOLDER] All stakeholder approval emails sent for user_email={user_email}")
    
    # Schedule reminder emails every 48 hours (2 days) for stakeholders who haven't responded
    # Cancel existing job if it exists to prevent duplicates
    if user_email in REMINDER_JOBS:
        try:
            REMINDER_JOBS[user_email].remove()
            logging.info(f"[STAKEHOLDER] Removed existing reminder job for user_email={user_email}")
        except Exception as e:
            logging.warning(f"[STAKEHOLDER] Failed to remove existing job for user_email={user_email}: {str(e)}")
    
    job = scheduler.add_job(send_reminder_emails, 'interval', hours=48, args=[user_email])
    REMINDER_JOBS[user_email] = job
    logging.info(f"[STAKEHOLDER] Scheduled reminder job for user_email={user_email}, job_id={job.id}")

def send_renewal_confirmation_email(user_email):
    """Send confirmation email after successful renewal."""
    logging.info(f"[RENEWAL] Sending renewal confirmation email to user_email={user_email}")
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()
    
    if not user:
        logging.error(f"[RENEWAL] User not found for confirmation email: user_email={user_email}")
        session.close()
        return
    
    # Calculate next renewal date (one year from now)
    next_renewal_date = (datetime.utcnow() + timedelta(days=365)).strftime("%B %d, %Y")
    lab = user.esrl_lab.upper()

    message = f"""Dear {user.first_name},

Thank you for reviewing and agreeing to GSL's GitHub Usage Policy.

Your renewal has been successfully completed! You are good for another year of access to NOAA's {lab} GitHub organization.

Your next renewal will be due on or around: {next_renewal_date}

You will receive a reminder email when it's time to renew again.

If you have any questions about the GitHub Usage Policy or your access, please contact your sponsor or the GSL ITS Team.

Thank you,
Your GSL ITS Team"""
    html_body = _build_approval_html_email(
        title="GitHub Access Renewed Successfully",
        greeting=f"Dear {user.first_name},",
        intro_lines=[
            "Thank you for reviewing and agreeing to GSL's GitHub Usage Policy.",
            f"Your renewal has been successfully completed! You are good for another year of access to NOAA's <strong>{lab} GitHub organization</strong>.",
        ],
        details_rows=[
            ("Status", "&#10003; Renewed"),
            ("Next Renewal Due", next_renewal_date),
        ],
        action_items=[
            "No further action is required at this time",
            "You will receive a reminder email when it is time to renew again",
        ],
        footer_note="If you have any questions, please contact your sponsor or the GSL ITS Team.",
    )

    send_email(user_email, "GitHub Access Renewed Successfully", message, html_body=html_body)
    logging.info(f"[EMAIL] Renewal confirmation sent to user_email={user_email}")
    session.close()

def send_reminder_emails(user_email):
    """Send reminder emails to stakeholders who haven't responded yet."""
    logging.info(f"[APPROVAL] Checking if reminder emails needed for user_email={user_email}")
    session = SessionLocal()
    try:
        user = session.query(UserAgreement).filter(UserAgreement.email == user_email).first()
        if not user:
            logging.warning(f"[APPROVAL] User not found for reminders: user_email={user_email}")
            return
        
        # Check if already fully approved - stop reminders
        if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
            logging.info(f"[APPROVAL] User fully approved, cancelling reminder job: user_email={user_email}")
            if user_email in REMINDER_JOBS:
                REMINDER_JOBS[user_email].remove()
                del REMINDER_JOBS[user_email]
            return
        
        # Check if any disapprovals - stop reminders
        if user.dissponsor or user.dissystemowner or user.disaccountadmin or user.disisso:
            logging.info(f"[APPROVAL] User has disapprovals, cancelling reminder job: user_email={user_email}")
            if user_email in REMINDER_JOBS:
                REMINDER_JOBS[user_email].remove()
                del REMINDER_JOBS[user_email]
            return
        
        # Check if reminder was sent less than 24 hours ago
        if user.last_reminder_sent:
            time_since_last_reminder = datetime.utcnow() - user.last_reminder_sent
            if time_since_last_reminder < timedelta(hours=24):
                hours_remaining = 24 - (time_since_last_reminder.total_seconds() / 3600)
                logging.info(f"[APPROVAL] Skipping reminder (sent {time_since_last_reminder.total_seconds()/3600:.1f}h ago, {hours_remaining:.1f}h remaining): user_email={user_email}")
                return

        stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
        tokens = [user.approval_token1, user.approval_token2, user.approval_token3, user.approval_token4]
        approval_fields = ['sponsorid', 'systemowner', 'accountadmin', 'isso']
        stakeholder_roles = ["Sponsor", "System Owner", "Account Admin", "ISSO"]
        lab = user.esrl_lab.upper()
        sponsor_name = user.sponsor.split('@')[0].replace('.', ' ').title()
        
        # Send reminders only to stakeholders who haven't responded
        for idx, (stakeholder, token, field, role) in enumerate(zip(stakeholders[0:4], tokens, approval_fields, stakeholder_roles), start=1):
            approval_value = getattr(user, field)
            disapproval_field = f"dis{field}" if field != 'sponsorid' else 'dissponsor'
            disapproval_value = getattr(user, disapproval_field)
            
            # Skip if this stakeholder already responded (approved or disapproved)
            if approval_value or disapproval_value:
                logging.debug(f"[APPROVAL] Skipping reminder for {role} (already responded): user_email={user_email}")
                continue
            
            # Send reminder
            approval_link = f"{BASE_URL}/approve_user/{user_email}/{idx}?token={token}"
            refusal_link = f"{BASE_URL}/refuse_user/{user_email}/{idx}?token={token}"
            
            message = f"""Dear GitHub Stakeholder ({role}),

NOTE: You must be on the wired network at NOAA or VPNed in to access the links below.

This is a reminder that {user_email} is awaiting your approval to join NOAA's {lab} GitHub organization.

Do you approve or refuse {user_email}'s request to join NOAA's {lab} GitHub organization?:
- Approve:
{approval_link}

- Refuse:
{refusal_link}

Thank you for your prompt attention to this matter.

NOTE: You must be on the wired network at NOAA or VPNed in to access the links above.

Best regards,
Your Approval Team"""
            html_body = _build_approval_html_email(
                title="Reminder: GitHub Access Approval Needed",
                greeting="Dear GitHub Stakeholder,",
                intro_lines=[
                    f"This is a reminder that <strong>{user_email}</strong> is still awaiting your approval to join NOAA's <strong>{lab} GitHub organization</strong>.",
                ],
                details_rows=[
                    ("Applicant Email", user_email),
                    ("Lab", f"NOAA's {lab} GitHub organization"),
                    ("Sponsor", sponsor_name),
                    ("Your Role", role),
                ],
                action_items=[
                    "Click <strong>Approve</strong> to approve or <strong>Refuse</strong> to deny access",
                ],
                approve_link=approval_link,
                refuse_link=refusal_link,
                footer_note="If you have any questions, please contact the GSL ITS Team.",
                is_reminder=True,
            )
            
            logging.info(f"[EMAIL] Sending reminder to {role}: stakeholder={stakeholder}, user_email={user_email}")
            send_email(stakeholder, "Reminder: User Agreement Approval Needed", message, html_body=html_body)
        
        # Update last_reminder_sent timestamp
        user.last_reminder_sent = datetime.utcnow()
        session.commit()
        logging.info(f"[APPROVAL] Updated last_reminder_sent for user_email={user_email}")
    
    except Exception as e:
        logging.error(f"[APPROVAL] Error sending reminder emails for user_email={user_email}: {str(e)}")
    finally:
        session.close()

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
    github_username: Optional[str] = None
    information_owner: Optional[bool] = False
    welcome_email_sent: Optional[bool] = False

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
    user_agreement.github_username = request.github_username
    user_agreement.information_owner = request.information_owner
    user_agreement.welcome_email_sent = request.welcome_email_sent
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
    return BASE_PATH

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
    github_username: str = Form(...),
    requirement1: bool = Form(...),
    requirement2: bool = Form(...),
    requirement3: bool = Form(...),
    requirement4: bool = Form(False)
):
    logging.info(f"[APPROVAL] Received agreement submission: user_email={email}, first_name={first_name}, last_name={last_name}, github_username={github_username}, lab={esrl_lab}, role={role}, sponsor={sponsor}")
    logging.debug(f"[APPROVAL] Requirements agreed: requirement1={requirement1}, requirement2={requirement2}, requirement3={requirement3}, requirement4={requirement4}")

    if not (requirement1 and requirement2 and requirement3):
        logging.error(f"[APPROVAL] Requirements not met for user_email={email}")
        raise HTTPException(status_code=400, detail="All requirements must be agreed to for GSL GitHub access.")

    session = SessionLocal()
    try:
        user_agreement = session.query(UserAgreement).filter(UserAgreement.email == email).first()
        if user_agreement:
            logging.error(f"[APPROVAL] Duplicate submission attempt for user_email={email}")
            raise HTTPException(status_code=400, detail="Agreement already submitted for this email. You should be hearing back shortly.")

        # Create the user agreement in the database
        user_agreement = UserAgreement(
            email=email,
            first_name=first_name,
            last_name=last_name,
            github_username=github_username.strip(),
            esrl_lab=esrl_lab,
            role=role,
            sponsor=sponsor,
            agreed=True,
            last_renewal_date=datetime.utcnow() # Set the last renewal date to now
        )
        session.add(user_agreement)
        session.commit()
        logging.info(f"[APPROVAL] Agreement created in database: user_email={email}, github_username={github_username}, lab={esrl_lab}, role={role}, sponsor={sponsor}")

        # Attempt to send approval emails
        try:
            logging.info(f"[APPROVAL] Initiating approval email process for user_email={email}")
            send_approval_emails(email)
        except HTTPException as e:
            logging.error(f"[APPROVAL] Failed to send approval emails for user_email={email}: {e.detail}")
            session.rollback()
            raise e
        except Exception as e:
            logging.error(f"[APPROVAL] Error sending approval emails for user_email={email}: {str(e)}")
            session.rollback()
            raise HTTPException(status_code=500, detail="Failed to send approval emails")

        logging.info(f"[APPROVAL] Agreement submitted successfully for user_email={email}")
        return {"message": "Agreement submitted. Awaiting approval."}
    except HTTPException as e:
        logging.error(f"[APPROVAL] HTTPException in submit_agreement for user_email={email}: {e.detail}")
        raise e
    except Exception as e:
        logging.error(f"[APPROVAL] Error submitting agreement for user_email={email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    finally:
        session.close()

@app.get("/approve_user/{email}/{approver_id}", response_class=HTMLResponse)
async def approve_user(request: Request, email: str, approver_id: int, token: str):
    logging.info(f"[APPROVAL] Approval endpoint called: user_email={email}, approver_id={approver_id}")
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        logging.error(f"[APPROVAL] User not found for approval: user_email={email}")
        raise HTTPException(status_code=404, detail="User not found")
    
    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
    logging.debug(f"[APPROVAL] Stakeholders for user_email={email}: {stakeholders}")
    
    # Check if the user has already been approved by all approvers
    if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
        logging.warning(f"[APPROVAL] User already fully approved: user_email={email}")
        raise HTTPException(status_code=400, detail="User has already been approved by all stakeholders.")

    if approver_id == 1 and user.approval_token1 != token:
        logging.error(f"[APPROVAL] Invalid token for user_email={email}, approver_id={approver_id}")
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 2 and user.approval_token2 != token:
        logging.error(f"[APPROVAL] Invalid token for user_email={email}, approver_id={approver_id}")
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 3 and user.approval_token3 != token:
        logging.error(f"[APPROVAL] Invalid token for user_email={email}, approver_id={approver_id}")
        raise HTTPException(status_code=403, detail="Invalid token")
    elif approver_id == 4 and user.approval_token4 != token:
        logging.error(f"[APPROVAL] Invalid token for user_email={email}, approver_id={approver_id}")
        raise HTTPException(status_code=403, detail="Invalid token")
    
    logging.info(f"[APPROVAL] Token validated successfully for user_email={email}, approver_id={approver_id}")

    if approver_id == 1:
        user.sponsorid = stakeholders[3] 
        user.approval_timestamp1 = datetime.utcnow()
        user.approver_email1 = stakeholders[3]
        logging.info(f"[APPROVAL] Sponsor approved: user_email={email}, sponsor={stakeholders[3]}, timestamp={user.approval_timestamp1.isoformat()}")
        session.commit()
        # Send approval emails to other stakeholders after sponsor approves
        logging.info(f"[APPROVAL] Triggering stakeholder notifications for user_email={email}")
        send_stakeholder_approval_emails(email)
    elif approver_id == 2:
        user.systemowner = stakeholders[0] 
        user.approval_timestamp2 = datetime.utcnow()
        user.approver_email2 = stakeholders[0]
        logging.info(f"[APPROVAL] System Owner approved: user_email={email}, approver={stakeholders[0]}, timestamp={user.approval_timestamp2.isoformat()}")
    elif approver_id == 3:
        user.accountadmin = stakeholders[1] 
        user.approval_timestamp3 = datetime.utcnow()
        user.approver_email3 = stakeholders[1]
        logging.info(f"[APPROVAL] Account Admin approved: user_email={email}, approver={stakeholders[1]}, timestamp={user.approval_timestamp3.isoformat()}")
    elif approver_id == 4:
        user.isso = stakeholders[2] 
        user.approval_timestamp4 = datetime.utcnow()
        user.approver_email4 = stakeholders[2]
        logging.info(f"[APPROVAL] ISSO approved: user_email={email}, approver={stakeholders[2]}, timestamp={user.approval_timestamp4.isoformat()}")

    session.commit()

    if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
        user.final_approval_timestamp = datetime.utcnow()
        session.commit()
        logging.info(f"[APPROVAL] All approvals complete for user_email={email}, triggering final confirmation, final_timestamp={user.final_approval_timestamp.isoformat()}")
        send_final_confirmation_email(user.email, user.sponsor, user.esrl_lab)
        
        # Cancel reminder job since approval is complete
        if email in REMINDER_JOBS:
            try:
                REMINDER_JOBS[email].remove()
                del REMINDER_JOBS[email]
                logging.info(f"[APPROVAL] Cancelled reminder job for fully approved user: user_email={email}")
            except Exception as e:
                logging.warning(f"[APPROVAL] Failed to cancel reminder job for user_email={email}: {str(e)}")

    session.close()
    return templates.TemplateResponse("confirmation.html", {
        "request": request,
        "page_title": "Approval Received",
        "heading": "Approval Received!",
        "message": "Thank you for your response.",
        "submessage": "Your approval has been received and the request will now continue through the approval process.",
        "icon_type": "success",
        "icon": "✓",
        "show_info_box": True,
        "info_items": [
            "✅ Your response has been recorded",
            "📧 Once the candidate is either approved or denied, you'll receive an update via email"
        ],
        "footer_message": "If you have any questions, please contact the GSL ITS Team."
    })

@app.get("/refuse_user/{email}/{approver_id}", response_class=HTMLResponse)
async def refuse_user(request: Request, email: str, approver_id: int, token: str):
    logging.info(f"[APPROVAL] REFUSAL endpoint called: user_email={email}, approver_id={approver_id}")
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        logging.error(f"[APPROVAL] User not found for refusal: user_email={email}")
        raise HTTPException(status_code=404, detail="User not found")
    
    stakeholders = get_stakeholders(user.esrl_lab, user.sponsor)
    logging.debug(f"[APPROVAL] Stakeholders for refusal of user_email={email}: {stakeholders}")

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
        user.dissponsor = stakeholders[3] 
        user.approval_timestamp1 = datetime.utcnow()
        user.disapprover_email1 = stakeholders[3]
        logging.info(f"[APPROVAL] Sponsor refused: user_email={email}, disapprover={stakeholders[3]}, timestamp={user.approval_timestamp1.isoformat()}")
    elif approver_id == 2:
        user.dissystemowner = stakeholders[0] 
        user.approval_timestamp2 = datetime.utcnow()
        user.disapprover_email2 = stakeholders[0]
        logging.info(f"[APPROVAL] System Owner refused: user_email={email}, disapprover={stakeholders[0]}, timestamp={user.approval_timestamp2.isoformat()}")
    elif approver_id == 3:
        user.disaccountadmin = stakeholders[1] 
        user.approval_timestamp3 = datetime.utcnow()
        user.disapprover_email3 = stakeholders[1]
        logging.info(f"[APPROVAL] Account Admin refused: user_email={email}, disapprover={stakeholders[1]}, timestamp={user.approval_timestamp3.isoformat()}")
    elif approver_id == 4:
        user.disisso = stakeholders[2] 
        user.approval_timestamp4 = datetime.utcnow()
        user.disapprover_email4 = stakeholders[2]
        logging.info(f"[APPROVAL] ISSO refused: user_email={email}, disapprover={stakeholders[2]}, timestamp={user.approval_timestamp4.isoformat()}")

    session.commit()

    logging.info(f"[EMAIL] Sending disapproval notification to user_email={email}")
    lab_upper = user.esrl_lab.upper()
    dis_message = f"Your request to join NOAA's {lab_upper} GitHub organization has been denied. Email help@gsl.noaa.gov if you have any questions."
    dis_html = _build_approval_html_email(
        title="GitHub Access Request Not Approved",
        greeting="Hello,",
        intro_lines=[
            f"We regret to inform you that your request to join NOAA's <strong>{lab_upper} GitHub organization</strong> has not been approved.",
        ],
        details_rows=[
            ("Lab", f"NOAA's {lab_upper} GitHub organization"),
            ("Status", "Not Approved"),
        ],
        action_items=[
            'Contact <a href="mailto:help@gsl.noaa.gov" style="color:#003087;">help@gsl.noaa.gov</a> if you have any questions or wish to appeal this decision',
        ],
        footer_note="If you believe this decision was made in error, please contact the GSL ITS Team.",
    )
    send_email(user.email, "GitHub Access Request Disapproved", dis_message, html_body=dis_html)
    logging.info(f"[APPROVAL] User disapproved and notified: user_email={email}, approver_id={approver_id}")
    
    # Cancel reminder job since user has been denied
    if email in REMINDER_JOBS:
        try:
            REMINDER_JOBS[email].remove()
            del REMINDER_JOBS[email]
            logging.info(f"[APPROVAL] Cancelled reminder job for denied user: user_email={email}")
        except Exception as e:
            logging.warning(f"[APPROVAL] Failed to cancel reminder job for user_email={email}: {str(e)}")
    
    session.close()
    return templates.TemplateResponse("confirmation.html", {
        "request": request,
        "page_title": "Response Received",
        "heading": "Response Received",
        "message": "Thank you for your response.",
        "submessage": "The candidate has been notified of the decision.",
        "icon_type": "info",
        "icon": "ℹ",
        "show_info_box": False,
        "footer_message": "If you have any questions, please contact the GSL ITS Team."
    })

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
    if IS_DEVELOPMENT:
        csv_path = "lab_sponsors.csv"  # local dev / test
    else:
        csv_path = "/data/lab_sponsors.csv"  # production volume
    df = pd.read_csv(csv_path)
    sponsors_by_lab = {}
    for _, row in df.iterrows():
        lab = row['lab']
        name = row.get('name')
        email = row.get('email')
        if pd.isna(name) or pd.isna(email):
            logging.warning(f"[LAB_SPONSORS] Skipping row with missing name or email: lab={lab}")
            continue
        sponsor = {"value": str(email), "text": str(name)}
        sponsors_by_lab.setdefault(lab, []).append(sponsor)
    return sponsors_by_lab

# Add a new endpoint for users to renew their agreement
@app.get("/renew/{email}", response_class=HTMLResponse)
async def renew_agreement(request: Request, email: str, token: str = None):
    logging.info(f"[RENEWAL] Renewal endpoint called: user_email={email}, token_provided={token is not None}")
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        logging.error(f"[RENEWAL] User not found for renewal: user_email={email}")
        session.close()
        return templates.TemplateResponse("confirmation.html", {
            "request": request,
            "page_title": "User Not Found",
            "heading": "User Not Found",
            "message": "We couldn't find an agreement associated with this email address.",
            "submessage": "Please contact the GSL ITS Team if you believe this is an error.",
            "icon_type": "error",
            "icon": "✗",
            "show_info_box": False,
            "email": email,
            "footer_message": "For assistance, please contact the GSL ITS Team."
        })

    # Check if token is missing
    if token is None:
        logging.warning(f"[RENEWAL] No token provided for user_email={email}")
        session.close()
        return templates.TemplateResponse("confirmation.html", {
            "request": request,
            "page_title": "Token Required",
            "heading": "Renewal Link Invalid",
            "message": "This renewal link is incomplete or has expired.",
            "submessage": "Please use the renewal link from your most recent reminder email.",
            "icon_type": "error",
            "icon": "✗",
            "show_info_box": True,
            "email": email,
            "info_items": [
                "🔗 Renewal links must include a security token",
                "📧 Check your email for the complete renewal link",
                "⏰ Tokens expire after use for security",
                "❓ Contact the GSL ITS Team if you need a new renewal link"
            ],
            "footer_message": "For assistance, please contact the GSL ITS Team."
        })

    # Validate the renewal token
    if user.approval_token1 != token:
        logging.warning(f"[RENEWAL] Invalid token provided for user_email={email}")
        session.close()
        return templates.TemplateResponse("confirmation.html", {
            "request": request,
            "page_title": "Invalid Token",
            "heading": "Renewal Link Invalid",
            "message": "This renewal link is invalid or has already been used.",
            "submessage": "Please use the renewal link from your most recent reminder email.",
            "icon_type": "error",
            "icon": "✗",
            "show_info_box": True,
            "email": email,
            "info_items": [
                "🔒 Each renewal link can only be used once",
                "📧 Check your email for the latest renewal link",
                "⏰ Old links expire after use for security",
                "❓ Contact the GSL ITS Team if you need a new renewal link"
            ],
            "footer_message": "For assistance, please contact the GSL ITS Team."
        })

    renewal_timestamp = datetime.utcnow()
    user.last_renewal_date = renewal_timestamp
    # Clear the token after successful renewal
    user.approval_token1 = None
    session.commit()
    logging.info(f"[RENEWAL] Agreement renewed successfully: user_email={email}, renewal_timestamp={renewal_timestamp.isoformat()}")
    
    # Calculate next renewal date for display
    next_renewal_date = (datetime.utcnow() + timedelta(days=365)).strftime("%B %d, %Y")
    
    # Send confirmation email
    try:
        send_renewal_confirmation_email(email)
    except Exception as e:
        logging.error(f"[RENEWAL] Failed to send confirmation email to user_email={email}: {str(e)}")
        # Don't fail the renewal if email fails
    
    session.close()
    return templates.TemplateResponse("confirmation.html", {
        "request": request,
        "page_title": "Renewal Confirmed",
        "heading": "Renewal Confirmed!",
        "message": "Thank you for reviewing GSL's GitHub Usage Policy.",
        "submessage": "Your response has been received and processed successfully.",
        "icon_type": "success",
        "icon": "✓",
        "show_info_box": True,
        "email": email,
        "info_items": [
            "✅ You're all set for another year of GitHub access!",
            f"📅 Your next renewal will be due on or around: <strong>{next_renewal_date}</strong>"
        ],
        "footer_message": "If you have any questions about the GitHub Usage Policy or your access, please contact your sponsor or the GSL ITS Team."
    })

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
    logging.info(f"[APPROVAL] Sending final confirmation emails: user_email={user_email}, sponsor={sponsor}, lab={lab}")
    stakeholders = get_stakeholders(lab, sponsor)
    logging.debug(f"[STAKEHOLDER] Stakeholders receiving final confirmation for user_email={user_email}: {stakeholders}")
    lab_upper = lab.upper()
    onboarding_link = "https://docs.google.com/document/d/1JuoRV9g2jOnbaGsy2EXJQ_8sPcSpYNEzqUqkvgghtp8/edit?tab=t.0"

    # Send access granted email to the user
    granted_message = (
        f"Congratulations! You have been granted access to NOAA's {lab_upper} GitHub organization.\n\n"
        "Please review the GSL Onboarding Documents to get started:\n"
        f"{onboarding_link}\n\n"
        "If you have any questions, contact your sponsor or the GSL ITS Team."
    )
    granted_html = _build_approval_html_email(
        title="GitHub Access Granted",
        greeting="Hello,",
        intro_lines=[
            f"Congratulations! You have been granted access to NOAA's <strong>{lab_upper} GitHub organization</strong>.",
            "All required approvals have been completed successfully.",
        ],
        details_rows=[
            ("Your Email", user_email),
            ("Lab", f"NOAA's {lab_upper} GitHub organization"),
            ("Status", "&#10003; Access Granted"),
        ],
        action_items=[
            f'Review the <a href="{onboarding_link}" style="color:#003087;">GSL GitHub Onboarding Documents</a> to get started',
            "Contact your sponsor if you have any questions about your access",
        ],
        action_link=onboarding_link,
        action_label="View Onboarding Documents",
        footer_note="If you have any questions, contact your sponsor or the GSL ITS Team.",
    )
    logging.info(f"[EMAIL] Sending access granted email to user_email={user_email}")
    send_email(user_email, "GitHub Access Granted", granted_message, html_body=granted_html)

    # Notify all stakeholders
    for stakeholder in stakeholders:
        logging.info(f"[EMAIL] Sending approval confirmation to stakeholder={stakeholder} for user_email={user_email}")
        stakeholder_message = f"{user_email} has been granted access to NOAA's {lab_upper} GitHub organization. All approvals are complete."
        stakeholder_html = _build_approval_html_email(
            title="User Approved — GitHub Access Granted",
            greeting="Hello,",
            intro_lines=[
                f"<strong>{user_email}</strong> has been granted access to NOAA's <strong>{lab_upper} GitHub organization</strong>.",
                "All required approvals have been completed.",
            ],
            details_rows=[
                ("Approved User", user_email),
                ("Lab", f"NOAA's {lab_upper} GitHub organization"),
                ("Status", "&#10003; Fully Approved"),
            ],
            action_items=[],
            footer_note="This is an automated notification. No further action is required.",
        )
        send_email(stakeholder, "User Approved", stakeholder_message, html_body=stakeholder_html)

    logging.info(f"[APPROVAL] Final confirmation process completed for user_email={user_email}")

#check_for_renewals()  # Initial check for renewals on launch of the server
scheduler.add_job(check_for_renewals, 'interval', days=3)  # Check every three days

# On startup, recover reminder jobs for any pending approvals
recover_pending_approval_reminders()

#testing workflow for sending emails to stakeholders when a user is approved by their sponsor