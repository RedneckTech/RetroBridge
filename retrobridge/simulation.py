"""
PTY Simulation for Development Testing
======================================
Simulates vintage minicomputers via pseudo-terminals, enabling end-to-end
testing of the job processing and interactive terminal pipelines without
real RS-232 hardware.

Job Simulation:
  - Mimics a vintage system listening for XMODEM transfers
  - Responds with prompts, echoes commands, receives XMODEM blocks
  - Provides simulated program output

Terminal Simulation:
  - Mimics a multi-user OS with login sequence and command shell
  - Banner, login prompt, password prompt, command prompt
  - Responds to basic commands (DIR, HELP, RUN, STATUS)
  - Supports rudimentary line editing (backspace)
"""

import os
import pty
import select
import termios
import threading
import time

# Command responses for simulated terminal sessions
TERMINAL_COMMANDS = {
    'centurion': {
        'banner': (
            '\r\n'
            'CENTURION CPU-6  MULTI-USER OPERATING SYSTEM v4.2\r\n'
            'Copyright (C) 1979 Centurion Computer Corporation\r\n'
            'All Rights Reserved\r\n'
            '\r\n'
        ),
        'prompt': 'A> ',
        'commands': {
            'dir': (
                '\r\n'
                '  Volume in drive A: SYSTEM\r\n'
                '  Directory of A:\\\r\n'
                '\r\n'
                '  BOOT     SYS     4096   01-15-82  08:00\r\n'
                '  KERNEL   SYS    16384   01-15-82  08:00\r\n'
                '  COMMAND  COM     8192   01-15-82  08:00\r\n'
                '  UTILS    COM     4096   01-15-82  08:00\r\n'
                '  BASIC    COM    12288   01-15-82  08:00\r\n'
                '  FORMAT   COM     2048   01-15-82  08:00\r\n'
                '        6 File(s)    47104 bytes\r\n'
                '\r\n'
            ),
            'help': (
                '\r\n'
                '  Available Commands:\r\n'
                '    DIR    - List directory\r\n'
                '    HELP   - Show this message\r\n'
                '    RUN    - Execute a program\r\n'
                '    STATUS - Show system status\r\n'
                '    LOGOUT - End session\r\n'
                '    TYPE   - Display file contents\r\n'
                '\r\n'
            ),
            'run': (
                '\r\n'
                '  RUN > No program in memory.\r\n'
                '  Use UPLOAD to transfer a program first.\r\n'
                '\r\n'
            ),
            'status': (
                '\r\n'
                '  System Status:\r\n'
                '  CPU:     Centurion CPU-6 @ 4 MHz\r\n'
                '  Memory:  64 KB RAM\r\n'
                '  Storage: 10 MB Winchester Drive\r\n'
                '  Uptime:  342 days 14:22:08\r\n'
                '  Users:   2 active\r\n'
                '\r\n'
            ),
            'logout': (
                '\r\n'
                '  Session terminated. Goodbye.\r\n'
                '\r\n'
            ),
            'type': (
                '\r\n'
                '  File not found.\r\n'
                '\r\n'
            ),
        },
    },
    'pdp11': {
        'banner': (
            '\r\n'
            'DEC PDP-11/44  RSX-11M  V4.3\r\n'
            'Copyright (C) 1980 Digital Equipment Corporation\r\n'
            '\r\n'
        ),
        'prompt': '> ',
        'commands': {
            'dir': (
                '\r\n'
                '  Directory DU0:[1,2]\r\n'
                '  22-JAN-1983 12:00\r\n'
                '\r\n'
                '  BOOT  .SYS;1     32.   22-JAN-83\r\n'
                '  RSX   .TSK;1    256.   22-JAN-83\r\n'
                '  PIP   .TSK;1     48.   22-JAN-83\r\n'
                '  TKB   .TSK;1    128.   22-JAN-83\r\n'
                '  MAC   .TSK;1     96.   22-JAN-83\r\n'
                '  Total of 560./1500. blocks in 5. files\r\n'
                '\r\n'
            ),
            'help': (
                '\r\n'
                '  Available Commands:\r\n'
                '    DIR    - Directory listing\r\n'
                '    HELP   - Display help\r\n'
                '    RUN    - Execute program\r\n'
                '    STATUS - System status\r\n'
                '    LOGOUT - Log off\r\n'
                '\r\n'
            ),
            'run': (
                '\r\n'
                '  RUN > No task loaded.\r\n'
                '  Install a task with TKB first.\r\n'
                '\r\n'
            ),
            'status': (
                '\r\n'
                '  System Status:\r\n'
                '  CPU:     PDP-11/44\r\n'
                '  Memory:  256 KW (512 KB)\r\n'
                '  Storage: RL02 Disk (10 MB)\r\n'
                '  Uptime:  128 days 06:45:12\r\n'
                '  Tasks:   4 active\r\n'
                '\r\n'
            ),
            'logout': (
                '\r\n'
                '  BYE\r\n'
                '\r\n'
            ),
            'type': (
                '\r\n'
                '  ?FILE NOT FOUND\r\n'
                '\r\n'
            ),
        },
    },
}


