/**
 * MERID Professional UI Components
 * Version: 2.0.0
 * 
 * Industrial-grade UI with:
 * - Advanced filtering
 * - Sortable tables
 * - Hover tooltips
 * - Real-time updates
 * - No emojis
 */

// ============================================
// TOOLTIP SYSTEM
// ============================================
const TooltipManager = {
    init() {
        document.addEventListener('mouseover', this.handleMouseOver.bind(this));
        document.addEventListener('mouseout', this.handleMouseOut.bind(this));
    },

    handleMouseOver(e) {
        const target = e.target.closest('[data-tooltip]');
        if (!target) return;
        
        // Tooltip is handled by CSS, but we can add dynamic tooltips here
        const tooltip = target.getAttribute('data-tooltip');
        if (tooltip && tooltip.startsWith('fn:')) {
            const fnName = tooltip.substring(3);
            if (typeof window[fnName] === 'function') {
                target.setAttribute('data-tooltip', window[fnName](target));
            }
        }
    },

    handleMouseOut(e) {
        // Cleanup if needed
    },

    setTooltip(element, text) {
        element.setAttribute('data-tooltip', text);
    },

    removeTooltip(element) {
        element.removeAttribute('data-tooltip');
    }
};

// ============================================
// FILTER SYSTEM
// ============================================
const FilterManager = {
    filters: {},
    callbacks: {},

    init() {
        document.querySelectorAll('[data-filter]').forEach(el => {
            el.addEventListener('change', this.handleFilterChange.bind(this));
            el.addEventListener('input', this.debounce(this.handleFilterChange.bind(this), 300));
        });
    },

    handleFilterChange(e) {
        const filterName = e.target.dataset.filter;
        const filterValue = e.target.value;
        
        this.filters[filterName] = filterValue;
        this.applyFilters();
        
        if (this.callbacks[filterName]) {
            this.callbacks[filterName](filterValue);
        }
    },

    applyFilters() {
        const containers = document.querySelectorAll('[data-filterable]');
        
        containers.forEach(container => {
            const items = container.querySelectorAll('[data-filter-item]');
            
            items.forEach(item => {
                let visible = true;
                
                for (const [filterName, filterValue] of Object.entries(this.filters)) {
                    if (!filterValue || filterValue === 'all') continue;
                    
                    const itemValue = item.dataset[filterName] || item.dataset.filterItem;
                    if (itemValue && !itemValue.toLowerCase().includes(filterValue.toLowerCase())) {
                        visible = false;
                        break;
                    }
                }
                
                item.style.display = visible ? '' : 'none';
            });
        });
    },

    registerCallback(filterName, callback) {
        this.callbacks[filterName] = callback;
    },

    setFilter(filterName, value) {
        this.filters[filterName] = value;
        const el = document.querySelector(`[data-filter="${filterName}"]`);
        if (el) el.value = value;
        this.applyFilters();
    },

    clearFilters() {
        this.filters = {};
        document.querySelectorAll('[data-filter]').forEach(el => {
            el.value = el.querySelector('option')?.value || '';
        });
        this.applyFilters();
    },

    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    }
};

// ============================================
// SORTABLE TABLE SYSTEM
// ============================================
const TableSorter = {
    init() {
        document.querySelectorAll('.data-table th.sortable').forEach(th => {
            th.addEventListener('click', this.handleSort.bind(this));
        });
    },

    handleSort(e) {
        const th = e.target.closest('th');
        const table = th.closest('table');
        const tbody = table.querySelector('tbody');
        const columnIndex = Array.from(th.parentNode.children).indexOf(th);
        const isAsc = th.classList.contains('asc');
        
        // Remove sort classes from all headers
        table.querySelectorAll('th').forEach(header => {
            header.classList.remove('asc', 'desc');
        });
        
        // Set new sort direction
        th.classList.add(isAsc ? 'desc' : 'asc');
        
        // Sort rows
        const rows = Array.from(tbody.querySelectorAll('tr'));
        const sortType = th.dataset.sortType || 'string';
        
        rows.sort((a, b) => {
            const aVal = a.children[columnIndex]?.textContent.trim() || '';
            const bVal = b.children[columnIndex]?.textContent.trim() || '';
            
            let comparison = 0;
            
            if (sortType === 'number') {
                const aNum = parseFloat(aVal.replace(/[^0-9.-]/g, '')) || 0;
                const bNum = parseFloat(bVal.replace(/[^0-9.-]/g, '')) || 0;
                comparison = aNum - bNum;
            } else if (sortType === 'date') {
                comparison = new Date(aVal) - new Date(bVal);
            } else {
                comparison = aVal.localeCompare(bVal);
            }
            
            return isAsc ? -comparison : comparison;
        });
        
        rows.forEach(row => tbody.appendChild(row));
    }
};

