document.addEventListener('DOMContentLoaded', function() {
    // הגדרת משתנה isMobile לזיהוי אם המשתמש בדפדפן נייד
    const isMobile = window.innerWidth < 768;
    console.log("📱 isMobile detected as:", isMobile);

    setTimeout(function() {
        const tooltip = document.querySelector('.mobile-tooltip');
        const tooltipButtonMobile = document.querySelector('.tooltip-button-mobile');
        const closeTooltipButton = document.querySelector('.close-tooltip'); // כפתור לסגירת ה-tooltip
        const slotsInfoMobile = document.querySelector('.slots-info-mobile'); // אלמנט מידע מוסתר

        // הסתרת .slots-info-mobile אוטומטית אם האלמנט קיים
        if (slotsInfoMobile) {
            slotsInfoMobile.style.display = 'none';
            console.log("ℹ️ .slots-info-mobile was hidden automatically.");
        } else {
            console.warn("⚠️ .slots-info-mobile element not found.");
        }

        // פונקציה להסתרת ה-tooltip כאשר המסך גדול מ-769px
        function hideTooltipOnDesktop() {
            if (window.innerWidth > 769) {
                if (tooltip) {
                    tooltip.style.display = 'none';
                    console.log("ℹ️ .mobile-tooltip hidden on desktop.");
                } else {
                    console.warn("⚠️ .mobile-tooltip element not found.");
                }
            }
        }

        // הפעלה ראשונית ובדיקה נוספת כאשר המסך משתנה
        hideTooltipOnDesktop();
        window.addEventListener('resize', hideTooltipOnDesktop);

        // בדיקה אם הכפתור או ה-tooltip קיימים לפני שמנסים להוסיף אירועים
        if (!tooltip || !tooltipButtonMobile) {
            console.warn("⚠️ Tooltip or tooltip button for mobile not found.");
            return;
        }

        // הצגת ה-tooltip בלחיצה על הכפתור ❔
        tooltipButtonMobile.addEventListener('click', function() {
            console.log("🔍 לפני הלחיצה - display:", window.getComputedStyle(tooltip).display);
            tooltip.style.display = tooltip.style.display === 'block' ? 'none' : 'block';
            console.log("✅ אחרי הלחיצה - display:", window.getComputedStyle(tooltip).display);
        });

        // סגירת ה-tooltip בלחיצה על כפתור ה-X
        if (closeTooltipButton) {
            closeTooltipButton.addEventListener('click', function() {
                console.log("❌ Tooltip closed via close button.");
                tooltip.style.display = 'none';
            });
        } else {
            console.warn("⚠️ Close button for tooltip not found.");
        }
    }, 1000); // המתנה של שנייה אחת לבדיקה מחדש

    // === ניהול tooltip למצב מובייל עבור "קוד לשימוש חד פעמי" ===
    const tooltipOneTimeButton = document.getElementById('tooltipButtonOneTime');
    const mobileTooltipOneTime = document.getElementById('MobileTooltipOneTimeUse');
    const closeMobileTooltipOneTime = document.getElementById('closeMobileTooltipOneTimeUse');

    // בדיקה שאין משתנה מוכרז פעמיים
    if (typeof window.tooltipOneTimeButtonInitialized === "undefined") {
        window.tooltipOneTimeButtonInitialized = true; // מניעת הצהרה כפולה

        if (isMobile) {
            if (tooltipOneTimeButton && mobileTooltipOneTime) {
                tooltipOneTimeButton.addEventListener('click', function() {
                    mobileTooltipOneTime.style.display = mobileTooltipOneTime.style.display === 'block' ? 'none' : 'block';
                });
            }

            if (closeMobileTooltipOneTime) {
                closeMobileTooltipOneTime.addEventListener('click', function() {
                    mobileTooltipOneTime.style.display = 'none';
                });
            }
        } else {
            // במצב דסקטופ – הצגת tooltip במעבר עכבר
            const formGroupOneTime = document.getElementById('TooltipOneTimeUse')?.parentElement;
            if (formGroupOneTime) {
                formGroupOneTime.addEventListener('mouseenter', function() {
                    document.getElementById('TooltipOneTimeUse').style.display = 'block';
                });
                formGroupOneTime.addEventListener('mouseleave', function() {
                    document.getElementById('TooltipOneTimeUse').style.display = 'none';
                });
            }
        }
    } else {
        console.warn("⚠️ tooltipOneTimeButton כבר הוגדר, נמנעת כפילות.");
    }

    // === בדיקת קיום של המודל בדף (לפתרון בעיית המודל שלא נפתח) ===
    const deleteButton = document.querySelector(".delete-action-button");
    const deleteModal = document.getElementById("deleteConfirmModal");

    if (deleteButton && deleteModal) {
        deleteButton.addEventListener("click", function() {
            console.log("🗑️ כפתור מחיקה נלחץ - ניסיון לפתוח את המודל");
            $("#deleteConfirmModal").modal("show");
        });
    } else {
        console.warn("⚠️ deleteButton או deleteModal לא נמצא(ים) ב-DOM.");
    }

    // הצגת מצב המודל בקונסול
    console.log("📌 מודל מחיקה נמצא ב-DOM:", document.getElementById("deleteConfirmModal"));
});
