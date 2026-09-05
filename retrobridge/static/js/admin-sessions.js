// RetroBridge admin sessions page JavaScript
(function() {
    'use strict';

    const page = document.getElementById('bulkDisconnectForm');
    if (!page) return;

    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.session-checkbox');
    const bulkBtn = document.getElementById('bulkDisconnectBtn');
    const bulkForm = document.getElementById('bulkDisconnectForm');
    const bulkContainer = document.getElementById('bulkSessionIds');
    const reasonFilter = document.querySelector('#reasonFilterForm select[name="reason"]');

    function toggleAll(checked) {
        checkboxes.forEach(function(cb) { cb.checked = checked; });
        updateBulkBtn();
    }

    function updateBulkBtn() {
        if (!bulkBtn) return;
        bulkBtn.disabled = document.querySelectorAll('.session-checkbox:checked').length === 0;
    }

    function bulkDisconnect() {
        const checked = document.querySelectorAll('.session-checkbox:checked');
        if (!bulkContainer || !bulkForm) return;
        bulkContainer.innerHTML = '';
        checked.forEach(function(cb) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'session_ids';
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
            bulkDisconnect();
        });
    }

    if (reasonFilter) {
        reasonFilter.addEventListener('change', function() {
            this.form.submit();
        });
    }

    document.querySelectorAll('.toggle-detail').forEach(function(btn) {
        btn.addEventListener('click', function() {
            const row = document.getElementById('detail-' + this.dataset.sessionId);
            if (row) row.style.display = row.style.display === 'none' ? 'table-row' : 'none';
        });
    });
})();
