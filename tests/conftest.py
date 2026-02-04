"""
Pytest Configuration and Fixtures for GitHub Approvals Testing

This module provides common fixtures for testing the FastAPI application,
including test database setup, mock email services, and GitHub API mocks.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import Mock, patch
import responses

# Set test environment variables before importing app
os.environ["ENVIRONMENT"] = "test"
os.environ["BASE_URL"] = "http://testserver"
os.environ["GITHUB_TOKEN"] = "test_github_token_12345"
os.environ["EMAIL_ADDRESS"] = "test@example.com"
os.environ["EMAIL_PASSWORD"] = "test_password"
os.environ["STAKEHOLDERS_PSD"] = "stakeholder1@noaa.gov,stakeholder2@noaa.gov,stakeholder3@noaa.gov"
os.environ["STAKEHOLDERS_GSD"] = "stakeholder1@noaa.gov,stakeholder2@noaa.gov,stakeholder3@noaa.gov"
os.environ["STAKEHOLDERS_ESRL"] = "stakeholder1@noaa.gov,stakeholder2@noaa.gov,stakeholder3@noaa.gov"

# Import Base and UserAgreement before creating engine
from approvals import Base, UserAgreement

# Create test engine at module level using shared memory
# Use file:memdb1?mode=memory&cache=shared to share the in-memory database across connections
TEST_DATABASE_URL = "sqlite:///file:memdb1?mode=memory&cache=shared&uri=true"
test_engine_module = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False, "uri": True}
)

# Patch the engine and SessionLocal before importing app
import approvals
approvals.engine = test_engine_module
approvals.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine_module)

# Now import app with patched database
from approvals import app


@pytest.fixture(scope="function", autouse=True)
def setup_test_db():
    """
    Setup and teardown test database for each test.
    This runs automatically for every test function.
    """
    # Create all tables
    Base.metadata.create_all(bind=test_engine_module)
    
    yield
    
    # Cleanup after test
    Base.metadata.drop_all(bind=test_engine_module)


@pytest.fixture(scope="function")
def test_engine():
    """
    Provide the test database engine.
    """
    yield test_engine_module


@pytest.fixture(scope="function")
def test_db():
    """
    Create a test database session.
    """
    db = approvals.SessionLocal()
    
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="function")
def client():
    """
    Create a TestClient with the test database.
    The database is already patched at module level.
    """
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def mock_smtp():
    """
    Mock SMTP server for email testing.
    """
    with patch('smtplib.SMTP_SSL') as mock_smtp_class:
        mock_smtp_instance = Mock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp_instance
        yield mock_smtp_instance


@pytest.fixture
def mock_github_api():
    """
    Mock GitHub API responses using responses library.
    """
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def sample_user_data():
    """
    Sample user data for testing user agreement submissions.
    FastAPI Form boolean fields accept 'on', 'true', 'yes', or '1' as True.
    """
    return {
        "email": "test.user@noaa.gov",
        "first_name": "Test",
        "last_name": "User",
        "esrl_lab": "PSD",
        "role": "Scientist",
        "sponsor": "sponsor@noaa.gov",
        "requirement1": "on",
        "requirement2": "on",
        "requirement3": "on"
    }


@pytest.fixture
def create_user_agreement(test_engine):
    """
    Factory fixture to create user agreements for testing.
    """
    def _create_user(
        email="test@noaa.gov",
        first_name="Test",
        last_name="User",
        esrl_lab="PSD",
        role="Scientist",
        sponsor="sponsor@noaa.gov",
        agreed=False,
        approval_token1=None,
        approval_token2=None,
        approval_token3=None,
        approval_token4=None,
        **kwargs
    ):
        db = approvals.SessionLocal()
        try:
            user = UserAgreement(
                email=email,
                first_name=first_name,
                last_name=last_name,
                esrl_lab=esrl_lab,
                role=role,
                sponsor=sponsor,
                agreed=agreed,
                approval_token1=approval_token1,
                approval_token2=approval_token2,
                approval_token3=approval_token3,
                approval_token4=approval_token4,
                **kwargs
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return user
        finally:
            db.close()
    
    return _create_user


@pytest.fixture
def authenticated_headers():
    """
    HTTP Basic Auth headers for authenticated endpoints.
    Uses credentials from environment variables.
    """
    # Use the same credentials set in environment
    username = "test@example.com"  # EMAIL_ADDRESS from env
    password = "test_password"      # EMAIL_PASSWORD from env
    import base64
    credentials = base64.b64encode(f"{username}:{password}".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {credentials}"}


@pytest.fixture
def auth_credentials():
    """
    Tuple of (username, password) for authenticated requests.
    Use with client.get(..., auth=auth_credentials)
    """
    return ("test@example.com", "test_password")


@pytest.fixture
def mock_send_email():
    """
    Mock the send_email function to prevent actual email sending during tests.
    """
    with patch('approvals.send_email') as mock_email:
        yield mock_email


@pytest.fixture
def mock_apscheduler():
    """
    Mock APScheduler to prevent background jobs from running during tests.
    """
    with patch('approvals.scheduler') as mock_scheduler:
        yield mock_scheduler


@pytest.fixture
def sample_github_org_response():
    """
    Sample GitHub organization API response.
    """
    return {
        "login": "NOAA-GSL",
        "id": 12345678,
        "node_id": "MDEyOk9yZ2FuaXphdGlvbjEyMzQ1Njc4",
        "url": "https://api.github.com/orgs/NOAA-GSL",
        "repos_url": "https://api.github.com/orgs/NOAA-GSL/repos",
        "events_url": "https://api.github.com/orgs/NOAA-GSL/events",
        "hooks_url": "https://api.github.com/orgs/NOAA-GSL/hooks",
        "issues_url": "https://api.github.com/orgs/NOAA-GSL/issues",
        "members_url": "https://api.github.com/orgs/NOAA-GSL/members{/member}",
        "public_members_url": "https://api.github.com/orgs/NOAA-GSL/public_members{/member}",
        "avatar_url": "https://avatars.githubusercontent.com/u/12345678?v=4",
        "description": "NOAA Global Systems Laboratory"
    }


@pytest.fixture
def freeze_time():
    """
    Fixture to freeze time for testing time-dependent functionality.
    """
    from freezegun import freeze_time as freezegun_freeze
    return freezegun_freeze


# Pytest configuration
def pytest_configure(config):
    """
    Pytest configuration hook to add custom markers.
    """
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
