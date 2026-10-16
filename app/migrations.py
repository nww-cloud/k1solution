"""경량 스키마 보강 (Alembic 없이, 기존 배포 DB에 누락된 컬럼을 추가한다).

db.create_all()은 새 테이블은 만들어도 기존 테이블에 추가된 컬럼은 반영하지
않는다. Render 등 이미 배포된 환경의 Postgres에 모델 변경사항을 안전하게
반영하기 위해, 앱 시작 시 실제 컬럼을 확인하고 없는 컬럼만 ALTER TABLE로
추가한다. SQLite/Postgres 모두 아래 문법으로 동작한다.

주의: ALTER TABLE을 실행하는 트랜잭션이 열려 있는 동안에는 다른 커넥션으로
같은 테이블을 조회하면 안 된다. Postgres에서는 ALTER TABLE이 테이블 전체
잠금을 잡기 때문에, 같은 프로세스의 다른 커넥션(inspector)이 그 잠금을
기다리며 앱 부팅이 영원히 멈춘다(SQLite에서는 재현되지 않는다).
그래서 컬럼 조회를 모두 끝낸 뒤에 ALTER만 한 트랜잭션에서 실행한다.
"""

from sqlalchemy import inspect, text

# (테이블, 컬럼, DDL 타입+기본값) - 새 컬럼이 생기면 이 목록에 추가한다.
COLUMN_MIGRATIONS = [
    ("leave_requests", "kind", "VARCHAR(20) NOT NULL DEFAULT '연차'"),
    ("leave_requests", "unit", "FLOAT NOT NULL DEFAULT 1.0"),
    ("leave_requests", "unit_label", "VARCHAR(20) NOT NULL DEFAULT '종일'"),
]


def _limit_lock_wait(conn):
    """Postgres에서 다른 프로세스가 쥔 잠금을 기다리며 부팅이 멈추지 않도록 대기 시간을 제한한다."""
    if conn.dialect.name == "postgresql":
        conn.execute(text("SET lock_timeout = '5s'"))


def _find_missing_columns(engine):
    """실제 DB를 조회해 누락된 (테이블, 컬럼, DDL) 목록을 반환한다. 조회 커넥션은 반환 전에 닫힌다."""
    missing = []
    with engine.connect() as conn:
        _limit_lock_wait(conn)
        inspector = inspect(conn)
        existing_tables = set(inspector.get_table_names())
        existing_columns = {
            table: {c["name"] for c in inspector.get_columns(table)}
            for table in {t for t, _, _ in COLUMN_MIGRATIONS}
            if table in existing_tables
        }
    for table, column, ddl in COLUMN_MIGRATIONS:
        if table not in existing_columns:
            continue  # create_all()이 방금 만든 새 테이블 -> 이미 최신 컬럼 포함
        if column not in existing_columns[table]:
            missing.append((table, column, ddl))
    return missing


def ensure_schema(db):
    """COLUMN_MIGRATIONS에 정의된 컬럼이 없으면 추가한다. 이미 있으면 아무 것도 하지 않는다."""
    try:
        missing = _find_missing_columns(db.engine)
        if not missing:
            return

        with db.engine.begin() as conn:
            _limit_lock_wait(conn)
            for table, column, ddl in missing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    except Exception as exc:  # noqa: BLE001 - 마이그레이션 실패가 앱 부팅 자체를 막으면 안 된다
        print(f"[migrations] 스키마 보강 실패(다음 부팅 때 재시도): {exc}", flush=True)
