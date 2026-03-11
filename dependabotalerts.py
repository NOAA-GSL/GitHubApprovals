#author: Renn Valo
#date: 08/1/2025
#Version: 5.0

import requests
import argparse
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import csv  # Import CSV module
from dotenv import load_dotenv
"""Standalone Dependabot alert notifier.

This version removes the internal scheduler so that an external scheduler (cron, task
scheduler, Kubernetes CronJob, etc.) can invoke the script. When run it will:

1. Load environment (.env + process env)
2. Load email map from informationowners.csv
3. Fetch current open Dependabot alerts for the org
4. Filter to high/critical severities
5. Fetch admin collaborators for affected repos
6. Send per‑repository notifications to collaborators
7. Send summary notifications to excluded oversight users

Exit codes:
 0 = success (even if no alerts)
 1 = configuration error (missing env vars / CSV issues)
 2 = GitHub API error
 3 = email send failures (non-fatal errors are printed; script still exits 0 unless global config missing)
"""

# NOTE: Internal 'schedule' library usage removed for standalone execution.

# Load .env from appropriate location (container vs development)
if os.path.exists("/data/.env"):
    load_dotenv(dotenv_path="/data/.env")
    print("[CONFIG] Loaded environment from /data/.env")
elif os.path.exists(".env"):
    load_dotenv(dotenv_path=".env")
    print("[CONFIG] Loaded environment from .env")
else:
    print("[CONFIG] No .env file found, using system environment variables")

def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

# GitHub API token with necessary permissions
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # May be validated later to allow .env absence
HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json"
} if GITHUB_TOKEN else {}

REQUEST_TIMEOUT = 15  # seconds for all outbound GitHub HTTP requests

# List of users to exclude from notifications
EXCLUDE_USERS = [
    "jennyf0x",
    "tristandietz",
    "shannon-m-johnston",
    "greg-pratt-noaa"
]

EXCLUSIVE_USERS = [
    "rvnoaa",
    "ygnoaa",
]