def create_terminal_simulation(device_name='centurion'):
    """
    Create a PTY-based interactive terminal simulation.

    Returns a dict with:
      - master_fd: file descriptor for the master PTY (for worker/bridge to use)
      - slave_name: path to the slave PTY
      - thread: the simulation thread
      - stop_event: threading.Event to signal shutdown
    """
    device_config = TERMINAL_COMMANDS.get(device_name, TERMINAL_COMMANDS['centurion'])

    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    # Disable echo on the slave so prompts don't feedback-loop
    attrs = termios.tcgetattr(slave_fd)
    attrs[3] = attrs[3] & ~termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

    stop_event = threading.Event()

    def simulate():
        try:
            while not stop_event.is_set():
                # Show banner and login prompt
                os.write(master_fd, device_config['banner'].encode())
                time.sleep(0.3)
                os.write(master_fd, b'USERNAME: ')

                buffer = b''
                cmd = ''
                login_complete = False

                while not stop_event.is_set() and not login_complete:
                    rfds, _, _ = select.select([master_fd], [], [], 0.5)
                    if not rfds:
                        continue

                    try:
                        chunk = os.read(master_fd, 1024)
                    except OSError:
                        return

                    if not chunk:
                        return

                    buffer += chunk
                    os.write(master_fd, chunk)

                    if b'\r' in chunk or b'\n' in chunk:
                        os.write(master_fd, b'\r\nPASSWORD: ')
                        buffer = b''
                        while not stop_event.is_set():
                            rfds, _, _ = select.select([master_fd], [], [], 0.5)
                            if rfds:
                                pw_chunk = os.read(master_fd, 1024)
                                os.write(master_fd, b'*' * len(pw_chunk))
                                if b'\r' in pw_chunk or b'\n' in pw_chunk:
                                    break
                        os.write(master_fd, b'\r\n')
                        time.sleep(0.3)
                        os.write(master_fd, f'\r\nWelcome to {device_name.upper()}!\r\n\r\n'.encode())
                        os.write(master_fd, device_config['prompt'].encode())
                        login_complete = True

                # Command shell loop
                buffer = b''
                while not stop_event.is_set() and login_complete:
                    rfds, _, _ = select.select([master_fd], [], [], 0.5)
                    if not rfds:
                        continue

                    try:
                        chunk = os.read(master_fd, 1024)
                    except OSError:
                        return

                    if not chunk:
                        return

                    for byte in chunk:
                        cb = bytes([byte])
                        if cb == b'\r' or cb == b'\n':
                            os.write(master_fd, b'\r\n')
                            cmd = buffer.decode('ascii', errors='replace').strip().lower()
                            buffer = b''

                            if cmd:
                                response = device_config['commands'].get(
                                    cmd, f'\r\n  ?UNKNOWN COMMAND: {cmd.upper()}\r\n'
                                )
                                os.write(master_fd, response.encode())

                            if cmd == 'logout':
                                time.sleep(1)
                                os.write(master_fd, b'\r\nDisconnected.\r\n')
                                login_complete = False
                                break

                            os.write(master_fd, device_config['prompt'].encode())
                        elif cb == b'\x7f' or cb == b'\x08':
                            if buffer:
                                buffer = buffer[:-1]
                                os.write(master_fd, b'\x08 \x08')
                        else:
                            buffer += cb
                            os.write(master_fd, cb)
        except Exception:
            pass
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                os.close(slave_fd)
            except OSError:
                pass

    thread = threading.Thread(target=simulate, daemon=True)
    thread.start()

    return {
        'master_fd': master_fd,
        'slave_name': slave_name,
        'thread': thread,
        'stop_event': stop_event,
    }


