# Tests for GitHub Approvals Application

✅ **Status: All 57 tests passing | 80% code coverage**

This directory contains the comprehensive test suite for the GitHub Approvals FastAPI application.

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                      # Shared fixtures and configuration
├── test_approvals_endpoints.py      # HTTP endpoint tests (31 tests)
└── test_approval_workflow.py        # Business logic tests (26 tests)
```

## Test Summary

### Workflow Tests (26 tests)
- ✅ Token Generation (2 tests)
- ✅ Email Notifications (4 tests)
- ✅ Approval State Machine (7 tests)
- ✅ Stakeholder Management (3 tests)
- ✅ Renewal Logic (3 tests)
- ✅ Edge Cases (5 tests)
- ✅ Status Reporting (3 tests)

### Endpoint Tests (31 tests)
- ✅ Public Endpoints (5 tests)
- ✅ Agreement Submission (4 tests)
- ✅ Approval Workflow (8 tests)
- ✅ Renewal Workflow (2 tests)
- ✅ Authenticated Endpoints (7 tests)
- ✅ Progress Endpoints (4 tests)
- ✅ Data Export (1 test)

## Running Tests

### Important: Container-Based Testing

**All dependencies are installed inside Docker containers.** Tests should be run inside the container to match the production environment.

### Build Container with Test Dependencies

```bash
# Build the Docker image (includes pytest and all test dependencies)
docker build -t github-approvals:test .
```

### Run Tests Inside Container

```bash
# Run all tests
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
  pytest tests/ -v
```

### Run Specific Test Files in Container

```bash
# Test only endpoints
docker run --rm \
  -e ENVIRONMENT=test \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest tests/test_approvals_endpoints.py -v

# Test only workflow logic
docker run --rm \
  -e ENVIRONMENT=test \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest tests/test_approval_workflow.py -v
```

### Run with Coverage Report in Container

```bash
# Generate coverage report
docker run --rm \
  -e ENVIRONMENT=test \
  -e BASE_URL=http://testserver \
  -e GITHUB_TOKEN=test_token \
  -e EMAIL_ADDRESS=test@example.com \
  -e EMAIL_PASSWORD=test_password \
  -e STAKEHOLDERS_PSD=test1@noaa.gov,test2@noaa.gov,test3@noaa.gov \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest tests/ -v --cov=. --cov-report=html --cov-report=term-missing

# Coverage report will be in htmlcov/ directory on your host
# Open htmlcov/index.html in your browser
```

### Optional: Local Testing (Without Container)

If you prefer faster iteration during development, you can install dependencies locally:

```bash
# Install dependencies on host (optional)
pip install -r requirements.txt -r requirements-dev.txt

# Run tests locally
pytest

# Run specific files
pytest tests/test_approvals_endpoints.py
```

### Run Only Unit Tests

```bash
docker run --rm \
  -e ENVIRONMENT=test \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest -m unit -v
```

### Run Only Integration Tests

```bash
docker run --rm \
  -e ENVIRONMENT=test \
  -v $(pwd):/workspace \
  -w /workspace \
  github-approvals:test \
  pytest -m integration -v
```

## Test Categories

### Unit Tests (`@pytest.mark.unit`)
- Test individual functions and methods in isolation
- Use mocked dependencies (database, email, GitHub API)
- Fast execution

### Integration Tests (`@pytest.mark.integration`)
- Test multiple components working together
- May use real database (in-memory SQLite)
- Slower execution

## Key Fixtures

Defined in `conftest.py`:

### Database Fixtures
- **`setup_test_db`**: Auto-run fixture that creates/drops tables for each test
- **`test_engine`**: Shared memory SQLite engine for all connections
- **`test_db`**: Database session for manual database operations
- **`client`**: FastAPI TestClient with patched test database

### Mock Fixtures
- **`mock_smtp`**: Mocked SMTP server for email tests
- **`mock_github_api`**: Mocked GitHub API responses using `responses` library
- **`mock_send_email`**: Mock email sending function

### Data Fixtures
- **`create_user_agreement`**: Factory to create test user agreements
- **`sample_user_data`**: Sample form data for agreement submissions
- **`authenticated_headers`**: HTTP Basic Auth headers (deprecated - use `auth_credentials`)
- **`auth_credentials`**: Tuple of (username, password) for httpx auth parameter
- **`freeze_time`**: Mock current time using freezegun

## Database Testing Architecture

The test suite uses a **shared in-memory SQLite database** with module-level patching:

1. **Module-Level Setup**: When tests load, `conftest.py` patches `approvals.engine` and `approvals.SessionLocal` before the FastAPI app initializes
2. **Shared Memory**: Uses `sqlite:///file:memdb1?mode=memory&cache=shared&uri=true` so all connections see the same database
3. **Auto-Cleanup**: The `setup_test_db` fixture (with `autouse=True`) creates tables before each test and drops them after
4. **Test Isolation**: Each test gets a clean database state automatically

This architecture ensures:
- ✅ All endpoints use the test database
- ✅ No file system pollution
- ✅ Fast test execution
- ✅ Proper test isolation

## Coverage Goals

**Current Coverage: 80%** (553 statements, 109 missed)

Coverage targets:
- Overall: 75%
- Critical paths: 90%+
  - Approval workflow
  - Token validation
  - Email notifications

## Writing New Tests

### Example Test

```python
@pytest.mark.unit
def test_my_feature(client, create_user_agreement, mock_send_email):
    """Test description goes here."""
    # Arrange
    user = create_user_agreement(email="test@noaa.gov")
    
    # Act
    response = client.get(f"/some_endpoint/{user.email}")
    
    # Assert
    assert response.status_code == 200
    assert mock_send_email.called
```

## CI/CD Integration

Tests run automatically on:
- Every push to `main` branch
- Every pull request to `main`
- Manual workflow dispatch

See `.github/workflows/docker-build.yml` for details.

## Troubleshooting

### Tests Fail with Database Errors

Make sure you're using the in-memory database fixture:
```python
def test_something(test_db, client):
    # test_db ensures fresh database
```

### Mock Not Working

Ensure you're patching at the right location:
```python
@patch('approvals.send_email')  # Patch where it's used, not where it's defined
def test_email(mock_email):
    ...
```

### Import Errors

Make sure all dependencies are installed:
```bash
pip install -r requirements.txt -r requirements-dev.txt
```
