import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _normalize_database_url(url):
    """Render/Heroku 등이 주는 'postgres://'를 SQLAlchemy가 요구하는 'postgresql://'로 보정."""
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.environ.get("DATABASE_URL")
    ) or "sqlite:///" + os.path.join(INSTANCE_DIR, "leave.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
