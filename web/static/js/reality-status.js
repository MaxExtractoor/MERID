/**
 * Reality Status Monitor - Polls Reality Registry and enforces blindness mode
 * 
 * CONSTITUTIONAL: This is the UI enforcement layer that prevents fake displays
 */

class RealityStatusMonitor {
    constructor() {
        this.pollInterval = 5000; // Poll every 5 seconds
        this.isBlind = false;
        this.currentStatus = null;
        this.pollTimer = null;
        
        console.log('Reality Status Monitor initialized');
    }
    
    start() {
        console.log('Starting reality status polling...');
        this.poll(); // Initial poll
        this.pollTimer = setInterval(() => this.poll(), this.pollInterval);
    }
    
    stop() {
        if (this.pollTimer) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
        }
    }
    
    async poll() {
        try {
            const response = await fetch('/api/v1/reality/status');
            if (!response.ok) {
                console.error('Failed to fetch reality status:', response.status);
                return;
            }
            
            const status = await response.json();
            this.currentStatus = status;
            
            // Check if blindness mode should be triggered
            const wasBlind = this.isBlind;
            this.isBlind = status.mode === 'BLIND';
            
            // Update UI based on status
            this.updateUI(status);
            
            // Trigger blindness mode if needed
            if (this.isBlind && !wasBlind) {
                console.warn('BLINDNESS MODE ACTIVATED:', status.reason);
                this.activateBlindnessMode(status);
            } else if (!this.isBlind && wasBlind) {
                console.info('BLINDNESS MODE DEACTIVATED - System operational');
                this.deactivateBlindnessMode();
            }
            
        } catch (error) {
            console.error('Error polling reality status:', error);
        }
    }
    
    updateUI(status) {
        // Update reality status panel if it exists
        const statusPanel = document.getElementById('reality-status-panel');
        if (statusPanel) {
            statusPanel.innerHTML = this.renderStatusPanel(status);
        }
        
        // Update mode indicator
        const modeIndicator = document.getElementById('reality-mode');
        if (modeIndicator) {
            modeIndicator.textContent = status.mode;
            modeIndicator.className = `reality-mode mode-${status.mode.toLowerCase()}`;
        }
        
        // Update assertion health
        const assertionHealth = document.getElementById('assertion-health');
        if (assertionHealth) {
            const validPct = status.valid_assertions_pct || 0;
            assertionHealth.textContent = `${validPct.toFixed(1)}%`;
            assertionHealth.className = validPct > 70 ? 'health-good' : validPct > 40 ? 'health-warning' : 'health-critical';
        }
        
        // Update entropy indicator
        const entropyIndicator = document.getElementById('regime-entropy');
        if (entropyIndicator) {
            const entropy = status.regime_entropy || 0;
            entropyIndicator.textContent = entropy.toFixed(3);
            entropyIndicator.className = entropy < 0.5 ? 'entropy-low' : entropy < 0.7 ? 'entropy-medium' : 'entropy-high';
        }
    }
    
    renderStatusPanel(status) {
        return `
            <div class="reality-status-content">
                <div class="status-row">
                    <span class="label">Mode:</span>
                    <span class="value mode-${status.mode.toLowerCase()}">${status.mode}</span>
                </div>
                <div class="status-row">
                    <span class="label">Valid Assertions:</span>
                    <span class="value">${status.valid_assertions_pct?.toFixed(1) || 0}%</span>
                </div>
                <div class="status-row">
                    <span class="label">Regime Entropy:</span>
                    <span class="value">${status.regime_entropy?.toFixed(3) || 0}</span>
                </div>
                <div class="status-row">
                    <span class="label">Conflicts:</span>
                    <span class="value ${status.conflicts > 0 ? 'warning' : ''}">${status.conflicts || 0}</span>
                </div>
                <div class="status-row">
                    <span class="label">Blind Spots:</span>
                    <span class="value ${status.blind_spots?.length > 0 ? 'warning' : ''}">${status.blind_spots?.length || 0}</span>
                </div>
            </div>
        `;
    }
    
    activateBlindnessMode(status) {
        // Show blindness overlay
        const overlay = document.getElementById('blindness-overlay');
        if (overlay) {
            overlay.classList.add('active');
            
            // Update failure panels
            const failurePanels = overlay.querySelector('.failure-panels');
            if (failurePanels && status.blind_spots) {
                failurePanels.innerHTML = status.blind_spots.map(spot => `
                    <div class="failure-panel">
                        <div class="failure-icon">⚠</div>
                        <div class="failure-title">${spot}</div>
                        <div class="failure-desc">Insufficient valid assertions</div>
                    </div>
                `).join('');
            }
        }
        
        // Disable all data displays
        this.disableDataDisplays();
        
        // Show warning banner
        this.showWarningBanner('BLINDNESS MODE: ' + (status.reason || 'Insufficient truth assertions'));
    }
    
    deactivateBlindnessMode() {
        // Hide blindness overlay
        const overlay = document.getElementById('blindness-overlay');
        if (overlay) {
            overlay.classList.remove('active');
        }
        
        // Re-enable data displays
        this.enableDataDisplays();
        
        // Hide warning banner
        this.hideWarningBanner();
    }
    
    disableDataDisplays() {
        // Add 'blind' class to all data containers
        const dataContainers = document.querySelectorAll('.price-ticker, .chart-container, .stats-grid');
        dataContainers.forEach(container => {
            container.classList.add('blind-mode');
        });
    }
    
    enableDataDisplays() {
        // Remove 'blind' class from all data containers
        const dataContainers = document.querySelectorAll('.price-ticker, .chart-container, .stats-grid');
        dataContainers.forEach(container => {
            container.classList.remove('blind-mode');
        });
    }
    
    showWarningBanner(message) {
        let banner = document.getElementById('reality-warning-banner');
        if (!banner) {
            banner = document.createElement('div');
            banner.id = 'reality-warning-banner';
            banner.className = 'reality-warning-banner';
            document.body.prepend(banner);
        }
        banner.textContent = message;
        banner.classList.add('active');
    }
    
    hideWarningBanner() {
        const banner = document.getElementById('reality-warning-banner');
        if (banner) {
            banner.classList.remove('active');
        }
    }
    
    getStatus() {
        return this.currentStatus;
    }
    
    isSystemBlind() {
        return this.isBlind;
    }
}

// Global instance
const realityMonitor = new RealityStatusMonitor();

// Auto-start on DOM load
document.addEventListener('DOMContentLoaded', () => {
    console.log('Starting Reality Status Monitor...');
    realityMonitor.start();
});

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.realityMonitor = realityMonitor;
}
