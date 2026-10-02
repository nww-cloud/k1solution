"""배포된 DB에 새 컬럼(kind/unit/unit_label)이 안전하게 추가되는지 확인.

실제 상황 재현: Render의 기존 Postgres처럼 "과거 스키마"로 leave_requests
테이블을 먼저 만들어두고, 앱을 다시 띄웠을 때(=재배포 시나리오) 누락된
컬럼이 자동으로 추가되는지 검증한다.
"""

import sqlalchemy as sa

from app import create_app
from app.extensions import db


def test_ensure_schema_adds_missing_columns_to_preexisting_table(tmp_path):
    db_path = tmp_path / "old.db"

    class OldConfig:
        SECRET_KEY = "test"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + str(db_path)
        SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 1) kind/unit/unit_label이 없는 "과거" leave_requests 테이블을 직접 만든다.
    engine = sa.create_engine(OldConfig.SQLALCHEMY_DATABASE_URI)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                CREATE TABLE employees (
                    emp_id INTEGER PRIMARY KEY, name VARCHAR(50) NOT NULL,
                    department VARCHAR(50), position VARCHAR(50),
                    hire_date DATE NOT NULL, resign_date DATE, status VARCHAR(10) NOT NULL
                )
                """
            )
        )
        conn.execute(
            sa.text(
                """
                CREATE TABLE leave_requests (
                    request_id INTEGER PRIMARY KEY, emp_id INTEGER NOT NULL,
                    request_date DATE NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL,
                    days_used FLOAT NOT NULL, status VARCHAR(10) NOT NULL, approver_id INTEGER
                )
                """
            )
        )
    engine.dispose()

    # 2) 앱을 띄우면(=재배포 시나리오) create_app 내부에서 ensure_schema가 실행되어야 한다.
    app = create_app(config_object=OldConfig)
    try:
        with app.app_context():
            inspector = sa.inspect(db.engine)
            columns = {c["name"] for c in inspector.get_columns("leave_requests")}
            assert {"kind", "unit", "unit_label"} <= columns
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
