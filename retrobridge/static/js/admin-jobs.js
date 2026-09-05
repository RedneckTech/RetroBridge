// RetroBridge admin jobs page JavaScript
(function() {
    'use strict';

    const page = document.getElementById('bulkCancelForm');
    if (!page) return;

    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.job-checkbox');
    const bulkBtn = document.getElementById('bulkCancelBtn');
    const bulkForm = document.getElementById('bulkCancelForm');
    const bulkContainer = document.getElementById('bulkJobIds');
    const deviceFilter = document.querySelector('#deviceFilterForm select[name="device_id"]');

    function toggleAll(checked) {
        checkboxes.forEach(function(cb) {
            if (cb.dataset.cancelable === 'true') {
                cb.checked = checked;
            }
        });
        updateBulkBtn();
    }

    function updateBulkBtn() {
        const checked = document.querySelectorAll('.job-checkbox:checked');
        if (bulkBtn) bulkBtn.disabled = checked.length === 0;
    }

    function bulkCancel() {
        const checked = document.querySelectorAll('.job-checkbox:checked');
        if (!bulkContainer || !bulkForm) return;
        bulkContainer.innerHTML = '';
        checked.forEach(function(cb) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'job_ids';
            input.value = cb.value;
            bulkContainer.appendChild(input);
        });
        bulkForm.submit();
    }

    if (selectAll) {
        selectAll.addEventListener('change', function() {
            toggleAll(this.checked);
        });
    }

    checkboxes.forEach(function(cb) {
        cb.addEventListener('change', updateBulkBtn);
    });

    if (bulkBtn) {
        bulkBtn.addEventListener('click', function(e) {
            e.preventDefault();
            bulkCancel();
        });
    }

    if (deviceFilter) {
        deviceFilter.addEventListener('change', function() {
            this.form.submit();
        });
    }

    // Inline detail toggle
    document.querySelectorAll('.toggle-detail').forEach(function(link) {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const jobId = this.dataset.jobId;
            const row = document.getElementById('detail-' + jobId);
            if (row) {
                row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
            }
        });
    });
})();
