// RetroBridge dashboard JavaScript
(function() {
    'use strict';

    const dashboard = document.getElementById('dashboard');
    if (!dashboard) return;

    // ── Poll active sessions ────────────────────────────────────────────────
    function pollSessions() {
        fetch('/api/my-sessions').then(function(r) { return r.json(); }).then(function(data) {
            const container = document.getElementById('active-sessions-container');
            if (!container) return;
            const sessions = data.sessions || [];
            if (!sessions.length) {
                container.innerHTML = '';
                return;
            }
            container.innerHTML = '';
            sessions.forEach(function(s) {
                const min = Math.floor(s.elapsed_seconds / 60);
                const sec = s.elapsed_seconds % 60;

                const indicator = document.createElement('span');
                indicator.className = 'active-indicator';

                const strong = document.createElement('strong');
                strong.textContent = 'Active terminal: ';

                const text = document.createTextNode(
                    (s.device_name || 'N/A') + ' \u2014 ' + (s.port_label || 'N/A') + ' '
                );

                const small = document.createElement('small');
                small.className = 'text-muted';
                small.textContent = 'for ' + min + 'm ' + sec + 's';

                const leftDiv = document.createElement('div');
                leftDiv.appendChild(indicator);
                leftDiv.appendChild(strong);
                leftDiv.appendChild(text);
                leftDiv.appendChild(small);

                const resumeLink = document.createElement('a');
                resumeLink.href = '/terminal/' + s.device_id;
                resumeLink.className = 'btn btn-sm btn-outline-primary';
                resumeLink.textContent = 'Resume';

                const alertDiv = document.createElement('div');
                alertDiv.className = 'alert alert-info d-flex justify-content-between align-items-center py-2 px-3 mb-1';
                alertDiv.appendChild(leftDiv);
                alertDiv.appendChild(resumeLink);

                container.appendChild(alertDiv);
            });
        });
    }
    pollSessions();
    setInterval(pollSessions, 10000);

    // ── Poll job statuses ───────────────────────────────────────────────────
    const cells = document.querySelectorAll('.job-status-cell[data-status="queued"], .job-status-cell[data-status="running"]');
    if (!cells.length) return;
    let activeIds = Array.from(cells).map(function(c) { return c.dataset.jobId; });

    const statusMap = {
        queued: ['bg-warning text-dark', 'Queued'],
        running: ['bg-info', 'Running'],
        completed: ['bg-success', 'Completed'],
        failed: ['bg-danger', 'Failed'],
        canceled: ['bg-secondary', 'Canceled']
    };

    function poll() {
        if (!activeIds.length) return;
        fetch('/api/jobs?per_page=50').then(function(r) { return r.json(); }).then(function(data) {
            if (!data.jobs) return;
            let updated = false;
            data.jobs.forEach(function(j) {
                if (activeIds.indexOf(String(j.id)) === -1) return;
                const cell = document.querySelector('.job-status-cell[data-job-id="' + j.id + '"]');
                if (!cell) return;
                const badge = cell.querySelector('.badge');
                if (!badge) return;
                const s = statusMap[j.status] || ['bg-secondary', j.status];
                badge.className = 'badge ' + s[0];
                badge.textContent = s[1];
                cell.dataset.status = j.status;
                if (j.status !== 'queued' && j.status !== 'running') {
                    activeIds = activeIds.filter(function(id) { return String(id) !== String(j.id); });
                    updated = true;
                }
            });
            if (updated) location.reload();
            if (activeIds.length) setTimeout(poll, 5000);
        });
    }
    if (activeIds.length) setTimeout(poll, 5000);
})();
