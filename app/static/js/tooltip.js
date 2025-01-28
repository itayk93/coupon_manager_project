document.addEventListener('DOMContentLoaded', function() {
    const tooltip = document.getElementById('Tooltip');
    const closeTooltip = document.getElementById('closeTooltip');
    const isMobile = window.matchMedia("(max-width: 768px)").matches;

    if (isMobile && tooltip && closeTooltip) {
        const submitButtonMobile = document.querySelector('.submit-button');
        if (submitButtonMobile) {
            submitButtonMobile.addEventListener('click', function(e) {
                e.preventDefault();
                tooltip.style.display = 'block';
            });
        }

        closeTooltip.addEventListener('click', function() {
            tooltip.style.display = 'none';
        });
    }
});
