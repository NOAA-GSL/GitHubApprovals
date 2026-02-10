# Testing Documentation

## Quick Start

Run all tests inside the Docker container:

```bash
# Build container
docker build -t github-approvals:test .

# Run tests
docker run --rm -e ENVIRONMENT=test -v $(pwd):/workspace -w /workspace github-approvals:test pytest tests/ -v
```

## Test Results

✅ **57/57 tests passing (100%)**  
📊 **80% code coverage**

## Test Organization

### Workflow Tests ([test_approval_workflow.py](tests/test_approval_workflow.py)) - 26 tests

Business logic and data processing:

| Test Class | Tests | Description |
|------------|-------|-------------|
| TestTokenGeneration | 2 | UUID token creation on submission |
| TestEmailNotifications | 4 | Email sending and error handling |
| TestApprovalStateMachine | 7 | Multi-stage approval state transitions |
| TestStakeholderManagement | 3 | Stakeholder identification per lab |
| TestRenewalLogic | 3 | Annual renewal checking |
| TestEdgeCases | 5 | Edge cases (empty strings, concurrent approvals) |
| TestStatusReporting | 3 | Status summary generation |

### Endpoint Tests ([test_approvals_endpoints.py](tests/test_approvals_endpoints.py)) - 31 tests

HTTP API integration:

| Test Class | Tests | Description |
|------------|-------|-------------|
| TestPublicEndpoints | 5 | Public pages (dashboard, status) |
| TestAgreementSubmission | 4 | Form submission workflow |
| TestApprovalWorkflow | 8 | Approval/refusal via tokens |
| TestRenewalWorkflow | 2 | Agreement renewal |
| TestAuthenticatedEndpoints | 7 | Admin endpoints with Basic Auth |
| TestProgressEndpoints | 4 | Progress tracking and GIF generation |
| TestDataExport | 1 | CSV export |

## Key Technical Implementation

### Database Testing Strategy

The test suite uses a **shared in-memory SQLite database** with module-level patching to ensure all code paths use the test database:

```python
# In conftest.py (simplified)
# 1. Create shared memory database
TEST_DATABASE_URL = "sqlite:///file:memdb1?mode=memory&cache=shared&uri=true"
test_engine_module = create_engine(TEST_DATABASE_URL, ...)

# 2. Patch at module level BEFORE app import
import approvals
approvals.engine = test_engine_module
approvals.SessionLocal = sessionmaker(..., bind=test_engine_module)

# 3. Now import app with patched database
from approvals import app
```

**Why this works:**
- Uses shared memory URI so all connections see the same database
- Patches happen before FastAPI app initialization
- Auto-cleanup fixture creates/drops tables for each test
- No file system pollution, no database files to clean up

### Form Testing

FastAPI boolean form fields require specific string values:

```python
# ✅ Correct
data = {
    "requirement1": "on",   # Checkbox checked
    "requirement2": "on",
    "requirement3": "on"
}

# ❌ Incorrect
data = {
    "requirement1": True,   # Won't parse correctly
    "requirement2": "true", # Won't work either
}
```

### Authenticated Endpoint Testing

Use httpx auth parameter, not headers:

```python
# ✅ Correct
response = client.get("/admin/endpoint", auth=("user@example.com", "password"))

# ❌ Old way (deprecated)
headers = {"Authorization": f"Basic {base64_encoded}"}
response = client.get("/admin/endpoint", headers=headers)
```

## CI/CD Integration

Tests run automatically via GitHub Actions ([.github/workflows/docker-build.yml](.github/workflows/docker-build.yml)):

1. **Build**: Docker image with all dependencies
2. **Test**: Run pytest inside container
3. **Coverage**: Extract coverage report (80% threshold)
4. **Deploy**: Push to GHCR on success (main branch only)

## Writing New Tests

### Workflow Test Template

```python
@pytest.mark.unit
class TestMyFeature:
    """Test my new feature."""

    def test_feature_behavior(self, test_engine, mock_send_email):
        """Test that feature behaves correctly."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                # Arrange
                user = UserAgreement(email="test@noaa.gov", ...)
                db.add(user)
                db.commit()
                
                # Act
                result = some_function("test@noaa.gov")
                
                # Assert
                assert result is not None
                assert mock_send_email.called
            finally:
                db.close()
```

### Endpoint Test Template

```python
@pytest.mark.integration
class TestMyEndpoint:
    """Test my new endpoint."""

    def test_endpoint_success(self, client, create_user_agreement):
        """Test successful endpoint call."""
        # Arrange
        user = create_user_agreement(email="test@noaa.gov")
        
        # Act
        response = client.get(f"/my-endpoint/{user.email}")
        
        # Assert
        assert response.status_code == 200
        data = response.json()
        assert "expected_field" in data
```

## Troubleshooting

### "no such table: user_agreements"

**Cause**: Database not properly patched or tables not created.

**Solution**: This should be automatic with the `setup_test_db` fixture. If you see this error, check that:
1. You're importing `client` fixture (not creating your own TestClient)
2. Tests are running inside the container
3. conftest.py hasn't been modified incorrectly

### Tests Pass Locally But Fail in CI

**Cause**: Different environment variables or missing dependencies.

**Solution**: 
1. Check `.github/workflows/docker-build.yml` for environment setup
2. Ensure all dependencies are in `requirements.txt` and `requirements-dev.txt`
3. Run tests inside container locally: `docker run --rm ...`

### Slow Test Execution

**Cause**: Database operations or API calls not mocked.

**Solution**:
1. Use `@pytest.mark.unit` for fast tests with mocked I/O
2. Use `@pytest.mark.integration` for slower tests
3. Check that external services (SMTP, GitHub API) are mocked

## References

- **Test Suite README**: [tests/README.md](tests/README.md) - Detailed testing guide
- **Fixtures**: [tests/conftest.py](tests/conftest.py) - All shared test fixtures
- **GitHub Actions**: [.github/workflows/docker-build.yml](.github/workflows/docker-build.yml) - CI/CD pipeline
