from sqlalchemy import Column, Integer, String, JSON
from database import Base


class Driver(Base):
    __tablename__ = "website_driver"

    id = Column(Integer, primary_key=True)
    first_name = Column(String)
    last_name = Column(String)
    slug = Column(String)
    city = Column(String, nullable=True)
    rating_by_class = Column(JSON, nullable=True)
