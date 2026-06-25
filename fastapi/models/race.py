from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text, Date
from database import Base


class WagtailPage(Base):
    __tablename__ = "wagtailcore_page"

    id = Column(Integer, primary_key=True)
    title = Column(String)
    slug = Column(String)
    url_path = Column(String)
    live = Column(Boolean)
    first_published_at = Column(DateTime(timezone=True))
    last_published_at = Column(DateTime(timezone=True))
    search_description = Column(String)
    depth = Column(Integer)
    path = Column(String)
    content_type_id = Column(Integer)


class ArticlePageDB(Base):
    __tablename__ = "website_articlepage"

    coderedpage_ptr_id = Column(Integer, ForeignKey("wagtailcore_page.id"), primary_key=True)
    caption = Column(String, nullable=True)
    date_display = Column(Date, nullable=True)
    author_display = Column(String, nullable=True)


class ChampionshipPageDB(Base):
    __tablename__ = "website_championshippage"

    coderedpage_ptr_id = Column(Integer, ForeignKey("wagtailcore_page.id"), primary_key=True)
    is_completed = Column(Boolean, default=False)


class StagePageDB(Base):
    __tablename__ = "website_stagepage"

    coderedpage_ptr_id = Column(Integer, ForeignKey("wagtailcore_page.id"), primary_key=True)
    start_date = Column(DateTime(timezone=True))
    end_date = Column(DateTime(timezone=True))
    track_id = Column(Integer, nullable=True)


class EventPageDB(Base):
    __tablename__ = "website_eventpage"

    coderedpage_ptr_id = Column(Integer, ForeignKey("wagtailcore_page.id"), primary_key=True)
    address = Column(String, nullable=True)
    track_id = Column(Integer, nullable=True)


class RaceClass(Base):
    __tablename__ = "website_raceclass"

    id = Column(Integer, primary_key=True)
    name = Column(String)


class Team(Base):
    __tablename__ = "website_team"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    slug = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    manager_name = Column(String)
    manager_email = Column(String)


class TeamMembership(Base):
    __tablename__ = "website_teammembership"

    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, ForeignKey("website_driver.id"))
    team_id = Column(Integer, ForeignKey("website_team.id"))
    race_class_id = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)


class RaceClassResultGroup(Base):
    __tablename__ = "website_raceclassresultgroup"

    id = Column(Integer, primary_key=True)
    page_id = Column(Integer, ForeignKey("wagtailcore_page.id"))
    race_class_id = Column(Integer, ForeignKey("website_raceclass.id"))
    sort_order = Column(Integer, nullable=True)
    air_temperature = Column(Float, nullable=True)
    humidity = Column(Integer, nullable=True)
    pressure = Column(Integer, nullable=True)
    wind_speed = Column(Float, nullable=True)
    precipitation = Column(Float, nullable=True)


class RaceResult(Base):
    __tablename__ = "website_raceresult"

    id = Column(Integer, primary_key=True)
    sort_order = Column(Integer, nullable=True)
    group_id = Column(Integer, ForeignKey("website_raceclassresultgroup.id"))
    driver_id = Column(Integer, ForeignKey("website_driver.id"))
    team_id = Column(Integer, nullable=True)
    race_number = Column(String, nullable=True)
    position = Column(Integer)
    points = Column(Float, default=0)

    # Финал
    start_position = Column(Integer, nullable=True)
    best_lap_ms = Column(Integer, nullable=True)
    best_s1_ms = Column(Integer, nullable=True)
    best_s2_ms = Column(Integer, nullable=True)
    best_s3_ms = Column(Integer, nullable=True)

    # Квалификация
    qual_position = Column(Integer, nullable=True)
    qual_best_lap_ms = Column(Integer, nullable=True)
    qual_s1_ms = Column(Integer, nullable=True)
    qual_s2_ms = Column(Integer, nullable=True)
    qual_s3_ms = Column(Integer, nullable=True)

    # Предфинал
    pre_final_position = Column(Integer, nullable=True)
    pre_final_start_pos = Column(Integer, nullable=True)
    pre_final_best_lap_ms = Column(Integer, nullable=True)
    pre_final_s1_ms = Column(Integer, nullable=True)
    pre_final_s2_ms = Column(Integer, nullable=True)
    pre_final_s3_ms = Column(Integer, nullable=True)


class PushToken(Base):
    __tablename__ = "accounts_pushtoken"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    token = Column(String, unique=True)
    created_at = Column(DateTime(timezone=True))
