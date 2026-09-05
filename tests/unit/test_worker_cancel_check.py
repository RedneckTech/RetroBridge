"""Tests for job cancellation checking during worker transfer."""
from datetime import datetime, timezone

from retrobridge.models import Device, DevicePort, Job, User
from worker import JobCancelledError, _check_job_cancelled


def test_check_job_cancelled_reuses_session(db_session):
    user = User(username='canceluser', email='c@example.com', password_hash='h')
    device = Device(name='canceldev')
    db_session.add_all([user, device])
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='T0', dev_path='/dev/tty0',
                      purpose='job_queue')
    db_session.add(port)
    db_session.flush()
    job = Job(user_id=user.id, device_id=device.id, port_id=port.id,
              original_filename='x.mod', status='running')
    db_session.add(job)
    db_session.commit()

    # Should not raise when job is not cancelled.
    _check_job_cancelled(job, db_session)

    # Mark cancelled in the same session to simulate an external update.
    db_session.execute(
        type(job).__table__.update()
        .where(type(job).__table__.c.id == job.id)
        .values(cancel_requested=True)
    )
    db_session.commit()

    # Reuse the same session object; it must see the updated row.
    try:
        _check_job_cancelled(job, db_session)
    except JobCancelledError:
        pass
    else:
        raise AssertionError('Expected JobCancelledError')


def test_check_job_cancelled_sees_canceled_status(db_session):
    user = User(username='canceleduser', email='c2@example.com', password_hash='h')
    device = Device(name='canceleddev')
    db_session.add_all([user, device])
    db_session.flush()
    port = DevicePort(device_id=device.id, port_label='T0', dev_path='/dev/tty0',
                      purpose='job_queue')
    db_session.add(port)
    db_session.flush()
    job = Job(user_id=user.id, device_id=device.id, port_id=port.id,
              original_filename='x.mod', status='canceled')
    db_session.add(job)
    db_session.commit()

    try:
        _check_job_cancelled(job, db_session)
    except JobCancelledError:
        pass
    else:
        raise AssertionError('Expected JobCancelledError')
