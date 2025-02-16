from fastapi import FastAPI, Form, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, func, Text
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
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

# Define stakeholders globally  -changing this will change who gets contacted.
def get_stakeholders(sponsor):
    return ["renn.valo@noaa.gov", "renn.valo@noaa.gov", "renn.valo@noaa.gov", sponsor]

#app = FastAPI()
app = FastAPI(root_path="https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/")

# List of allowed origins (single domain)
origins = [
    "https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/",
    "http://localhost:8000",
]

# Add CORS middleware to the FastAPI application
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Allow requests from this origin
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods
    allow_headers=["*"],  # Allow all headers
)

# DATABASE_URL = "sqlite:///./data/agreement.db"
DATABASE_URL = "sqlite:////data/agreement.db" # setting path for production server drive mapping
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

templates = Jinja2Templates(directory="templates")

# Serve static files from the /data directory 
app.mount("/images", StaticFiles(directory="images"), name="images")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Load environment variables
#load_dotenv()
load_dotenv('/data/.env')

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
    users_to_renew = session.query(UserAgreement).filter(
        UserAgreement.last_renewal_date <= datetime.utcnow() - timedelta(days=365) 
    ).all()

    for user in users_to_renew:
        renewal_link = f"https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/renew/{user.email}"
        message = f"""
        Dear {user.first_name},

        It has been over a year since your last agreement renewal. Please renew your agreement by clicking the link below:
        Additionally, please make sure you have read and understood GSL's current GitHub Usage Policy:

        href="https://docs.google.com/document/d/1RpJN1kbkheUj5SQCjN4Ta4SWBgrV1uHD/edit" target="_blank">

        Read and understand GSL's GitHub Usage Policy
        
        Please click the link below to renew your agreement:
        {renewal_link}


        Thank you,
        Your Approval Team
        """
        send_email(user.email, "Agreement Renewal Reminder", message)

    session.close()

# Schedule the check_for_renewals function to run periodically
scheduler.add_job(check_for_renewals, 'interval', days=3)

def send_email(recipient, subject, message):
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
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(sender_email, password)
            server.sendmail(sender_email, recipient, msg.as_string())
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


    stakeholders = get_stakeholders(user.sponsor)
    tokens = [user.approval_token1, user.approval_token2, user.approval_token3, user.approval_token4]

    for idx, (stakeholder, token) in enumerate(zip(stakeholders, tokens), start=1):
        approval_link = f'"https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/approve_user/{user_email}/{idx}?token={token}"'
        refusal_link = f'"https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/refuse_user/{user_email}/{idx}?token={token}"'
        #message = f"New user agreement from {user_email}. Click to approve: {approval_link} or refuse: {refusal_link}"
        message = f"""
        Dear GitHub Stakeholder,

        A new user agreement from {user_email} requires your attention.

        Please review the request and take the appropriate action:
        - Approve: 
        {approval_link}

        - Refuse: 
        {refusal_link}

        Thank you for your prompt attention to this matter.

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

    stakeholders = get_stakeholders(user.sponsor)
    for idx, stakeholder in enumerate(stakeholders, start=1):
        if not getattr(user, f"approved{idx}"):
            approval_link = f"https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/{user_email}/{idx}"
            message = f"Reminder: Please approve the new user agreement from {user_email}. Click to approve: or ignore if you've already responded {approval_link}"
            send_email(stakeholder, "Reminder: User Agreement Approval Needed", message)

@app.get("/", response_class=HTMLResponse)
async def get_agreement_form(request: Request):
    return templates.TemplateResponse("agreement_form.html", {"request": request})

@app.get("/browse_agreements", response_class=HTMLResponse)
async def browse_agreements(request: Request):
    session = SessionLocal()
    agreements = session.query(UserAgreement).all()
    return templates.TemplateResponse("browse_agreements.html", {"request": request, "agreements": agreements})

class UpdateAgreementRequest(BaseModel):
    first_name: str
    last_name: str
    esrl_lab: str
    role: str
    agreed: bool
    last_renewal_date: datetime  # New field for last renewal date

@app.put("/api/agreements/{email}")
async def update_agreement(email: str, request: UpdateAgreementRequest):
    session = SessionLocal()
    user_agreement = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user_agreement:
        raise HTTPException(status_code=404, detail="User not found")

    user_agreement.first_name = request.first_name
    user_agreement.last_name = request.last_name
    user_agreement.esrl_lab = request.esrl_lab
    user_agreement.role = request.role
    user_agreement.agreed = request.agreed
    user_agreement.last_renewal_date = request.last_renewal_date  # Update the last renewal date
    session.commit()
    return {"message": "Agreement updated successfully"}

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
            raise HTTPException(status_code=400, detail="Agreement already submitted for this email. You should be hearing back shortly.")

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
    
    stakeholders = get_stakeholders(user.sponsor)
    
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
        user.systemowner = stakeholders[0] 
        user.approval_timestamp1 = datetime.utcnow()
        user.approver_email1 = stakeholders[0]
    elif approver_id == 2:
        user.accountadmin = stakeholders[1] 
        user.approval_timestamp2 = datetime.utcnow()
        user.approver_email2 = stakeholders[1]
    elif approver_id == 3:
        user.isso = stakeholders[2] 
        user.approval_timestamp3 = datetime.utcnow()
        user.approver_email3 = stakeholders[2]
    elif approver_id == 4:
        user.sponsorid = stakeholders[3] 
        user.approval_timestamp4 = datetime.utcnow()
        user.approver_email4 = stakeholders[3]

    session.commit()

    if user.systemowner and user.accountadmin and user.isso and user.sponsorid:
        user.final_approval_timestamp = datetime.utcnow()
        session.commit()
        send_final_confirmation_email(user.email,user.sponsor)

    return {"message": "User approved"}

@app.get("/refuse_user/{email}/{approver_id}")
async def refuse_user(email: str, approver_id: int, token: str):
    session = SessionLocal()
    user = session.query(UserAgreement).filter(UserAgreement.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    stakeholders = get_stakeholders(user.sponsor)

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

def send_final_confirmation_email(user_email, sponsor):
    stakeholders = get_stakeholders(sponsor)
    send_email(user_email, "GitHub Access Granted", "You have been granted an account on GitHub!")
    for stakeholder in stakeholders:
        send_email(stakeholder, "User Approved", f"{user_email} has been granted an account on GitHub.")

if __name__ == "__main__":
    uvicorn.run("approvals:app", host="0.0.0.0", port=8000, reload=False)