// ============================================
// METRIC FORMATTER
// ============================================
const MetricFormatter = {
    formatNumber(value, decimals = 2) {
        if (typeof value !== 'number') value = parseFloat(value) || 0;
        
        if (Math.abs(value) >= 1e9) {
            return (value / 1e9).toFixed(decimals) + 'B';
        } else if (Math.abs(value) >= 1e6) {
            return (value / 1e6).toFixed(decimals) + 'M';
        } else if (Math.abs(value) >= 1e3) {
            return (value / 1e3).toFixed(decimals) + 'K';
        }
        return value.toFixed(decimals);
    },

    formatCurrency(value, currency = 'USD') {
        if (typeof value !== 'number') value = parseFloat(value) || 0;
        
        const formatted = this.formatNumber(Math.abs(value));
        const sign = value < 0 ? '-' : '';
        
        if (currency === 'USD') {
            return sign + '$' + formatted;
        }
        return sign + formatted + ' ' + currency;
    },

    formatPercent(value, decimals = 2) {
        if (typeof value !== 'number') value = parseFloat(value) || 0;
        const sign = value > 0 ? '+' : '';
        return sign + value.toFixed(decimals) + '%';
    },

    formatDuration(seconds) {
        if (seconds < 60) return Math.round(seconds) + 's';
        if (seconds < 3600) return Math.round(seconds / 60) + 'm';
        if (seconds < 86400) return Math.round(seconds / 3600) + 'h';
        return Math.round(seconds / 86400) + 'd';
    },

    formatTimestamp(timestamp) {
        const date = new Date(timestamp * 1000);
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });
    },

    formatRelativeTime(timestamp) {
        const now = Date.now() / 1000;
        const diff = now - timestamp;
        
        if (diff < 60) return 'just now';
        if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
        if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
        return Math.floor(diff / 86400) + 'd ago';
    }
};

// ============================================
// STATUS INDICATOR SYSTEM
// ============================================
const StatusIndicator = {
    getStatusClass(status) {
        const statusMap = {
            'operational': 'success',
            'healthy': 'success',
            'running': 'success',
            'active': 'success',
            'completed': 'success',
            'degraded': 'warning',
            'warning': 'warning',
            'pending': 'warning',
            'paused': 'warning',
            'down': 'danger',
            'error': 'danger',
            'failed': 'danger',
            'critical': 'danger',
            'stopped': 'danger',
            'unknown': 'neutral',
            'idle': 'neutral'
        };
        return statusMap[status.toLowerCase()] || 'neutral';
    },

    createBadge(status, text = null) {
        const statusClass = this.getStatusClass(status);
        const displayText = text || status.toUpperCase();
        return `<span class="status-badge ${statusClass}">${displayText}</span>`;
    },

    createDot(status) {
        const dotClass = this.getStatusClass(status);
        const classMap = {
            'success': 'operational',
            'warning': 'degraded',
            'danger': 'down',
            'neutral': 'unknown'
        };
        return `<span class="status-dot ${classMap[dotClass] || 'unknown'}"></span>`;
    },

    createIndicator(status, text = null) {
        return `<span class="status-indicator">${this.createDot(status)} ${text || status}</span>`;
    }
};

