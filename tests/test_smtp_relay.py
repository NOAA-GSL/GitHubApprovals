from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import Mock, patch

import approvals
import dependabotalerts
import smtp_relay


def test_send_via_relay_uses_configured_host_and_port(monkeypatch):
    monkeypatch.setenv("SMTP_RELAY_HOST", "relay.example.test")
    monkeypatch.setenv("SMTP_RELAY_PORT", "2525")
    message = MIMEMultipart()
    smtp_instance = Mock()

    with patch("smtp_relay.smtplib.SMTP") as smtp_class:
        smtp_class.return_value.__enter__.return_value = smtp_instance
        smtp_relay.send_via_relay(message)

    smtp_class.assert_called_once_with("relay.example.test", 2525, timeout=30)
    smtp_instance.send_message.assert_called_once_with(message)
    smtp_instance.login.assert_not_called()
    smtp_instance.starttls.assert_not_called()


def test_approvals_email_keeps_from_and_multipart_body(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "github.gsl@noaa.gov")

    with patch("approvals.send_via_relay") as send_via_relay:
        approvals.send_email("person@example.test", "Subject", "Plain text", "<b>HTML</b>")

    message = send_via_relay.call_args.args[0]
    assert message["From"] == "github.gsl@noaa.gov"
    assert message["To"] == "person@example.test"
    assert message.get_content_type() == "multipart/alternative"
    assert [part.get_content_type() for part in message.get_payload()] == ["text/plain", "text/html"]


def test_dependabot_email_uses_shared_relay_and_from(monkeypatch):
    monkeypatch.setenv("MAIL_FROM", "github.gsl@noaa.gov")

    with patch("dependabotalerts.send_via_relay") as send_via_relay:
        dependabotalerts.send_email("person@example.test", "Subject", "Alert text")

    message = send_via_relay.call_args.args[0]
    assert message["From"] == "github.gsl@noaa.gov"
    assert message["To"] == "person@example.test"
    assert message.get_payload(0).get_payload(decode=True).decode() == "Alert text"