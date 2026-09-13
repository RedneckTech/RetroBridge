"""Tests for worker log accuracy (review #20)."""
import logging

from retrobridge.models import DevicePort, Job
from worker import run_job_on_device


def test_no_serial_port_closed_log_when_transport_fails(tmp_path, monkeypatch,
                                                        caplog):
    uploads = tmp_path / 'uploads'
    uploads.mkdir()
    job_dir = uploads / 'job-1'
    job_dir.mkdir()
    (job_dir / 'prog.bin').write_bytes(b'data')

    monkeypatch.setenv('RETROBRIDGE_UPLOAD_DIR', str(uploads))
    monkeypatch.setenv('RETROBRIDGE_OUTPUT_DIR', str(tmp_path / 'outputs'))

    job = Job(id=1, user_id=1, device_id=1, original_filename='prog.bin',
              stored_filename='job-1/prog.bin', status='running')
    port = DevicePort(dev_path='/dev/nonexistent-retrobridge-test-xyz',
                      transport='serial', baud=9600)
    logger = logging.getLogger('test-worker-logging')

    with caplog.at_level(logging.INFO, logger='test-worker-logging'):
        result = run_job_on_device(job, port, logger)

    assert result is False
    assert 'Serial port closed' not in caplog.text
    assert 'nonexistent-retrobridge-test-xyz' in caplog.text
