import os
import smtplib


def send_via_relay(message):
    host = os.getenv("SMTP_RELAY_HOST", "smtp-gw1.gsd.esrl.noaa.gov")
    port = int(os.getenv("SMTP_RELAY_PORT", "25"))

    with smtplib.SMTP(host, port, timeout=30) as server:
        server.send_message(message)