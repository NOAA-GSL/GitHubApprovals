"""
Unit Tests for Approval Workflow Business Logic

This module tests the core approval workflow logic including:
- Token generation and validation
- Email notification sequencing
- Multi-stage approval state transitions
- Status tracking and reporting
- Edge cases and error handling
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, Mock, call
from sqlalchemy.orm import sessionmaker
from approvals import (
    UserAgreement,
    send_approval_emails,
    send_stakeholder_approval_emails,
    check_for_renewals,
    build_status_from_agreement,
    get_stakeholders
)


@pytest.mark.unit
class TestTokenGeneration:
    """Test token generation for approval workflow."""

    def test_tokens_generated_on_submission(self, test_engine, mock_send_email):
        """Test that unique tokens are generated for each approval stage."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        # Patch SessionLocal to use test database
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="tokentest@noaa.gov",
                    first_name="Token",
                    last_name="Test",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov"
                )
                db.add(user)
                db.commit()
                
                # Simulate sending approval emails which generates tokens
                send_approval_emails("tokentest@noaa.gov")
                
                db.refresh(user)
                
                # Verify all tokens are generated
                assert user.approval_token1 is not None
                assert user.approval_token2 is not None
                assert user.approval_token3 is not None
                assert user.approval_token4 is not None
                
                # Verify tokens are unique
                tokens = [
                    user.approval_token1,
                    user.approval_token2,
                    user.approval_token3,
                    user.approval_token4
                ]
                assert len(tokens) == len(set(tokens)), "Tokens should be unique"
            finally:
                db.close()

    def test_tokens_are_uuids(self, test_engine, mock_send_email):
        """Test that generated tokens are valid UUIDs."""
        import uuid
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="uuidtest@noaa.gov",
                    first_name="UUID",
                    last_name="Test",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov"
                )
                db.add(user)
                db.commit()
                
                send_approval_emails("uuidtest@noaa.gov")
                db.refresh(user)
                
                # Verify each token can be parsed as a UUID
                for token in [user.approval_token1, user.approval_token2, 
                              user.approval_token3, user.approval_token4]:
                    try:
                        uuid.UUID(token)
                    except ValueError:
                        pytest.fail(f"Token {token} is not a valid UUID")
            finally:
                db.close()


@pytest.mark.unit
class TestEmailNotifications:
    """Test email notification logic and sequencing."""

    def test_sponsor_email_sent_first(self, test_engine, mock_send_email):
        """Test that sponsor receives the first approval email."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="emailseq@noaa.gov",
                    first_name="Email",
                    last_name="Sequence",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov"
                )
                db.add(user)
                db.commit()
                
                send_approval_emails("emailseq@noaa.gov")
                
                # Verify sponsor email was sent
                mock_send_email.assert_called_once()
                call_args = mock_send_email.call_args
                assert call_args[0][0] == "sponsor@noaa.gov"
                assert "approval needed" in call_args[0][1].lower()
            finally:
                db.close()

    def test_stakeholder_emails_after_sponsor_approval(self, test_engine, mock_send_email):
        """Test that stakeholder emails are sent after sponsor approves."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="stakeholder@noaa.gov",
                    first_name="Stakeholder",
                    last_name="Test",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    approval_token1="token1",
                    approval_token2="token2",
                    approval_token3="token3",
                    approval_token4="token4"
                )
                db.add(user)
                db.commit()
                
                send_stakeholder_approval_emails("stakeholder@noaa.gov")
                
                # Verify multiple stakeholder emails were sent
                assert mock_send_email.call_count >= 3
                
                # Verify stakeholder emails contain approval links
                for call_obj in mock_send_email.call_args_list:
                    email_body = call_obj[0][2]
                    assert "approve" in email_body.lower() or "refuse" in email_body.lower()
            finally:
                db.close()

    def test_email_contains_approval_links(self, test_engine, mock_send_email):
        """Test that approval emails contain valid links."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="links@noaa.gov",
                    first_name="Links",
                    last_name="Test",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov"
                )
                db.add(user)
                db.commit()
                
                send_approval_emails("links@noaa.gov")
                
                email_body = mock_send_email.call_args[0][2]
                
                # Verify both approve and refuse links are present
                assert "/approve_user/" in email_body
                assert "/refuse_user/" in email_body
                assert "token=" in email_body
            finally:
                db.close()

    def test_email_notification_error_handling(self, test_engine):
        """Test that email errors are handled gracefully."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            with patch('approvals.send_email', side_effect=Exception("SMTP Error")):
                db = TestingSessionLocal()
                try:
                    user = UserAgreement(
                        email="error@noaa.gov",
                        first_name="Error",
                        last_name="Test",
                        esrl_lab="PSD",
                        role="Scientist",
                        sponsor="sponsor@noaa.gov"
                    )
                    db.add(user)
                    db.commit()
                    
                    # Should raise an exception (either HTTPException or base Exception)
                    with pytest.raises(Exception):
                        send_approval_emails("error@noaa.gov")
                finally:
                    db.close()