# Load email addresses from a CSV file (with optional date_added column)
def load_email_addresses(csv_file_path):
    """Load email map from CSV. Returns dict: {username: {"email": email, "date_added": date}}.
    
    Backward compatible with 2-column CSV (username, email only).
    """
    email_map = {}
    try:
        with open(csv_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                username = row.get("username", "").strip().lower()  # Normalize to lowercase
                email = row.get("email", "").strip()
                date_added = row.get("date_added", "").strip()  # Optional field
                if username and email:
                    email_map[username] = {
                        "email": email,
                        "date_added": date_added if date_added else ""
                    }
    except FileNotFoundError:
        print(f"Error: The file {csv_file_path} was not found.")
    except Exception as e:
        print(f"Error reading the CSV file: {str(e)}")
    return email_map

# Helper function to extract email from email_map
def get_email_from_map(email_map, username):
    """Extract email from email_map, handling both old (string) and new (dict) formats."""
    data = email_map.get(username.lower())
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get("email")
    return data  # Old format: direct string

# Save email addresses to a CSV file
def save_email_addresses(csv_file_path, email_map):
    """Save email map to CSV with username, email, and date_added columns."""
    try:
        with open(csv_file_path, mode='w', encoding='utf-8', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["username", "email", "date_added"])  # Header
            for username, data in sorted(email_map.items()):
                email = data.get("email", "") if isinstance(data, dict) else data
                date_added = data.get("date_added", "") if isinstance(data, dict) else ""
                writer.writerow([username, email, date_added])
        print(f"Successfully saved email map to {csv_file_path}")
    except Exception as e:
        print(f"Error saving CSV file: {str(e)}")    

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

# Send email to a recipient
def send_email(recipient, subject, message):
    print(f"Preparing to send email to {recipient} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    sender_email = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    if not sender_email or not password:
        raise RuntimeError("Email configuration is missing (EMAIL_ADDRESS / EMAIL_PASSWORD)")
    
    # Specify the alternative "from" email address
    from_email = "github.gsl@noaa.gov"  # Alternative email address authorized in Gmail account

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
        print("Failed to send email due to authentication error. Please check your email credentials.")
    except Exception as e:
        print(f"Failed to send email: {str(e)}")

# Fetch repositories alerts regarding creating or removing repositories
def get_repository_alerts(org):
    url = f"https://api.github.com/orgs/{org}/events"
    events = []
    page = 1

    while True:
        response = requests.get(f"{url}?per_page=100&page={page}", headers=HEADERS)
        response.raise_for_status()
        current_page_events = response.json()
        if not current_page_events:
            break
        for e in current_page_events:
            if e['type'] in ['CreateEvent', 'DeleteEvent']:
                if e['payload'].get('ref_type') == 'repository':
                    events.append(e)
        page += 1

    return events

# Function to send repository add/remove summary email
def send_repository_add_remove_summary_email(events, email_map):
    print("Running send_repository_add_remove_summary_email...")
    if not events:
        print("No repository add/remove events found.")
        return
    # Placeholder for actual implementation
    subject = "Repository Add/Remove Summary"
    message = "This is a summary of repository additions and removals."
    for event in events:
        action_time = event['created_at']
        action = "created" if event['type'] == 'CreateEvent' else "deleted"
        repo_name = event['repo']['name']
        actor = event['actor']['login']
        message += f"\n- Repository '{repo_name}' was {action} by {actor} at {action_time}."
    # Send to a predefined list of recipients or a specific email
    recipients = []

    for user in EXCLUSIVE_USERS:
        email = get_email_from_map(email_map, user)  # Get email from the email map
        if email:
            recipients.append(email)

    for recipient in recipients:
        send_email(recipient, subject, message)

# Fetch collaborators with admin access for a repository
def get_collaborators_with_admin_access(owner, repo, email_map):
    url = f"https://api.github.com/repos/{owner}/{repo}/collaborators?per_page=100"
    page = 1
    all_collaborators = []
    while True:
        paged_url = f"{url}&page={page}"
        print(f"[Collaborators] Fetching page {page} for {owner}/{repo}...")
        try:
            response = requests.get(paged_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            print(f"[Collaborators] Request failed: {e}")
            break
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            print(f"[Collaborators] HTTP error on page {page}: {e} - body: {response.text[:300]}")
            break
        collaborators = response.json()
        if not collaborators:
            print(f"[Collaborators] No more collaborators pages for {owner}/{repo}.")
            break
        print(f"[Collaborators] Retrieved {len(collaborators)} collaborators (admin filter later).")
        all_collaborators.extend(collaborators)
        page += 1
    result = []
    for collab in all_collaborators:
        if collab.get("permissions", {}).get("admin", False):
            login = collab["login"].strip().lower()
            email = get_email_from_map(email_map, login)
            print(f"Processing collaborator: {login}, Found email: {email}")
            result.append({
                "login": collab["login"],
                "email": email
            })
    return result

# Fetch repositories with Dependabot alerts
def get_dependabot_alerts(org, max_pages=None, max_total=None):
    """Fetch OPEN Dependabot alerts for an org (no pagination supported)."""
    url = f"https://api.github.com/orgs/{org}/dependabot/alerts?state=open"
    print(f"[Dependabot] Fetching all open alerts for org {org}...")
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[Dependabot] Request failed: {e}")
        return []
    except requests.HTTPError as e:
        print(f"[Dependabot] HTTP error: {e} - body: {response.text[:300]}")
        return []
    data = response.json()
    if not isinstance(data, list):
        print(f"[Dependabot] Unexpected response type (not list): {data}")
        return []
    open_alerts = [a for a in data if a.get('state') == 'open']
    print(f"[Dependabot] Fetched {len(open_alerts)} open alerts.")
    if max_total and len(open_alerts) > max_total:
        open_alerts = open_alerts[:max_total]
        print(f"[Dependabot] Truncated to max_total {max_total} alerts.")
    return open_alerts

# ============================================================================
# NEW: Admin Detection and Synchronization Functions
# ============================================================================

# Fetch all repositories for an organization
def get_all_org_repositories(org):
    """Fetch all repositories in an organization with pagination."""
    url = f"https://api.github.com/orgs/{org}/repos?per_page=100"
    page = 1
    all_repos = []
    while True:
        paged_url = f"{url}&page={page}"
        print(f"[Repositories] Fetching page {page} for org {org}...")
        try:
            response = requests.get(paged_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[Repositories] Request failed: {e}")
            break
        except requests.HTTPError as e:
            print(f"[Repositories] HTTP error on page {page}: {e} - body: {response.text[:300]}")
            break
        repos = response.json()
        if not repos:
            print(f"[Repositories] No more repository pages for {org}.")
            break
        print(f"[Repositories] Retrieved {len(repos)} repositories.")
        all_repos.extend(repos)
        page += 1
    print(f"[Repositories] Total repositories fetched: {len(all_repos)}")
    return all_repos

# Fetch GitHub user's public email
def get_github_user_email(username):
    """Fetch a user's public email from GitHub API. Returns None if unavailable."""
    url = f"https://api.github.com/users/{username}"
    print(f"[GitHub Email] Fetching email for user: {username}")
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        user_data = response.json()
        email = user_data.get("email")
        if email:
            print(f"[GitHub Email] Found email for {username}: {email}")
            return email
        else:
            print(f"[GitHub Email] No public email available for {username}")
            return None
    except requests.RequestException as e:
        print(f"[GitHub Email] Request failed for {username}: {e}")
        return None
    except requests.HTTPError as e:
        print(f"[GitHub Email] HTTP error for {username}: {e}")
        return None

# Discover all unique admin users across all organization repositories
def discover_all_org_admins(org, email_map):
    """Discover all users with admin access across all org repositories.
    
    Returns dict: {username: {"repos": [repo_list], "email": email_or_none}}
    """
    print(f"\n=== Discovering all admins for org: {org} ===")
    repos = get_all_org_repositories(org)
    if not repos:
        print("[Admin Discovery] No repositories found or error occurred.")
        return {}
    
    admin_map = {}  # {username: {"repos": [repo_names], "email": email}}
    
    for repo in repos:
        repo_name = repo["name"]
        owner = repo["owner"]["login"]
        print(f"\n[Admin Discovery] Processing repository: {repo_name}")
        
        # Fetch admin collaborators for this repo
        collaborators = get_collaborators_with_admin_access(owner, repo_name, email_map)
        
        for collab in collaborators:
            username = collab["login"].lower()
            email = collab.get("email")
            
            if username not in admin_map:
                admin_map[username] = {
                    "repos": [],
                    "email": email
                }
            
            admin_map[username]["repos"].append(repo_name)
            # Update email if we found one and didn't have it before
            if email and not admin_map[username]["email"]:
                admin_map[username]["email"] = email
    
    print(f"\n[Admin Discovery] Total unique admins found: {len(admin_map)}")
    return admin_map

# Compare discovered admins with CSV entries
def compare_admins(discovered_admins, email_map):
    """Compare discovered admins against CSV entries.
    
    Returns tuple: (new_admins_with_email, new_admins_missing_email, stale_admins)
    """
    from datetime import datetime
    
    print("\n=== Comparing discovered admins with CSV ===")
    
    # Convert email_map keys to lowercase for comparison
    csv_usernames = {username.lower() for username in email_map.keys()}
    discovered_usernames = {username.lower() for username in discovered_admins.keys()}
    
    # Find new admins (in GitHub but not in CSV)
    new_usernames = discovered_usernames - csv_usernames
    print(f"[Compare] New admins found: {len(new_usernames)}")
    
    # Find stale admins (in CSV but not in GitHub)
    stale_usernames = csv_usernames - discovered_usernames
    print(f"[Compare] Stale admins found: {len(stale_usernames)}")
    
    new_admins_with_email = []
    new_admins_missing_email = []
    
    current_date = datetime.now().strftime("%Y-%m-%d")
    
    for username in new_usernames:
        admin_info = discovered_admins[username]
        email = admin_info.get("email")
        repos = admin_info.get("repos", [])
        
        # Try to fetch email from GitHub API if not found in collaborator data
        if not email:
            print(f"[Compare] Attempting to fetch email from GitHub API for: {username}")
            email = get_github_user_email(username)
        
        new_admin_entry = {
            "username": username,
            "email": email,
            "repos": repos,
            "date_added": current_date
        }
        
        if email:
            new_admins_with_email.append(new_admin_entry)
        else:
            new_admins_missing_email.append(new_admin_entry)
    
    # Build stale admin list with their CSV info
    stale_admins = []
    for username in stale_usernames:
        csv_data = email_map.get(username, {})
        if isinstance(csv_data, dict):
            email = csv_data.get("email", "")
            date_added = csv_data.get("date_added", "")
        else:
            email = csv_data
            date_added = ""
        
        stale_admins.append({
            "username": username,
            "email": email,
            "date_added": date_added
        })
    
    print(f"[Compare] New admins with email: {len(new_admins_with_email)}")
    print(f"[Compare] New admins missing email: {len(new_admins_missing_email)}")
    print(f"[Compare] Stale admins: {len(stale_admins)}")
    
    return new_admins_with_email, new_admins_missing_email, stale_admins

# Send welcome email to new admin
def send_new_admin_welcome_email(admin_email, username, repo_list):
    """Send policy notification email to newly detected admin."""
    repo_text = "\n".join([f"  - {repo}" for repo in repo_list])
    
    subject = "Welcome: You are now an Information Owner for NOAA-GSL Repositories"
    message = f"""Hello {username},

You have been detected as a repository administrator for the following NOAA-GSL GitHub repositories:

{repo_text}

As a repository administrator (Information Owner), you are required to follow NOAA-GSL's GitHub repository management policy. This includes:

1. Ensuring your repository has appropriate security settings
2. Reviewing and addressing Dependabot security alerts promptly
3. Managing repository access and collaborator permissions appropriately
4. Following data classification and handling guidelines

You will receive automated notifications about Dependabot security alerts for your repositories. Please review the full policy documentation at your earliest convenience.

If you believe you received this message in error or have questions about your responsibilities, please contact the GitHub administration team.

Best regards,
GitHub Approvals Team
NOAA Global Systems Laboratory
"""
    
    try:
        send_email(admin_email, subject, message)
        print(f"[New Admin Email] Sent welcome email to {username} at {admin_email}")
    except Exception as e:
        print(f"[New Admin Email] Failed to send email to {username}: {e}")

# Send alert about missing email
def send_missing_email_alert(admin_username, repo_list):
    """Send notification to oversight about new admin without email."""
    repo_text = "\n".join([f"  - {repo}" for repo in repo_list])
    
    subject = f"Action Required: New Repository Admin Missing Email - {admin_username}"
    message = f"""New repository administrator detected without email address.

GitHub Username: {admin_username}
Repository Access Detected On:
{repo_text}

The system attempted to:
1. Look up email in informationowners.csv - NOT FOUND
2. Fetch public email from GitHub API - NOT AVAILABLE

Action Required:
Please manually obtain the email address for this user and update informationowners.csv with:
  - Username: {admin_username}
  - Email: [TO BE ADDED]
  - Date Added: [CURRENT DATE]

Once the email is added, the user will receive policy notification on the next run.

Best regards,
GitHub Approvals Automation
"""
    
    # Send alert to all automation owners
    for owner_email in get_automation_owners():
        try:
            send_email(owner_email, subject, message)
            print(f"[Missing Email Alert] Sent alert to {owner_email} for {admin_username}")
        except Exception as e:
            print(f"[Missing Email Alert] Failed to send alert to {owner_email} for {admin_username}: {e}")

# Send stale admin report
def send_stale_admin_report(stale_admins):
    """Send report of users in CSV who no longer have admin access.
    
    Sends report to all automation owners configured in AUTOMATION_OWNERS environment variable.
    """
    if not stale_admins:
        print("[Stale Admin Report] No stale admins to report.")
        return
    
    subject = f"Information Owners Report: {len(stale_admins)} User(s) No Longer Have Admin Access"
    
    admin_list = []
    for admin in stale_admins:
        username = admin["username"]
        email = admin.get("email", "N/A")
        date_added = admin.get("date_added", "N/A")
        admin_list.append(f"  - {username} (Email: {email}, Added: {date_added})")
    
    admin_text = "\n".join(admin_list)
    
    message = f"""Information Owners Synchronization Report

The following users are listed in informationowners.csv but NO LONGER have admin access to any NOAA-GSL GitHub repositories:

{admin_text}

Total Count: {len(stale_admins)}

Possible Reasons:
- User's admin permissions were revoked
- User left the organization
- User account was deleted or renamed
- All repositories where user had admin access were deleted

Action Required:
Please review these users and determine if they should be:
1. Removed from informationowners.csv (if intentionally removed or left org)
2. Investigated (if this was unintentional or unexpected)
3. Kept in CSV (if temporary situation or API error)

Note: These users have NOT been automatically removed from the CSV file. Manual review and action is required.

Best regards,
GitHub Approvals Automation
NOAA Global Systems Laboratory
"""
    
    # Send report to all automation owners
    for owner_email in get_automation_owners():
        try:
            send_email(owner_email, subject, message)
            print(f"[Stale Admin Report] Sent report to {owner_email} for {len(stale_admins)} stale admins")
        except Exception as e:
            print(f"[Stale Admin Report] Failed to send report to {owner_email}: {e}")

# Update CSV file with new admins
def update_informationowners_csv(new_admins, csv_file_path, email_map):
    """Append new admins to CSV file while preserving existing entries."""
    if not new_admins:
        print("[CSV Update] No new admins to add.")
        return
    
    print(f"[CSV Update] Adding {len(new_admins)} new admin(s) to {csv_file_path}")
    
    # Update email_map with new entries
    for admin in new_admins:
        username = admin["username"].lower()
        email = admin.get("email", "")
        date_added = admin.get("date_added", "")
        
        email_map[username] = {
            "email": email,
            "date_added": date_added
        }
        print(f"[CSV Update] Added {username} with email: {email if email else 'MISSING'}")
    
    # Save updated map back to CSV
    try:
        save_email_addresses(csv_file_path, email_map)
        print(f"[CSV Update] Successfully updated {csv_file_path}")
    except Exception as e:
        print(f"[CSV Update] Failed to update CSV: {e}")
        raise

# ============================================================================
# End of Admin Detection Functions
# ============================================================================

# Notify collaborators (save to a Markdown file and send emails)
def notify_collaborators_by_repo(alerts_by_repo):
    print("Running notify_collaborators_by_repo...")
    with open("dependabot_alerts.md", "w") as file:  # Open the file in write mode
        for repo_name, alerts in alerts_by_repo.items():
            print(f"Processing repo: {repo_name}")
            file.write(f"## Repository: {repo_name}\n")
            file.write("### Alerts:\n")
            alert_details = []
            for alert in alerts:
                alert_type = alert['alert_type']
                severity = alert['severity']
                alert_details.append(f"- **Alert Type**: {alert_type}, **Severity**: {severity}")
            file.write("\n".join(alert_details) + "\n")
            
            if not alerts:
                continue
            collaborators = alerts[0]['collaborators']  # assume uniform collaborator set
            file.write("  - Collaborators Notified:\n")
            for collaborator in collaborators:
                file.write(f"    - {collaborator['login']}\n")
                # Send a single email per repository
                if collaborator.get("email"):
                    print(f"Sending email to {collaborator['login']} at {collaborator['email']}")
                    subject = f"Dependabot Alerts for Repository: {repo_name}"
                    message = (
                        f"Hello {collaborator['login']},\n\n"
                        f"The following Dependabot alerts have been detected in the repository '{repo_name}':\n\n"
                        + "\n".join(alert_details) +
                        "\n\nPlease take appropriate action.\n\n"
                        "Best regards,\nGitHub Approvals Team"
                    )
                    send_email(collaborator["email"], subject, message)
                else:
                    print(f"No email found for {collaborator['login']}")
            file.write("\n")  # Add a blank line for readability

def send_summary_to_excluded_users(alerts_by_repo, email_map):
    """Send a summary email of alert counts per repository.

    Recipients include:
      - Users in EXCLUDE_USERS (oversight / non-direct collaborators)
      - Users in EXCLUSIVE_USERS (explicitly opted-in special recipients)
      - All AUTOMATION_OWNERS (email addresses from environment variable)

    Deduplicates usernames case-insensitively.
    """
    summary = []
    for repo_name, alerts in alerts_by_repo.items():
        counts = {}
        for a in alerts:
            counts[a['alert_type']] = counts.get(a['alert_type'], 0) + 1
        summary.append({"repo_name": repo_name, "counts": counts})

    subject = "Dependabot Alerts Summary Report"
    summary_message = (
        "This is the summary report from GitHub's Approvals API detailing this run's GitHub Dependabot alerts. All Information Owners have been provided updates on their repository alerts.\n\n"
        "Summary of Dependabot Alerts:\n\n"
    )
    for repo in summary:
        summary_message += f"Repository: {repo['repo_name']}\n"
        for alert_type, count in repo['counts'].items():
            summary_message += f"  - {alert_type}: {count}\n"
        summary_message += "\n"

    # Send to username-based recipients (EXCLUDE_USERS and EXCLUSIVE_USERS)
    recipients = {u.lower() for u in EXCLUDE_USERS} | {u.lower() for u in EXCLUSIVE_USERS}
    for user in recipients:
        email = get_email_from_map(email_map, user)
        if email:
            try:
                send_email(email, subject, summary_message)
                print(f"[Summary] Sent to {user} at {email}")
            except Exception as e:
                print(f"Failed sending summary to {user}: {e}")
    
    # Send to all automation owners (direct email addresses)
    automation_owners = get_automation_owners()
    print(f"[Summary] Sending to {len(automation_owners)} automation owner(s): {', '.join(automation_owners)}")
    for owner_email in automation_owners:
        try:
            send_email(owner_email, subject, summary_message)
            print(f"[Summary] Sent to automation owner: {owner_email}")
        except Exception as e:
            print(f"Failed sending summary to automation owner {owner_email}: {e}")

def main(argv=None):
    parser = argparse.ArgumentParser(description="Dependabot alert notifier")
    parser.add_argument("--summary-only", action="store_true", help="Send only weekly summary report (no per-repo collaborator emails)")
    parser.add_argument("--no-summary", action="store_true", help="Skip summary report even if normally sent")
    args = parser.parse_args(argv)
    try:
        token = _require_env("GITHUB_TOKEN")
        global HEADERS
        HEADERS = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"
        }
    except RuntimeError as e:
        print(f"CONFIG ERROR: {e}")
        raise SystemExit(1)

    if not os.getenv("EMAIL_ADDRESS") or not os.getenv("EMAIL_PASSWORD"):
        print("WARNING: Email credentials not set; notifications will fail during send.")

    org = "NOAA-GSL"
    
    # Determine CSV path with migration logic for existing deployments
    if os.path.exists("/data"):
        csv_file_path = "/data/informationowners.csv"
        # Migration: if file doesn't exist in /data but exists in root, copy it
        if not os.path.exists(csv_file_path) and os.path.exists("/informationowners.csv"):
            print(f"[MIGRATION] Copying CSV from root to persistent storage...")
            try:
                import shutil
                shutil.copy2("/informationowners.csv", csv_file_path)
                print(f"[MIGRATION] Successfully migrated CSV to {csv_file_path}")
            except Exception as e:
                print(f"[MIGRATION] Failed to migrate CSV: {e}")
                print(f"[MIGRATION] Falling back to root location: /informationowners.csv")
                csv_file_path = "/informationowners.csv"
        print(f"[CONFIG] Running in container mode - using: {csv_file_path}")
    else:
        csv_file_path = "informationowners.csv"
        print(f"[CONFIG] Running in development mode - using local storage: {csv_file_path}")
    email_map = load_email_addresses(csv_file_path)
    if not email_map:
        print("WARNING: Email map is empty; collaborator emails will be missing.")
    else:
        print(f"Loaded email map entries: {len(email_map)}")

    # =========================================================================
    # NEW: Admin Detection and Synchronization
    # =========================================================================
    print("\n" + "="*80)
    print("Starting Information Owner Admin Detection")
    print("="*80)
    
    try:
        # Discover all admins across org repositories
        discovered_admins = discover_all_org_admins(org, email_map)
        
        if discovered_admins:
            # Compare with CSV to find new and stale admins
            new_with_email, new_missing_email, stale_admins = compare_admins(discovered_admins, email_map)
            
            # Process new admins with email
            if new_with_email:
                print(f"\n[Admin Sync] Processing {len(new_with_email)} new admin(s) with email...")
                for admin in new_with_email:
                    send_new_admin_welcome_email(
                        admin["email"], 
                        admin["username"], 
                        admin["repos"]
                    )
                # Update CSV with new admins
                update_informationowners_csv(new_with_email, csv_file_path, email_map)
            
            # Process new admins without email
            if new_missing_email:
                print(f"\n[Admin Sync] Processing {len(new_missing_email)} new admin(s) without email...")
                for admin in new_missing_email:
                    send_missing_email_alert(admin["username"], admin["repos"])
                # Still add to CSV even without email (manual update needed)
                update_informationowners_csv(new_missing_email, csv_file_path, email_map)
            
            # Process stale admins (in CSV but not in GitHub)
            if stale_admins:
                print(f"\n[Admin Sync] Processing {len(stale_admins)} stale admin(s)...")
                send_stale_admin_report(stale_admins)
            
            # Summary
            print("\n" + "="*80)
            print("Admin Detection Summary:")
            print(f"  - New admins added (with email): {len(new_with_email)}")
            print(f"  - New admins added (missing email): {len(new_missing_email)}")
            print(f"  - Stale admins reported: {len(stale_admins)}")
            print("="*80 + "\n")
        else:
            print("[Admin Sync] No admins discovered (possible API error). Skipping sync.")
    
    except Exception as e:
        print(f"[Admin Sync] ERROR during admin detection: {e}")
        print("[Admin Sync] Continuing with Dependabot alert processing...")
    
    # =========================================================================
    # End of Admin Detection - Continue with normal Dependabot workflow
    # =========================================================================

    try:
        # Optional diagnostic limits via env
        max_pages_env = os.getenv("MAX_ALERT_PAGES")
        max_total_env = os.getenv("MAX_TOTAL_ALERTS")
        max_pages = int(max_pages_env) if max_pages_env and max_pages_env.isdigit() else None
        max_total = int(max_total_env) if max_total_env and max_total_env.isdigit() else None
        alerts = get_dependabot_alerts(org, max_pages=max_pages, max_total=max_total)
    except requests.HTTPError as e:
        print(f"GitHub API error fetching dependabot alerts: {e}")
        raise SystemExit(2)

    print(f"Fetched {len(alerts)} open dependabot alerts.")

    alerts_by_repo = {}
    exclude_lower = {u.lower() for u in EXCLUDE_USERS}
    for alert in alerts:
        try:
            repo_name = alert['repository']['name']
            owner = alert['repository']['owner']['login']
            severity = alert['security_advisory']['severity']
            alert_type = alert['security_advisory']['summary']
        except KeyError as e:
            print(f"Skipping alert with missing key: {e}")
            continue

        if severity not in {"critical", "high"}:
            continue

        try:
            collaborators = get_collaborators_with_admin_access(owner, repo_name, email_map)
        except requests.HTTPError as e:
            print(f"Failed to fetch collaborators for {owner}/{repo_name}: {e}")
            collaborators = []

        filtered_collaborators = [
            collab for collab in collaborators if collab['login'].lower() not in exclude_lower
        ]
        alerts_by_repo.setdefault(repo_name, []).append({
            "alert_type": alert_type,
            "severity": severity,
            "collaborators": filtered_collaborators
        })

    print(f"Prepared alert groups for {len(alerts_by_repo)} repositories.")

    if alerts_by_repo:
        if not args.summary_only:
            notify_collaborators_by_repo(alerts_by_repo)
        else:
            print("--summary-only specified: skipping per-repo collaborator emails.")
        if not args.no_summary:
            send_summary_to_excluded_users(alerts_by_repo, email_map)
        else:
            print("--no-summary specified: skipping summary report.")
    else:
        print("No high/critical alerts to notify.")

    print("Completed Dependabot alert notification run.")

if __name__ == "__main__":
    main()