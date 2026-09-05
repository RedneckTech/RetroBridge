import hashlib
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    full_name = Column(String(128), nullable=True)
    bio = Column(Text, nullable=True)
    preferences = Column(Text, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    max_queued_jobs = Column(Integer, default=3, nullable=False)
    max_terminal_sessions = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login = Column(DateTime, nullable=True)
    email_notify_jobs = Column(Boolean, default=False, nullable=False)
    email_notify_security = Column(Boolean, default=True, nullable=False)
    patreon_id = Column(String(64), nullable=True, unique=True)
    patreon_tier = Column(String(32), nullable=True)
    _patreon_access_token = Column('patreon_access_token', Text, nullable=True)
    _patreon_refresh_token = Column('patreon_refresh_token', Text, nullable=True)
    patreon_expires_at = Column(DateTime, nullable=True)

    jobs = relationship('Job', back_populates='user',
                        cascade='all, delete-orphan')
    terminal_sessions = relationship('TerminalSession', back_populates='user',
                                     cascade='all, delete-orphan')

    @property
    def patreon_access_token(self):
        from retrobridge.integrations.patreon_crypto import decrypt_token
        return decrypt_token(self._patreon_access_token)

    @patreon_access_token.setter
    def patreon_access_token(self, value):
        from retrobridge.integrations.patreon_crypto import encrypt_token
        self._patreon_access_token = encrypt_token(value)

    @property
    def patreon_refresh_token(self):
        from retrobridge.integrations.patreon_crypto import decrypt_token
        return decrypt_token(self._patreon_refresh_token)

    @patreon_refresh_token.setter
    def patreon_refresh_token(self, value):
        from retrobridge.integrations.patreon_crypto import encrypt_token
        self._patreon_refresh_token = encrypt_token(value)

    def avatar_url(self, size=80):
        h = hashlib.md5(self.email.strip().lower().encode()).hexdigest()
        return f'https://www.gravatar.com/avatar/{h}?s={size}&d=identicon&r=g'

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)


class Device(Base):
    __tablename__ = 'devices'

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), unique=True, nullable=False)
    display_name = Column(String(64), nullable=True)
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    ports = relationship('DevicePort', back_populates='device',
                         cascade='all, delete-orphan')
    jobs = relationship('Job', back_populates='device',
                        cascade='all, delete-orphan')
    terminal_sessions = relationship('TerminalSession', back_populates='device',
                                     cascade='all, delete-orphan')


class DevicePort(Base):
    __tablename__ = 'device_ports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.id'), nullable=False)
    port_label = Column(String(32), nullable=False)
    transport = Column(String(16), default='serial', nullable=False)
    dev_path = Column(String(256), nullable=False)
    purpose = Column(String(16), nullable=False, default='job_queue')
    baud = Column(Integer, default=9600)
    data_bits = Column(Integer, default=8)
    parity = Column(String(1), default='N')
    stop_bits = Column(Integer, default=1)
    flow_control = Column(String(8), default='none')
    newline_mode = Column(String(4), default='crlf')
    max_concurrent_jobs = Column(Integer, default=1)
    max_runtime_seconds = Column(Integer, default=300)
    idle_timeout_seconds = Column(Integer, default=5)
    pre_transfer_cmds = Column(Text, nullable=True)
    post_transfer_cmds = Column(Text, nullable=True)
    transfer_protocol = Column(String(16), default='xmodem')
    is_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    device = relationship('Device', back_populates='ports')
    jobs = relationship('Job', back_populates='port',
                        cascade='all, delete-orphan')
    terminal_sessions = relationship('TerminalSession', back_populates='port',
                                     cascade='all, delete-orphan')
    port_leases = relationship('PortLease', back_populates='port',
                               cascade='all, delete-orphan')


class Job(Base):
    __tablename__ = 'jobs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    device_id = Column(Integer, ForeignKey('devices.id'), nullable=False)
    port_id = Column(Integer, ForeignKey('device_ports.id'), nullable=True)
    original_filename = Column(String(256), nullable=False)
    stored_filename = Column(String(512), nullable=True)
    status = Column(String(16), default='queued', nullable=False)
    priority = Column(Integer, default=0)
    file_size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    runtime_seconds = Column(Integer, nullable=True)
    exit_code = Column(Integer, nullable=True)
    output_path = Column(String(512), nullable=True)
    error_message = Column(Text, nullable=True)
    worker_pid = Column(Integer, nullable=True)
    claimed_by = Column(String(128), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    override_newline_mode = Column(String(4), nullable=True)
    override_pre_transfer_cmds = Column(Text, nullable=True)
    override_post_transfer_cmds = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index('ix_jobs_status_created_at', 'status', 'created_at'),
        Index('ix_jobs_port_status', 'port_id', 'status'),
    )

    user = relationship('User', back_populates='jobs')
    device = relationship('Device', back_populates='jobs')
    port = relationship('DevicePort', back_populates='jobs')


class TerminalSession(Base):
    __tablename__ = 'terminal_sessions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    device_id = Column(Integer, ForeignKey('devices.id'), nullable=False)
    port_id = Column(Integer, ForeignKey('device_ports.id'), nullable=False)
    status = Column(String(16), default='active', nullable=False)
    connected_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    disconnected_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    bytes_sent = Column(Integer, default=0)
    bytes_received = Column(Integer, default=0)
    disconnect_reason = Column(String(64), nullable=True)

    user = relationship('User', back_populates='terminal_sessions')
    device = relationship('Device', back_populates='terminal_sessions')
    port = relationship('DevicePort', back_populates='terminal_sessions')
    port_leases = relationship('PortLease', back_populates='session')


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ip_address = Column(String(45), nullable=False, index=True)
    username = Column(String(64), nullable=True, index=True)
    success = Column(Boolean, default=False, nullable=False)
    attempted_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class PortLease(Base):
    __tablename__ = 'port_leases'

    id = Column(Integer, primary_key=True, autoincrement=True)
    port_id = Column(Integer, ForeignKey('device_ports.id'),
                     unique=True, nullable=False)
    session_id = Column(Integer, ForeignKey('terminal_sessions.id'),
                        nullable=False)
    claimed_by = Column(String(128), nullable=False)
    claimed_at = Column(DateTime, nullable=False)
    lease_expires_at = Column(DateTime, nullable=False)
    heartbeat_at = Column(DateTime, nullable=False)

    port = relationship('DevicePort', back_populates='port_leases')
    session = relationship('TerminalSession', back_populates='port_leases')


class AdminSetting(Base):
    __tablename__ = 'admin_settings'

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    description = Column(String(256), nullable=True)
