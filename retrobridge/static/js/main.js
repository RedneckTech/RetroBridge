// RetroBridge main JavaScript

document.addEventListener('DOMContentLoaded', function () {
    // Auto-dismiss flash messages after 5 seconds
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function (alert) {
        setTimeout(function () {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    var jobEl = document.getElementById('job-detail');
    if (jobEl) {
        initJobSSE(jobEl.dataset.jobId, jobEl.dataset.jobStatus);
    }

    var dashboardEl = document.getElementById('dashboard');
    if (dashboardEl) {
        initDashboardSSE();
    }

    // Generic confirmation handler for buttons and forms
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        var message = el.dataset.confirm;
        if (!message) return;
        el.addEventListener('click', function (e) {
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });

    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
        var message = form.dataset.confirm;
        if (!message) return;
        form.addEventListener('submit', function (e) {
            if (!confirm(message)) {
                e.preventDefault();
                return false;
            }
        });
    });
});

function initJobSSE(jobId, initialStatus) {
    var terminalStates = ['completed', 'failed', 'canceled'];
    if (terminalStates.indexOf(initialStatus) !== -1) {
        return;
    }

    var evtSource = new EventSource('/api/jobs/' + jobId + '/events');

    evtSource.addEventListener('status', function (e) {
        var data = JSON.parse(e.data);
        updateJobStatusBadge(data.status);

        var el = document.getElementById('job-started-at');
        if (el && data.started_at) { el.textContent = data.started_at; }

        el = document.getElementById('job-finished-at');
        if (el && data.finished_at) { el.textContent = data.finished_at; }

        el = document.getElementById('job-runtime');
        if (el && data.runtime_seconds != null) { el.textContent = data.runtime_seconds + 's'; }

        if (data.output_path) {
            var dlBtn = document.getElementById('job-download-btn');
            if (dlBtn) { dlBtn.classList.remove('d-none'); }
        }

        var cancelBtn = document.getElementById('job-cancel-btn');
        if (cancelBtn && data.status !== 'queued') {
            cancelBtn.remove();
        }
    }, false);

    evtSource.addEventListener('output', function (e) {
        var data = JSON.parse(e.data);
        var logContainer = document.getElementById('job-output-log');
        if (!logContainer) {
            var viewer = document.querySelector('.log-viewer code');
            if (viewer) {
                viewer.textContent += data.text;
                var pre = viewer.parentElement;
                pre.scrollTop = pre.scrollHeight;
            }
        }
    }, false);

    evtSource.addEventListener('done', function (e) {
        var data = JSON.parse(e.data);
        updateJobStatusBadge(data.status);
        evtSource.close();
        setTimeout(function () { location.reload(); }, 500);
    }, false);

    evtSource.onerror = function () {
        evtSource.close();
    };
}

function updateJobStatusBadge(status) {
    var badge = document.getElementById('job-status-badge');
    if (!badge) return;

    badge.classList.remove('bg-warning', 'text-dark', 'bg-info', 'bg-success', 'bg-danger', 'bg-secondary');

    var labels = {
        'queued': { css: 'bg-warning text-dark', text: 'Queued' },
        'running': { css: 'bg-info', text: 'Running' },
        'completed': { css: 'bg-success', text: 'Completed' },
        'failed': { css: 'bg-danger', text: 'Failed' },
        'canceled': { css: 'bg-secondary', text: 'Canceled' },
    };

    var s = labels[status] || { css: 'bg-secondary', text: status };
    badge.classList.add.apply(badge.classList, s.css.split(' '));
    badge.textContent = s.text;
}

function initDashboardSSE() {
    var rows = document.querySelectorAll('.job-status-cell');
    if (!rows.length) return;

    var activeJobIds = [];
    rows.forEach(function (cell) {
        if (cell.dataset.status === 'queued' || cell.dataset.status === 'running') {
            activeJobIds.push(parseInt(cell.dataset.jobId));
        }
    });
    if (!activeJobIds.length) return;

    var poll = function () {
        if (!activeJobIds.length) return;
        fetch('/api/jobs?per_page=50').then(function (r) {
            return r.json();
        }).then(function (data) {
            var jobs = data.jobs;
            jobs.forEach(function (j) {
                var cell = document.querySelector('.job-status-cell[data-job-id="' + j.id + '"]');
                if (cell) {
                    updateJobStatusBadge(j.status);
                    if (j.status === 'completed' || j.status === 'failed' || j.status === 'canceled') {
                        activeJobIds = activeJobIds.filter(function (id) { return id !== j.id; });
                    }
                }
            });
            if (activeJobIds.length) {
                setTimeout(poll, 5000);
            }
        });
    };
    poll();
}
