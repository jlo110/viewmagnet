"""
Authentication service - handles user registration, login, and sessions.
"""

import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

import structlog
from sqlalchemy.orm import Session

from src.database.models import User
from src.auth.models import UserSession, SubscriptionTier  # session/tier helpers

logger = structlog.get_logger()


class AuthService:
    """
    Authentication service for user management.
    
    Handles:
    - User registration
    - Login/logout
    - Session management
    - Password reset
    """
    
    def __init__(self, db_session: Session):
        """Initialize with database session."""
        self.db = db_session
        self.session_duration_days = 30
    
    def register(
        self,
        email: str,
        password: str,
        name: Optional[str] = None
    ) -> Tuple[Optional[User], Optional[str]]:
        """
        Register a new user.
        
        Args:
            email: User's email address
            password: Plain text password
            name: Optional display name
            
        Returns:
            (User, None) on success
            (None, error_message) on failure
        """
        # Validate email
        if not self._validate_email(email):
            return None, "Invalid email address"
        
        # Check if email already exists
        existing = self.db.query(User).filter(User.email == email.lower()).first()
        if existing:
            return None, "An account with this email already exists"
        
        # Validate password
        password_error = self._validate_password(password)
        if password_error:
            return None, password_error
        
        # Create user
        user = User(
            email=email.lower().strip(),
            name=name,
            subscription_tier=SubscriptionTier.FREE,
            verification_token=secrets.token_urlsafe(32),
        )
        user.set_password(password)
        
        try:
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            
            logger.info("User registered", user_id=user.id, email=user.email)
            return user, None
            
        except Exception as e:
            self.db.rollback()
            logger.error("Registration failed", error=str(e))
            return None, "Registration failed. Please try again."
    
    def login(
        self,
        email: str,
        password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Authenticate user and create session.
        
        Args:
            email: User's email
            password: Plain text password
            ip_address: Optional IP for session tracking
            user_agent: Optional browser/client info
            
        Returns:
            (session_token, None) on success
            (None, error_message) on failure
        """
        # Find user
        user = self.db.query(User).filter(User.email == email.lower()).first()
        
        if not user:
            return None, "Invalid email or password"
        
        if not user.is_active:
            return None, "This account has been deactivated"
        
        if not user.check_password(password):
            return None, "Invalid email or password"
        
        # Create session
        session = UserSession(
            user_id=user.id,
            session_token=UserSession.create_token(),
            expires_at=datetime.utcnow() + timedelta(days=self.session_duration_days),
            ip_address=ip_address,
            user_agent=user_agent,
        )
        
        # Update last login
        user.last_login_at = datetime.utcnow()
        
        try:
            self.db.add(session)
            self.db.commit()
            
            logger.info("User logged in", user_id=user.id)
            return session.session_token, None
            
        except Exception as e:
            self.db.rollback()
            logger.error("Login failed", error=str(e))
            return None, "Login failed. Please try again."
    
    def logout(self, session_token: str) -> bool:
        """
        Invalidate a session.
        
        Args:
            session_token: The session token to invalidate
            
        Returns:
            True if session was found and deleted
        """
        session = self.db.query(UserSession).filter(
            UserSession.session_token == session_token
        ).first()
        
        if session:
            self.db.delete(session)
            self.db.commit()
            logger.info("User logged out", user_id=session.user_id)
            return True
        
        return False
    
    def logout_all_sessions(self, user_id: int) -> int:
        """
        Invalidate all sessions for a user.
        
        Returns:
            Number of sessions deleted
        """
        count = self.db.query(UserSession).filter(
            UserSession.user_id == user_id
        ).delete()
        
        self.db.commit()
        logger.info("All sessions logged out", user_id=user_id, count=count)
        return count
    
    def get_user_by_session(self, session_token: str) -> Optional[User]:
        """
        Get user from session token.
        
        Args:
            session_token: The session token
            
        Returns:
            User if session is valid, None otherwise
        """
        session = self.db.query(UserSession).filter(
            UserSession.session_token == session_token
        ).first()
        
        if not session:
            return None
        
        if not session.is_valid():
            # Session expired, clean up
            self.db.delete(session)
            self.db.commit()
            return None
        
        # Update last activity
        session.last_activity_at = datetime.utcnow()
        self.db.commit()
        
        return session.user
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email address."""
        return self.db.query(User).filter(User.email == email.lower()).first()
    
    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        return self.db.query(User).filter(User.id == user_id).first()
    
    def change_password(
        self,
        user: User,
        old_password: str,
        new_password: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Change user's password.
        
        Args:
            user: The user
            old_password: Current password
            new_password: New password
            
        Returns:
            (True, None) on success
            (False, error_message) on failure
        """
        if not user.check_password(old_password):
            return False, "Current password is incorrect"
        
        password_error = self._validate_password(new_password)
        if password_error:
            return False, password_error
        
        user.set_password(new_password)
        self.db.commit()
        
        # Invalidate all other sessions
        self.db.query(UserSession).filter(
            UserSession.user_id == user.id
        ).delete()
        self.db.commit()
        
        logger.info("Password changed", user_id=user.id)
        return True, None
    
    def request_password_reset(self, email: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Generate password reset token.
        
        Args:
            email: User's email
            
        Returns:
            (reset_token, None) on success
            (None, error_message) on failure
        """
        user = self.get_user_by_email(email)
        
        if not user:
            # Don't reveal if email exists
            return None, None
        
        # Generate reset token (store in verification_token temporarily)
        reset_token = secrets.token_urlsafe(32)
        user.verification_token = f"reset:{reset_token}:{datetime.utcnow().timestamp()}"
        self.db.commit()
        
        logger.info("Password reset requested", user_id=user.id)
        return reset_token, None
    
    def reset_password(
        self,
        reset_token: str,
        new_password: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Reset password using token.
        
        Args:
            reset_token: The reset token
            new_password: New password
            
        Returns:
            (True, None) on success
            (False, error_message) on failure
        """
        # Find user with this token
        users = self.db.query(User).filter(
            User.verification_token.like(f"reset:{reset_token}:%")
        ).all()
        
        if not users:
            return False, "Invalid or expired reset token"
        
        user = users[0]
        
        # Check token expiry (24 hours)
        try:
            _, _, timestamp = user.verification_token.split(':')
            token_time = datetime.fromtimestamp(float(timestamp))
            if datetime.utcnow() - token_time > timedelta(hours=24):
                return False, "Reset token has expired"
        except (ValueError, AttributeError):
            return False, "Invalid reset token"
        
        # Validate new password
        password_error = self._validate_password(new_password)
        if password_error:
            return False, password_error
        
        # Set new password
        user.set_password(new_password)
        user.verification_token = None
        
        # Invalidate all sessions
        self.db.query(UserSession).filter(
            UserSession.user_id == user.id
        ).delete()
        
        self.db.commit()
        
        logger.info("Password reset completed", user_id=user.id)
        return True, None
    
    def verify_email(self, token: str) -> Tuple[bool, Optional[str]]:
        """
        Verify user's email address.
        
        Args:
            token: Verification token
            
        Returns:
            (True, None) on success
            (False, error_message) on failure
        """
        user = self.db.query(User).filter(
            User.verification_token == token,
            User.is_verified == False
        ).first()
        
        if not user:
            return False, "Invalid verification token"
        
        user.is_verified = True
        user.verification_token = None
        self.db.commit()
        
        logger.info("Email verified", user_id=user.id)
        return True, None
    
    def update_subscription(
        self,
        user: User,
        tier: SubscriptionTier,
        stripe_subscription_id: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ):
        """Update user's subscription."""
        user.subscription_tier = tier
        user.stripe_subscription_id = stripe_subscription_id
        user.subscription_expires_at = expires_at
        self.db.commit()
        
        logger.info(
            "Subscription updated",
            user_id=user.id,
            tier=tier.value,
            expires_at=expires_at
        )
    
    def cleanup_expired_sessions(self) -> int:
        """Delete all expired sessions. Returns count deleted."""
        count = self.db.query(UserSession).filter(
            UserSession.expires_at < datetime.utcnow()
        ).delete()
        
        self.db.commit()
        logger.info("Cleaned up expired sessions", count=count)
        return count
    
    def _validate_email(self, email: str) -> bool:
        """Validate email format."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))
    
    def _validate_password(self, password: str) -> Optional[str]:
        """
        Validate password strength.
        
        Returns error message if invalid, None if valid.
        """
        if len(password) < 8:
            return "Password must be at least 8 characters"
        
        if not re.search(r'[A-Z]', password):
            return "Password must contain at least one uppercase letter"
        
        if not re.search(r'[a-z]', password):
            return "Password must contain at least one lowercase letter"
        
        if not re.search(r'\d', password):
            return "Password must contain at least one number"
        
        return None









