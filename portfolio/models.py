from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(UTC).isoformat()


class Base(DeclarativeBase):
    pass


class Manager(Base):
    __tablename__ = "managers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))


class Property(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("manager_id", "external_id", name="uq_property_external"),
        UniqueConstraint("manager_id", "name", "address", name="uq_property_address"),
        CheckConstraint("bedrooms BETWEEN 0 AND 20", name="ck_bedrooms"),
        CheckConstraint(
            "price_cents >= 0 AND price_cents <= 100000000000", name="ck_price"
        ),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_rating"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_latitude"),
        CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_longitude"),
        CheckConstraint(
            "property_type IN ('apartment', 'house', 'office', 'retail')",
            name="ck_type",
        ),
        Index("ix_property_search", "manager_id", "property_type", "price_cents"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(240))
    city: Mapped[str] = mapped_column(String(100))
    property_type: Mapped[str] = mapped_column(String(20))
    bedrooms: Mapped[int] = mapped_column(Integer)
    price_cents: Mapped[int] = mapped_column(BigInteger)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'manager', 'reader')", name="ck_key_role"),
        CheckConstraint(
            "role = 'admin' OR manager_id IS NOT NULL", name="ck_key_scope"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("managers.id"), nullable=True
    )
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)
    expires_at: Mapped[str] = mapped_column(String(40))
    revoked: Mapped[bool] = mapped_column(default=False)


class ImportRun(Base):
    __tablename__ = "imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("managers.id"))
    key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"))
    digest: Mapped[str] = mapped_column(String(64))
    report: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(primary_key=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"))
    action: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[int] = mapped_column(Integer)
    details: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40), default=utcnow)


class RateBucket(Base):
    __tablename__ = "rate_buckets"
    key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), primary_key=True)
    window: Mapped[int] = mapped_column(primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