// ============================================
// DATA RENDERER
// ============================================
const DataRenderer = {
    renderTable(data, columns, options = {}) {
        const { sortable = true, filterable = false, emptyMessage = 'No data available' } = options;
        
        if (!data || data.length === 0) {
            return `<div class="empty-state-pro">
                <svg class="icon" viewBox="0 0 24 24"><path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14H6v-2h6v2zm4-4H6v-2h10v2zm0-4H6V7h10v2z"/></svg>
                <div class="title">${emptyMessage}</div>
            </div>`;
        }
        
        let html = '<table class="data-table">';
        
        // Header
        html += '<thead><tr>';
        columns.forEach(col => {
            const sortClass = sortable && col.sortable !== false ? 'sortable' : '';
            const sortType = col.type || 'string';
            const tooltip = col.tooltip ? `data-tooltip="${col.tooltip}"` : '';
            html += `<th class="${sortClass}" data-sort-type="${sortType}" ${tooltip}>${col.label}</th>`;
        });
        html += '</tr></thead>';
        
        // Body
        html += '<tbody>';
        data.forEach(row => {
            const filterAttr = filterable ? `data-filter-item="${row.type || ''}"` : '';
            html += `<tr ${filterAttr}>`;
            columns.forEach(col => {
                const value = this.getValue(row, col.key);
                const formatted = this.formatValue(value, col);
                const cellClass = this.getCellClass(value, col);
                const tooltip = col.cellTooltip ? `data-tooltip="${this.getValue(row, col.cellTooltip)}"` : '';
                html += `<td class="${cellClass}" ${tooltip}>${formatted}</td>`;
            });
            html += '</tr>';
        });
        html += '</tbody></table>';
        
        return html;
    },

    getValue(obj, path) {
        if (!path) return '';
        return path.split('.').reduce((o, k) => (o || {})[k], obj) ?? '';
    },

    formatValue(value, col) {
        if (value === null || value === undefined) return '-';
        
        switch (col.type) {
            case 'number':
                return MetricFormatter.formatNumber(value, col.decimals || 2);
            case 'currency':
                return MetricFormatter.formatCurrency(value, col.currency);
            case 'percent':
                return MetricFormatter.formatPercent(value, col.decimals || 2);
            case 'timestamp':
                return MetricFormatter.formatTimestamp(value);
            case 'relative':
                return MetricFormatter.formatRelativeTime(value);
            case 'duration':
                return MetricFormatter.formatDuration(value);
            case 'status':
                return StatusIndicator.createBadge(value);
            case 'boolean':
                return value ? 'Yes' : 'No';
            default:
                return this.escapeHtml(String(value));
        }
    },

    getCellClass(value, col) {
        let classes = [];
        
        if (col.type === 'number' || col.type === 'currency' || col.type === 'percent') {
            classes.push('cell-number');
            if (typeof value === 'number') {
                if (value > 0 && col.colorize) classes.push('cell-positive');
                if (value < 0 && col.colorize) classes.push('cell-negative');
            }
        }
        
        if (col.mono) classes.push('cell-mono');
        if (col.muted) classes.push('cell-muted');
        
        return classes.join(' ');
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    renderMetricCard(metric) {
        const changeClass = metric.change > 0 ? 'up' : metric.change < 0 ? 'down' : 'neutral';
        const changeIcon = metric.change > 0 ? '&#9650;' : metric.change < 0 ? '&#9660;' : '';
        const valueClass = metric.positive ? 'positive' : metric.negative ? 'negative' : '';
        
        return `
            <div class="metric-card" data-tooltip="${metric.tooltip || ''}">
                <div class="metric-header">
                    <span class="metric-label">${metric.label}</span>
                </div>
                <div class="metric-value ${valueClass}">${metric.value}</div>
                ${metric.change !== undefined ? `
                    <div class="metric-change ${changeClass}">
                        ${changeIcon} ${MetricFormatter.formatPercent(Math.abs(metric.change))}
                    </div>
                ` : ''}
                ${metric.footer ? `<div class="metric-footer">${metric.footer}</div>` : ''}
            </div>
        `;
    },

    renderProgressBar(value, max = 100, options = {}) {
        const percent = Math.min(100, Math.max(0, (value / max) * 100));
        const colorClass = options.color || (percent > 80 ? 'danger' : percent > 60 ? 'warning' : '');
        
        return `
            <div class="progress-bar" data-tooltip="${value}/${max}">
                <div class="progress-bar-fill ${colorClass}" style="width: ${percent}%"></div>
            </div>
        `;
    }
};

// ============================================
// REAL-TIME UPDATE MANAGER
// ============================================
const RealtimeManager = {
    intervals: {},
    callbacks: {},

    register(id, callback, intervalMs = 5000) {
        this.callbacks[id] = callback;
        this.intervals[id] = setInterval(() => {
            if (typeof callback === 'function') {
                callback();
            }
        }, intervalMs);
    },

    unregister(id) {
        if (this.intervals[id]) {
            clearInterval(this.intervals[id]);
            delete this.intervals[id];
            delete this.callbacks[id];
        }
    },

    pause(id) {
        if (this.intervals[id]) {
            clearInterval(this.intervals[id]);
            delete this.intervals[id];
        }
    },

    resume(id, intervalMs = 5000) {
        if (this.callbacks[id] && !this.intervals[id]) {
            this.intervals[id] = setInterval(this.callbacks[id], intervalMs);
        }
    },

    triggerNow(id) {
        if (this.callbacks[id]) {
            this.callbacks[id]();
        }
    },

    pauseAll() {
        Object.keys(this.intervals).forEach(id => this.pause(id));
    },

    resumeAll(intervalMs = 5000) {
        Object.keys(this.callbacks).forEach(id => this.resume(id, intervalMs));
    }
};

// ============================================
// NOTIFICATION SYSTEM (UI)
// ============================================
const NotificationUI = {
    container: null,

    init() {
        this.container = document.createElement('div');
        this.container.id = 'notification-container';
        this.container.style.cssText = `
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 9999;
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-width: 400px;
        `;
        document.body.appendChild(this.container);
    },

    show(message, type = 'info', duration = 5000) {
        if (!this.container) this.init();
        
        const notification = document.createElement('div');
        notification.className = `notification-toast notification-${type}`;
        notification.style.cssText = `
            padding: 12px 16px;
            background: var(--color-bg-elevated);
            border: 1px solid var(--color-border);
            border-left: 3px solid var(--color-${type === 'error' ? 'danger' : type === 'success' ? 'success' : type === 'warning' ? 'warning' : 'info'});
            border-radius: 4px;
            color: var(--color-text-primary);
            font-size: 13px;
            box-shadow: var(--shadow-md);
            animation: slideIn 0.2s ease;
        `;
        notification.textContent = message;
        
        this.container.appendChild(notification);
        
        if (duration > 0) {
            setTimeout(() => {
                notification.style.animation = 'slideOut 0.2s ease';
                setTimeout(() => notification.remove(), 200);
            }, duration);
        }
        
        return notification;
    },

    success(message, duration) { return this.show(message, 'success', duration); },
    error(message, duration) { return this.show(message, 'error', duration); },
    warning(message, duration) { return this.show(message, 'warning', duration); },
    info(message, duration) { return this.show(message, 'info', duration); }
};

// ============================================
// INITIALIZATION
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    TooltipManager.init();
    FilterManager.init();
    TableSorter.init();
    NotificationUI.init();
    
    // Add animation styles
    const style = document.createElement('style');
    style.textContent = `
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes slideOut {
            from { transform: translateX(0); opacity: 1; }
            to { transform: translateX(100%); opacity: 0; }
        }
    `;
    document.head.appendChild(style);
});

// Export for global use
window.MERID = window.MERID || {};
window.MERID.UI = {
    TooltipManager,
    FilterManager,
    TableSorter,
    MetricFormatter,
    StatusIndicator,
    DataRenderer,
    RealtimeManager,
    NotificationUI
};
