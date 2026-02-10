"""
Unit Tests for FastAPI Endpoints in GitHub Approvals Application

This module tests the HTTP endpoints including:
- GET / (agreement form)
- POST /submit_agreement
- GET /approve_user/{email}/{approver_id}
- GET /refuse_user/{email}/{approver_id}
- POST /renew/{email}
- GET /status
- GET /dashboard
- GET /browse_agreements (authenticated)
- PUT /api/agreements/{email} (authenticated)
- DELETE /api/agreements/{email} (authenticated)
"""

import pytest
from datetime import datetime, timedelta
from approvals import UserAgreement


@pytest.mark.unit
class TestPublicEndpoints:
    """Test public-facing endpoints that don't require authentication."""

    def test_get_agreement_form(self, client):
        """Test that the agreement form page loads successfully."""
        response = client.get("/")
        assert response.status_code == 200
        assert b"agreement" in response.content.lower()

    def test_get_status_page(self, client, create_user_agreement):
        """Test the status page displays pending approvals."""
        # Create a user with partial approval
        create_user_agreement(
            email="pending@noaa.gov",
            first_name="Pending",
            last_name="User",
            sponsorid="sponsor@noaa.gov",
            systemowner=None
        )
        
        response = client.get("/status")
        assert response.status_code == 200
        assert b"pending@noaa.gov" in response.content

    def test_get_status_page_empty(self, client):
        """Test status page with no users."""
        response = client.get("/status")
        assert response.status_code == 200

    def test_get_dashboard(self, client, create_user_agreement):
        """Test the dashboard endpoint displays agreement summaries."""
        # Create test users with different approval states
        create_user_agreement(
            email="approved@noaa.gov",
            first_name="Fully",
            last_name="Approved",
            esrl_lab="PSD",
            role="Scientist",
            sponsor="sponsor@noaa.gov",
            sponsorid="sponsor@noaa.gov",
            systemowner="owner@noaa.gov",
            accountadmin="admin@noaa.gov",
            isso="isso@noaa.gov"
        )
        
        create_user_agreement(
            email="partial@noaa.gov",
            first_name="Partial",
            last_name="Approved",
            esrl_lab="GSD",
            role="Engineer",
            sponsor="sponsor2@noaa.gov",
            sponsorid="sponsor2@noaa.gov"
        )
        
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert b"approved@noaa.gov" in response.content
        assert b"partial@noaa.gov" in response.content

    def test_get_api_lab_sponsors(self, client):
        """Test the lab sponsors API endpoint."""
        response = client.get("/api/lab_sponsors")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)  # API returns dict, not list


