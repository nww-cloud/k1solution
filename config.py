import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


def _normalize_database_url(url):
    """Render/Heroku 등이 주는 'postgres://'를 SQLAlchemy용 URL로 보정하고, 드라이버를 psycopg2로 명시한다.

    드라이버를 생략하면 SQLAlchemy 버전에 따라 기본 드라이버(psycopg2 / psycopg3)가 달라져
    배포 때 ModuleNotFoundError가 날 수 있으므로 항상 명시한다.
    """
    if not url:
        return url
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_DATABASE_URI = _normalize_database_url(
        os.environ.get("DATABASE_URL")
    ) or "sqlite:///" + os.path.join(INSTANCE_DIR, "leave.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
