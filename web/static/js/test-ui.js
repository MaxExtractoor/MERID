/**
 * Minimal UI Test - Verify basic functionality
 */

console.log('=== MERID UI TEST STARTING ===');

// Test 1: Check if DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    console.log('✓ DOM Content Loaded');
    
    // Test 2: Check sidebar links
    const sidebarLinks = document.querySelectorAll('.sidebar-link');
    console.log(`✓ Found ${sidebarLinks.length} sidebar links`);
    
    if (sidebarLinks.length === 0) {
        console.error('✗ CRITICAL: No sidebar links found!');
        return;
    }
    
    // Test 3: Check content sections
    const contentSections = document.querySelectorAll('.content-section');
    console.log(`✓ Found ${contentSections.length} content sections`);
    
    if (contentSections.length === 0) {
        console.error('✗ CRITICAL: No content sections found!');
        return;
    }
    
    // Test 4: Manually bind click handlers
    console.log('Manually binding sidebar navigation...');
    sidebarLinks.forEach((link, index) => {
        const section = link.getAttribute('data-section');
        console.log(`  Link ${index}: data-section="${section}"`);
        
        link.addEventListener('click', (e) => {
            e.preventDefault();
            console.log(`CLICK: Navigating to section "${section}"`);
            
            // Remove all active classes
            sidebarLinks.forEach(l => l.classList.remove('active'));
            contentSections.forEach(s => s.classList.remove('active'));
            
            // Add active to clicked link
            link.classList.add('active');
            
            // Show target section
            const targetSection = document.getElementById(section);
            if (targetSection) {
                targetSection.classList.add('active');
                console.log(`✓ Activated section: ${section}`);
            } else {
                console.error(`✗ Section not found: ${section}`);
            }
        });
    });
    
    console.log('✓ Navigation handlers bound');
    
    // Test 5: Check critical elements
    const criticalIds = [
        'price-btc', 'price-eth', 'price-sol', 'price-avax',
        'main-chart-price', 'div-score', 'stat-equity'
    ];
    
    criticalIds.forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            console.log(`✓ Element found: #${id}`);
        } else {
            console.warn(`⚠ Element missing: #${id}`);
        }
    });
    
    // Test 6: Force data fetch
    console.log('Attempting to fetch data...');
    fetch('/api/v1/institutional/realtime/stream')
        .then(res => res.json())
        .then(data => {
            console.log('✓ API Response:', data);
            
            // Update prices manually
            if (data.prices) {
                const btcPrice = data.prices['BTC/USDT'];
                if (btcPrice) {
                    const el = document.getElementById('price-btc');
                    if (el) {
                        el.textContent = `$${btcPrice.price.toLocaleString()}`;
                        console.log(`✓ Updated BTC price: ${btcPrice.price}`);
                    }
                }
            }
        })
        .catch(err => {
            console.error('✗ API Error:', err);
        });
    
    console.log('=== UI TEST COMPLETE ===');
});
