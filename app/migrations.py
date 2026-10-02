"""경량 스키마 보강 (Alembic 없이, 기존 배포 DB에 누락된 컬럼을 추가한다).

db.create_all()은 새 테이블은 만들어도 기존 테이블에 추가된 컬럼은 반영하지
않는다. Render 등 이미 배포된 환경의 Postgres에 모델 변경사항을 안전하게
반영하기 위해, 앱 시작 시 inspector로 실제 컬럼을 확인하고 없는 컬럼만
ALTER TABLE로 추가한다. SQLite/Postgres 모두 아래 문법으로 동작한다.
"""

from sqlalchemy import inspect, text

# (테이블, 컬럼, DDL 타입+기본값) - 새 컬럼이 생기면 이 목록에 추가한다.
COLUMN_MIGRATIONS = [
    ("leave_requests", "kind", "VARCHAR(20) NOT NULL DEFAULT '연차'"),
    ("leave_requests", "unit", "FLOAT NOT NULL DEFAULT 1.0"),
    ("leave_requests", "unit_label", "VARCHAR(20) NOT NULL DEFAULT '종일'"),
]


def ensure_schema(db):
    """COLUMN_MIGRATIONS에 정의된 컬럼이 없으면 추가한다. 이미 있으면 아무 것도 하지 않는다."""
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    with db.engine.begin() as conn:
        for table, column, ddl in COLUMN_MIGRATIONS:
            if table not in existing_tables:
                continue  # create_all()이 아직 안 만든 새 테이블 -> 이미 최신 컬럼 포함
            existing_columns = {c["name"] for c in inspector.get_columns(table)}
            if column in existing_columns:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
