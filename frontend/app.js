// API Base URL
const API_BASE = 'http://localhost:8000';

// Global state
let dashboardData = null;
let categoryChart = null;
let vendorChart = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    // Clear backend cache on page load
    try {
        await fetch(`${API_BASE}/clear`, { method: 'POST' });
    } catch (error) {
        console.log('Cache clear skipped:', error);
    }

    setupEventListeners();
});

// Setup event listeners
function setupEventListeners() {
    document.getElementById('uploadBtn').addEventListener('click', () => {
        document.getElementById('csvFile').click();
    });

    document.getElementById('uploadInvoiceBtn').addEventListener('click', () => {
        document.getElementById('invoiceFile').click();
    });

    document.getElementById('csvFile').addEventListener('change', handleFileUpload);

    document.getElementById('invoiceFile').addEventListener('change', handleInvoiceUpload);

    document.getElementById('toggleAnomalies').addEventListener('click', toggleAnomaliesView);

    // Add invoice upload handler
    const invoiceBtn = document.getElementById('uploadInvoiceBtn');
    if (invoiceBtn) {
        invoiceBtn.addEventListener('click', () => {
            document.getElementById('invoiceFile').click();
        });
    }

    const invoiceFile = document.getElementById('invoiceFile');
    if (invoiceFile) {
        invoiceFile.addEventListener('change', handleInvoiceUpload);
    }

    // Navbar scroll effect
    let lastScrollY = window.scrollY;
    const navbar = document.querySelector('.navbar');
    if (navbar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 50) {
                navbar.classList.add('floating');
            } else {
                navbar.classList.remove('floating');
            }

            if (window.scrollY > lastScrollY && window.scrollY > 100) {
                navbar.classList.add('hide');
            } else {
                navbar.classList.remove('hide');
            }
            lastScrollY = window.scrollY;
        });
    }
}

// T051: Handle invoice file upload
async function handleInvoiceUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const uploadStatus = document.getElementById('uploadStatus');
    uploadStatus.textContent = 'Processing invoice...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload-invoice`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Invoice upload failed');
        }

        const result = await response.json();

        if (result.status === 'already_processed') {
            uploadStatus.textContent = `✓ Invoice already processed`;
            alert('This invoice was already processed.');
        } else {
            uploadStatus.textContent = `✓ Invoice processed: ${result.invoice_data.vendor} - $${result.invoice_data.amounts.total} (${(result.invoice_data.confidence * 100).toFixed(0)}% confidence)`;

            // Show extracted data
            showInvoiceModal(result.invoice_data);

            // Reload dashboard if data exists
            if (dashboardData) {
                await loadDashboard();
            }
        }

    } catch (error) {
        uploadStatus.textContent = `✗ Error: ${error.message}`;
        console.error('Invoice upload error:', error);

        // Check if Tesseract error
        if (error.message.includes('Tesseract')) {
            alert('Tesseract OCR is not installed. Please install it first.\n\nSee TESSERACT_INSTALL.md for instructions.');
        }
    }
}

