"""Authentication persistence, isolated from Agent resources."""

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.models import Base, new_id


class User(Base):
    __tablename__ = "cornagent_auth_users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)


class LoginSession(Base):
    __tablename__ = "cornagent_auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    authenticated_at: Mapped[int] = mapped_column(BigInteger)


class Challenge(Base):
    __tablename__ = "cornagent_auth_challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(254))
    secret: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    attempts: Mapped[int] = mapped_column(default=0)


class Passkey(Base):
    __tablename__ = "cornagent_auth_passkeys"
    id: Mapped[str] = mapped_column(String(1024), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    public_key: Mapped[str] = mapped_column(Text)
    sign_count: Mapped[int] = mapped_column(BigInteger)
    transports: Mapped[list] = mapped_column(JSON, default=list)


class RateBucket(Base):
    __tablename__ = "cornagent_auth_rate_buckets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    attempts: Mapped[int] = mapped_column(default=0)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
