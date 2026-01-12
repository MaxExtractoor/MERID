/**
 * UI Fix - Ensures all DOM elements exist and functions are properly bound
 */

// Add defensive checks and ensure all elements exist
document.addEventListener('DOMContentLoaded', () => {
    console.log('UI Fix: DOM loaded, checking elements...');
    
    // Check critical elements
    const criticalElements = [
        'price-btc', 'price-eth', 'price-sol', 'price-avax',
        'change-btc', 'change-eth', 'change-sol', 'change-avax',
        'main-chart-price', 'main-chart-change', 'main-chart-symbol',
        'div-score', 'div-status', 'guardian-state', 'guardian-threat'
    ];
    
    const missing = [];
    criticalElements.forEach(id => {
        if (!document.getElementById(id)) {
            missing.push(id);
        }
    });
    
    if (missing.length > 0) {
        console.error('UI Fix: Missing elements:', missing);
    } else {
        console.log('UI Fix: All critical elements present');
    }
    
    // Ensure sidebar links work
    const sidebarLinks = document.querySelectorAll('.sidebar-link');
    console.log(`UI Fix: Found ${sidebarLinks.length} sidebar links`);
    
    if (sidebarLinks.length === 0) {
        console.error('UI Fix: No sidebar links found!');
    }
    
    // Ensure navigation is initialized
    setTimeout(() => {
        if (typeof initNavigation === 'function') {
            console.log('UI Fix: Re-initializing navigation');
            initNavigation();
        }
    }, 100);
    
    // Force initial data fetch
    setTimeout(() => {
        if (typeof refreshAll === 'function') {
            console.log('UI Fix: Forcing initial data refresh');
            refreshAll();
        }
    }, 500);
});

// Override console.error to make errors visible
const originalError = console.error;
console.error = function(...args) {
    originalError.apply(console, args);
    // Show error in UI if possible
    const errorDiv = document.getElementById('error-display');
    if (errorDiv) {
        errorDiv.textContent = args.join(' ');
        errorDiv.style.display = 'block';
    }
};

console.log('UI Fix script loaded');