// Show invoice extraction results in modal
function showInvoiceModal(invoiceData) {
    const modal = document.createElement('div');
    modal.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0,0,0,0.8);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 10000;
    `;

    const content = document.createElement('div');
    content.style.cssText = `
        background: white;
        padding: 30px;
        border-radius: 10px;
        max-width: 600px;
        max-height: 80vh;
        overflow-y: auto;
    `;

    const lineItemsHtml = invoiceData.line_items && invoiceData.line_items.length > 0
        ? `
            <h3>Line Items:</h3>
            <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
                <thead>
                    <tr style="border-bottom: 2px solid #ddd;">
                        <th style="text-align: left; padding: 8px;">Description</th>
                        <th style="text-align: right; padding: 8px;">Qty</th>
                        <th style="text-align: right; padding: 8px;">Price</th>
                        <th style="text-align: right; padding: 8px;">Total</th>
                    </tr>
                </thead>
                <tbody>
                    ${invoiceData.line_items.map(item => `
                        <tr style="border-bottom: 1px solid #eee;">
                            <td style="padding: 8px;">${item.description}</td>
                            <td style="text-align: right; padding: 8px;">${item.quantity}</td>
                            <td style="text-align: right; padding: 8px;">$${item.unit_price.toFixed(2)}</td>
                            <td style="text-align: right; padding: 8px;">$${item.total.toFixed(2)}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `
        : '<p style="color: #666;">No line items detected</p>';

    content.innerHTML = `
        <h2 style="margin-top: 0;">Invoice Extracted Successfully</h2>
        <div style="margin: 20px 0;">
            <p><strong>Vendor:</strong> ${invoiceData.vendor}</p>
            <p><strong>Invoice Number:</strong> ${invoiceData.invoice_number || 'Not detected'}</p>
            <p><strong>Date:</strong> ${invoiceData.date || 'Not detected'}</p>
            <p><strong>Total Amount:</strong> $${invoiceData.amounts.total?.toFixed(2) || '0.00'}</p>
            ${invoiceData.amounts.subtotal ? `<p><strong>Subtotal:</strong> $${invoiceData.amounts.subtotal.toFixed(2)}</p>` : ''}
            ${invoiceData.amounts.tax ? `<p><strong>Tax:</strong> $${invoiceData.amounts.tax.toFixed(2)}</p>` : ''}
            <p><strong>Confidence:</strong> ${(invoiceData.confidence * 100).toFixed(0)}%</p>
        </div>
        ${lineItemsHtml}
        <div style="margin-top: 20px;">
            <button onclick="this.closest('div').parentElement.parentElement.remove()" style="
                background: #667eea;
                color: white;
                border: none;
                padding: 10px 20px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 16px;
            ">Close</button>
        </div>
    `;

    modal.appendChild(content);
    document.body.appendChild(modal);

    // Close on background click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.remove();
        }
    });
}

// T051: Handle CSV file upload
async function handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    const uploadStatus = document.getElementById('uploadStatus');
    uploadStatus.textContent = 'Uploading...';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/upload`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Upload failed');
        }

        const result = await response.json();
        uploadStatus.textContent = `✓ Processed ${result.transaction_count} transactions in ${result.processing_time_ms}ms`;

        // Load dashboard data
        await loadDashboard();

    } catch (error) {
        uploadStatus.textContent = `✗ Error: ${error.message}`;
        console.error('Upload error:', error);
    }
}

// T051: Load dashboard data from API
async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE}/dashboard`);
        if (!response.ok) {
            throw new Error('Failed to load dashboard');
        }

        dashboardData = await response.json();

        // Hide empty state, show dashboard
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('dashboardContent').style.display = 'block';

        // Render all sections
        renderKeyMetrics(dashboardData.summary);
        renderInsights(dashboardData.insights);
        renderActions(dashboardData.actions);
        renderCharts(dashboardData.summary);
        renderAnomalies(dashboardData.anomalies);

    } catch (error) {
        console.error('Dashboard load error:', error);
        alert('Failed to load dashboard: ' + error.message);
    }
}

// T052: Render key metrics section
function renderKeyMetrics(summary) {
    document.getElementById('totalSpend').textContent = `$${summary.total_spend.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}`;
    document.getElementById('anomalyCount').textContent = summary.anomaly_count;
    document.getElementById('anomalyPercent').textContent = `${summary.anomaly_percentage}% of transactions`;
    document.getElementById('categoriesCount').textContent = summary.categories_tracked;
    document.getElementById('highRiskCount').textContent = summary.high_risk_count;
}

