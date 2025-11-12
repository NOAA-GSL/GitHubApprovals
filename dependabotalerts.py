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

load_dotenv(dotenv_path="data/.env")

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

# Load email addresses from a CSV file
def load_email_addresses(csv_file_path):
    email_map = {}
    try:
        with open(csv_file_path, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                username = row.get("username").strip().lower()  # Normalize to lowercase
                email = row.get("email").strip()
                if username and email:
                    email_map[username] = email
    except FileNotFoundError:
        print(f"Error: The file {csv_file_path} was not found.")
    except Exception as e:
        print(f"Error reading the CSV file: {str(e)}")
    return email_map    

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
        email = email_map.get(user.lower())  # Get email from the email map
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
            email = email_map.get(login)
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

    recipients = {u.lower() for u in EXCLUDE_USERS} | {u.lower() for u in EXCLUSIVE_USERS}
    for user in recipients:
        email = email_map.get(user)
        if email:
            try:
                send_email(email, subject, summary_message)
            except Exception as e:
                print(f"Failed sending summary to {user}: {e}")
        else:
            print(f"No email found for summary recipient: {user}")

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
    csv_file_path = "informationowners.csv"
    email_map = load_email_addresses(csv_file_path)
    if not email_map:
        print("WARNING: Email map is empty; collaborator emails will be missing.")
    else:
        print(f"Loaded email map entries: {len(email_map)}")

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