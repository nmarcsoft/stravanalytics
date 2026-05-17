from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    strava_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=False, default="")
    profile_url = Column(String)
    access_token = Column(String, nullable=False)
    refresh_token = Column(String, nullable=False)
    token_expires_at = Column(Integer, nullable=False)
    last_sync_at = Column(DateTime)
    last_filters = Column(JSON)

    activities = relationship("Activity", back_populates="user", cascade="all, delete-orphan")


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    strava_id = Column(BigInteger, unique=True, nullable=False)
    name = Column(String, nullable=False, default="")
    description = Column(String)
    activity_type = Column(String, nullable=False, default="Run")
    start_date = Column(DateTime, nullable=False)
    distance = Column(Float, default=0)             # mètres
    moving_time = Column(Integer, default=0)        # secondes
    total_elevation_gain = Column(Float, default=0) # mètres
    average_speed = Column(Float)                   # m/s
    average_heartrate = Column(Float)
    max_heartrate = Column(Float)
    average_watts = Column(Float)
    session_type = Column(String, default="OTHER")  # classification auto
    session_type_override = Column(String)          # override manuel

    user = relationship("User", back_populates="activities")

    @property
    def effective_session_type(self) -> str:
        return self.session_type_override or self.session_type

    @property
    def distance_km(self) -> float:
        return (self.distance or 0) / 1000

    @property
    def duration_min(self) -> float:
        return (self.moving_time or 0) / 60

    @property
    def pace_min_per_km(self) -> float | None:
        if self.average_speed and self.average_speed > 0:
            return 1000 / (self.average_speed * 60)
        return None