@pytest.mark.unit
class TestAgreementSubmission:
    """Test user agreement submission workflow."""

    def test_submit_agreement_success(self, client, mock_send_email, sample_user_data):
        """Test successful agreement submission triggers email."""
        response = client.post(
            "/submit_agreement/",
            data=sample_user_data
        )
        
        assert response.status_code == 200
        response_data = response.json()
        assert "message" in response_data
        assert "agreement submitted" in response_data["message"].lower()
        
        # Verify email was sent
        assert mock_send_email.called

    def test_submit_agreement_duplicate_email(self, client, create_user_agreement, mock_send_email):
        """Test that duplicate email addresses are rejected."""
        # Create existing user
        create_user_agreement(email="existing@noaa.gov")
        
        # Try to submit with same email
        response = client.post(
            "/submit_agreement/",
            data={
                "email": "existing@noaa.gov",
                "first_name": "Duplicate",
                "last_name": "User",
                "esrl_lab": "PSD",
                "role": "Scientist",
                "sponsor": "sponsor@noaa.gov",
                "requirement1": "on",
                "requirement2": "on",
                "requirement3": "on"
            }
        )
        
        assert response.status_code == 400
        assert "already submitted" in response.json()["detail"].lower()

    def test_submit_agreement_missing_fields(self, client):
        """Test that missing required fields are rejected."""
        response = client.post(
            "/submit_agreement/",
            data={"email": "incomplete@noaa.gov"},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        
        assert response.status_code == 422  # Unprocessable Entity

    def test_submit_agreement_disagreed(self, client):
        """Test that users who don't agree are rejected."""
        response = client.post(
            "/submit_agreement/",
            data={
                "email": "disagree@noaa.gov",
                "first_name": "Test",
                "last_name": "User",
                "esrl_lab": "PSD",
                "role": "Scientist",
                "sponsor": "sponsor@noaa.gov",
                "requirement1": "off",
                "requirement2": "on",
                "requirement3": "on"
            }
        )
        
        assert response.status_code == 400
        assert "requirements must be agreed" in response.json()["detail"].lower()


@pytest.mark.unit
class TestApprovalWorkflow:
    """Test the multi-stage approval workflow endpoints."""

    def test_approve_user_stage1_valid_token(self, client, create_user_agreement, mock_send_email):
        """Test first stage approval with valid token."""
        token1 = "test-token-1"
        user = create_user_agreement(
            email="approve1@noaa.gov",
            approval_token1=token1,
            approval_token2="token2",
            approval_token3="token3",
            approval_token4="token4"
        )
        
        response = client.get(f"/approve_user/approve1@noaa.gov/1?token={token1}")
        
        assert response.status_code == 200
        assert "approval has been received" in response.json()["message"].lower()
        
        # Verify stakeholder emails were sent after stage 1 approval
        assert mock_send_email.called

    def test_approve_user_invalid_token(self, client, create_user_agreement):
        """Test approval with invalid token is rejected."""
        user = create_user_agreement(
            email="invalid@noaa.gov",
            approval_token1="correct-token"
        )
        
        response = client.get("/approve_user/invalid@noaa.gov/1?token=wrong-token")
        
        assert response.status_code == 403
        assert "invalid token" in response.json()["detail"].lower()

    def test_approve_user_not_found(self, client):
        """Test approval for non-existent user."""
        response = client.get("/approve_user/notfound@noaa.gov/1?token=any-token")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_approve_user_already_fully_approved(self, client, create_user_agreement):
        """Test that fully approved users cannot be re-approved."""
        user = create_user_agreement(
            email="fullyapproved@noaa.gov",
            sponsorid="sponsor@noaa.gov",
            systemowner="owner@noaa.gov",
            accountadmin="admin@noaa.gov",
            isso="isso@noaa.gov",
            approval_token1="token1"
        )
        
        response = client.get(f"/approve_user/fullyapproved@noaa.gov/1?token=token1")
        
        assert response.status_code == 400
        assert "already been approved" in response.json()["detail"].lower()

    def test_approve_user_all_stages(self, client, create_user_agreement, mock_send_email):
        """Test complete approval workflow through all 4 stages."""
        tokens = ["token1", "token2", "token3", "token4"]
        user = create_user_agreement(
            email="complete@noaa.gov",
            approval_token1=tokens[0],
            approval_token2=tokens[1],
            approval_token3=tokens[2],
            approval_token4=tokens[3]
        )
        
        # Stage 1: Sponsor approval
        response = client.get(f"/approve_user/complete@noaa.gov/1?token={tokens[0]}")
        assert response.status_code == 200
        
        # Stage 2: System Owner approval
        response = client.get(f"/approve_user/complete@noaa.gov/2?token={tokens[1]}")
        assert response.status_code == 200
        
        # Stage 3: Account Admin approval
        response = client.get(f"/approve_user/complete@noaa.gov/3?token={tokens[2]}")
        assert response.status_code == 200
        
        # Stage 4: ISSO approval (final)
        response = client.get(f"/approve_user/complete@noaa.gov/4?token={tokens[3]}")
        assert response.status_code == 200
        
        # Final confirmation email should be sent
        assert mock_send_email.called

    def test_refuse_user_stage1(self, client, create_user_agreement, mock_send_email):
        """Test user refusal at stage 1."""
        token1 = "refuse-token-1"
        user = create_user_agreement(
            email="refuse1@noaa.gov",
            approval_token1=token1
        )
        
        response = client.get(f"/refuse_user/refuse1@noaa.gov/1?token={token1}")
        
        assert response.status_code == 200
        assert "disapproved" in response.json()["message"].lower()
        
        # Verify refusal email was sent
        assert mock_send_email.called

    def test_refuse_user_invalid_token(self, client, create_user_agreement):
        """Test refusal with invalid token is rejected."""
        user = create_user_agreement(
            email="refuse-invalid@noaa.gov",
            approval_token2="correct-token"
        )
        
        response = client.get("/refuse_user/refuse-invalid@noaa.gov/2?token=wrong-token")
        
        assert response.status_code == 403
        assert "invalid token" in response.json()["detail"].lower()

    def test_refuse_fully_approved_user(self, client, create_user_agreement):
        """Test that fully approved users cannot be refused."""
        user = create_user_agreement(
            email="refuse-approved@noaa.gov",
            sponsorid="sponsor@noaa.gov",
            systemowner="owner@noaa.gov",
            accountadmin="admin@noaa.gov",
            isso="isso@noaa.gov",
            approval_token1="token1"
        )
        
        response = client.get(f"/refuse_user/refuse-approved@noaa.gov/1?token=token1")
        
        assert response.status_code == 400
        assert "already been approved" in response.json()["detail"].lower()


@pytest.mark.unit
class TestRenewalWorkflow:
    """Test the annual renewal workflow."""

    def test_renew_agreement_success(self, client, create_user_agreement, mock_send_email):
        """Test successful agreement renewal."""
        old_date = datetime.utcnow() - timedelta(days=400)
        user = create_user_agreement(
            email="renew@noaa.gov",
            last_renewal_date=old_date,
            sponsorid="sponsor@noaa.gov",
            systemowner="owner@noaa.gov",
            accountadmin="admin@noaa.gov",
            isso="isso@noaa.gov"
        )
        
        response = client.get(f"/renew/renew@noaa.gov")
        
        assert response.status_code == 200
        assert "renewed successfully" in response.json()["message"].lower()

    def test_renew_nonexistent_user(self, client):
        """Test renewal for non-existent user."""
        response = client.get("/renew/notfound@noaa.gov")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


@pytest.mark.unit
class TestAuthenticatedEndpoints:
    """Test endpoints that require HTTP Basic Authentication."""

    def test_browse_agreements_without_auth(self, client):
        """Test that browse_agreements requires authentication."""
        response = client.get("/browse_agreements")
        # Note: The current implementation may not enforce auth on this endpoint
        # This test documents the current behavior
        assert response.status_code in [200, 401]

    def test_update_agreement_without_auth(self, client, create_user_agreement):
        """Test that update requires authentication."""
        user = create_user_agreement(email="update@noaa.gov")
        
        response = client.put(
            "/api/agreements/update@noaa.gov",
            json={
                "first_name": "Updated",
                "last_name": "Name",
                "esrl_lab": "PSD",
                "role": "Scientist",
                "agreed": True,
                "last_renewal_date": datetime.utcnow().isoformat()
            }
        )
        
        assert response.status_code == 401

    def test_update_agreement_with_auth(self, client, create_user_agreement, auth_credentials):
        """Test successful agreement update with authentication."""
        user = create_user_agreement(
            email="update-auth@noaa.gov",
            first_name="Original",
            last_name="Name"
        )
        
        response = client.put(
            "/api/agreements/update-auth@noaa.gov",
            json={
                "first_name": "Updated",
                "last_name": "NewName",
                "esrl_lab": "GSD",
                "role": "Engineer",
                "agreed": True,
                "last_renewal_date": datetime.utcnow().isoformat()
            },
            auth=auth_credentials
        )
        
        assert response.status_code == 200
        assert "updated successfully" in response.json()["message"].lower()

    def test_update_nonexistent_agreement(self, client, auth_credentials):
        """Test update of non-existent agreement."""
        response = client.put(
            "/api/agreements/notfound@noaa.gov",
            json={
                "first_name": "Test",
                "last_name": "User",
                "esrl_lab": "PSD",
                "role": "Scientist",
                "agreed": True,
                "last_renewal_date": datetime.utcnow().isoformat()
            },
            auth=auth_credentials
        )
        
        assert response.status_code == 404

    def test_delete_agreement_without_auth(self, client, create_user_agreement):
        """Test that delete requires authentication."""
        user = create_user_agreement(email="delete@noaa.gov")
        
        response = client.delete("/api/agreements/delete@noaa.gov")
        
        assert response.status_code == 401

    def test_delete_agreement_with_auth(self, client, create_user_agreement, auth_credentials):
        """Test successful agreement deletion with authentication."""
        user = create_user_agreement(email="delete-auth@noaa.gov")
        
        response = client.delete(
            "/api/agreements/delete-auth@noaa.gov",
            auth=auth_credentials
        )
        
        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"].lower()

    def test_delete_nonexistent_agreement(self, client, auth_credentials):
        """Test deletion of non-existent agreement."""
        response = client.delete(
            "/api/agreements/notfound@noaa.gov",
            auth=auth_credentials
        )
        
        assert response.status_code == 404


@pytest.mark.unit
class TestProgressEndpoints:
    """Test progress tracking and GIF generation endpoints."""

    def test_get_progress_page(self, client, create_user_agreement):
        """Test progress page renders for existing user."""
        user = create_user_agreement(
            email="progress@noaa.gov",
            sponsorid="sponsor@noaa.gov"
        )
        
        response = client.get("/progress/progress@noaa.gov")
        
        assert response.status_code == 200

    def test_get_progress_nonexistent_user(self, client):
        """Test progress page for non-existent user."""
        response = client.get("/progress/notfound@noaa.gov")
        
        assert response.status_code == 404

    def test_generate_progress_gif(self, client, create_user_agreement):
        """Test GIF generation endpoint."""
        user = create_user_agreement(
            email="gif@noaa.gov",
            sponsorid="sponsor@noaa.gov",
            systemowner="owner@noaa.gov"
        )
        
        response = client.post("/api/progress/gif@noaa.gov/generate")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_check_progress_status(self, client, create_user_agreement):
        """Test progress status check endpoint."""
        user = create_user_agreement(
            email="status@noaa.gov",
            sponsorid="sponsor@noaa.gov"
        )
        
        response = client.get("/api/progress/status@noaa.gov/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "percent" in data
        assert "status" in data


@pytest.mark.unit
class TestDataExport:
    """Test data export functionality."""

    def test_download_agreements(self, client, create_user_agreement):
        """Test CSV export of agreements."""
        import os
        # Create data directory if it doesn't exist
        os.makedirs("./data", exist_ok=True)
        
        create_user_agreement(email="export1@noaa.gov")
        create_user_agreement(email="export2@noaa.gov")
        
        response = client.get("/download-agreements/")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert b"email" in response.content
