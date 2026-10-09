from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from dotenv import load_dotenv
import os

_base = os.path.dirname(os.path.abspath(__file__))
# Локальный .env имеет приоритет; на проде переменные приходят из системного окружения
load_dotenv(dotenv_path=os.path.join(_base, '.env'))
load_dotenv(dotenv_path=os.path.join(_base, '..', '.env'))

DATABASE_URL = (
    f"postgresql+psycopg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:5432/{os.getenv('POSTGRES_DB')}"
)

# pool_pre_ping: после перезапуска PostgreSQL (автообновления Ubuntu) соединения из пула мертвы —
# проверяем перед выдачей, иначе первые запросы получат 500.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
