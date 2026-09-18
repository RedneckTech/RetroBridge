"""Concurrency test for job creation quota enforcement.

Verifies that two concurrent create_job calls for the same user cannot both
pass the quota check, even when the route-level advisory check races.
"""

import tempfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash

from retrobridge.jobs.utils import create_job
from retrobridge.models import AdminSetting, Base, Device, Job, User


def _make_file():
    return FileStorage(
        stream=BytesIO(b'valid content'),
        filename='test.bin',
        content_type='application/octet-stream',
    )


def _create_job_in_thread(app, user_id, device_id, upload_dir, results, idx):
    """Attempt to create a job from a worker thread; store the outcome."""
    with app.app_context():
        db_session = app.db_session
        try:
            job = create_job(
                db_session, user_id, device_id, 'test.bin',
                _make_file(), str(upload_dir),
            )
            results[idx] = ('ok', job.id)
        except ValueError as exc:
            results[idx] = ('error', str(exc))
        except Exception as exc:  # noqa: BLE001 - capture any unexpected worker failure
            results[idx] = ('exception', repr(exc))


def test_concurrent_create_job_respects_quota():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import scoped_session, sessionmaker

    from retrobridge import create_app

    with tempfile.TemporaryDirectory() as tmpdir:
        upload_dir = Path(tmpdir) / 'uploads'
        upload_dir.mkdir()
        db_path = Path(tmpdir) / 'retrobridge_concurrency.db'

        # Use a file-backed SQLite DB with cross-thread access enabled so each
        # worker thread gets its own connection and the row-level lock can
        # serialize concurrent create_job calls for the same user.
        db_uri = f'sqlite:///{db_path}'
        engine = create_engine(
            db_uri,
            connect_args={'check_same_thread': False},
        )
        Base.metadata.create_all(bind=engine)

        # Seed user/device in the main thread before starting workers.
        Session = sessionmaker(bind=engine)
        seed_session = Session()
        user = User(
            username='concurrent',
            email='c@example.com',
            password_hash=generate_password_hash('Pass123'),
            max_queued_jobs=1,
        )
        device = Device(name='concurrent-dev')
        # Disable the per-hour rate limit for this test so only the quota
        # check matters.
        seed_session.add_all([
            user,
            device,
            AdminSetting(key='MAX_JOBS_PER_HOUR', value='0',
                         description='disabled for concurrency test'),
        ])
        seed_session.commit()
        user_id = user.id
        device_id = device.id
        seed_session.close()

        # Build the app but override its session factory to use our shared
        # engine so each thread gets its own scoped session over the same DB.
        app = create_app('config.TestConfig')
        app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
        app.config['UPLOAD_DIR'] = str(upload_dir)
        app.config['OUTPUT_DIR'] = str(Path(tmpdir) / 'outputs')
        app.config['RATE_LIMIT_ENABLED'] = False
        app.db_engine = engine
        app.db_session = scoped_session(sessionmaker(bind=engine))

        results = [None, None]
        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(
                _create_job_in_thread, app, user_id, device_id,
                upload_dir, results, 0,
            )
            f2 = executor.submit(
                _create_job_in_thread, app, user_id, device_id,
                upload_dir, results, 1,
            )
            f1.result(timeout=10)
            f2.result(timeout=10)

        # Exactly one thread should succeed; the other should be quota-blocked.
        outcomes = [r[0] for r in results]
        assert outcomes.count('ok') == 1, f'expected one success, got {results}'
        assert outcomes.count('error') == 1, f'expected one quota error, got {results}'
        assert 'maximum' in results[outcomes.index('error')][1].lower()

        # Verify only one job exists for the user.
        check_session = Session()
        count = check_session.query(Job).filter_by(user_id=user_id).count()
        assert count == 1, f'expected 1 job in DB, got {count}'
        check_session.close()