// T053: Render insights panel
function renderInsights(insights) {
    const panel = document.getElementById('insightsPanel');
    const noInsights = document.getElementById('noInsights');

    if (insights.length === 0) {
        panel.style.display = 'none';
        noInsights.style.display = 'block';
        return;
    }

    panel.style.display = 'grid';
    noInsights.style.display = 'none';
    panel.innerHTML = '';

    insights.forEach(insight => {
        const card = document.createElement('div');
        card.className = `insight-card ${insight.severity}`;
        card.onclick = () => filterAnomaliesByInsight(insight);

        let iconName = 'bar-chart-2';
        if (insight.severity === 'high') iconName = 'alert-triangle';
        else if (insight.severity === 'medium') iconName = 'zap';

        card.innerHTML = `
            <div class="insight-header">
                <div class="insight-icon-box ${insight.severity}">
                    <i data-lucide="${iconName}" size="16"></i>
                </div>
                <h3 class="insight-title">${insight.title}</h3>
            </div>
            <p class="insight-description">${insight.description}</p>
            ${insight.impact_amount ? `<div class="insight-pill impact">Impact: $${insight.impact_amount.toLocaleString('en-US', {minimumFractionDigits: 2})}</div>` : ''}
        `;

        panel.appendChild(card);
    });

    if (window.lucide) window.lucide.createIcons();
}

// T054: Render recommended actions
function renderActions(actions) {
    const panel = document.getElementById('actionsPanel');
    const noActions = document.getElementById('noActions');

    if (actions.length === 0) {
        panel.style.display = 'none';
        noActions.style.display = 'block';
        return;
    }

    panel.style.display = 'grid';
    noActions.style.display = 'none';
    panel.innerHTML = '';

    actions.forEach(action => {
        const card = document.createElement('div');
        card.className = 'action-card';

        const priorityClass = action.priority;
        const statusHtml = action.status === 'executed'
            ? '<span class="action-status executed">Executed</span>'
            : action.status === 'dismissed'
            ? '<span class="action-status dismissed">Dismissed</span>'
            : `
                <div class="action-buttons">
                    <button class="btn-execute" onclick="executeAction('${action.id}')" ${!action.auto_executable ? 'disabled title="Requires human approval"' : ''}>
                        ${action.auto_executable ? 'Execute' : 'Manual Only'}
                    </button>
                    <button class="btn-dismiss" onclick="dismissAction('${action.id}')">Dismiss</button>
                </div>
            `;

        card.innerHTML = `
            <div class="action-info">
                <div class="action-header">
                    <h3 class="action-title">${action.title}</h3>
                    <span class="priority-badge ${priorityClass}">${action.priority.toUpperCase()}</span>
                </div>
                <p class="action-description">${action.description}</p>
            </div>
            ${statusHtml}
        `;

        panel.appendChild(card);
    });
}

// T055: Render spend breakdown charts
function renderCharts(summary) {
    if (categoryChart) categoryChart.destroy();
    if (vendorChart) vendorChart.destroy();

    Chart.defaults.color = '#888888';
    Chart.defaults.font.family = "'Inter', sans-serif";

    // Vibrant but tasteful minimal palette (Linear/Vercel inspired)
    const sleekPalette = [
        '#60A5FA', '#34D399', '#A78BFA', '#F472B6', 
        '#FBBF24', '#38BDF8', '#818CF8', '#E879F9'
    ];

    const categoryCtx = document.getElementById('categoryChart').getContext('2d');
    const categoryLabels = Object.keys(summary.category_breakdown);
    const categoryData = Object.values(summary.category_breakdown);

    categoryChart = new Chart(categoryCtx, {
        type: 'doughnut',
        data: {
            labels: categoryLabels,
            datasets: [{
                data: categoryData,
                backgroundColor: sleekPalette,
                borderWidth: 0,
                hoverOffset: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '80%',
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#EDEDED', boxWidth: 12, padding: 15, usePointStyle: true }
                },
                tooltip: {
                    backgroundColor: '#111111',
                    titleColor: '#888888',
                    bodyColor: '#EDEDED',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    padding: 12,
                    callbacks: { label: c => ` $${c.parsed.toLocaleString('en-US', {minimumFractionDigits: 2})}` }
                }
            }
        }
    });

    const vendorCtx = document.getElementById('vendorChart').getContext('2d');
    const vendorLabels = summary.top_vendors.map(v => v.vendor.charAt(0).toUpperCase() + v.vendor.slice(1));
    const vendorData = summary.top_vendors.map(v => v.amount);

    vendorChart = new Chart(vendorCtx, {
        type: 'bar',
        data: {
            labels: vendorLabels,
            datasets: [{
                label: 'Total Spend',
                data: vendorData,
                backgroundColor: '#60A5FA',
                borderRadius: 4,
                barPercentage: 0.5
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111111',
                    titleColor: '#888888',
                    bodyColor: '#EDEDED',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    padding: 12,
                    displayColors: false,
                    callbacks: { label: c => `$${c.parsed.y.toLocaleString('en-US', {minimumFractionDigits: 2})}` }
                }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#888888', font: { size: 11 } } },
                y: { grid: { color: 'rgba(255,255,255,0.05)', borderDash: [4, 4] }, ticks: { color: '#888888', font: { size: 11 }, callback: v => '$' + v.toLocaleString() } }
            }
        }
    });
}

