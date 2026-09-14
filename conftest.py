import os
import tempfile

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture
def app():
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    class TestConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path
        SQLALCHEMY_TRACK_MODIFICATIONS = False

    flask_app = create_app(config_object=TestConfig)

    yield flask_app

    with flask_app.app_context():
        _db.session.remove()
        _db.engine.dispose()

    os.close(db_fd)
    try:
        os.unlink(db_path)
    except PermissionError:
        pass  # Windows에서 sqlite 파일 핸들 해제가 늦어지는 경우 무시


@pytest.fixture
def app_ctx(app):
    with app.app_context():
        yield app


@pytest.fixture
def session(app_ctx):
    yield _db.session


@pytest.fixture
def make_employee(session):
    from app.models import Employee

    def _make(hire_date, name="테스트직원", **kwargs):
        kwargs.setdefault("status", "재직")
        employee = Employee(name=name, hire_date=hire_date, **kwargs)
        session.add(employee)
        session.commit()
        return employee

    return _make


@pytest.fixture
def make_grant(session):
    from app.models import LeaveGrant

    def _make(employee, grant_type="연차", grant_date=None, expire_date=None, granted_days=15, used_days=0):
        grant = LeaveGrant(
            emp_id=employee.emp_id,
            grant_type=grant_type,
            grant_date=grant_date,
            expire_date=expire_date,
            granted_days=granted_days,
            used_days=used_days,
            source_rule="테스트용 수동 부여",
        )
        session.add(grant)
        session.commit()
        return grant

    return _make


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login_as(client):
    def _login(employee):
        with client.session_transaction() as sess:
            sess["current_emp_id"] = employee.emp_id
        return client

    return _login
