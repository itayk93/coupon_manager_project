(function () {
    const modalId = 'rtl-modal-alert';
    const styleId = 'rtl-modal-alert-style';
    let closeTimer = null;
    let lastFocusedElement = null;

    function ensureStyles() {
        if (document.getElementById(styleId)) {
            return;
        }

        const style = document.createElement('style');
        style.id = styleId;
        style.textContent = `
            #${modalId} {
                position: fixed;
                inset: 0;
                z-index: 2147483000;
                display: none;
                align-items: center;
                justify-content: center;
                padding: 18px;
                direction: rtl;
                font-family: Rubik, Heebo, Arial, sans-serif;
            }

            #${modalId}.is-open {
                display: flex;
            }

            #${modalId} .rtl-modal-alert-backdrop {
                position: absolute;
                inset: 0;
                background: rgba(15, 23, 42, 0.5);
                backdrop-filter: blur(6px);
                -webkit-backdrop-filter: blur(6px);
            }

            #${modalId} .rtl-modal-alert-panel {
                position: relative;
                z-index: 1;
                width: min(92vw, 520px);
                max-height: min(82vh, 620px);
                overflow: auto;
                background: #fff;
                border: 1px solid rgba(148, 163, 184, 0.35);
                border-radius: 18px;
                box-shadow: 0 24px 60px rgba(15, 23, 42, 0.24);
                padding: 22px 22px 18px;
                text-align: right;
                color: #111827;
            }

            #${modalId} .rtl-modal-alert-close {
                position: absolute;
                top: 12px;
                left: 12px;
                width: 36px;
                height: 36px;
                border: 0;
                border-radius: 999px;
                background: #f3f4f6;
                color: #374151;
                font-size: 22px;
                line-height: 1;
                cursor: pointer;
            }

            #${modalId} .rtl-modal-alert-content {
                display: flex;
                align-items: flex-start;
                gap: 14px;
                padding-top: 18px;
            }

            #${modalId} .rtl-modal-alert-icon {
                width: 44px;
                height: 44px;
                flex: 0 0 44px;
                border-radius: 14px;
                display: flex;
                align-items: center;
                justify-content: center;
                background: #dbeafe;
                color: #1d4ed8;
                font-size: 24px;
                font-weight: 700;
            }

            #${modalId} .rtl-modal-alert-title {
                margin: 0 0 8px;
                color: #111827;
                font-size: 18px;
                font-weight: 700;
                line-height: 1.35;
            }

            #${modalId} .rtl-modal-alert-message {
                margin: 0;
                color: #374151;
                font-size: 16px;
                line-height: 1.6;
                white-space: pre-wrap;
                overflow-wrap: anywhere;
            }

            #${modalId} .rtl-modal-alert-actions {
                display: flex;
                justify-content: flex-start;
                margin-top: 20px;
            }

            #${modalId} .rtl-modal-alert-button {
                min-width: 110px;
                height: 44px;
                border: 0;
                border-radius: 999px;
                background: #1d4ed8;
                color: #fff;
                font-size: 16px;
                font-weight: 700;
                cursor: pointer;
                padding: 0 18px;
            }

            #${modalId} .rtl-modal-alert-button:hover {
                background: #1e40af;
            }

            @media (max-width: 480px) {
                #${modalId} {
                    align-items: flex-end;
                    padding: 12px;
                }

                #${modalId} .rtl-modal-alert-panel {
                    width: 100%;
                    border-radius: 18px 18px 14px 14px;
                }
            }
        `;
        document.head.appendChild(style);
    }

    function ensureModal() {
        ensureStyles();

        let modal = document.getElementById(modalId);
        if (modal) {
            return modal;
        }

        modal = document.createElement('div');
        modal.id = modalId;
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-hidden', 'true');
        modal.innerHTML = `
            <div class="rtl-modal-alert-backdrop" data-rtl-modal-alert-close></div>
            <div class="rtl-modal-alert-panel" role="document" tabindex="-1">
                <button type="button" class="rtl-modal-alert-close" data-rtl-modal-alert-close aria-label="סגירת הודעה">×</button>
                <div class="rtl-modal-alert-content">
                    <div class="rtl-modal-alert-icon" aria-hidden="true">i</div>
                    <div>
                        <h2 class="rtl-modal-alert-title">הודעה</h2>
                        <p class="rtl-modal-alert-message"></p>
                    </div>
                </div>
                <div class="rtl-modal-alert-actions">
                    <button type="button" class="rtl-modal-alert-button" data-rtl-modal-alert-close>אישור</button>
                </div>
            </div>
        `;

        modal.addEventListener('click', function (event) {
            if (event.target && event.target.hasAttribute('data-rtl-modal-alert-close')) {
                window.closeRtlModalAlert();
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape' && modal.classList.contains('is-open')) {
                window.closeRtlModalAlert();
            }
        });

        document.body.appendChild(modal);
        return modal;
    }

    window.closeRtlModalAlert = function () {
        const modal = document.getElementById(modalId);
        if (!modal) {
            return;
        }

        modal.classList.remove('is-open');
        modal.setAttribute('aria-hidden', 'true');

        if (closeTimer) {
            clearTimeout(closeTimer);
            closeTimer = null;
        }

        if (lastFocusedElement && typeof lastFocusedElement.focus === 'function') {
            lastFocusedElement.focus();
        }
        lastFocusedElement = null;
    };

    window.showRtlModalAlert = function (message, options) {
        const modal = ensureModal();
        const settings = options || {};
        const title = settings.title || 'הודעה';
        const buttonText = settings.buttonText || 'אישור';

        lastFocusedElement = document.activeElement;
        modal.querySelector('.rtl-modal-alert-title').textContent = title;
        modal.querySelector('.rtl-modal-alert-message').textContent = message == null ? '' : String(message);
        modal.querySelector('.rtl-modal-alert-button').textContent = buttonText;
        modal.classList.add('is-open');
        modal.setAttribute('aria-hidden', 'false');
        modal.querySelector('.rtl-modal-alert-panel').focus();

        if (settings.autoCloseMs) {
            closeTimer = setTimeout(window.closeRtlModalAlert, settings.autoCloseMs);
        }
    };

    window.alert = function (message) {
        window.showRtlModalAlert(message);
    };
}());
