from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import ARRAY
from database import Base


class AuthUser(Base):
    __tablename__ = "auth_user"

    id = Column(Integer, primary_key=True)
    username = Column(String)
    email = Column(String)
    password = Column(String)
    is_active = Column(Boolean)
    first_name = Column(String)
    last_name = Column(String)


class UserProfile(Base):
    __tablename__ = "accounts_userprofile"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    roles = Column(ARRAY(String))
    verified = Column(Boolean)
    driver_id = Column(Integer, nullable=True)
    team_id = Column(Integer, nullable=True)
