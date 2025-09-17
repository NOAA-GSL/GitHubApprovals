#author: Renn Valo
#date: 08/1/2025
#Version: 5.0

import requests
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
import csv  # Import CSV module
from dotenv import load_dotenv
import schedule  # Import the schedule library

load_dotenv(dotenv_path="data/.env")

# GitHub API token with necessary permissions
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # get token so you can use API
HEADERS = {"Authorization": f"Bearer {GITHUB_TOKEN}"}

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
        raise Exception("Email configuration is missing")
    
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
        response = requests.get(f"{url}&per_page=100&page={page}", headers=HEADERS)
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
    url = f"https://api.github.com/repos/{owner}/{repo}/collaborators"
    response = requests.get(url, headers=HEADERS)
    response.raise_for_status()
    collaborators = response.json()
    # Filter collaborators with admin access and add email from the CSV file
    result = []
    for collab in collaborators:
        if collab.get("permissions", {}).get("admin", False):
            login = collab["login"].strip().lower()  # Normalize to lowercase
            email = email_map.get(login)
            # Debugging output
            print(f"Processing collaborator: {login}, Found email: {email}")
            result.append({
                "login": collab["login"],
                "email": email
            })
    return result

# Fetch repositories with Dependabot alerts
def get_dependabot_alerts(org):
    url = f"https://api.github.com/orgs/{org}/dependabot/alerts?state=open"
    alerts = []
    page = 1

    while True:
        response = requests.get(f"{url}&per_page=100&page={page}", headers=HEADERS)
        response.raise_for_status()
        current_page_alerts = response.json()
        if not current_page_alerts:
            break
        alerts.extend(current_page_alerts)
        page += 1

    return alerts

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
            
            collaborators = alerts[0]['collaborators']  # All alerts share the same collaborators
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
    # Aggregate summary data
    summary = []
    for repo_name, alerts in alerts_by_repo.items():
        alert_counts = {}
        for alert in alerts:
            alert_type = alert['alert_type']
            alert_counts[alert_type] = alert_counts.get(alert_type, 0) + 1
        summary.append({
            "repo_name": repo_name,
            "alert_counts": alert_counts
        })

    # Format the summary report
    summary_message = (
        "This is the summary report from GitHub's Approvals API detailing this week's GitHub Dependabot alerts.  All Information Owners have been provided daily updates on their repository alerts.\n\n"
        "Summary of Dependabot Alerts:\n\n"
    )
    for repo in summary:
        summary_message += f"Repository: {repo['repo_name']}\n"
        for alert_type, count in repo['alert_counts'].items():
            summary_message += f"  - {alert_type}: {count}\n"
        summary_message += "\n"

    # Send the summary email to excluded users
    subject = "Dependabot Alerts Summary Report"
    for user in EXCLUDE_USERS:
        email = email_map.get(user.lower())  # Get email from the email map
        if email:
            send_email(
                recipient=email,
                subject=subject,
                message=summary_message
            )
        else:
            print(f"No email found for excluded user: {user}")

# Main function
def main():
    org = "NOAA-GSL"
    csv_file_path = "informationowners.csv"  # Path to the CSV file
    email_map = load_email_addresses(csv_file_path)  # Load email addresses from the CSV file
    print(f"Loaded email map: {email_map}")

    alerts = get_dependabot_alerts(org)
    print(f"Fetched alerts: {alerts}")

    alerts_by_repo = {}
    for alert in alerts:
        repo_name = alert['repository']['name']
        owner = alert['repository']['owner']['login']
        severity = alert['security_advisory']['severity']
        alert_type = alert['security_advisory']['summary']  # Extract the alert type

        if severity in ["critical", "high"]:
            collaborators = get_collaborators_with_admin_access(owner, repo_name, email_map)
            filtered_collaborators = [
                collab for collab in collaborators if collab['login'] not in EXCLUDE_USERS
            ]
            print(f"Collaborators for {repo_name}: {filtered_collaborators}")
            if repo_name not in alerts_by_repo:
                alerts_by_repo[repo_name] = []
            alerts_by_repo[repo_name].append({
                "alert_type": alert_type,
                "severity": severity,
                "collaborators": filtered_collaborators
            })

    print(f"Alerts by repo: {alerts_by_repo}")

    # Schedule notify_collaborators_by_repo to run every 48 hours
    schedule.every(48).hours.do(notify_collaborators_by_repo, alerts_by_repo)

    # Schedule send_summary_to_excluded_users to run every 74 hours
    schedule.every(74).hours.do(send_summary_to_excluded_users, alerts_by_repo, email_map)

    events = get_repository_alerts(org)
    print(f"Fetched repository events: {events}")
    # schedule send_repository_add_remove_summary_email to run every 48 hours
    schedule.every(48).hours.do(send_repository_add_remove_summary_email, events, email_map)

    # Keep the script running to execute scheduled tasks
    while True:
        schedule.run_pending()
        time.sleep(1000)  # Sleep for a while to avoid busy waiting

if __name__ == "__main__":
    main()