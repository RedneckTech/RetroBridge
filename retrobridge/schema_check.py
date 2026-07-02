"""Schema health check — detects stale databases missing model columns.

Usage: python -m retrobridge.schema_check /path/to/db.sqlite
Exit code 0 = schema matches models, 1 = needs recreate.
"""

import sys

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool


def check_schema(db_path, verbose=False):
    actual_engine = create_engine(
        f'sqlite:///{db_path}',
        connect_args={'timeout': 10},
    )

    reference_engine = create_engine(
        'sqlite:///:memory:',
        poolclass=StaticPool,
        connect_args={'check_same_thread': False},
    )

    from retrobridge.models import Base
    Base.metadata.create_all(bind=reference_engine)

    actual_insp = inspect(actual_engine)
    ref_insp = inspect(reference_engine)

    missing = []
    for table_name in ref_insp.get_table_names():
        if table_name not in actual_insp.get_table_names():
            missing.append(f'  Table missing: {table_name}')
            continue

        ref_cols = {c['name'] for c in ref_insp.get_columns(table_name)}
        actual_cols = {c['name'] for c in actual_insp.get_columns(table_name)}
        for col in sorted(ref_cols - actual_cols):
            missing.append(f'  Column missing: {table_name}.{col}')

    actual_engine.dispose()
    reference_engine.dispose()

    if missing and verbose:
        print('[!] Schema mismatch detected:')
        for m in missing:
            print(m)
    return len(missing) == 0


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python -m retrobridge.schema_check <db_path>', file=sys.stderr)
        sys.exit(2)
    ok = check_schema(sys.argv[1], verbose=True)
    sys.exit(0 if ok else 1)