def create_job_simulation(device_name='centurion'):
    """
    Create a PTY-based job processing simulation.

    The simulation mimics a vintage machine that:
      1. Shows a READY prompt after connection
      2. Echoes pre-transfer commands
      3. Sends XMODEM 'C' character for CRC transfer initiation
      4. Receives XMODEM blocks
      5. Outputs simulated program results
      6. Exits after idle timeout

    Returns same dict shape as create_terminal_simulation.
    """
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    # Disable echo on the slave
    attrs = termios.tcgetattr(slave_fd)
    attrs[3] = attrs[3] & ~termios.ECHO
    termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)

    stop_event = threading.Event()

    def simulate():
        try:
            time.sleep(0.3)
            os.write(master_fd, b'\r\nCENTURION CPU-6 BOOT LOADER v2.1\r\n')
            os.write(master_fd, b'READY\r\n')

            start_time = time.time()

            while not stop_event.is_set():
                if time.time() - start_time > 60:
                    os.write(master_fd, b'\r\nTIMEOUT - No transfer initiated\r\n')
                    break

                # Wait for activity
                rfds, _, _ = select.select([master_fd], [], [], 0.5)
                if not rfds:
                    continue

                try:
                    chunk = os.read(master_fd, 1024)
                except OSError:
                    break

                if not chunk:
                    continue

                # Check for CR to initiate XMODEM receive
                if b'\r' in chunk or b'\n' in chunk:
                    # XMODEM receive loop: send C, wait for blocks, ACK everything
                    first = True
                    while not stop_event.is_set():
                        if first:
                            os.write(master_fd, b'C')
                            first = False

                        rfds, _, _ = select.select([master_fd], [], [], 3.0)
                        if not rfds:
                            continue

                        try:
                            chunk = os.read(master_fd, 1024)
                        except OSError:
                            return
                        if not chunk:
                            continue

                        b0 = chunk[0]
                        if b0 == 0x01:  # SOH
                            os.write(master_fd, b'\x06')
                        elif b0 == 0x04:  # EOT
                            os.write(master_fd, b'\x06')
                            os.write(master_fd, b'\r\nPROGRAM LOADED. EXECUTING...\r\n'.encode())
                            time.sleep(0.5)
                            os.write(master_fd, b'Hello, World!\r\n'.encode())
                            os.write(master_fd, b'Execution complete. Return code: 0\r\n'.encode())
                            time.sleep(1)
                            # Go back to idle for next job
                            os.write(master_fd, b'\r\nREADY\r\n'.encode())
                            start_time = time.time()
                            break  # Exit XMODEM loop, back to idle
                    break
        except Exception:
            pass
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass
            try:
                os.close(slave_fd)
            except OSError:
                pass

    thread = threading.Thread(target=simulate, daemon=True)
    thread.start()

    return {
        'master_fd': master_fd,
        'slave_name': slave_name,
        'thread': thread,
        'stop_event': stop_event,
    }
