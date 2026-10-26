"""Tests for the GitHub Policy Assessment (quiz) gate on new agreements and renewals."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

import approvals
from approvals import QUIZ, QUIZ_QUESTIONS, QuizAttempt, UserAgreement, check_for_renewals


def _wrong_option(question):
    return next(o for o in question["options"] if o != question["correctAnswer"])


def _start(client, email="quiz.user@noaa.gov", purpose="new"):
    response = client.post("/api/quiz/start", json={"email": email, "purpose": purpose})
    assert response.status_code == 200
    return response.json()["attempt_id"]


def _answer(client, attempt_id, question, answer=None):
    return client.post("/api/quiz/answer", json={
        "attempt_id": attempt_id,
        "question_id": question["id"],
        "answer": answer if answer is not None else question["correctAnswer"],
    })


def _form_data(email, attempt_id=None):
    data = {
        "email": email,
        "first_name": "Quiz",
        "last_name": "User",
        "github_username": "quizuser",
        "esrl_lab": "PSD",
        "role": "Scientist",
        "sponsor": "sponsor@noaa.gov",
        "requirement1": "on",
        "requirement2": "on",
        "requirement3": "on",
    }
    if attempt_id:
        data["quiz_attempt_id"] = attempt_id
    return data


def _get_user(email):
    db = approvals.SessionLocal()
    try:
        return db.query(UserAgreement).filter(UserAgreement.email == email).first()
    finally:
        db.close()


@pytest.mark.unit
class TestQuizApi:

    def test_quiz_questions_do_not_expose_answers(self, client):
        response = client.get("/api/quiz")
        assert response.status_code == 200
        questions = response.json()["questions"]
        assert len(questions) == len(QUIZ["questions"])
        assert all("correctAnswer" not in q for q in questions)
        assert b"correctAnswer" not in response.content

    def test_start_requires_valid_email_and_purpose(self, client):
        assert client.post("/api/quiz/start", json={"email": "not-an-email"}).status_code == 400
        assert client.post("/api/quiz/start", json={"email": "a@noaa.gov", "purpose": "other"}).status_code == 400

    def test_all_correct_passes(self, client):
        attempt_id = _start(client)
        result = None
        for question in QUIZ["questions"]:
            result = _answer(client, attempt_id, question).json()
            assert result["correct"] is True
        assert result["complete"] is True
        assert result["passed"] is True
        assert result["score"] == len(QUIZ_QUESTIONS)

    def test_wrong_answer_reveals_correct_answer_and_fails(self, client):
        attempt_id = _start(client)
        first = QUIZ["questions"][0]
        result = _answer(client, attempt_id, first, _wrong_option(first)).json()
        assert result["correct"] is False
        assert result["correct_answer"] == first["correctAnswer"]

        for question in QUIZ["questions"][1:]:
            result = _answer(client, attempt_id, question).json()
        assert result["complete"] is True
        assert result["passed"] is False

    def test_question_cannot_be_answered_twice(self, client):
        attempt_id = _start(client)
        first = QUIZ["questions"][0]
        _answer(client, attempt_id, first, _wrong_option(first))
        response = _answer(client, attempt_id, first)
        assert response.status_code == 409

    def test_finished_attempt_rejects_answers(self, client):
        attempt_id = _start(client)
        for question in QUIZ["questions"]:
            _answer(client, attempt_id, question)
        response = _answer(client, attempt_id, QUIZ["questions"][0])
        assert response.status_code == 400

    def test_invalid_option_and_unknown_question_rejected(self, client):
        attempt_id = _start(client)
        first = QUIZ["questions"][0]
        assert _answer(client, attempt_id, first, "made up answer").status_code == 400
        response = client.post("/api/quiz/answer", json={"attempt_id": attempt_id, "question_id": 9999, "answer": "x"})
        assert response.status_code == 400

    def test_unknown_attempt_rejected(self, client):
        response = _answer(client, "does-not-exist", QUIZ["questions"][0])
        assert response.status_code == 404


@pytest.mark.unit
class TestSubmitAgreementRequiresQuiz:

    def test_submit_without_attempt_rejected(self, client, mock_send_email):
        response = client.post("/submit_agreement/", data=_form_data("noquiz@noaa.gov"))
        assert response.status_code == 400
        assert "assessment" in response.json()["detail"].lower()

    def test_submit_with_failed_attempt_rejected(self, client, mock_send_email, create_quiz_attempt):
        attempt_id = create_quiz_attempt(email="failed@noaa.gov", passed=False)
        response = client.post("/submit_agreement/", data=_form_data("failed@noaa.gov", attempt_id))
        assert response.status_code == 400

    def test_submit_with_other_email_attempt_rejected(self, client, mock_send_email, create_quiz_attempt):
        attempt_id = create_quiz_attempt(email="someone.else@noaa.gov")
        response = client.post("/submit_agreement/", data=_form_data("me@noaa.gov", attempt_id))
        assert response.status_code == 400

    def test_submit_with_expired_attempt_rejected(self, client, mock_send_email, create_quiz_attempt):
        attempt_id = create_quiz_attempt(email="old@noaa.gov", completed_at=datetime.utcnow() - timedelta(hours=25))
        response = client.post("/submit_agreement/", data=_form_data("old@noaa.gov", attempt_id))
        assert response.status_code == 400

    def test_submit_with_renewal_attempt_rejected(self, client, mock_send_email, create_quiz_attempt):
        attempt_id = create_quiz_attempt(email="purpose@noaa.gov", purpose="renewal")
        response = client.post("/submit_agreement/", data=_form_data("purpose@noaa.gov", attempt_id))
        assert response.status_code == 400

    def test_submit_records_quiz_and_consumes_attempt(self, client, mock_send_email, create_quiz_attempt):
        create_quiz_attempt(email="pass@noaa.gov", passed=False)
        attempt_id = create_quiz_attempt(email="pass@noaa.gov")
        response = client.post("/submit_agreement/", data=_form_data("Pass@noaa.gov", attempt_id))
        assert response.status_code == 200

        user = _get_user("Pass@noaa.gov")
        assert user.quiz_passed_at is not None
        assert user.quiz_attempts == 2

        # Attempt cannot be reused for another submission
        db = approvals.SessionLocal()
        try:
            db.query(UserAgreement).delete()
            db.commit()
            assert db.query(QuizAttempt).filter(QuizAttempt.attempt_id == attempt_id).first().consumed
        finally:
            db.close()
        response = client.post("/submit_agreement/", data=_form_data("pass@noaa.gov", attempt_id))
        assert response.status_code == 400

    def test_end_to_end_quiz_then_submit(self, client, mock_send_email):
        attempt_id = _start(client, email="e2e@noaa.gov")
        for question in QUIZ["questions"]:
            _answer(client, attempt_id, question)
        response = client.post("/submit_agreement/", data=_form_data("e2e@noaa.gov", attempt_id))
        assert response.status_code == 200

    def test_sponsor_email_includes_assessment(self, client, mock_send_email, create_quiz_attempt):
        attempt_id = create_quiz_attempt(email="emailcheck@noaa.gov")
        client.post("/submit_agreement/", data=_form_data("emailcheck@noaa.gov", attempt_id))
        _, _, message = mock_send_email.call_args.args[:3]
        assert "GitHub Policy Assessment: Passed 100%" in message
        assert "Policy Assessment" in mock_send_email.call_args.kwargs["html_body"]


@pytest.mark.unit
class TestRenewalRequiresQuiz:

    TOKEN = "renew-token-123"

    def _create_due_user(self, create_user_agreement, email="due@noaa.gov", issued_days_ago=1):
        return create_user_agreement(
            email=email,
            last_renewal_date=datetime.utcnow() - timedelta(days=400),
            approval_token1=self.TOKEN,
            renewal_token_issued_at=datetime.utcnow() - timedelta(days=issued_days_ago),
            final_approval_timestamp=datetime.utcnow() - timedelta(days=500),
        )

    def test_get_renewal_link_does_not_renew(self, client, create_user_agreement):
        self._create_due_user(create_user_agreement)
        response = client.get(f"/renew/due@noaa.gov?token={self.TOKEN}")
        assert response.status_code == 200
        assert b"GitHub Policy Assessment" in response.content
        user = _get_user("due@noaa.gov")
        assert user.approval_token1 == self.TOKEN
        assert user.last_renewal_date < datetime.utcnow() - timedelta(days=300)

    def test_post_without_passed_attempt_rejected(self, client, create_user_agreement, create_quiz_attempt):
        self._create_due_user(create_user_agreement)
        failed = create_quiz_attempt(email="due@noaa.gov", purpose="renewal", passed=False)
        response = client.post("/renew/due@noaa.gov", data={"token": self.TOKEN, "quiz_attempt_id": failed, "acknowledge": "true"})
        assert response.status_code == 400
        assert _get_user("due@noaa.gov").approval_token1 == self.TOKEN

    def test_post_without_acknowledge_rejected(self, client, create_user_agreement, create_quiz_attempt):
        self._create_due_user(create_user_agreement)
        attempt_id = create_quiz_attempt(email="due@noaa.gov", purpose="renewal")
        response = client.post("/renew/due@noaa.gov", data={"token": self.TOKEN, "quiz_attempt_id": attempt_id})
        assert response.status_code == 400

    def test_post_with_passed_attempt_renews(self, client, create_user_agreement, create_quiz_attempt, mock_send_email):
        self._create_due_user(create_user_agreement)
        attempt_id = create_quiz_attempt(email="due@noaa.gov", purpose="renewal")
        response = client.post("/renew/due@noaa.gov", data={"token": self.TOKEN, "quiz_attempt_id": attempt_id, "acknowledge": "true"})
        assert response.status_code == 200
        assert b"Renewal Confirmed" in response.content
        user = _get_user("due@noaa.gov")
        assert user.approval_token1 is None
        assert user.renewal_token_issued_at is None
        assert user.quiz_passed_at is not None
        assert user.quiz_attempts == 1
        assert user.last_renewal_date > datetime.utcnow() - timedelta(minutes=5)

    def test_token_valid_at_59_days(self, client, create_user_agreement):
        self._create_due_user(create_user_agreement, issued_days_ago=59)
        response = client.get(f"/renew/due@noaa.gov?token={self.TOKEN}")
        assert b"GitHub Policy Assessment" in response.content

    def test_token_expired_at_61_days(self, client, create_user_agreement, create_quiz_attempt):
        self._create_due_user(create_user_agreement, issued_days_ago=61)
        response = client.get(f"/renew/due@noaa.gov?token={self.TOKEN}")
        assert b"Renewal Link Expired" in response.content
        attempt_id = create_quiz_attempt(email="due@noaa.gov", purpose="renewal")
        response = client.post("/renew/due@noaa.gov", data={"token": self.TOKEN, "quiz_attempt_id": attempt_id, "acknowledge": "true"})
        assert b"Renewal Link Expired" in response.content
        assert _get_user("due@noaa.gov").approval_token1 == self.TOKEN

    def test_invalid_token_rejected(self, client, create_user_agreement):
        self._create_due_user(create_user_agreement)
        response = client.get("/renew/due@noaa.gov?token=wrong")
        assert b"Renewal Link Invalid" in response.content


@pytest.mark.unit
class TestRenewalScheduling:

    def test_reuses_fresh_token(self, create_user_agreement, mock_send_email):
        create_user_agreement(
            email="reuse@noaa.gov",
            last_renewal_date=datetime.utcnow() - timedelta(days=400),
            approval_token1="existing-token",
            renewal_token_issued_at=datetime.utcnow() - timedelta(days=10),
        )
        check_for_renewals()
        assert _get_user("reuse@noaa.gov").approval_token1 == "existing-token"
        assert "existing-token" in mock_send_email.call_args.args[2]

    def test_replaces_token_older_than_ttl(self, create_user_agreement, mock_send_email):
        create_user_agreement(
            email="stale@noaa.gov",
            last_renewal_date=datetime.utcnow() - timedelta(days=400),
            approval_token1="stale-token",
            renewal_token_issued_at=datetime.utcnow() - timedelta(days=61),
        )
        check_for_renewals()
        user = _get_user("stale@noaa.gov")
        assert user.approval_token1 != "stale-token"
        assert user.renewal_token_issued_at > datetime.utcnow() - timedelta(minutes=5)

    def test_cutoff_requires_renewal_for_approved_users_without_quiz(self, create_user_agreement, mock_send_email, monkeypatch):
        monkeypatch.setenv("QUIZ_REQUIRED_SINCE", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))
        create_user_agreement(
            email="approved@noaa.gov",
            last_renewal_date=datetime.utcnow() - timedelta(days=30),
            final_approval_timestamp=datetime.utcnow() - timedelta(days=60),
        )
        check_for_renewals()
        recipients = [c.args[0] for c in mock_send_email.call_args_list]
        assert recipients == ["approved@noaa.gov"]

    def test_cutoff_skips_users_who_passed_since_cutoff(self, create_user_agreement, mock_send_email, monkeypatch):
        monkeypatch.setenv("QUIZ_REQUIRED_SINCE", (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d"))
        create_user_agreement(
            email="passed@noaa.gov",
            last_renewal_date=datetime.utcnow() - timedelta(days=1),
            final_approval_timestamp=datetime.utcnow() - timedelta(days=60),
            quiz_passed_at=datetime.utcnow() - timedelta(days=1),
        )
        check_for_renewals()
        assert not mock_send_email.called

    def test_cutoff_skips_pending_users(self, create_user_agreement, mock_send_email, monkeypatch):
        monkeypatch.setenv("QUIZ_REQUIRED_SINCE", (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d"))
        create_user_agreement(
            email="pending@noaa.gov",
            last_renewal_date=datetime.utcnow() - timedelta(days=10),
            approval_token1="sponsor-token",
            sponsorid="sponsor@noaa.gov",
        )
        check_for_renewals()
        assert not mock_send_email.called
        assert _get_user("pending@noaa.gov").approval_token1 == "sponsor-token"

    def test_future_or_unset_cutoff_has_no_effect(self, create_user_agreement, mock_send_email, monkeypatch):
        create_user_agreement(
            email="future@noaa.gov",
            last_renewal_date=datetime.utcnow() - timedelta(days=10),
            final_approval_timestamp=datetime.utcnow() - timedelta(days=60),
        )
        monkeypatch.delenv("QUIZ_REQUIRED_SINCE", raising=False)
        check_for_renewals()
        monkeypatch.setenv("QUIZ_REQUIRED_SINCE", (datetime.utcnow() + timedelta(days=10)).strftime("%Y-%m-%d"))
        check_for_renewals()
        assert not mock_send_email.called
