"""
Tests for authentication endpoints.
"""
import pytest


class TestAuthEndpoints:
    """Test authentication endpoints."""
    
    def test_signup_success(self, client):
        """Test successful user signup."""
        response = client.post(
            "/auth/signup",
            json={
                "email": "newuser@example.com",
                "password": "securepassword123",
                "name": "New User",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "newuser@example.com"
        assert data["user"]["name"] == "New User"
        assert data["user"]["plan"] == "free"
    
    def test_signup_duplicate_email(self, client, test_user):
        """Test signup with already registered email."""
        response = client.post(
            "/auth/signup",
            json={
                "email": test_user["email"],
                "password": "anotherpassword123",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["error"]["message"].lower()
    
    def test_signup_weak_password(self, client):
        """Test signup with password that's too short."""
        response = client.post(
            "/auth/signup",
            json={
                "email": "test2@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 422
    
    def test_login_success(self, client, test_user):
        """Test successful login."""
        response = client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == test_user["email"]
    
    def test_login_wrong_password(self, client, test_user):
        """Test login with wrong password."""
        response = client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401
        assert "invalid" in response.json()["error"]["message"].lower()
    
    def test_login_nonexistent_user(self, client):
        """Test login with non-existent email."""
        response = client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "anypassword123",
            },
        )
        assert response.status_code == 401
    
    def test_get_me_authenticated(self, client, auth_headers, test_user):
        """Test getting current user when authenticated."""
        response = client.get("/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user["email"]
        assert data["id"] == test_user["id"]
    
    def test_get_me_unauthenticated(self, client):
        """Test getting current user without authentication."""
        response = client.get("/auth/me")
        assert response.status_code == 401
    
    def test_refresh_token(self, client, test_user):
        """Test refreshing access token."""
        # First login to get tokens
        login_response = client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": test_user["password"],
            },
        )
        refresh_token = login_response.json()["refresh_token"]
        
        # Refresh the token
        response = client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
    
    def test_refresh_token_invalid(self, client):
        """Test refreshing with invalid token."""
        response = client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid_token"},
        )
        assert response.status_code == 401
