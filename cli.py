import os
import time

import click
from flask.cli import AppGroup


def _human_size(bytes_val):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if bytes_val < 1024:
            return f'{bytes_val:.1f} {unit}'
        bytes_val /= 1024
    return f'{bytes_val:.1f} TB'


def _auto_backup(app):
    from retrobridge.backup import backup_database
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    backup_dir = app.config.get('BACKUP_DIR',
                                 os.path.join(os.path.dirname(__file__), 'backups'))
    backup_dir = os.path.abspath(backup_dir)
    try:
        path = backup_database(db_uri, backup_dir, compress=True, label='pre-init')
        click.echo(f'Auto-backup before init: {path}')
    except FileNotFoundError:
        pass


def register_cli_commands(app):
    db_cli = AppGroup('db')

    @db_cli.command('init')
    def init_db():
        from retrobridge.models import Base
        Base.metadata.create_all(bind=app.db_engine)
        click.echo('Database tables created.')

    @db_cli.command('backup')
    @click.option('--no-compress', is_flag=True, help='Skip gzip compression')
    @click.option('--label', default=None, help='Optional label embedded in filename')
    def db_backup(no_compress, label):
        from retrobridge.backup import backup_database, prune_backups, list_backups

        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        backup_dir = app.config.get('BACKUP_DIR', os.path.join(app.instance_path, '..', 'backups'))
        backup_dir = os.path.abspath(backup_dir)

        os.makedirs(backup_dir, exist_ok=True)
        path = backup_database(db_uri, backup_dir, compress=not no_compress, label=label)

        size = os.path.getsize(path)
        click.echo(f'Backup created: {path} ({_human_size(size)})')

        retention_days = app.config.get('BACKUP_RETENTION_DAYS', 30)
        retention_count = app.config.get('BACKUP_RETENTION_COUNT', 10)
        removed = prune_backups(backup_dir, retention_days, retention_count)
        for r in removed:
            click.echo(f'  Pruned old backup: {os.path.basename(r)}')

    @db_cli.command('restore')
    @click.argument('backup_path', type=click.Path(exists=True))
    @click.confirmation_option(prompt='This will OVERWRITE the current database. Continue?')
    def db_restore(backup_path):
        from retrobridge.backup import restore_database

        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
        path = restore_database(backup_path, db_uri)
        click.echo(f'Database restored from: {backup_path}')
        click.echo(f'Target database: {path}')

    @db_cli.command('list-backups')
    @click.option('--human-readable', '-h', is_flag=True, help='Show sizes in human-readable format')
    def db_list_backups(human_readable):
        from retrobridge.backup import list_backups

        backup_dir = app.config.get('BACKUP_DIR', os.path.join(app.instance_path, '..', 'backups'))
        backup_dir = os.path.abspath(backup_dir)

        backups = list_backups(backup_dir)
        if not backups:
            click.echo('No backups found.')
            return

        click.echo(f'{"Filename":<50} {"Size":>10}  {"Modified (UTC)":<20}')
        click.echo('-' * 82)
        for b in backups:
            size = _human_size(b['size_bytes']) if human_readable else str(b['size_bytes'])
            click.echo(f'{b["filename"]:<50} {size:>10}  {b["modified"].strftime("%Y-%m-%d %H:%M:%S"):<20}')
        click.echo(f'\n{len(backups)} backup(s) in {backup_dir}')

    app.cli.add_command(db_cli)

    @app.cli.command('init-db')
    def init_db_alias():
        _auto_backup(app)
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
            'MAX_UPLOAD_SIZE_BYTES': ('16777216', 'Maximum file upload size in bytes'),
            'DEFAULT_MAX_QUEUED_JOBS': ('3', 'Default max queued jobs per user'),
            'DEFAULT_MAX_TERMINAL_SESSIONS': ('1', 'Default max terminal sessions per user'),
            'MAX_JOBS_PER_HOUR': ('10', 'Max job submissions per user per hour'),
            'MAX_TERMINAL_SESSION_SECONDS': ('3600', 'Max terminal session duration in seconds'),
            'TERMINAL_IDLE_TIMEOUT_SECONDS': ('300', 'Terminal idle timeout in seconds'),
            'WORKER_POLL_SECONDS': ('5', 'Worker poll interval in seconds'),
            'REGISTRATION_OPEN': ('1', 'Whether new user registration is allowed'),
            'MAINTENANCE_MODE': ('0', 'Site-wide maintenance mode toggle'),
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
        Creates a pseudo-terminal that mimics a vintage machine, updates the
        device port to point to the PTY, and runs the job worker against it.
        """
        from retrobridge.simulation import create_job_simulation
        from retrobridge.models import Device, DevicePort

        click.echo(f'Creating PTY simulation for {device}...')
        sim = create_job_simulation(device)

        # Update the device's job_queue port dev_path to the PTY slave
        device_obj = app.db_session.query(Device).filter_by(name=device).first()
        if not device_obj:
            click.echo(f'Device "{device}" not found in database.')
            return

        port = (
            app.db_session.query(DevicePort)
            .filter_by(device_id=device_obj.id, purpose='job_queue')
            .first()
        )
        if not port:
            click.echo(f'No job_queue port found for device "{device}".')
            return

        old_path = port.dev_path
        port.dev_path = sim['slave_name']
        app.db_session.commit()
        click.echo(f'Port dev_path updated: {old_path} -> {sim["slave_name"]}')

        try:
            click.echo(f'Starting worker for {device}...')
            import subprocess
            worker_script = os.path.join(os.path.dirname(__file__), 'worker.py')
            subprocess.run(
                ['python3', worker_script, '--device', device, '--poll-interval', '3'],
                cwd=os.path.dirname(__file__),
            )
        finally:
            port.dev_path = old_path
            app.db_session.commit()
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)
            click.echo('Simulation shut down.')

    @app.cli.command('simulation-terminal')
    @click.option('--device', required=True, help='Device name (centurion or pdp11)')
    def simulation_terminal(device):
        """
        Launch a PTY-based interactive terminal simulation for testing.
        Creates a pseudo-terminal that mimics a vintage multi-user OS,
        updates the interactive port to point to the PTY, and keeps
        running until Ctrl+C.
        """
        from retrobridge.simulation import create_terminal_simulation
        from retrobridge.models import Device, DevicePort

        click.echo(f'Creating PTY terminal simulation for {device}...')
        sim = create_terminal_simulation(device)

        # Update the device's interactive port dev_path to the PTY slave
        device_obj = app.db_session.query(Device).filter_by(name=device).first()
        if not device_obj:
            click.echo(f'Device "{device}" not found in database.')
            return

        port = (
            app.db_session.query(DevicePort)
            .filter_by(device_id=device_obj.id, purpose='interactive')
            .first()
        )
        if not port:
            click.echo(f'No interactive port found for device "{device}".')
            return

        old_path = port.dev_path
        port.dev_path = sim['slave_name']
        app.db_session.commit()
        click.echo(f'Port dev_path updated: {old_path} -> {sim["slave_name"]}')
        click.echo(f'\nPTY terminal simulation running.')
        click.echo(f'Connect via the web UI at http://127.0.0.1:5000/terminal/{device_obj.id}')
        click.echo(f'Press Ctrl+C to stop.\n')

        try:
            while sim['thread'].is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            port.dev_path = old_path
            app.db_session.commit()
            sim['stop_event'].set()
            sim['thread'].join(timeout=2)
            click.echo('Simulation shut down.')
