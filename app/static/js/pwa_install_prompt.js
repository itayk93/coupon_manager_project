(function () {
    const STORAGE_KEYS = {
        dismissUntil: 'cm_pwa_install_dismiss_until',
        dismissCount: 'cm_pwa_install_dismiss_count',
        permanentlyDismissed: 'cm_pwa_install_permanently_dismissed',
        iosMarkedInstalled: 'cm_pwa_install_ios_marked_installed'
    };

    const DISMISS_DAYS = 7;

    let deferredPrompt = null;
    let isInstalled = false;
    let isIOS = false;
    let isSafari = false;
    let modalOverlay = null;

    function normalizeLang(raw) {
        const value = (raw || '').toLowerCase().trim();
        if (value.startsWith('he')) return 'he';
        if (value.startsWith('ru')) return 'ru';
        if (value.startsWith('en')) return 'en';
        return '';
    }

    function detectLanguage() {
        const bodyLang = normalizeLang(document.body && document.body.getAttribute('data-ui-lang'));
        if (bodyLang) return bodyLang;

        const stored = normalizeLang(localStorage.getItem('app_language') || localStorage.getItem('language'));
        if (stored) return stored;

        const cookieMatch = document.cookie.match(/(?:^|;\s*)(?:language|lang)=([^;]+)/i);
        if (cookieMatch && cookieMatch[1]) {
            const cookieLang = normalizeLang(decodeURIComponent(cookieMatch[1]));
            if (cookieLang) return cookieLang;
        }

        const htmlLang = normalizeLang(document.documentElement.getAttribute('lang'));
        if (htmlLang && htmlLang !== 'he') return htmlLang;

        const nav = normalizeLang(navigator.language || (navigator.languages && navigator.languages[0]));
        if (nav) return nav;
        return htmlLang || 'he';
    }

    function isStandalone() {
        return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    }

    function hasDismissCooldown() {
        const untilRaw = localStorage.getItem(STORAGE_KEYS.dismissUntil);
        if (!untilRaw) return false;

        const until = Number(untilRaw);
        if (!Number.isFinite(until)) {
            localStorage.removeItem(STORAGE_KEYS.dismissUntil);
            return false;
        }

        if (Date.now() < until) {
            return true;
        }

        localStorage.removeItem(STORAGE_KEYS.dismissUntil);
        return false;
    }

    function isPermanentlyDismissed() {
        return localStorage.getItem(STORAGE_KEYS.permanentlyDismissed) === '1';
    }

    function dismissPrompt() {
        const currentCount = Number(localStorage.getItem(STORAGE_KEYS.dismissCount) || '0');
        const nextCount = Number.isFinite(currentCount) ? currentCount + 1 : 1;
        localStorage.setItem(STORAGE_KEYS.dismissCount, String(nextCount));

        if (nextCount >= 2) {
            localStorage.setItem(STORAGE_KEYS.permanentlyDismissed, '1');
            localStorage.removeItem(STORAGE_KEYS.dismissUntil);
            return;
        }

        const dismissUntil = Date.now() + DISMISS_DAYS * 24 * 60 * 60 * 1000;
        localStorage.setItem(STORAGE_KEYS.dismissUntil, String(dismissUntil));
    }

    function getCopy(lang) {
        const map = {
            he: {
                dir: 'rtl',
                title: 'התקן את Coupon Master',
                subtitle: 'גישה מהירה מהמסך הראשי, בלי לחפש בדפדפן בכל פעם.',
                benefits: [
                    'פתיחה מהירה ישירות מהמסך הראשי',
                    'חוויה נקייה ונוחה יותר מהגרסה בדפדפן',
                    'גישה מהירה לכל הקופונים ברגע שצריך'
                ],
                installButton: 'התקן עכשיו',
                laterButton: 'לא עכשיו',
                note: 'לא רוצים עכשיו? נזכיר שוב בעוד כמה ימים בלבד.',
                iosTitle: 'התקנה באייפון (Safari)',
                iosStep1: '1. לחצו על כפתור השיתוף בדפדפן Safari.',
                iosStep2: '2. בחרו “הוסף למסך הבית” (Add to Home Screen).',
                iosStep3: '3. אשרו עם “הוסף”.',
                iosWarning: 'ב-iPhone ההתקנה נתמכת מתוך Safari בלבד.',
                iosDone: 'סיימתי להתקין',
                iosBack: 'חזרה',
                success: 'מעולה. מעכשיו אפשר לפתוח את האפליקציה מהמסך הראשי.'
            },
            ru: {
                dir: 'ltr',
                title: 'Установите Coupon Master',
                subtitle: 'Открывайте быстрее с главного экрана вместо поиска в браузере.',
                benefits: [
                    'Быстрый запуск с главного экрана',
                    'Более удобный формат приложения, чем вкладка браузера',
                    'Быстрый доступ ко всем купонам в нужный момент'
                ],
                installButton: 'Установить сейчас',
                laterButton: 'Позже',
                note: 'Если пропустите сейчас, напомним позже без лишних уведомлений.',
                iosTitle: 'Установка на iPhone (Safari)',
                iosStep1: '1. Нажмите кнопку «Поделиться» в Safari.',
                iosStep2: '2. Выберите «Добавить на экран Домой».',
                iosStep3: '3. Подтвердите кнопкой «Добавить».',
                iosWarning: 'На iPhone установка поддерживается только через Safari.',
                iosDone: 'Установил',
                iosBack: 'Назад',
                success: 'Готово. Теперь можно открывать приложение с главного экрана.'
            },
            en: {
                dir: 'ltr',
                title: 'Install Coupon Master',
                subtitle: 'Open it faster from your home screen instead of searching in the browser.',
                benefits: [
                    'Quick launch from the home screen',
                    'Cleaner app-like experience than a browser tab',
                    'Fast access to all your coupons when needed'
                ],
                installButton: 'Install now',
                laterButton: 'Not now',
                note: 'If you skip now, we will remind you later without spamming.',
                iosTitle: 'Install on iPhone (Safari)',
                iosStep1: '1. Tap the Share button in Safari.',
                iosStep2: '2. Choose “Add to Home Screen”.',
                iosStep3: '3. Confirm with “Add”.',
                iosWarning: 'On iPhone, installation is supported from Safari only.',
                iosDone: 'I installed it',
                iosBack: 'Back',
                success: 'Great. You can now open the app from your home screen.'
            }
        };

        return map[lang] || map.he;
    }

    function renderModal(copy) {
        const existing = document.getElementById('pwa-install-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.className = 'pwa-install-overlay';
        overlay.id = 'pwa-install-overlay';

        overlay.innerHTML = [
            '<div class="pwa-install-modal" id="pwa-install-modal" data-dir="' + copy.dir + '">',
            '  <div class="pwa-install-header">',
            '    <div class="pwa-install-brand">',
            '      <img class="pwa-install-logo" src="/static/images/logo.png" alt="Coupon Master logo">',
            '      <div class="pwa-install-title-wrap">',
            '        <h3 id="pwa-main-title"></h3>',
            '        <p id="pwa-main-subtitle"></p>',
            '      </div>',
            '    </div>',
            '    <button type="button" class="pwa-close-btn" id="pwa-close-btn" aria-label="Close">&times;</button>',
            '  </div>',
            '  <div id="pwa-main-view">',
            '    <ul class="pwa-benefits" id="pwa-benefits"></ul>',
            '    <div class="pwa-install-actions" id="pwa-main-actions">',
            '      <button type="button" class="pwa-install-btn" id="pwa-install-btn"></button>',
            '      <button type="button" class="pwa-later-btn" id="pwa-later-btn"></button>',
            '    </div>',
            '    <p class="pwa-install-note" id="pwa-main-note"></p>',
            '  </div>',
            '  <div id="pwa-ios-view" style="display:none;">',
            '    <h3 id="pwa-ios-title" style="margin:4px 0 0; color:#1e2d4a; font-size:1.08rem;"></h3>',
            '    <div class="pwa-ios-steps">',
            '      <div class="pwa-step" id="pwa-ios-step-1"></div>',
            '      <div class="pwa-step" id="pwa-ios-step-2"></div>',
            '      <div class="pwa-step" id="pwa-ios-step-3"></div>',
            '    </div>',
            '    <div class="pwa-warning" id="pwa-ios-warning" style="display:none;"></div>',
            '    <div class="pwa-ios-actions" id="pwa-ios-actions">',
            '      <button type="button" class="pwa-install-btn" id="pwa-ios-done-btn"></button>',
            '      <button type="button" class="pwa-secondary-btn" id="pwa-ios-back-btn"></button>',
            '    </div>',
            '    <div class="pwa-success" id="pwa-success-msg" style="display:none;"></div>',
            '  </div>',
            '</div>'
        ].join('');

        const modal = overlay.querySelector('#pwa-install-modal');
        modal.setAttribute('dir', copy.dir);

        if (copy.dir === 'rtl') {
            overlay.querySelector('#pwa-main-actions').setAttribute('dir', 'rtl');
            overlay.querySelector('#pwa-ios-actions').setAttribute('dir', 'rtl');
        }

        document.body.appendChild(overlay);

        overlay.querySelector('#pwa-main-title').textContent = copy.title;
        overlay.querySelector('#pwa-main-subtitle').textContent = copy.subtitle;
        overlay.querySelector('#pwa-install-btn').textContent = copy.installButton;
        overlay.querySelector('#pwa-later-btn').textContent = copy.laterButton;
        overlay.querySelector('#pwa-main-note').textContent = copy.note;

        const benefits = overlay.querySelector('#pwa-benefits');
        benefits.innerHTML = copy.benefits.map((text) => '<li>' + text + '</li>').join('');

        overlay.querySelector('#pwa-ios-title').textContent = copy.iosTitle;
        overlay.querySelector('#pwa-ios-step-1').textContent = copy.iosStep1;
        overlay.querySelector('#pwa-ios-step-2').textContent = copy.iosStep2;
        overlay.querySelector('#pwa-ios-step-3').textContent = copy.iosStep3;
        overlay.querySelector('#pwa-ios-done-btn').textContent = copy.iosDone;
        overlay.querySelector('#pwa-ios-back-btn').textContent = copy.iosBack;
        overlay.querySelector('#pwa-success-msg').textContent = copy.success;

        if (isIOS && !isSafari) {
            const warning = overlay.querySelector('#pwa-ios-warning');
            warning.textContent = copy.iosWarning;
            warning.style.display = 'block';
        }

        return overlay;
    }

    function openModal(overlay) {
        overlay.classList.add('pwa-open');
    }

    function closeModal(overlay) {
        overlay.classList.remove('pwa-open');
    }

    async function handleInstall(copy, overlay) {
        const mainView = overlay.querySelector('#pwa-main-view');
        const iosView = overlay.querySelector('#pwa-ios-view');

        if (isIOS) {
            mainView.style.display = 'none';
            iosView.style.display = 'block';
            return;
        }

        if (!deferredPrompt) {
            const note = overlay.querySelector('#pwa-main-note');
            note.textContent = copy.note;
            return;
        }

        try {
            await deferredPrompt.prompt();
            const choice = await deferredPrompt.userChoice;
            if (choice && choice.outcome === 'accepted') {
                closeModal(overlay);
            }
            deferredPrompt = null;
        } catch (error) {
            console.error('PWA install prompt failed:', error);
        }
    }

    function shouldShowPrompt() {
        if (isInstalled) return false;
        if (isPermanentlyDismissed()) return false;
        if (hasDismissCooldown()) return false;

        if (isIOS) return true;
        return !!deferredPrompt;
    }

    function setupAndMaybeShow() {
        const lang = detectLanguage();
        const copy = getCopy(lang);

        modalOverlay = renderModal(copy);
        const closeBtn = modalOverlay.querySelector('#pwa-close-btn');
        const laterBtn = modalOverlay.querySelector('#pwa-later-btn');
        const installBtn = modalOverlay.querySelector('#pwa-install-btn');
        const iosDoneBtn = modalOverlay.querySelector('#pwa-ios-done-btn');
        const iosBackBtn = modalOverlay.querySelector('#pwa-ios-back-btn');

        closeBtn.addEventListener('click', function () {
            dismissPrompt();
            closeModal(modalOverlay);
        });

        laterBtn.addEventListener('click', function () {
            dismissPrompt();
            closeModal(modalOverlay);
        });

        modalOverlay.addEventListener('click', function (event) {
            if (event.target === modalOverlay) {
                dismissPrompt();
                closeModal(modalOverlay);
            }
        });

        installBtn.addEventListener('click', function () {
            handleInstall(copy, modalOverlay);
        });

        iosDoneBtn.addEventListener('click', function () {
            localStorage.setItem(STORAGE_KEYS.iosMarkedInstalled, '1');
            const success = modalOverlay.querySelector('#pwa-success-msg');
            success.style.display = 'block';
            setTimeout(function () {
                closeModal(modalOverlay);
            }, 1200);
        });

        iosBackBtn.addEventListener('click', function () {
            modalOverlay.querySelector('#pwa-ios-view').style.display = 'none';
            modalOverlay.querySelector('#pwa-main-view').style.display = 'block';
        });

        if (shouldShowPrompt()) {
            window.setTimeout(function () {
                openModal(modalOverlay);
            }, 1100);
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        isInstalled = isStandalone() || localStorage.getItem(STORAGE_KEYS.iosMarkedInstalled) === '1';

        const ua = navigator.userAgent || '';
        isIOS = /iPad|iPhone|iPod/.test(ua) && !(window.MSStream);
        isSafari = isIOS && !(/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua));

        window.addEventListener('beforeinstallprompt', function (event) {
            event.preventDefault();
            deferredPrompt = event;
            if (modalOverlay && shouldShowPrompt()) {
                openModal(modalOverlay);
            }
        });

        window.addEventListener('appinstalled', function () {
            isInstalled = true;
            localStorage.setItem(STORAGE_KEYS.iosMarkedInstalled, '1');
            const overlay = document.getElementById('pwa-install-overlay');
            if (overlay) {
                overlay.classList.remove('pwa-open');
            }
        });

        setupAndMaybeShow();
    });
})();
