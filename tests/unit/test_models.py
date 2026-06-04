"""Unit tests for models."""
import pytest
from werkzeug.security import generate_password_hash, check_password_hash

from retrobridge.models import User, Device, DevicePort, Job, TerminalSession, AdminSetting


class TestUser:
    def test_create_user(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash=generate_password_hash('password'))
        db_session.add(user)
        db_session.commit()

        assert user.id is not None
        assert user.username == 'testuser'
        assert user.is_admin is False
        assert user.max_queued_jobs == 3
        assert user.max_terminal_sessions == 1
        assert check_password_hash(user.password_hash, 'password')
        assert not check_password_hash(user.password_hash, 'wrong')

    def test_user_unique_username(self, db_session):
        user1 = User(username='testuser', email='a@example.com',
                     password_hash='hash')
        user2 = User(username='testuser', email='b@example.com',
                     password_hash='hash')
        db_session.add(user1)
        db_session.commit()
        db_session.add(user2)
        with pytest.raises(Exception):
            db_session.commit()


class TestDevice:
    def test_create_device(self, db_session):
        device = Device(name='centurion', display_name='Centurion CPU-6')
        db_session.add(device)
        db_session.commit()

        assert device.id is not None
        assert device.name == 'centurion'
        assert device.is_enabled is True


class TestDevicePort:
    def test_create_port(self, db_session):
        device = Device(name='centurion', display_name='Centurion CPU-6')
        db_session.add(device)
        db_session.commit()

        port = DevicePort(
            device_id=device.id, port_label='TTY0',
            dev_path='/dev/centurion_tty0', purpose='job_queue',
        )
        db_session.add(port)
        db_session.commit()

        assert port.id is not None
        assert port.baud == 9600
        assert port.parity == 'N'
        assert port.flow_control == 'none'
        assert port.purpose == 'job_queue'


class TestJob:
    def test_create_job(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        db_session.add_all([user, device])
        db_session.commit()

        job = Job(
            user_id=user.id, device_id=device.id,
            original_filename='test.bin', status='queued',
        )
        db_session.add(job)
        db_session.commit()

        assert job.id is not None
        assert job.status == 'queued'
        assert job.created_at is not None

    def test_job_status_transitions(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        db_session.add_all([user, device])
        db_session.commit()

        job = Job(user_id=user.id, device_id=device.id,
                  original_filename='test.bin', status='queued')
        db_session.add(job)
        db_session.commit()

        # queued -> running
        job.status = 'running'
        db_session.commit()
        assert job.status == 'running'

        # running -> completed
        job.status = 'completed'
        db_session.commit()
        assert job.status == 'completed'


class TestTerminalSession:
    def test_create_session(self, db_session):
        user = User(username='testuser', email='test@example.com',
                    password_hash='hash')
        device = Device(name='centurion')
        db_session.add_all([user, device])
        db_session.commit()

        port = DevicePort(device_id=device.id, port_label='TTY1',
                          dev_path='/dev/centurion_tty1', purpose='interactive')
        db_session.add(port)
        db_session.commit()

        session = TerminalSession(
            user_id=user.id, device_id=device.id,
            port_id=port.id, status='active',
        )
        db_session.add(session)
        db_session.commit()

        assert session.id is not None
        assert session.status == 'active'
        assert session.connected_at is not None
        assert session.bytes_sent == 0
        assert session.bytes_received == 0


class TestAdminSetting:
    def test_create_setting(self, db_session):
        setting = AdminSetting(key='TEST_KEY', value='test_value',
                               description='A test setting')
        db_session.add(setting)
        db_session.commit()

        assert setting.key == 'TEST_KEY'
        assert setting.value == 'test_value'

    def test_setting_primary_key(self, db_session):
        setting1 = AdminSetting(key='UNIQUE_KEY', value='v1')
        setting2 = AdminSetting(key='UNIQUE_KEY', value='v2')
        db_session.add(setting1)
        db_session.commit()
        db_session.add(setting2)
        with pytest.raises(Exception):
            db_session.commit()
