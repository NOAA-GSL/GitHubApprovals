# Security Policy

## Runtime Secrets and Email

Production configuration is loaded from `/data/.env`. Keep `ADMIN_USERNAME`, `ADMIN_PASSWORD`, and `GITHUB_TOKEN` secret, restrict access to the mounted data volume, and never commit real values. Email uses the internal SMTP relay on port 25 without SMTP authentication or TLS; restrict relay access to trusted workloads and networks. `MAIL_FROM` defaults to `github.gsl@noaa.gov`.

## Supported Versions

Use this section to tell people about which versions of your project are
currently being supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| 5.1.x   | :white_check_mark: |
| 5.0.x   | :x:                |
| 4.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

Use this section to tell people how to report a vulnerability.

Please send an email to renn.valo@noaa.gov if you see any packages or dependencies that look like an issue.
