# Quick Reference: Testing & CI/CD

## Important: Container-Based Development

**All dependencies are installed inside Docker containers, not on the host.**

### Local Testing (In Container)

```bash
# Build the Docker image (includes test dependencies)
docker build -t github-approvals:test .

# Run tests inside the container
docker run --rm \
  -e ENVIRONMENT=test \
  -e BASE_URL=http://testserver \
  -e GITHUB_TOKEN=test_token \
  -e EMAIL_ADDRESS=test@example.com \
  -e EMAIL_PASSWORD=test_password \
  -e STAKEHOLDERS_PSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -e STAKEHOLDERS_GSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -e STAKEHOLDERS_ESRL=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest tests/ -v

# Run tests with coverage
docker run --rm \
  -e ENVIRONMENT=test \
  -e BASE_URL=http://testserver \
  -e GITHUB_TOKEN=test_token \
  -e EMAIL_ADDRESS=test@example.com \
  -e EMAIL_PASSWORD=test_password \
  -e STAKEHOLDERS_PSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -e STAKEHOLDERS_GSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing

# Extract coverage report from container
docker run --rm \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  sh -c "pytest --cov=. --cov-report=html && cp -r htmlcov /workspace/"
```

### Optional: Local Development (Host-Based)

If you prefer to run tests on your host machine for faster iteration:

```bash
# Install dependencies locally (optional)
pip install -r requirements.txt -r requirements-dev.txt

# Run tests locally
pytest -v

# Run with coverage
pytest --cov=. --cov-report=html
```

## Local Development

## Docker

### Build Container with Tests
```bash
# Build Docker image (includes both production and test dependencies)
docker build -t github-approvals:local .

# Verify test dependencies are installed
docker run --rm github-approvals:local pytest --version
docker run --rm github-approvals:local python3 -c "import pytest; import responses; print('Test deps OK')"
```

### Run Application Container
```bash
# Run container locally for development
docker run -d --name test-approvals \
  -e ENVIRONMENT=development \
  -e GITHUB_TOKEN=your_token \
  -e EMAIL_ADDRESS=your_email \
  -e EMAIL_PASSWORD=your_password \
  -p 8000:8000 \
  github-approvals:local

# Check logs
docker logs test-approvals

# Stop and remove
docker stop test-approvals
docker rm test-approvals
```

### Interactive Container Shell
```bash
# Get a shell inside the container for debugging
docker run -it --rm \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:local \
  /bin/bash

# Inside the container, you can run:
# pytest tests/
# python3 approvals.py
# etc.
```

### Pull from Registry
```bash
# Pull latest image
docker pull ghcr.io/noaa-gsl/githubapprovals/approvals-container-ghcr-test:latest

# Pull specific commit
docker pull ghcr.io/noaa-gsl/githubapprovals/approvals-container-ghcr-test:<git-sha>
```

## GitHub Actions

### Trigger Workflow
```bash
# Push to main (triggers automatically)
git push origin main

# Manual trigger (via GitHub UI)
# Go to: Repository → Actions → Docker Build and Push → Run workflow
```

### View Results
```bash
# Via GitHub CLI
gh run list
gh run view <run-id>

# Or visit: https://github.com/NOAA-GSL/githubapprovals/actions
```

## Troubleshooting

### Tests Fail with Import Errors
```bash
# Reinstall dependencies
pip install --upgrade -r requirements.txt -r requirements-dev.txt

# Clear Python cache
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete
```

### Database Errors in Tests
```bash
# Tests should use in-memory database automatically
# If issues persist, delete local database
rm agreement.db

# Run tests again
pytest
```

### Docker Build Fails
```bash
# Check Dockerfile syntax
docker build --no-cache -t test:latest .

# Check for missing files
ls -la requirements.txt Dockerfile approvals.py
```

### Coverage Not Working
```bash
# Reinstall pytest-cov
pip install --upgrade pytest-cov

# Run with explicit coverage source
pytest --cov=approvals --cov=dependabotalerts
```

## Common Test Patterns

### Test a Single Endpoint
```python
def test_my_endpoint(client):
    response = client.get("/my-endpoint")
    assert response.status_code == 200
```

### Test with Database
```python
def test_with_db(test_db, create_user_agreement):
    user = create_user_agreement(email="test@example.com")
    assert user.email == "test@example.com"
```

### Test with Mocked Email
```python
def test_email_sent(client, mock_send_email):
    client.post("/submit_agreement/", data={...})
    assert mock_send_email.called
```

### Test with Authentication
```python
def test_authenticated(client, authenticated_headers):
    response = client.put(
        "/api/agreements/test@example.com",
        json={...},
        headers=authenticated_headers
    )
    assert response.status_code == 200
```

## File Structure
```
GitHubApprovals/
├── .github/workflows/
│   └── docker-build.yml          # CI/CD workflow
├── tests/
│   ├── conftest.py               # Shared fixtures
│   ├── test_approvals_endpoints.py
│   ├── test_approval_workflow.py
│   └── README.md
├── approvals.py                  # Main application
├── requirements.txt              # Production deps
├── requirements-dev.txt          # Development deps
├── pytest.ini                    # Test configuration
├── Dockerfile                    # Container image
└── IMPLEMENTATION_SUMMARY.md     # Full documentation
```

## Environment Variables

### Required for Tests
```bash
ENVIRONMENT=test
BASE_URL=http://testserver
GITHUB_TOKEN=test_token
EMAIL_ADDRESS=test@example.com
EMAIL_PASSWORD=test_password
STAKEHOLDERS_PSD=email1,email2,email3
STAKEHOLDERS_GSD=email1,email2,email3
```

### Required for Production
```bash
ENVIRONMENT=production
BASE_URL=https://your-domain.com
GITHUB_TOKEN=<real_github_token>
EMAIL_ADDRESS=<real_email>
EMAIL_PASSWORD=<real_app_password>
STAKEHOLDERS_<LAB>=<comma_separated_emails>
```

## Git Workflow

### Standard Development Flow
```bash
# Create feature branch
git checkout -b feature/add-tests

# Make changes and run tests
pytest

# Commit changes
git add .
git commit -m "Add comprehensive test suite"

# Push and create PR
git push origin feature/add-tests
# Create PR via GitHub UI

# Merge after CI passes
# Delete branch after merge
```

## Getting Help

- **Tests Documentation**: See `tests/README.md`
- **Full Implementation Guide**: See `IMPLEMENTATION_SUMMARY.md`
- **Main Application README**: See `README.md`
- **GitHub Actions**: Check `.github/workflows/docker-build.yml`

## Quick Health Check

Run this to verify everything is working:

```bash
# 1. Check Python version (need 3.9+)
python --version

# 2. Install dependencies
pip install -r requirements.txt -r requirements-dev.txt

# 3. Run tests
pytest -v

# 4. Check coverage
pytest --cov=. --cov-report=term-missing

# 5. Build Docker image
docker build -t test:latest .

# If all pass: ✅ You're good to go!
```
