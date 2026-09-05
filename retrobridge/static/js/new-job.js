// RetroBridge new-job page JavaScript
(function() {
    'use strict';

    const page = document.getElementById('new-job-page');
    if (!page) return;

    const ALLOWED_EXTS = ['bin','hex','obj','asm','s','txt'];
    const deviceStatsEl = document.getElementById('device-cards');
    const deviceStats = JSON.parse(deviceStatsEl.dataset.devices || '[]');
    const maxUploadBytes = parseInt(deviceStatsEl.dataset.maxUploadBytes || '0', 10);

    const deviceCards = document.querySelectorAll('.device-card');
    const deviceInput = document.getElementById('device-id-input');
    const deviceInfo = document.getElementById('device-info');
    const dropZone = document.getElementById('drop-zone');
    const fileInput = document.getElementById('file-input');
    const uploadForm = document.getElementById('upload-form');
    const prioritySlider = document.getElementById('priority-slider');
    const priorityVal = document.getElementById('priority-val');

    function selectDevice(deviceId) {
        deviceCards.forEach(function(c) { c.classList.remove('selected'); });
        const card = document.querySelector('.device-card[data-device-id="' + deviceId + '"]');
        if (card) card.classList.add('selected');
        deviceInput.value = deviceId;

        deviceInfo.classList.remove('d-none');

        const ds = deviceStats.find(function(d) { return d.id === deviceId; });
        if (!ds) return;

        const jobPort = (ds.ports || []).find(function(p) { return p.purpose === 'job_queue'; });
        document.getElementById('info-protocol').textContent = (jobPort && jobPort.transfer_protocol) || 'xmodem';
        document.getElementById('info-newline').textContent = (jobPort && jobPort.newline_mode) || 'crlf';
        document.getElementById('info-queue-pos').textContent = ds.queue_count + ' ahead of you';

        const preCmds = (jobPort && jobPort.pre_cmds) || '';
        const postCmds = (jobPort && jobPort.post_cmds) || '';

        const preDiv = document.getElementById('info-pre-cmds');
        const postDiv = document.getElementById('info-post-cmds');

        if (preCmds) {
            preDiv.classList.remove('d-none');
            var prettyPre = preCmds;
            try { prettyPre = JSON.stringify(JSON.parse(preCmds), null, 2); } catch(e) {}
            document.getElementById('info-pre-text').textContent = prettyPre;
        } else {
            preDiv.classList.add('d-none');
        }

        if (postCmds) {
            postDiv.classList.remove('d-none');
            var prettyPost = postCmds;
            try { prettyPost = JSON.stringify(JSON.parse(postCmds), null, 2); } catch(e) {}
            document.getElementById('info-post-text').textContent = prettyPost;
        } else {
            postDiv.classList.add('d-none');
        }
    }

    deviceCards.forEach(function(card) {
        card.addEventListener('click', function() {
            selectDevice(parseInt(this.dataset.deviceId, 10));
        });
    });

    // ── Drag & drop ─────────────────────────────────────────────────────────
    ['dragenter','dragover'].forEach(function(evt) {
        dropZone.addEventListener(evt, function(e) {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
    });
    ['dragleave','drop'].forEach(function(evt) {
        dropZone.addEventListener(evt, function(e) {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
        });
    });

    dropZone.addEventListener('drop', function(e) {
        const files = e.dataTransfer.files;
        if (files.length) setFile(files[0]);
    });

    dropZone.addEventListener('click', function() {
        fileInput.click();
    });

    fileInput.addEventListener('change', function() {
        if (this.files.length) setFile(this.files[0]);
    });

    function setFile(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (ALLOWED_EXTS.indexOf(ext) === -1) {
            alert('Invalid file type: .' + ext + '\nAllowed: .bin, .hex, .obj, .asm, .s, .txt');
            return;
        }
        if (maxUploadBytes && file.size > maxUploadBytes) {
            alert('File is too large (' + (file.size / 1024 / 1024).toFixed(1) +
                  ' MB). Maximum is ' + (maxUploadBytes / 1024 / 1024) + ' MB.');
            return;
        }
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;

        document.getElementById('drop-placeholder').classList.add('d-none');
        document.getElementById('file-selected').classList.remove('d-none');
        dropZone.classList.add('has-file');
        document.getElementById('file-name').textContent = file.name;
        document.getElementById('file-size').textContent = (file.size / 1024).toFixed(1) + ' KB';
    }

    const removeLink = dropZone.querySelector('#file-selected a');
    if (removeLink) {
        removeLink.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            fileInput.value = '';
            document.getElementById('drop-placeholder').classList.remove('d-none');
            document.getElementById('file-selected').classList.add('d-none');
            dropZone.classList.remove('has-file');
        });
    }

    // ── Priority slider ─────────────────────────────────────────────────────
    if (prioritySlider) {
        prioritySlider.addEventListener('input', function() {
            priorityVal.textContent = this.value;
        });
    }

    // ── Last job re-submit ──────────────────────────────────────────────────
    const reSubmitBtn = document.getElementById('re-submit-btn');
    if (reSubmitBtn) {
        reSubmitBtn.addEventListener('click', function() {
            const deviceId = parseInt(this.dataset.deviceId, 10);
            selectDevice(deviceId);
        });
    }

    // ── Form validation before submit ───────────────────────────────────────
    uploadForm.addEventListener('submit', function(e) {
        if (!deviceInput.value) {
            e.preventDefault();
            alert('Please select a target device.');
            return;
        }
        if (!fileInput.files.length) {
            e.preventDefault();
            alert('Please select a file to upload.');
            return;
        }
    });

    // ── Restore previously selected device on load ──────────────────────────
    if (deviceInput.value) {
        selectDevice(parseInt(deviceInput.value, 10));
    }
})();
