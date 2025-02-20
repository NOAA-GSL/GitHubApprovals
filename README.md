# GitHub Approvals

This project is a FastAPI application designed to manage user agreements for accessing GitHub repositories. It includes functionalities for submitting agreements, browsing existing agreements, and handling approval processes by multiple sponsors.

## Description

The application consists of the following main components:

1. **FastAPI Application**: The backend server that handles HTTP requests and responses.
2. **Database**: SQLite database to store user agreements.
3. **Templates**: HTML templates for rendering forms and browsing agreements.
4. **Email Notifications**: Sending emails to stakeholders for approval and reminders.

## Files

- **approvals.py**: The main FastAPI application file.
- **templates/agreement_form.html**: HTML template for submitting a new agreement.
- **templates/browse_agreements.html**: HTML template for browsing existing agreements.

## How It Works
Users goto https://apps-dev.gsd.esrl.noaa.gov/githubapprovals/ and sign up.  Approvals are automattically sent out to all stakeholders for the approval process.

### Submitting an Agreement

1. **Form**: The user fills out the agreement form in agreement_form.html.
2. **Submission**: The form data is submitted to the `/submit_agreement/` endpoint.
3. **Validation**: The server validates the form data and stores it in the database.
4. **Email Notifications**: Approval emails are sent to stakeholders.

### Browsing Agreements

1. **Page**: The user navigates to the browse agreements page in browse_agreements.html.
2. **Display**: The server fetches all agreements from the database and displays them in a table.
3. **Editing**: Users can edit agreement details and save changes.

### Approval Process

1. **Approval Links**: Stakeholders receive approval links via email.
2. **Approval/Refusal**: Stakeholders can approve or refuse the agreement by clicking the respective links.
3. **Final Approval**: Once all stakeholders approve, a final confirmation email is sent to the user.


### Implementation
The current implementation is on our internal Kubernetes network.  You can view the deployment on Rancher for those with access.

### Sample Deployment Workflow
1. **Build Container**: Build the container with your GitHub repo and package tag: docker build . -t ghcr.io/noaa-gsl/githubapprovals/container_name-ghcr
2. **Push Container to GitHub**: Push the new tagged container to your repo: docker push ghcr.io/noaa-gsl/githubapprovals/container_name-ghcr:latest
3. **Redeploy Container in Kubernetes**: This last step is handles via CLI or Rancher depending on preferences and current setup of your Kubernetes network at GSL.

### Database Models

The database model is defined in `approvals.py` using SQLAlchemy: and SQLite

```python
def get_stakeholders(sponsor): # This is where we set the current stakeholders.  
    
class UserAgreement(Base):
    __tablename__ = "user_agreements"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    esrl_lab = Column(String, nullable=False)
    role = Column(String, nullable=False)
    agreed = Column(Boolean, default=False)
    approved1 = Column(Boolean, default=False)
    approved2 = Column(Boolean, default=False)
    approved3 = Column(Boolean, default=False)
    disapproved1 = Column(Boolean, default=False)
    disapproved2 = Column(Boolean, default=False)
    disapproved3 = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=func.now())
    approval_timestamp1 = Column(DateTime)
    approval_timestamp2 = Column(DateTime)
    approval_timestamp3 = Column(DateTime)
    final_approval_timestamp = Column(DateTime)
    approval_token1 = Column(Text, unique=True)
    approval_token2 = Column(Text, unique=True)
    approval_token3 = Column(Text, unique=True)# GitHubApprovals
    etc
```
### Endpoints

```GET /: Renders the agreement form.
POST /submit_agreement/: Handles form submission.
GET /browse_agreements: Renders the browse agreements page.
PUT /api/agreements/{email}: Updates an existing agreement.
GET /approve_user/{email}/{approver_id}: Approves an agreement.
GET /refuse_user/{email}/{approver_id}: Refuses an agreement.
GET /download-agreements/: Downloads all agreements as a CSV file.
Email Notifications
Emails are sent using the smtplib library. The send_email function handles the email sending process.
```

### Background Tasks
The application uses APScheduler to schedule reminder emails for pending approvals.

### Running the Application
Install Dependencies: Install the required Python packages.
```pip install fastapi sqlalchemy apscheduler pydantic pandas jinja2 python-dotenv```
### Run the Server: Start the FastAPI server.
``` uvicorn approvals:app --host 0.0.0.0 --port 7860```
NOTE:  Now that the server has been converted you can just start it manually with python3 approvals.py.  This was done to accomidate Docker for the new container.
### Alternative to running in locally - running in Docker by building the Dockerfile after cloning the Repo
```docker build -t github-approvals .```


```docker run --rm -p 8000:8000 -v /data:/data github-approvals```

```docker run --rm -d -p 8000:8000 -v /data:/data github-approvals``` 
to run as a server without a console


### Access the Application: Open your browser and navigate to
```http://127.0.0.1:8000/```

Conclusion
This FastAPI application provides a comprehensive solution for managing user agreements and approvals for GitHub access. It includes form submissions, roles, browsing agreements, and an approval process with email notifications. ```
