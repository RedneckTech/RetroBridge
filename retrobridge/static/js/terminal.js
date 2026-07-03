// RetroBridge Terminal JavaScript
// Handles xterm.js initialization and WebSocket communication via Flask-SocketIO

const COLOR_SCHEMES = {
    dark:   { background: '#0a0a0a', foreground: '#33ff33', cursor: '#33ff33', selectionBackground: '#33ff3366' },
    amber:  { background: '#0a0a0a', foreground: '#ffb000', cursor: '#ffb000', selectionBackground: '#ffb00066' },
    light:  { background: '#f5f5f5', foreground: '#1a1a1a', cursor: '#1a1a1a', selectionBackground: '#1a1a1a33' },
    cyan:   { background: '#0a0a0a', foreground: '#00ffff', cursor: '#00ffff', selectionBackground: '#00ffff66' },
};

let term;
let socket;
let fitAddon;
let sessionId = null;
let connected = false;
let durationTimer = null;
let connectedAt = null;

function initTerminal(deviceId, prefs) {
    prefs = prefs || {};
    const scheme = COLOR_SCHEMES[prefs.colorScheme] || COLOR_SCHEMES.dark;

    term = new Terminal({
        cursorBlink: true,
        fontSize: prefs.fontSize || 14,
        fontFamily: "'Courier New', monospace",
        theme: scheme,
        cols: 80,
        rows: 24,
        allowProposedApi: true,
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);

    term.open(document.getElementById('terminal-container'));
    fitAddon.fit();

    socket = io('/terminal');

    socket.on('connect', function () {
        updateStatus(true, 'Connecting...');
        setBtnDisabled('connect-btn', true);
        socket.emit('request_session', { device_id: deviceId });
    });

    socket.on('disconnect', function () {
        connected = false;
        stopDurationTimer();
        updateStatus(false, 'Disconnected');
        setBtnDisabled('connect-btn', false);
        setBtnDisabled('disconnect-btn', true);
    });

    socket.on('session_granted', function (data) {
        connected = true;
        connectedAt = Date.now();
        sessionId = data.session_id;
        updateStatus(true, 'Connected');
        document.getElementById('stat-port').textContent = data.port_label || '\u2014';
        document.getElementById('stat-baud').textContent = data.baud || '\u2014';
        term.writeln('=== Session established on ' + data.device_name + ' ===');
        term.writeln('Port: ' + data.port_label + '  Baud: ' + data.baud);
        term.writeln('');
        setBtnDisabled('connect-btn', true);
        setBtnDisabled('disconnect-btn', false);
        startDurationTimer();
    });

    socket.on('session_denied', function (data) {
        updateStatus(false, 'Denied: ' + data.reason);
        alert('Session denied: ' + data.reason);
        setBtnDisabled('connect-btn', false);
    });

    socket.on('terminal_output', function (data) {
        if (term && data.data) {
            term.write(data.data);
        }
    });

    socket.on('session_closed', function (data) {
        connected = false;
        stopDurationTimer();
        updateStatus(false, 'Closed: ' + (data.reason || 'unknown'));
        term.writeln('');
        term.writeln('=== Session closed: ' + (data.reason || 'unknown') + ' ===');
        setBtnDisabled('connect-btn', false);
        setBtnDisabled('disconnect-btn', true);
        sessionId = null;
    });

    socket.on('heartbeat_ack', function (data) {
        if (data && data.bytes_sent !== undefined) {
            document.getElementById('stat-tx').textContent = formatBytes(data.bytes_sent);
            document.getElementById('stat-rx').textContent = formatBytes(data.bytes_received);
        }
    });

    term.onData(function (data) {
        if (connected && socket) {
            socket.emit('terminal_input', { data: data });
        }
    });

    term.onResize(function (size) {
        if (connected && socket) {
            socket.emit('terminal_resize', { cols: size.cols, rows: size.rows });
        }
    });

    document.getElementById('terminal-container').addEventListener('paste', function (e) {
        if (!connected) return;
        var text = (e.clipboardData || window.clipboardData).getData('text');
        if (text && socket) {
            socket.emit('terminal_input', { data: text });
            e.preventDefault();
        }
    });

    // Heartbeat for stats and keep-alive
    setInterval(function () {
        if (connected && socket) {
            socket.emit('heartbeat', {});
        }
    }, 10000);

    // Connect button
    var cBtn = document.getElementById('connect-btn');
    if (cBtn) {
        cBtn.addEventListener('click', function () {
            socket.emit('request_session', { device_id: deviceId });
            this.disabled = true;
            updateStatus(true, 'Connecting...');
        });
    }

    // Disconnect button
    var dBtn = document.getElementById('disconnect-btn');
    if (dBtn) {
        dBtn.addEventListener('click', function () {
            if (socket && connected) {
                socket.emit('client_disconnect');
                connected = false;
                stopDurationTimer();
                updateStatus(false, 'Disconnected');
                setBtnDisabled('connect-btn', false);
                setBtnDisabled('disconnect-btn', true);
                sessionId = null;
            }
        });
    }

    window.addEventListener('resize', function () {
        if (fitAddon && term) {
            try {
                fitAddon.fit();
            } catch (e) {}
        }
    });
}

function updateStatus(connected, text) {
    var dot = document.getElementById('status-dot');
    var statusText = document.getElementById('status-text');
    if (dot) {
        dot.className = 'dot ' + (connected ? 'connected' : 'disconnected');
    }
    if (statusText) {
        statusText.textContent = text;
    }
}

function startDurationTimer() {
    stopDurationTimer();
    connectedAt = Date.now();
    durationTimer = setInterval(function () {
        var elapsed = Math.floor((Date.now() - connectedAt) / 1000);
        var h = Math.floor(elapsed / 3600);
        var m = Math.floor((elapsed % 3600) / 60);
        var s = elapsed % 60;
        document.getElementById('stat-duration').textContent =
            String(h).padStart(2, '0') + ':' +
            String(m).padStart(2, '0') + ':' +
            String(s).padStart(2, '0');
    }, 1000);
}

function stopDurationTimer() {
    if (durationTimer) {
        clearInterval(durationTimer);
        durationTimer = null;
    }
}

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}

function setBtnDisabled(id, disabled) {
    var btn = document.getElementById(id);
    if (btn) btn.disabled = disabled;
}
