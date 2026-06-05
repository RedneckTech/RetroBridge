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
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);

    term.open(document.getElementById('terminal-container'));
    fitAddon.fit();

    socket = io('/terminal');

    socket.on('connect', function () {
        updateStatus(true, 'Connected to server');
    });

    socket.on('disconnect', function () {
        connected = false;
        updateStatus(false, 'Disconnected');
        document.getElementById('connect-btn').disabled = false;
        document.getElementById('disconnect-btn').disabled = true;
    });

    socket.on('session_granted', function (data) {
        connected = true;
        sessionId = data.session_id;
        updateStatus(true, 'Connected to ' + data.device_name + ' (' + data.port_label + ')');
        term.writeln('=== Session established on ' + data.device_name + ' ===');
        term.writeln('Port: ' + data.port_label);
        term.writeln('');
        document.getElementById('connect-btn').disabled = true;
        document.getElementById('disconnect-btn').disabled = false;
    });

    socket.on('session_denied', function (data) {
        updateStatus(false, 'Denied: ' + data.reason);
        alert('Session denied: ' + data.reason);
    });

    socket.on('terminal_output', function (data) {
        if (term && data.data) {
            term.write(data.data);
        }
    });

    socket.on('session_closed', function (data) {
        connected = false;
        updateStatus(false, 'Session closed: ' + (data.reason || 'unknown'));
        term.writeln('');
        term.writeln('=== Session closed: ' + (data.reason || 'unknown') + ' ===');
        document.getElementById('connect-btn').disabled = false;
        document.getElementById('disconnect-btn').disabled = true;
        sessionId = null;
    });

    socket.on('heartbeat_ack', function () {
        // Heartbeat acknowledged
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

    // Heartbeat keep-alive
    setInterval(function () {
        if (connected && socket) {
            socket.emit('heartbeat', {});
        }
    }, 30000);

    // Connect button
    document.getElementById('connect-btn').addEventListener('click', function () {
        socket.emit('request_session', { device_id: deviceId });
    });

    // Disconnect button
    document.getElementById('disconnect-btn').addEventListener('click', function () {
        if (socket) {
            socket.disconnect();
        }
    });

    window.addEventListener('resize', function () {
        if (fitAddon && term) {
            try {
                fitAddon.fit();
            } catch (e) {
                // Ignore resize errors
            }
        }
    });
}

function updateStatus(connected, text) {
    const dot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    if (dot) {
        dot.className = 'dot ' + (connected ? 'connected' : 'disconnected');
    }
    if (statusText) {
        statusText.textContent = text;
    }
}
