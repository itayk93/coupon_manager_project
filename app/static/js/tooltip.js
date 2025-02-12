
document.addEventListener('DOMContentLoaded', function() {
    const isMobile = window.innerWidth < 768;
    console.log("📱 isMobile detected as:", isMobile);
    
    setTimeout(function() {
        const tooltip = document.querySelector('.mobile-tooltip');
        const tooltipButtonMobile = document.querySelector('.tooltip-button-mobile');
        const closeTooltipButton = document.querySelector('.close-tooltip'); // הכפתור לסגירה
        const slotsInfoMobile = document.querySelector('.slots-info-mobile'); // האלמנט שמוסתר אוטומטית

        // הסתרת .slots-info-mobile אוטומטית
        if (slotsInfoMobile) {
            slotsInfoMobile.style.display = 'none';
            console.log("ℹ️ .slots-info-mobile was hidden automatically.");
        } else {
            console.error("❌ .slots-info-mobile element not found.");
        }

        // הסתרת .mobile-tooltip במסכים גדולים (מעל 769px)
        function hideTooltipOnDesktop() {
            if (window.innerWidth > 769) {
                if (tooltip) {
                    tooltip.style.display = 'none';
                    console.log("ℹ️ .mobile-tooltip hidden on desktop.");
                } else {
                    console.error("❌ .mobile-tooltip element not found.");
                }
            }
        }

        // בדיקה ראשונית
        hideTooltipOnDesktop();

        // בדיקה נוספת כאשר משנים את גודל המסך
        window.addEventListener('resize', hideTooltipOnDesktop);

        if (!tooltip || !tooltipButtonMobile) {
            console.error("❌ Tooltip or tooltip button for mobile not found.");
            return;
        }

        // הצגת tooltip בלחיצה על הכפתור ❔
        tooltipButtonMobile.addEventListener('click', function() {
            console.log("🔍 לפני הלחיצה - display:", window.getComputedStyle(tooltip).display);
            if (tooltip.style.display === 'block') {
                tooltip.style.display = 'none';
            } else {
                tooltip.style.display = 'block';
            }
            console.log("✅ אחרי הלחיצה - display:", window.getComputedStyle(tooltip).display);
        });

        // סגירת ה-tooltip בלחיצה על כפתור ה-X
        if (closeTooltipButton) {
            closeTooltipButton.addEventListener('click', function() {
                console.log("❌ Tooltip closed via close button.");
                tooltip.style.display = 'none';
            });
        } else {
            console.error("❌ Close button for tooltip not found.");
        }

    }, 1000); // ממתין שנייה אחת לבדיקה מחדש
});

// === ניהול tooltip למצב מובייל עבור "קוד לשימוש חד פעמי" ===
const tooltipOneTimeButton = document.getElementById('tooltipButtonOneTime');
const mobileTooltipOneTime = document.getElementById('MobileTooltipOneTimeUse');
const closeMobileTooltipOneTime = document.getElementById('closeMobileTooltipOneTimeUse');

if (isMobile) {
    if (tooltipOneTimeButton && mobileTooltipOneTime) {
        tooltipOneTimeButton.addEventListener('click', function() {
            if (mobileTooltipOneTime.style.display === 'block') {
                mobileTooltipOneTime.style.display = 'none';
            } else {
                mobileTooltipOneTime.style.display = 'block';
            }
        });
    }

    if (closeMobileTooltipOneTime) {
        closeMobileTooltipOneTime.addEventListener('click', function() {
            mobileTooltipOneTime.style.display = 'none';
        });
    }
} else {
    // במצב דסקטופ – ניתן להשאיר את ההתנהגות הקיימת (הצגה במעבר עכבר) או להוסיף קוד דומה
    const formGroupOneTime = document.getElementById('TooltipOneTimeUse').parentElement;
    if (formGroupOneTime) {
        formGroupOneTime.addEventListener('mouseenter', function() {
            document.getElementById('TooltipOneTimeUse').style.display = 'block';
        });
        formGroupOneTime.addEventListener('mouseleave', function() {
            document.getElementById('TooltipOneTimeUse').style.display = 'none';
        });
    }
}
