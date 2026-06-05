import click
from flask.cli import AppGroup


def register_cli_commands(app):
    db_cli = AppGroup('db')

    @db_cli.command('init')
    def init_db():
        from retrobridge.models import Base
        Base.metadata.create_all(bind=app.db_engine)
        click.echo('Database tables created.')

    app.cli.add_command(db_cli)

    @app.cli.command('init-db')
    def init_db_alias():
        from retrobridge.models import Base
        Base.metadata.create_all(bind=app.db_engine)
        click.echo('Database tables created.')

    @app.cli.command('seed')
    def seed():
        from werkzeug.security import generate_password_hash
        from retrobridge.models import User, Device, DevicePort, AdminSetting

        s = app.db_session

        if not s.get(User, 1):
            admin = User(
                username='admin',
                email='admin@retrobridge.local',
                password_hash=generate_password_hash('admin'),
                full_name='Administrator',
                is_admin=True,
                max_queued_jobs=10,
                max_terminal_sessions=5,
            )
            s.add(admin)

        if not s.query(Device).filter_by(name='centurion').first():
            centurion = Device(
                name='centurion',
                display_name='Centurion CPU-6',
                is_enabled=True,
            )
            s.add(centurion)
            s.flush()
            s.add(DevicePort(
                device_id=centurion.id, port_label='TTY0', dev_path='/dev/centurion_tty0',
                purpose='job_queue', baud=9600,
            ))
            s.add(DevicePort(
                device_id=centurion.id, port_label='TTY1', dev_path='/dev/centurion_tty1',
                purpose='interactive', baud=9600,
                max_runtime_seconds=3600, idle_timeout_seconds=300,
            ))

        if not s.query(Device).filter_by(name='pdp11').first():
            pdp11 = Device(
                name='pdp11',
                display_name='DEC PDP-11/44',
                is_enabled=True,
            )
            s.add(pdp11)
            s.flush()
            s.add(DevicePort(
                device_id=pdp11.id, port_label='TTY0', dev_path='/dev/pdp11_tty0',
                purpose='job_queue', baud=9600,
            ))
            s.add(DevicePort(
                device_id=pdp11.id, port_label='TTY1', dev_path='/dev/pdp11_tty1',
                purpose='interactive', baud=9600,
                max_runtime_seconds=3600, idle_timeout_seconds=300,
            ))

        default_settings = {
            'MAX_UPLOAD_SIZE_BYTES': ('8388608', 'Maximum file upload size in bytes'),
            'DEFAULT_MAX_QUEUED_JOBS': ('3', 'Default max queued jobs per user'),
            'DEFAULT_MAX_TERMINAL_SESSIONS': ('1', 'Default max terminal sessions per user'),
            'IDLE_SLEEP_SECONDS': ('5', 'Worker poll interval in seconds'),
            'MAX_JOBS_PER_HOUR': ('10', 'Max job submissions per user per hour'),
            'MAX_TERMINAL_SESSION_SECONDS': ('3600', 'Global max terminal session duration'),
            'TERMINAL_IDLE_TIMEOUT_SECONDS': ('300', 'Global terminal idle timeout'),
        }
        for key, (value, desc) in default_settings.items():
            if not s.get(AdminSetting, key):
                s.add(AdminSetting(key=key, value=value, description=desc))

        s.commit()
        click.echo('Database seeded with default devices and admin user (admin/admin).')

    @app.cli.command('run-worker')
    @click.option('--device', required=True, help='Device name (centurion or pdp11)')
    @click.option('--poll-interval', type=int, default=5, help='Seconds between polls')
    def run_worker(device, poll_interval):
        """
        Launch a job worker for the specified device.
        The worker polls for queued jobs, claims them atomically,
        and executes them over RS-232 (or PTY in simulation mode).
        """
        import subprocess
        worker_script = os.path.join(os.path.dirname(__file__), 'worker.py')
        click.echo(f'Starting worker for {device} (poll interval: {poll_interval}s)')
        subprocess.run(
            ['python3', worker_script, '--device', device, '--poll-interval', str(poll_interval)],
            cwd=os.path.dirname(__file__),
        )

    @app.cli.command('simulation-worker')
    @click.option('--device', required=True, help='Device name (centurion or pdp11)')
    def simulation_worker(device):
        """
        Launch a PTY-based simulation worker for testing without hardware.
        Creates a pseudo-terminal that mimics a vintage machine, then runs
        the job worker against it.
        """
        click.echo(f'Simulation worker for {device} starting...')
        click.echo('(PTY simulation engine not yet implemented — '
                    'use "flask run-worker --device {device}" with real serial hardware)')

    @app.cli.command('simulation-terminal')
    @click.option('--device', required=True, help='Device name (centurion or pdp11)')
    def simulation_terminal(device):
        """
        Launch a PTY-based interactive terminal simulation for testing without hardware.
        """
        click.echo(f'Simulation terminal for {device} starting...')
        click.echo('(PTY simulation engine not yet implemented)')
