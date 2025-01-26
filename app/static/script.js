// static/script.js

document.addEventListener('DOMContentLoaded', () => {
    // פונקציה להצגת סיסמה
    function showPassword(fieldId) {
        const passwordField = document.getElementById(fieldId);
        if (passwordField) {
            passwordField.type = 'text';
        }
    }

    // פונקציה להסתתרות סיסמה
    function hidePassword(fieldId) {
        const passwordField = document.getElementById(fieldId);
        if (passwordField) {
            passwordField.type = 'password';
        }
    }

    // פונקציה להצגת/הסתרת סיסמה בעת לחיצה
    function togglePasswordVisibility(button) {
        const fieldId = button.getAttribute('data-field-id');
        const passwordField = document.getElementById(fieldId);
        if (passwordField) {
            if (passwordField.type === 'password') {
                passwordField.type = 'text';
                button.textContent = '🙈';
            } else {
                passwordField.type = 'password';
                button.textContent = '👁️';
            }
        }
    }

    // הוספת מאזינים לכל כפתורי הצגת הסיסמה
    const togglePasswordButtons = document.querySelectorAll('.show-password-button');
    togglePasswordButtons.forEach(button => {
        const fieldId = button.getAttribute('data-field-id');
        button.addEventListener('mousedown', () => showPassword(fieldId));
        button.addEventListener('mouseup', () => hidePassword(fieldId));
        button.addEventListener('mouseleave', () => hidePassword(fieldId));
        button.addEventListener('click', () => togglePasswordVisibility(button));
    });

    // פונקציה לחישוב חוזק הסיסמה
    function calculatePasswordStrength(password) {
        let score = 0;
        if (password.length >= 6) score++;
        if (password.length >= 8) score++;
        if (/[0-9]/.test(password)) score++;
        if (/[a-z]/.test(password)) score++;
        if (/[A-Z]/.test(password)) score++;
        if (/[^A-Za-z0-9]/.test(password)) score++;
        return score;
    }

    // פונקציה לעדכון פס החוזק וההודעה
    function updatePasswordStrength(passwordField, strengthBar, strengthMessage) {
        const password = passwordField.value;
        const score = calculatePasswordStrength(password);

        const strengthLevels = ['חלשה', 'חלשה', 'חלשה', 'בינונית', 'חזקה', 'חזקה', 'חזקה'];
        const strengthColors = ['red', 'red', 'red', 'orange', 'green', 'green', 'green'];

        strengthBar.style.width = `${(score / 6) * 100}%`;
        strengthBar.style.backgroundColor = strengthColors[score] || 'red';
        strengthMessage.textContent = `חוזק סיסמה: ${strengthLevels[score] || 'N/A'}`;

        if (score < 4) {
            strengthMessage.textContent += ' (השתמש בלפחות 8 תווים, שילוב של אותיות, מספרים וסמלים)';
        }
    }

    // הוספת מאזינים לשדות הסיסמה לצורך אינדיקטור חוזק
    const passwordFields = document.querySelectorAll('.input-field[type="password"]');
    passwordFields.forEach(passwordField => {
        const parent = passwordField.parentElement;
        const strengthBar = parent.querySelector('#password-strength-bar') || parent.querySelector('.password-strength-bar');
        const strengthMessage = parent.querySelector('#strength-message') || parent.querySelector('.strength-message');

        if (strengthBar && strengthMessage) {
            passwordField.addEventListener('input', () => {
                updatePasswordStrength(passwordField, strengthBar, strengthMessage);
            });
        }
    });

    // Dropdown Menu Functionality with Responsive Behavior
    const dropdowns = document.querySelectorAll('.dropdown');
    const mobileBreakpoint = 768; // px

    // פונקציות לטיפול באירועים
    function toggleDropdownClick(e) {
        e.stopPropagation(); // מונע מהאירוע להתפשט אל המסמך
        this.querySelector('.dropdown-content').classList.toggle('show');
    }

    // פונקציה לסגירת כל התפריטים הפתוחים
    function closeAllDropdowns() {
        document.querySelectorAll('.dropdown-content.show').forEach(dropdownContent => {
            dropdownContent.classList.remove('show');
        });
    }

    // הוספת מאזין אירועים למסמך לסגירת התפריטים בעת לחיצה מחוץ
    document.addEventListener('click', function(event) {
        // אם הלחיצה לא הייתה בתוך אלמנט dropdown
        if (!event.target.closest('.dropdown')) {
            closeAllDropdowns();
        }
    });

    function openDropdownHover() {
        this.querySelector('.dropdown-content').classList.add('show');
    }

    function closeDropdownHover() {
        this.querySelector('.dropdown-content').classList.remove('show');
    }

    // פונקציה להגדרת dropdowns בהתאם לגודל המסך
    function setupDropdowns() {
        const isMobile = window.innerWidth < mobileBreakpoint;

        dropdowns.forEach(dropdown => {
            const dropbtn = dropdown.querySelector('.dropbtn');
            const dropdownContent = dropdown.querySelector('.dropdown-content');

            // הסרת כל האירועים הקודמים כדי למנוע כפילויות
            dropdown.removeEventListener('click', toggleDropdownClick);
            dropdown.removeEventListener('mouseenter', openDropdownHover);
            dropdown.removeEventListener('mouseleave', closeDropdownHover);

            if (isMobile) {
                // במכשירים ניידים: השתמש באירועי click על האלמנט dropdown
                dropdown.addEventListener('click', toggleDropdownClick);
            } else {
                // במחשבים שולחניים: השתמש באירועי hover
                dropdown.addEventListener('mouseenter', openDropdownHover);
                dropdown.addEventListener('mouseleave', closeDropdownHover);
            }
        });
    }

    // קריאה ראשונית להגדרת התפריטים
    setupDropdowns();

    // טיפול באירוע שינוי גודל המסך
    window.addEventListener('resize', () => {
        setupDropdowns();
    });

    // Hamburger Menu Functionality
    const hamburger = document.querySelector('.hamburger');
    const nav = document.querySelector('.header-right nav');
    if (hamburger && nav) { // בדיקה שהאלמנטים קיימים
        hamburger.addEventListener('click', () => {
            const isActive = nav.classList.toggle('active');
            hamburger.classList.toggle('active');

            if (!isActive) {
                // סגירת כל התפריטים הנפתחים
                dropdowns.forEach(dropdown => {
                    const dropdownContent = dropdown.querySelector('.dropdown-content');
                    if (dropdownContent.classList.contains('show')) {
                        dropdownContent.classList.remove('show');
                    }
                });
            }
        });
    }

    // פונקציה לשליפת ה-CSRF Token מהמטא טאג
    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    // פונקציה לעיכוב פעולות (Debounce)
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            const context = this;
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(context, args), wait);
        };
    }

    // פונקציה לשליחת נתוני הפרופיל לשרת
    const saveProfileField = debounce((fieldId, value) => {
        const csrfToken = getCSRFToken();

        fetch('/update_profile_field', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            credentials: 'include',
            body: JSON.stringify({ field: fieldId, value: value })
        })
        .then(response => response.json())
        .then(data => {
            const indicator = document.getElementById(`${fieldId}-save-indicator`);
            if (data.status === 'success') {
                if (indicator) {
                    indicator.classList.remove('error');
                    indicator.classList.add('success');
                }
            } else {
                if (indicator) {
                    indicator.classList.remove('success');
                    indicator.classList.add('error');
                }
            }

            // הצגת הודעת שמירה אוטומטית
            /*
            const autoSaveMessage = document.getElementById('auto-save-message');
            if (autoSaveMessage) {
                if (data.status === 'success') {
                    autoSaveMessage.textContent = 'שינויים נשמרו אוטומטית';
                } else {
                    autoSaveMessage.textContent = 'אירעה שגיאה בשמירת השינויים';
                }
                autoSaveMessage.classList.add('show');
                setTimeout(() => {
                    autoSaveMessage.classList.remove('show');
                }, 3000);
            }
            */
        })
        .catch(error => {
            console.error('Error saving profile field:', error);
            const indicator = document.getElementById(`${fieldId}-save-indicator`);
            if (indicator) {
                indicator.classList.remove('success');
                indicator.classList.add('error');
            }

            // הצגת הודעת שגיאה
            /*
            const autoSaveMessage = document.getElementById('auto-save-message');
            if (autoSaveMessage) {
                autoSaveMessage.textContent = 'אירעה שגיאה בשמירת השינויים';
                autoSaveMessage.classList.add('show');
                setTimeout(() => {
                    autoSaveMessage.classList.remove('show');
                }, 3000);
            }
            */
        });
    }, 500); // 500 מילישניות דיליי

    // הוספת מאזינים לשדות הפרופיל
    const profileForm = document.getElementById('profile-form');
    if (profileForm) {
        const inputs = profileForm.querySelectorAll('.input-field');

        inputs.forEach(input => {
            // מאזינים לאירוע 'input' כדי לזהות שינויים
            input.addEventListener('input', (e) => {
                const fieldId = e.target.id;
                const value = e.target.value;
                saveProfileField(fieldId, value);
            });
        });
    }

    // פונקציה למחיקת התראה
    /*
    function deleteNotification(notificationId, element) {
        fetch('/delete_notification/' + notificationId, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCSRFToken()
            },
            credentials: 'include'
        }).then(response => {
            if (response.ok) {
                element.remove();
            } else {
                console.error('Error hiding notification:', response);
            }
        }).catch(error => {
            console.error('Error hiding notification:', error);
        });
    }
    */

    // פונקציה להגדרת מחיקת התראה בהחלקה
    /*
    function setupSwipeToDelete() {
        const notificationCards = document.querySelectorAll('.notification-card');

        notificationCards.forEach(card => {
            let touchstartX = 0;
            let touchendX = 0;

            card.addEventListener('touchstart', function(event) {
                touchstartX = event.changedTouches[0].screenX;
            }, false);

            card.addEventListener('touchend', function(event) {
                touchendX = event.changedTouches[0].screenX;
                handleGesture(card);
            }, false);

            function handleGesture(card) {
                if (touchstartX - touchendX > 50) {
                    // החלקה שמאלה - הסתרת התראה
                    const notificationId = card.getAttribute('data-notification-id');
                    deleteNotification(notificationId, card);
                }
            }
        });
    }
    */

    // פונקציה למחיקת התראה בודדת
    /*
    function setupNotificationDeletion() {
        document.querySelectorAll('.notification-card .close-button').forEach(function(button) {
            button.addEventListener('click', function() {
                const notificationCard = this.parentElement;
                const notificationId = notificationCard.getAttribute('data-notification-id');
                deleteNotification(notificationId, notificationCard);
            });
        });

        // קריאה לפונקציה שהוספנו
        setupSwipeToDelete();

        // מחיקת כל ההתראות
        const deleteAllButton = document.getElementById('delete-all-notifications');
        if (deleteAllButton) {
            deleteAllButton.addEventListener('click', function() {
                // שליחת בקשה להסתרת כל ההתראות מהשרת
                fetch('/delete_all_notifications', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCSRFToken()
                    },
                    credentials: 'include'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'success') {
                        // הסרת כל ההתראות מה-DOM
                        document.querySelectorAll('.notification-card').forEach(function(card) {
                            card.remove();
                        });
                        alert(`ההתראות הוסתרו בהצלחה (${data.deleted} התראות).`);
                    } else {
                        alert('אירעה שגיאה בהסתרת ההתראות: ' + data.message);
                    }
                })
                .catch(error => {
                    console.error('Error hiding all notifications:', error);
                    alert('אירעה שגיאה בהסתרת ההתראות.');
                });
            });
        }
    }
    */

    // הסרה של קריאות לפונקציות הקשורות להתראות על המסך הראשי
    // setupNotificationDeletion(); // אם פונקציה זו משמשת במקום אחר, ניתן להשאיר אותה

    // הסרנו את הפונקציות fetchNotifications ו-displayNotification
    // כמו כן, הסרנו את הקריאות setInterval(fetchNotifications, 15000) ו-fetchNotifications()

    // Functionality for the 'is_one_time' checkbox and 'purpose' field
    const checkbox = document.getElementById('is_one_time');
    const purposeGroup = document.getElementById('purpose_group');

    if (checkbox && purposeGroup) {
        // Function to toggle the visibility of the purpose field
        function togglePurposeField() {
            if (checkbox.checked) {
                purposeGroup.style.display = 'block';
            } else {
                purposeGroup.style.display = 'none';
                const purposeField = document.getElementById('purpose');
                if (purposeField) {
                    purposeField.value = ''; // Clear the field when hidden
                }
            }
        }

        // Initial check on page load
        togglePurposeField();

        // Add event listener for changes
        checkbox.addEventListener('change', togglePurposeField);
    }


});