// T056: Render anomalies table
function renderAnomalies(anomalies) {
    const tbody = document.getElementById('anomaliesTableBody');
    const noAnomalies = document.getElementById('noAnomalies');
    const table = document.getElementById('anomaliesTable');

    if (anomalies.length === 0) {
        table.style.display = 'none';
        noAnomalies.style.display = 'block';
        return;
    }

    table.style.display = 'table';
    noAnomalies.style.display = 'none';
    tbody.innerHTML = '';

    anomalies.forEach(anomaly => {
        const row = document.createElement('tr');
        row.className = 'anomaly-row';

        const scoreClass = anomaly.anomaly_score >= 8 ? 'score-high' : 'score-medium';
        const confidenceClass = anomaly.confidence === 'High' ? 'confidence-high' : 'confidence-medium';

        const reasons = Array.isArray(anomaly.anomaly_reasons)
            ? anomaly.anomaly_reasons.join('; ')
            : anomaly.anomaly_reasons;

        row.innerHTML = `
            <td>${anomaly.date}</td>
            <td>${anomaly.vendor.charAt(0).toUpperCase() + anomaly.vendor.slice(1)}</td>
            <td>$${anomaly.amount_float.toLocaleString('en-US', {minimumFractionDigits: 2})}</td>
            <td>${anomaly.category}</td>
            <td><span class="score-badge ${scoreClass}">${anomaly.anomaly_score}/10</span></td>
            <td><span class="confidence-badge ${confidenceClass}">${anomaly.confidence}</span></td>
            <td class="reasons-list">${reasons}</td>
        `;

        tbody.appendChild(row);
    });
}

// T057: Filter anomaly table by insight click
function filterAnomaliesByInsight(insight) {
    // Extract category from insight title if it's a cost spike
    if (insight.type === 'cost_spike') {
        const category = insight.title.split(' spending')[0];
        const filteredAnomalies = dashboardData.anomalies.filter(a => a.category === category);
        renderAnomalies(filteredAnomalies);
    } else {
        // For other insights, show all anomalies
        renderAnomalies(dashboardData.anomalies);
    }

    // Scroll to anomalies section
    document.getElementById('anomaliesSection').scrollIntoView({ behavior: 'smooth' });
}

// Toggle between anomalies and all transactions
function toggleAnomaliesView() {
    const btn = document.getElementById('toggleAnomalies');
    if (btn.textContent.includes('All')) {
        // Show all transactions (not implemented in MVP - would need to fetch from /transactions)
        btn.textContent = 'Show Only Anomalies';
    } else {
        // Show only anomalies
        renderAnomalies(dashboardData.anomalies);
        btn.textContent = 'Show All Transactions';
    }
}

// T059: Execute action
async function executeAction(actionId) {
    try {
        const response = await fetch(`${API_BASE}/actions/${actionId}/execute`, {
            method: 'POST'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Execution failed');
        }

        const result = await response.json();
        // Remove emoji alert
        console.log(`Executed action ${result.message}`);

        // Reload dashboard to show updated action status
        await loadDashboard();

    } catch (error) {
        // Remove emoji alert
        console.error('Execute error:', error);
    }
}

// T060: Dismiss action
async function dismissAction(actionId) {
    try {
        const response = await fetch(`${API_BASE}/actions/${actionId}/dismiss`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error('Dismiss failed');
        }

        // Reload dashboard to show updated action status
        await loadDashboard();

    } catch (error) {
        console.error('Dismiss error:', error);
    }
}