@pytest.mark.unit
class TestApprovalStateMachine:
    """Test the multi-stage approval state machine logic."""

    def test_initial_state_all_pending(self, test_engine):
        """Test that new users start with all stages pending."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="initial@noaa.gov",
                    first_name="Initial",
                    last_name="State",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov"
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                # All stages should be "waiting"
                for stage_num in range(1, 5):
                    assert status[f"stage{stage_num}"]["status"] == "waiting"
            finally:
                db.close()

    def test_stage1_approval_updates_state(self, test_engine):
        """Test that stage 1 approval updates the correct fields."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="stage1@noaa.gov",
                    first_name="Stage",
                    last_name="One",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="sponsor@noaa.gov",  # Stage 1 approved
                    approval_timestamp1=datetime.utcnow()
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                assert status["stage1"]["status"] == "validated"
                assert status["stage2"]["status"] == "waiting"
                assert status["stage3"]["status"] == "waiting"
                assert status["stage4"]["status"] == "waiting"
            finally:
                db.close()

    def test_partial_approval_state(self, test_engine):
        """Test state with partial approvals."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="partial@noaa.gov",
                    first_name="Partial",
                    last_name="Approval",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="sponsor@noaa.gov",
                    systemowner="owner@noaa.gov",
                    approval_timestamp1=datetime.utcnow(),
                    approval_timestamp2=datetime.utcnow()
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                assert status["stage1"]["status"] == "validated"
                assert status["stage2"]["status"] == "validated"
                assert status["stage3"]["status"] == "waiting"
                assert status["stage4"]["status"] == "waiting"
            finally:
                db.close()

    def test_full_approval_state(self, test_engine):
        """Test state with all approvals complete."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="full@noaa.gov",
                    first_name="Full",
                    last_name="Approval",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="sponsor@noaa.gov",
                    systemowner="owner@noaa.gov",
                    accountadmin="admin@noaa.gov",
                    isso="isso@noaa.gov",
                    approval_timestamp1=datetime.utcnow(),
                    approval_timestamp2=datetime.utcnow(),
                    approval_timestamp3=datetime.utcnow(),
                    approval_timestamp4=datetime.utcnow()
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                # All stages should be validated
                for stage_num in range(1, 5):
                    assert status[f"stage{stage_num}"]["status"] == "validated"
            finally:
                db.close()

    def test_denial_overrides_approval(self, test_engine):
        """Test that denial status overrides approval status."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="denied@noaa.gov",
                    first_name="Denied",
                    last_name="User",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="sponsor@noaa.gov",  # Approved
                    dissystemowner="owner@noaa.gov",  # Denied at stage 2
                    approval_timestamp1=datetime.utcnow(),
                    approval_timestamp2=datetime.utcnow()
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                assert status["stage1"]["status"] == "validated"
                assert status["stage2"]["status"] == "denied"
            finally:
                db.close()

    def test_timestamps_recorded(self, test_engine):
        """Test that approval timestamps are recorded correctly."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                now = datetime.utcnow()
                user = UserAgreement(
                    email="timestamp@noaa.gov",
                    first_name="Timestamp",
                    last_name="Test",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="sponsor@noaa.gov",
                    approval_timestamp1=now
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                assert status["stage1"]["stamp"] == now
                assert status["stage2"]["stamp"] is None
            finally:
                db.close()


@pytest.mark.unit
class TestStakeholderManagement:
    """Test stakeholder identification and management."""

    def test_get_stakeholders_for_lab(self):
        """Test that stakeholders are retrieved for each lab."""
        stakeholders = get_stakeholders("PSD", "sponsor@noaa.gov")
        
        assert isinstance(stakeholders, list)
        assert len(stakeholders) >= 3
        assert "sponsor@noaa.gov" in stakeholders
        assert "renn.valo@noaa.gov" in stakeholders

    def test_stakeholders_include_sponsor(self):
        """Test that sponsor is included in stakeholders list."""
        stakeholders = get_stakeholders("GSD", "custom.sponsor@noaa.gov")
        
        assert "custom.sponsor@noaa.gov" in stakeholders

    def test_stakeholders_invalid_lab(self):
        """Test that invalid lab raises an error."""
        with pytest.raises(ValueError, match="No stakeholders defined"):
            get_stakeholders("INVALID_LAB", "sponsor@noaa.gov")


@pytest.mark.unit
class TestRenewalLogic:
    """Test annual renewal checking logic."""

    def test_renewal_check_finds_expired_users(self, test_engine, mock_send_email, freeze_time):
        """Test that renewal check identifies users needing renewal."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with freeze_time("2026-02-04"):
            with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
                db = TestingSessionLocal()
                try:
                    # Create user with old renewal date
                    old_date = datetime(2024, 1, 1)  # Over 2 years ago
                    user = UserAgreement(
                        email="expired@noaa.gov",
                        first_name="Expired",
                        last_name="User",
                        esrl_lab="PSD",
                        role="Scientist",
                        sponsor="sponsor@noaa.gov",
                        last_renewal_date=old_date
                    )
                    db.add(user)
                    db.commit()
                    
                    # Run renewal check
                    check_for_renewals()
                    
                    # Verify renewal email was sent
                    assert mock_send_email.called
                finally:
                    db.close()

    def test_renewal_check_skips_recent_renewals(self, test_engine, mock_send_email, freeze_time):
        """Test that recent renewals are not flagged."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with freeze_time("2026-02-04"):
            with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
                db = TestingSessionLocal()
                try:
                    # Create user with recent renewal
                    recent_date = datetime(2025, 6, 1)  # Less than 1 year ago
                    user = UserAgreement(
                        email="recent@noaa.gov",
                        first_name="Recent",
                        last_name="User",
                        esrl_lab="PSD",
                        role="Scientist",
                        sponsor="sponsor@noaa.gov",
                        last_renewal_date=recent_date
                    )
                    db.add(user)
                    db.commit()
                    
                    # Run renewal check
                    check_for_renewals()
                    
                    # Verify no email was sent
                    assert not mock_send_email.called
                finally:
                    db.close()

    def test_renewal_updates_timestamp(self, test_engine):
        """Test that renewal updates the last_renewal_date."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                old_date = datetime(2024, 1, 1)
                user = UserAgreement(
                    email="renew@noaa.gov",
                    first_name="Renew",
                    last_name="Test",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    last_renewal_date=old_date
                )
                db.add(user)
                db.commit()
                
                # Update renewal date
                user.last_renewal_date = datetime.utcnow()
                db.commit()
                db.refresh(user)
                
                # Verify date was updated
                assert user.last_renewal_date > old_date
            finally:
                db.close()


@pytest.mark.unit
class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_empty_string_treated_as_not_approved(self, test_engine):
        """Test that empty strings are treated as unapproved."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="emptystring@noaa.gov",
                    first_name="Empty",
                    last_name="String",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="",  # Empty string
                    systemowner=""
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                assert status["stage1"]["status"] == "waiting"
                assert status["stage2"]["status"] == "waiting"
            finally:
                db.close()

    def test_zero_value_treated_as_not_approved(self, test_engine):
        """Test that zero values are treated as unapproved."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="zero@noaa.gov",
                    first_name="Zero",
                    last_name="Value",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    sponsorid="0"  # String "0"
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                assert status["stage1"]["status"] == "waiting"
            finally:
                db.close()

    def test_concurrent_approvals_same_stage(self, test_engine, create_user_agreement):
        """Test that duplicate approvals at the same stage are handled."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = create_user_agreement(
                    email="concurrent@noaa.gov",
                    approval_token2="token2"
                )
                
                # Retrieve user in this session
                user = db.query(UserAgreement).filter_by(email="concurrent@noaa.gov").first()
                
                # First approval
                user.systemowner = "owner1@noaa.gov"
                db.commit()
                
                # Second approval attempt (should not fail)
                user.systemowner = "owner2@noaa.gov"
                db.commit()
                
                status = build_status_from_agreement(user)
                assert status["stage2"]["status"] == "validated"
            finally:
                db.close()

    def test_approval_after_denial(self, test_engine):
        """Test behavior when approval is attempted after denial."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    email="afterdenial@noaa.gov",
                    first_name="After",
                    last_name="Denial",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov",
                    dissponsor="sponsor@noaa.gov",  # Denied at stage 1
                    sponsorid="sponsor@noaa.gov"  # Also marked as approved
                )
                db.add(user)
                db.commit()
                
                status = build_status_from_agreement(user)
                
                # Denial should take precedence
                assert status["stage1"]["status"] == "denied"
            finally:
                db.close()

    def test_missing_email_field(self, test_engine):
        """Test that users can be created without email (though not recommended)."""
        import approvals
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        with patch.object(approvals, 'SessionLocal', TestingSessionLocal):
            db = TestingSessionLocal()
            try:
                user = UserAgreement(
                    first_name="No",
                    last_name="Email",
                    esrl_lab="PSD",
                    role="Scientist",
                    sponsor="sponsor@noaa.gov"
                )
                db.add(user)
                db.commit()
                
                # Should successfully create user even without email
                # (though this is not recommended in practice)
                assert user.id is not None
                assert user.email is None
            finally:
                db.close()


@pytest.mark.unit
class TestStatusReporting:
    """Test status reporting and summary generation."""

    def test_build_status_includes_all_stages(self, create_user_agreement):
        """Test that status dict includes all 4 stages."""
        user = create_user_agreement()
        
        status = build_status_from_agreement(user)
        
        assert "stage1" in status
        assert "stage2" in status
        assert "stage3" in status
        assert "stage4" in status

    def test_build_status_includes_role_info(self, create_user_agreement):
        """Test that status includes role information."""
        user = create_user_agreement()
        
        status = build_status_from_agreement(user)
        
        assert status["stage1"]["role"] == "sponsor"
        assert status["stage2"]["role"] == "systemowner"
        assert status["stage3"]["role"] == "accountadmin"
        assert status["stage4"]["role"] == "isso"

    def test_build_status_includes_timestamps(self, test_db):
        """Test that status includes approval timestamps."""
        now = datetime.utcnow()
        user = UserAgreement(
            email="timestamps@noaa.gov",
            first_name="Time",
            last_name="Stamps",
            esrl_lab="PSD",
            role="Scientist",
            sponsor="sponsor@noaa.gov",
            sponsorid="sponsor@noaa.gov",
            approval_timestamp1=now
        )
        test_db.add(user)
        test_db.commit()
        
        status = build_status_from_agreement(user)
        
        assert status["stage1"]["stamp"] == now
        assert "stamp" in status["stage2"]
