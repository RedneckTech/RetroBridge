// RetroBridge registration page JavaScript
(function() {
    'use strict';

    const form = document.getElementById('registerForm');
    if (!form) return;

    const usernameField = document.getElementById('usernameField');
    const usernameError = document.getElementById('usernameError');
    const usernameOk = document.getElementById('usernameOk');
    const usernameChecking = document.getElementById('usernameChecking');
    const passwordField = document.getElementById('passwordField');
    const passwordError = document.getElementById('passwordError');
    const confirmField = document.getElementById('confirmPasswordField');
    const confirmError = document.getElementById('confirmError');
    const confirmOk = document.getElementById('confirmOk');
    const pwLen = document.getElementById('pwLen');
    const pwUpper = document.getElementById('pwUpper');
    const pwDigit = document.getElementById('pwDigit');

    // Username availability check (debounced)
    let checkTimer;
    if (usernameField) {
        usernameField.addEventListener('input', function() {
            clearTimeout(checkTimer);
            const val = this.value.trim();

            if (val.length < 2) {
                usernameError.textContent = '';
                usernameError.style.display = 'none';
                usernameOk.style.display = 'none';
                usernameChecking.style.display = 'none';
                this.classList.remove('is-invalid', 'is-valid');
                return;
            }

            usernameChecking.style.display = 'block';
            usernameOk.style.display = 'none';
            usernameError.style.display = 'none';
            this.classList.remove('is-invalid', 'is-valid');

            checkTimer = setTimeout(function() {
                fetch('/api/check-username?username=' + encodeURIComponent(val))
                    .then(function(r) { return r.json(); })
                    .then(function(data) {
                        usernameChecking.style.display = 'none';
                        if (data.available) {
                            usernameOk.style.display = 'block';
                            usernameError.style.display = 'none';
                            usernameField.classList.remove('is-invalid');
                            usernameField.classList.add('is-valid');
                        } else {
                            usernameError.textContent = 'This username is already taken.';
                            usernameError.style.display = 'block';
                            usernameOk.style.display = 'none';
                            usernameField.classList.remove('is-valid');
                            usernameField.classList.add('is-invalid');
                        }
                    });
            }, 400);
        });
    }

    // Password real-time validation
    function updatePasswordValidation() {
        const pw = passwordField.value;
        const lenOk = pw.length >= 8;
        const upperOk = /[A-Z]/.test(pw);
        const digitOk = /[0-9]/.test(pw);
        const allOk = lenOk && upperOk && digitOk;

        pwLen.innerHTML = lenOk ? '&#x2713;' : '&#x2717;';
        pwLen.className = lenOk ? 'text-success' : 'text-danger';
        pwUpper.innerHTML = upperOk ? '&#x2713;' : '&#x2717;';
        pwUpper.className = upperOk ? 'text-success' : 'text-danger';
        pwDigit.innerHTML = digitOk ? '&#x2713;' : '&#x2717;';
        pwDigit.className = digitOk ? 'text-success' : 'text-danger';

        if (pw.length === 0) {
            passwordError.style.display = 'none';
            passwordField.classList.remove('is-invalid', 'is-valid');
        } else if (allOk) {
            passwordError.style.display = 'none';
            passwordField.classList.remove('is-invalid');
            passwordField.classList.add('is-valid');
        } else {
            passwordField.classList.remove('is-valid');
            passwordField.classList.add('is-invalid');
        }
    }

    if (passwordField) {
        passwordField.addEventListener('input', updatePasswordValidation);
    }

    // Confirm password real-time check
    function updateConfirmValidation() {
        if (confirmField.value.length === 0) {
            confirmError.style.display = 'none';
            confirmOk.style.display = 'none';
            confirmField.classList.remove('is-invalid', 'is-valid');
        } else if (confirmField.value === passwordField.value) {
            confirmError.style.display = 'none';
            confirmOk.style.display = 'block';
            confirmField.classList.remove('is-invalid');
            confirmField.classList.add('is-valid');
        } else {
            confirmError.textContent = 'Passwords do not match.';
            confirmError.style.display = 'block';
            confirmOk.style.display = 'none';
            confirmField.classList.remove('is-valid');
            confirmField.classList.add('is-invalid');
        }
    }

    if (confirmField) {
        confirmField.addEventListener('input', updateConfirmValidation);
    }

    // Show server-side errors on page load (after a failed submit)
    function showServerError(field, errorEl) {
        if (errorEl && errorEl.textContent.trim()) {
            field.classList.add('is-invalid');
            errorEl.style.display = 'block';
        }
    }
    if (usernameField) showServerError(usernameField, usernameError);
    if (passwordField) showServerError(passwordField, passwordError);
    if (confirmField) showServerError(confirmField, confirmError);

    // Also check password field state on load for the checklist
    if (passwordField && passwordField.value) {
        updatePasswordValidation();
    }
    if (confirmField && confirmField.value) {
        updateConfirmValidation();
    }
})();
