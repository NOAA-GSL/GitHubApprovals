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

### Removing an existing user
1. Go to the "Browse Agreements" page in the application.
2. Locate the user you wish to remove and use the delete option provided in the interface.
3. Deletion is now handled via the web form and requires authentication.
4. The API endpoint `/api/agreements/{email}` (DELETE) is still available for programmatic removal, but the preferred method is through the application UI.


### Implementation
The current implementation is on our internal Kubernetes network.  You can view the deployment on Rancher for those with access.

### Sample Deployment Workflow
1. **Build Container**: Build the container with your GitHub repo and package tag: ```docker build . -t ghcr.io/noaa-gsl/githubapprovals/container_name-ghcr```
2. **Push Container to GitHub**: Push the new tagged container to your repo: ```docker push ghcr.io/noaa-gsl/githubapprovals/container_name-ghcr:latest```
3. **Redeploy Container in Kubernetes**: This last step is handled via CLI or Rancher depending on preferences and current setup of your Kubernetes network at GSL.
4. **Don't forget to push your updated code to the GitHub GSL repo if you've made changes to the container ```git push https://github.com/NOAA-GSL/GitHubApprovals.git```

### Database Models
The database model is defined in `approvals.py` using SQLAlchemy and SQLite. The `UserAgreement` model now includes expanded fields for tracking approvals, disapprovals, renewal dates, and stakeholder information:

```python
class UserAgreement(Base):
    __tablename__ = "user_agreements"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    esrl_lab = Column(String, nullable=False)
    role = Column(String, nullable=False)
    agreed = Column(Boolean, default=False)
    sponsor = Column(String, nullable=False)
    systemowner = Column(String, nullable=True)
    accountadmin = Column(String, nullable=True)
    isso = Column(String, nullable=True)
    sponsorid = Column(String, nullable=True)
    dissystemowner = Column(String, nullable=True)
    disaccountadmin = Column(String, nullable=True)
    disisso = Column(String, nullable=True)
    dissponsor = Column(String, nullable=True)
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
```
### Endpoints

**Main Endpoints:**

- `GET /`: Renders the agreement form.
- `POST /submit_agreement/`: Handles form submission and starts the approval workflow.
- `GET /browse_agreements`: Renders the browse agreements page and allows editing/deleting agreements.
- `PUT /api/agreements/{email}`: Updates an existing agreement (requires authentication).
- `DELETE /api/agreements/{email}`: Deletes an agreement (requires authentication).
- `GET /approve_user/{email}/{approver_id}`: Approves an agreement (via emailed link).
- `GET /refuse_user/{email}/{approver_id}`: Refuses an agreement (via emailed link).
- `GET /download-agreements/`: Downloads all agreements as a CSV file.
- `GET /api/lab_sponsors`: Returns a list of labs and their sponsors for the form.
- `GET /renew/{email}`: Allows users to renew their agreement.

**Email Notifications:**
Emails are sent using the `smtplib` library. The `send_email` function handles the email sending process for approvals, reminders, and confirmations.

### Background Tasks
The application uses APScheduler to schedule reminder emails for pending approvals and to check for users who need to renew their agreements. Renewal reminders are sent automatically every three days.

### Running the Application
Install Dependencies: Install the required Python packages.
```pip install fastapi sqlalchemy apscheduler pydantic pandas jinja2 python-dotenv```
### Run the Server: Start the FastAPI server.
``` uvicorn approvals:app --host 0.0.0.0 --port 7860```
NOTE:  You can also start the server manually with `python3 approvals.py` for Docker compatibility.
### Alternative to running in locally - running in Docker by building the Dockerfile after cloning the Repo
```docker build -t github-approvals .```


```docker run --rm -p 8000:8000 -v /data:/data github-approvals```

```docker run --rm -d -p 8000:8000 -v /data:/data github-approvals``` 
to run as a server without a console.


### Access the Application: Open your browser and navigate to
```http://127.0.0.1:8000/```

Conclusion
This FastAPI application provides a comprehensive solution for managing user agreements and approvals for GitHub access. It includes:
- Form submissions and validation
- Role-based approval workflow with multiple stakeholders
- Browsing, editing, and deleting agreements via the web interface
- Automated email notifications for approvals, refusals, reminders, and renewals
- CSV export and renewal management
- Background tasks for reminders and renewals
All major features and endpoints are documented above. For the latest details, see `approvals.py`.

## Notifications

The `notification/dependabotalerts.py` script provides automated notifications for critical and high-severity Dependabot alerts across all repositories in the organization. Its main purpose is to keep developers, information owners, and managers up to date on the latest security vulnerabilities and required actions.

### What It Does

- Connects to the GitHub API to fetch open Dependabot alerts for all repositories in the organization.
- Loads a mapping of GitHub usernames to email addresses from a CSV file (`informationowners.csv`).
- Identifies collaborators with admin access for each affected repository.
- Notifies relevant collaborators (excluding certain users) via email about new critical/high alerts, including details and recommended actions.
- Generates a Markdown summary file (`dependabot_alerts.md`) listing all alerts and notifications sent.
- Sends a weekly summary report to excluded users (e.g., managers) with an overview of all alerts and actions taken.

### How It Works

1. The script runs as a scheduled or manual job.
2. It fetches all open Dependabot alerts for the organization using the GitHub API and a secure token.
3. For each alert, it determines the repository, severity, and type, and finds the admin collaborators using the API and the CSV mapping.
4. For each repository with critical or high alerts, it sends a detailed email to each admin collaborator (except those in the exclusion list), summarizing the alert and requesting action.
5. It writes a Markdown file summarizing all alerts and notifications for record-keeping and transparency.
6. A summary email is sent to excluded users (such as managers) with an overview of all alerts and actions taken during the week.

### Why It's Important

- Ensures that information owners and developers are immediately notified of security issues in their repositories.
- Provides managers with regular summary reports for oversight and compliance.
- Automates the notification process, reducing manual effort and improving response times to vulnerabilities.
- Maintains a clear record of alerts and notifications for auditing and review.

For details on configuration and customization, see `notification/dependabotalerts.py` and the associated CSV file. This notification system is a key part of keeping the organization secure and responsive to GitHub security advisories.
