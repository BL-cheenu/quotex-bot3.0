/**
 * Astra Engine v11.0 — Dashboard
 */

// ══════════════════════════════════════════════
// STATE
// ══════════════════════════════════════════════
let ws = null;
let logEntries = 0;
let tradeCount = 0;
let isRunning = false;
let countdownMax = 0;

// ══════════════════════════════════════════════
// DOM REFS
// ══════════════════════════════════════════════
const $ = (id) => document.getElementById(id);

const dom = {
    connectionDot: $('connectionDot'),
    connectionText: $('connectionText'),
    connectionBadge: $('connectionBadge'),
    btnStart: $('btnStart'),
    btnStop: $('btnStop'),
    statBalance: $('statBalance'),
    statPnl: $('statPnl'),
    statTrades: $('statTrades'),
    statWinRate: $('statWinRate'),
    statWL: $('statWL'),
    statAmount: $('statAmount'),
    statAccount: $('statAccount'),
    statName: $('statName'),
    statHTF: $('statHTF'),
    countdownBar: $('countdownBar'),
    countdownLabel: $('countdownLabel'),
    countdownValue: $('countdownValue'),
    countdownProgress: $('countdownProgress'),
    scanBar: $('scanBar'),
    scanProgress: $('scanProgress'),
    scanCount: $('scanCount'),
    signalPanel: $('signalPanel'),
    signalBadge: $('signalBadge'),
    signalEmpty: $('signalEmpty'),
    signalGrid: $('signalGrid'),
    logScroll: $('logScroll'),
    logCount: $('logCount'),
    tradesScroll: $('tradesScroll'),
    tradesCount: $('tradesCount'),
    mgVisual: $('mgVisual'),
};

// ══════════════════════════════════════════════
// WEBSOCKET
// ══════════════════════════════════════════════
function connectWS() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        setConnectionStatus('connected', 'Connected');
        addLog('WebSocket connected', 'info');
    };

    ws.onclose = () => {
        setConnectionStatus('disconnected', 'Disconnected');
        addLog('WebSocket disconnected — reconnecting...', 'warn');
        setTimeout(connectWS, 3000);
    };

    ws.onerror = () => {
        setConnectionStatus('disconnected', 'Error');
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleEvent(msg.type, msg.data);
        } catch (e) {
            console.error('WS parse error:', e);
        }
    };
}

function setConnectionStatus(status, text) {
    dom.connectionDot.className = 'connection-dot ' + status;
    dom.connectionText.textContent = text;
}

// ══════════════════════════════════════════════
// EVENT HANDLERS
// ══════════════════════════════════════════════
function handleEvent(type, data) {
    switch (type) {
        case 'log':
            addLog(data.msg);
            break;

        case 'error':
            addLog('✘ ' + data.msg, 'error');
            break;

        case 'connected':
            dom.statAccount.textContent = data.account;
            dom.statName.textContent = data.name;
            dom.statHTF.textContent = data.htf;
            dom.statBalance.textContent = '₹' + data.balance.toFixed(2);
            addLog(`✔ Connected as ${data.name} | ${data.account}`, 'success');
            break;

        case 'status_update':
            updateStatus(data);
            break;

        case 'countdown':
            showCountdown(data.seconds, data.label);
            break;

        case 'scan_start':
            showScanBar(data.total);
            break;

        case 'scan_progress':
            updateScanProgress(data.done, data.total);
            break;

        case 'asset_update':
            handleAssetUpdate(data);
            break;

        case 'signal_found':
            showSignal(data);
            break;

        case 'trade_entry':
            addLog(`▶ TRADE: ${data.asset} ${data.signal.toUpperCase()} ₹${data.amount} (${data.confidence}%)`, 'info');
            break;

        case 'trade_result':
            handleTradeResult(data);
            break;

        case 'bot_stopped':
            handleBotStopped(data);
            break;
    }
}

// ══════════════════════════════════════════════
// UI UPDATES
// ══════════════════════════════════════════════
function updateStatus(data) {
    dom.statBalance.textContent = '₹' + data.balance.toFixed(2);

    const pnl = data.pnl;
    dom.statPnl.textContent = (pnl >= 0 ? '+₹' : '-₹') + Math.abs(pnl).toFixed(2);
    dom.statPnl.className = 'stat-value ' + (pnl >= 0 ? 'positive' : 'negative');

    dom.statTrades.textContent = data.trades;

    const wr = data.win_rate;
    dom.statWinRate.textContent = wr.toFixed(1) + '%';
    dom.statWinRate.className = 'stat-value ' + (wr >= 60 ? 'positive' : wr >= 50 ? 'yellow' : 'negative');

    dom.statWL.innerHTML =
        `<span style="color:var(--green)">${data.wins}</span>` +
        `<span style="color:var(--text-dim)"> / </span>` +
        `<span style="color:var(--red)">${data.losses}</span>`;

    dom.statAmount.textContent = '₹' + data.amount;

    isRunning = data.running;
    dom.btnStart.disabled = isRunning;
    dom.btnStop.disabled = !isRunning;

    if (isRunning) {
        setConnectionStatus('running', 'Running');
    } else {
        setConnectionStatus('connected', 'Connected');
    }

    // Update MG visual
    updateMGVisual(data.mg_step || 0);
}

function updateMGVisual(step) {
    const dots = dom.mgVisual.querySelectorAll('.mg-dot');
    dots.forEach((dot, i) => {
        dot.classList.remove('active', 'base');
        if (i === 0) {
            dot.classList.add(step === 0 ? 'base' : '');
        }
        if (i <= step && step > 0) {
            dot.classList.add('active');
        } else if (i === 0 && step === 0) {
            dot.classList.add('base');
        }
    });
}

function showCountdown(seconds, label) {
    dom.countdownBar.style.display = 'flex';
    
    // Target the inner text span if it exists, otherwise fallback to the label container
    const textSpan = $('countdownText');
    if (textSpan) {
        textSpan.textContent = label;
    } else {
        dom.countdownLabel.textContent = label;
    }
    
    dom.countdownValue.textContent = seconds + 's';

    if (seconds > countdownMax) countdownMax = seconds;
    const pct = countdownMax > 0 ? (seconds / countdownMax) * 100 : 100;
    dom.countdownProgress.style.width = pct + '%';

    if (seconds <= 0) {
        countdownMax = 0;
        setTimeout(() => { dom.countdownBar.style.display = 'none'; }, 500);
    }
}

function showScanBar(total) {
    dom.scanBar.classList.add('active');
    dom.scanCount.textContent = `0/${total}`;
    dom.scanProgress.style.width = '0%';
    hideScanBarLater();
}

function updateScanProgress(done, total) {
    dom.scanCount.textContent = `${done}/${total}`;
    dom.scanProgress.style.width = (done / total * 100) + '%';
    if (done >= total) {
        hideScanBarLater();
    }
}

function hideScanBarLater() {
    setTimeout(() => { dom.scanBar.classList.remove('active'); }, 3000);
}

function handleAssetUpdate(data) {
    if (data.status === 'signal') {
        addLog(`✓ ${data.asset} → ${data.decision.toUpperCase()} ${data.confidence}%`, 'success');
    } else if (data.status === 'blacklisted') {
        addLog(`⊘ ${data.asset} [BL] ${data.reason}`, 'warn');
    }
    // Don't log every rejected asset to avoid flooding
}

function showSignal(data) {
    dom.signalEmpty.style.display = 'none';
    dom.signalGrid.style.display = 'grid';
    dom.signalBadge.style.display = 'inline-block';

    const isCall = data.signal === 'call';
    dom.signalBadge.textContent = isCall ? 'CALL ▲' : 'PUT ▼';
    dom.signalBadge.className = 'signal-badge ' + (isCall ? 'call' : 'put');
    dom.signalPanel.className = 'signal-panel has-signal ' + (isCall ? 'call-signal' : 'put-signal');

    const fmt = (v, d = 1) => v != null ? Number(v).toFixed(d) : 'N/A';
    const fmtSign = (v) => v != null ? (v >= 0 ? '+' : '') + Number(v).toFixed(7) : 'N/A';

    // v10.3: Indicator direction arrows
    const arrow = (curr, prev) => {
        if (curr == null || prev == null) return '▬';
        return curr > prev ? '⬆' : curr < prev ? '⬇' : '▬';
    };
    const rsiDir = arrow(data.rsi, data.rsi_prev);
    const macdStatus = data.macd_val > data.macd_sig_val ? '🟢' : '🔴';
    const stochStatus = data.stoch_k > data.stoch_d ? '🟢' : '🔴';

    const items = [
        { label: 'Asset', value: data.asset, cls: 'cyan' },
        { label: 'Strategy', value: data.strategy || '⚡ REMASTERED SYNC', cls: 'magenta' },
        { label: 'Regime', value: data.regime || 'UNKNOWN', cls: 'yellow' },
        { label: 'Conf', value: data.confidence + '%', cls: 'green' },
        { label: 'Payout', value: data.payout + '%', cls: '' },
        { label: 'RSI', value: fmt(data.rsi) + ' ' + rsiDir, cls: rsiDir === '⬆' ? 'green' : rsiDir === '⬇' ? 'red' : '' },
        { label: 'CCI', value: fmt(data.cci), cls: isCall ? 'green' : 'red' },
        { label: 'MACD Line', value: fmtSign(data.macd_val) + ' ' + macdStatus, cls: data.macd_val > data.macd_sig_val ? 'green' : 'red' },
        { label: 'Stoch K', value: fmt(data.stoch_k) + ' ' + stochStatus, cls: data.stoch_k > data.stoch_d ? 'green' : 'red' },
        { label: 'ADX', value: fmt(data.adx), cls: data.adx >= 18 ? 'green' : '' },
        { label: 'HTF (5m)', value: (data.htf_trend || 'N/A').toUpperCase(), cls: data.htf_trend === data.signal ? 'cyan' : '' },
        { label: 'Trend', value: data.higher_trend, cls: isCall ? 'green' : 'red' },
        { label: 'Amount', value: '₹' + data.amount, cls: 'yellow' },
        { label: 'MG Step', value: data.mg_step || 0, cls: data.mg_step > 0 ? 'magenta' : '' },
    ];

    dom.signalGrid.innerHTML = items.map(item => `
        <div class="signal-item">
            <span class="signal-item-label">${item.label}</span>
            <span class="signal-item-value ${item.cls}">${item.value}</span>
        </div>
    `).join('');
}

function handleTradeResult(data) {
    const isWin = data.result === 'WIN';

    // Flash effect
    dom.signalPanel.classList.add(isWin ? 'flash-win' : 'flash-loss');

    // Reset signal panel after 2 seconds
    setTimeout(() => {
        dom.signalPanel.className = 'signal-panel';
        dom.signalGrid.style.display = 'none';
        dom.signalBadge.style.display = 'none';
        // v10.3: Show scanning message if bot is still running
        if (isRunning) {
            dom.signalEmpty.style.display = 'block';
            dom.signalEmpty.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none"
                    stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
                    style="animation: pulse 1.5s infinite;">
                    <circle cx="11" cy="11" r="8"></circle>
                    <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                </svg>
                <br>Scanning for next signal...
                <br><span style="font-size:0.75rem; color:var(--text-dim);">Astra Engine active</span>
            `;
        } else {
            dom.signalEmpty.style.display = 'block';
        }
    }, 2000);

    // Log
    const symbol = isWin ? '✔' : '✘';
    const profitStr = isWin ? `+₹${data.profit.toFixed(2)}` : `-₹${Math.abs(data.profit).toFixed(2)}`;
    addLog(`${symbol} ${data.result} ${data.asset} ${profitStr} | P&L: ₹${data.pnl.toFixed(2)} | Bal: ₹${data.balance.toFixed(2)}`,
        isWin ? 'success' : 'error');

    // Add to trade history
    addTradeRow(data);
}

function addTradeRow(data) {
    tradeCount++;
    dom.tradesCount.textContent = tradeCount + ' trades';

    const isWin = data.result === 'WIN';
    const profitStr = isWin ? `+₹${data.profit.toFixed(2)}` : `-₹${Math.abs(data.profit).toFixed(2)}`;
    
    // v10.3: Extract entry time (HH:MM)
    let timeStr = '';
    if (data.entry_time) {
        const parts = data.entry_time.split(' ');
        timeStr = parts.length > 1 ? parts[1].slice(0, 5) : '';
    } else {
        const now = new Date();
        timeStr = now.toTimeString().slice(0, 5);
    }

    const row = document.createElement('div');
    row.className = 'trade-row';
    row.innerHTML = `
        <span class="trade-no">${data.trade_no || tradeCount}</span>
        <span class="trade-time">${timeStr}</span>
        <span class="trade-asset" title="${data.asset}">${data.asset}</span>
        <span class="trade-dir ${data.signal}">${data.signal.toUpperCase()}</span>
        <span class="trade-conf">${data.confidence}%</span>
        <span class="trade-result ${isWin ? 'win' : 'loss'}">${data.result}</span>
        <span class="trade-profit ${isWin ? 'positive' : 'negative'}">${profitStr}</span>
    `;

    // Insert at top
    if (dom.tradesScroll.firstChild) {
        dom.tradesScroll.insertBefore(row, dom.tradesScroll.firstChild);
    } else {
        dom.tradesScroll.appendChild(row);
    }
}

function handleBotStopped(data) {
    isRunning = false;
    dom.btnStart.disabled = false;
    dom.btnStop.disabled = true;
    setConnectionStatus('connected', 'Connected');

    let reason = 'Manual stop';
    if (data.reason === 'stop_loss') reason = '⛔ STOP LOSS HIT';
    if (data.reason === 'take_profit') reason = '🎯 TAKE PROFIT HIT';

    addLog(`${reason} — Final P&L: ₹${data.pnl.toFixed(2)}`, data.pnl >= 0 ? 'success' : 'error');

    // Reset signal panel
    dom.signalPanel.className = 'signal-panel';
    dom.signalEmpty.style.display = 'block';
    dom.signalGrid.style.display = 'none';
    dom.signalBadge.style.display = 'none';
    dom.countdownBar.style.display = 'none';
}

// ══════════════════════════════════════════════
// LOG
// ══════════════════════════════════════════════
function addLog(msg, cls = '') {
    logEntries++;
    dom.logCount.textContent = logEntries + ' entries';

    const now = new Date();
    const ts = now.toTimeString().slice(0, 8);

    const entry = document.createElement('div');
    entry.className = 'log-entry ' + cls;
    entry.innerHTML = `<span class="log-time">${ts}</span>${escapeHtml(msg)}`;

    dom.logScroll.appendChild(entry);

    // Keep only last 200 entries
    while (dom.logScroll.children.length > 200) {
        dom.logScroll.removeChild(dom.logScroll.firstChild);
    }

    dom.logScroll.scrollTop = dom.logScroll.scrollHeight;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ══════════════════════════════════════════════
// BOT CONTROLS
// ══════════════════════════════════════════════
function startBot() {
    if (isRunning) return;

    const config = {
        account: $('accountType').value,
        timeframe: $('timeframe').value,
        amount: parseFloat($('amount').value) || 10,
        stop_loss: parseFloat($('stopLoss').value) || 100,
        take_profit: parseFloat($('takeProfit').value) || 50,
        min_payout: parseFloat($('minPayout').value) || 85,
        martingale: $('martingale').checked,
        adaptive_learning: $('adaptiveLearning').checked,
    };

    // Validate
    if (config.amount <= 0) { alert('Amount must be > 0'); return; }
    if (config.stop_loss <= 0) { alert('Stop Loss must be > 0'); return; }
    if (config.take_profit <= 0) { alert('Take Profit must be > 0'); return; }

    // Reset UI
    tradeCount = 0;
    dom.tradesScroll.innerHTML = '';
    dom.tradesCount.textContent = '0 trades';
    dom.signalGrid.style.display = 'none';
    dom.signalBadge.style.display = 'none';
    dom.signalPanel.className = 'signal-panel';
    // v10.3: Show scanning message immediately
    dom.signalEmpty.style.display = 'block';
    dom.signalEmpty.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"
            style="animation: pulse 1.5s infinite;">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
        </svg>
        <br>Scanning for next signal...
        <br><span style="font-size:0.75rem; color:var(--text-dim);">Astra Engine active</span>
    `;

    addLog(`Starting bot: ${config.account} | ${config.timeframe} | ₹${config.amount} | SL:₹${config.stop_loss} | TP:₹${config.take_profit} | Payout:≥${config.min_payout}% | MG:${config.martingale ? 'ON' : 'OFF'}`, 'info');

    // Send via WebSocket
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'start', config }));
        dom.btnStart.disabled = true;
        dom.btnStop.disabled = false;
        isRunning = true;
    } else {
        // Fallback to REST
        fetch('/api/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        })
            .then(r => r.json())
            .then(data => {
                if (data.status === 'ok') {
                    dom.btnStart.disabled = true;
                    dom.btnStop.disabled = false;
                    isRunning = true;
                } else {
                    addLog('Error: ' + data.msg, 'error');
                }
            })
            .catch(e => addLog('Start error: ' + e, 'error'));
    }
}

function stopBot() {
    if (!isRunning) return;

    addLog('Stopping bot...', 'warn');

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'stop' }));
    } else {
        fetch('/api/stop', { method: 'POST' })
            .then(r => r.json())
            .then(data => addLog(data.msg, 'info'))
            .catch(e => addLog('Stop error: ' + e, 'error'));
    }
}

// ══════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
    connectWS();
    addLog('Dashboard loaded — configure and start the bot', 'info');

    // Load existing trades if any
    fetch('/api/trades')
        .then(r => r.json())
        .then(data => {
            if (data.sessions && data.sessions.length > 0) {
                const latest = data.sessions[data.sessions.length - 1];
                if (latest.trades) {
                    latest.trades.forEach(t => {
                        addTradeRow({
                            trade_no: t.trade_no,
                            asset: t.asset,
                            signal: (t.direction || '').toLowerCase(),
                            confidence: t.confidence,
                            result: t.result,
                            profit: t.profit,
                            pnl: t.pnl,
                            balance: t.balance,
                        });
                    });
                }
            }
        })
        .catch(() => { });

    // Load status
    fetch('/api/status')
        .then(r => r.json())
        .then(data => {
            if (data.running) {
                isRunning = true;
                dom.btnStart.disabled = true;
                dom.btnStop.disabled = false;
            }
            updateStatus(data);
        })
        .catch(() => { });
});

// ══════════════════════════════════════════════
// ANALYTICS MODAL
// ══════════════════════════════════════════════
let dashCharts = {};

function openAnalyticsModal() {
    $('analyticsModal').style.display = 'flex';
    $('dashRange').value = 'all';
    fetchDashboard('all');
}

let lastDailyStats = [];

function fetchDashboard(range) {
    $('dashLoading').style.display = 'block';
    $('dashContent').style.display = 'none';
    
    const account = $('dashAccount') ? $('dashAccount').value : 'all';
    
    fetch(`/api/analytics-dashboard?range=${range}&account=${account}`)
        .then(r => r.json())
        .then(data => {
            $('dashLoading').style.display = 'none';
            if (data.empty) {
                $('dashLoading').style.display = 'block';
                $('dashLoading').innerHTML = 'No trading data found for this period.';
                return;
            }
            
            $('dashContent').style.display = 'block';
            
            // Populate KPIs
            if ($('kpiTotal')) $('kpiTotal').textContent = data.kpi.total_trades;
            if ($('kpiWR')) $('kpiWR').textContent = data.kpi.win_rate + '%';
            if ($('kpiPnL')) $('kpiPnL').textContent = (data.kpi.net_pnl >= 0 ? '+$' : '-$') + Math.abs(data.kpi.net_pnl);
            
            // Render Charts
            renderDashCharts(data.charts);
            
            // Calculate Smart Insights
            calculateSmartInsights(data);
            
            // Update Pattern UI
            if (data.pattern_data) updatePatternUI(data.pattern_data, data);
            
            // Fetch Adaptive Learning Status
            fetchAdaptiveStatus();
            
            // Now fetch daily sessions
            fetch(`/api/daily-stats?range=${range}&account=${account}`)
                .then(r => r.json())
                .then(dailyData => {
                    const stats = dailyData.stats || [];
                    lastDailyStats = stats;
                    
                    // Render Heatmap
                    renderHeatmap(stats);
                    
                    if (stats.length === 0) {
                        $('analyticsBody').innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-dim);">No daily sessions found.</div>';
                        return;
                    }
                    
                    $('analyticsBody').innerHTML = stats.map(s => {
                        const profitCls = s.profit >= 0 ? 'positive' : 'negative';
                        const profitStr = (s.profit >= 0 ? '+₹' : '-₹') + Math.abs(s.profit).toFixed(2);
                        const winRateCls = s.win_rate >= 50 ? 'positive' : 'negative';
                        
                        return `
                            <div class="analytics-row clickable" onclick="openDateDetails('${s.date}')">
                                <span class="a-date">${s.date}</span>
                                <span>${s.total}</span>
                                <span><span style="color:var(--green)">${s.wins}</span> / <span style="color:var(--red)">${s.losses}</span></span>
                                <span class="${winRateCls}">${s.win_rate}%</span>
                                <span class="a-profit ${profitCls}">${profitStr}</span>
                                <span class="a-late" style="color:var(--yellow)">${s.late_entry}</span>
                                <span class="a-wrong" style="color:var(--magenta)">${s.wrong_analysis}</span>
                            </div>
                        `;
                    }).join('');
                });
        })
        .catch(err => {
            $('dashLoading').innerHTML = `<span style="color:var(--red)">Error loading dashboard data: ${err.message}<br>${err.stack}</span>`;
            $('dashLoading').style.display = 'block';
        });
}

function renderHeatmap(stats) {
    if (!$('dashHeatmap')) return;
    
    // Sort chronologically (oldest first)
    const sorted = [...stats].sort((a,b) => new Date(a.date) - new Date(b.date));
    
    // Take max last 30 for the heatmap UI to fit nicely
    const recent = sorted.slice(-30);
    
    if (recent.length === 0) {
        $('dashHeatmap').innerHTML = '<span style="color:var(--text-dim); font-size:0.8rem;">Not enough data yet.</span>';
        return;
    }
    
    $('dashHeatmap').innerHTML = recent.map(s => {
        let cls = 'neutral';
        if (s.profit > 0) cls = 'win';
        if (s.profit < 0) cls = 'loss';
        const title = `${s.date}: ${s.wins}W/${s.losses}L ($${s.profit})`;
        return `<div class="heatmap-cell ${cls}" title="${title}"></div>`;
    }).join('');
}

function exportCSV() {
    if (lastDailyStats.length === 0) {
        alert("No data to export!");
        return;
    }
    
    let csvContent = "data:text/csv;charset=utf-8,";
    csvContent += "Date,Trades,Wins,Losses,WinRate(%),Profit,LateEntryLoss,WrongAnalysisLoss\n";
    
    lastDailyStats.forEach(row => {
        csvContent += `${row.date},${row.total},${row.wins},${row.losses},${row.win_rate},${row.profit},${row.late_entry},${row.wrong_analysis}\n`;
    });
    
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `trading_report_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function calculateSmartInsights(data) {
    const charts = data.charts;
    const stats = data.stats;
    
    // 1. Best Asset
    if (charts.asset_labels && charts.asset_labels.length > 0) {
        const bestAsset = charts.asset_labels[0];
        const bestProfit = charts.asset_data[0];
        if (bestProfit > 0) {
            if ($('insightBest')) $('insightBest').innerHTML = `
                <span class="insight-icon">👍</span>
                <div class="insight-text">Your most profitable asset is <strong>${bestAsset}</strong> (+₹${bestProfit}). Keep trading it!</div>
            `;
        } else {
            if ($('insightBest')) $('insightBest').innerHTML = `<span class="insight-icon">ℹ️</span><div class="insight-text">Not enough profitable data yet to determine best asset.</div>`;
        }
    } else {
        if ($('insightBest')) $('insightBest').innerHTML = `<span class="insight-icon">ℹ️</span><div class="insight-text">Trade more to unlock asset insights.</div>`;
    }

    // 2. Biggest Weakness
    if (charts.loss_labels && charts.loss_data && Math.max(...charts.loss_data) > 0) {
        let maxIndex = 0;
        let maxVal = 0;
        for (let i=0; i<charts.loss_data.length; i++) {
            if (charts.loss_data[i] > maxVal) { maxVal = charts.loss_data[i]; maxIndex = i; }
        }
        const reason = charts.loss_labels[maxIndex];
        if ($('insightWorst')) $('insightWorst').innerHTML = `
            <span class="insight-icon">⚠️</span>
            <div class="insight-text">Most of your losses (${maxVal}) are due to <strong>${reason}</strong>. Review your strategy settings.</div>
        `;
    } else {
        if ($('insightWorst')) $('insightWorst').innerHTML = `<span class="insight-icon">🚀</span><div class="insight-text">No significant loss patterns detected. Great job!</div>`;
    }

    // 3. Best Market Regime
    let bestRegime = "";
    let bestWR = -1;
    ['TRENDING', 'BREAKOUT'].forEach(reg => {
        if (stats[reg] && stats[reg].trades >= 2 && stats[reg].wr > bestWR) {
            bestWR = stats[reg].wr;
            bestRegime = reg;
        }
    });
    
    if (bestRegime) {
        if ($('insightRegime')) $('insightRegime').innerHTML = `
            <span class="insight-icon">🧠</span>
            <div class="insight-text">The bot performs best in <strong>${bestRegime}</strong> markets (${bestWR}% Win Rate).</div>
        `;
    } else {
        if ($('insightRegime')) $('insightRegime').innerHTML = `<span class="insight-icon">🧠</span><div class="insight-text">More trades needed to determine optimal market conditions.</div>`;
    }
}

function renderDashCharts(cData) {
    // Destroy old charts
    Object.values(dashCharts).forEach(c => c.destroy());
    dashCharts = {};
    
    // Guard: Chart.js might not be loaded
    if (typeof Chart === 'undefined') {
        console.warn('Chart.js not loaded, skipping chart rendering');
        return;
    }
    
    Chart.defaults.color = '#94A3B8';
    Chart.defaults.font.family = "'Inter', sans-serif";
    
    // 1. Top Assets (Doughnut)
    if ($('chartAssets')) {
        dashCharts.assets = new Chart($('chartAssets'), {
            type: 'doughnut',
            data: {
                labels: cData.asset_labels.slice(0, 5),
                datasets: [{
                    data: cData.asset_data.slice(0, 5),
                    backgroundColor: ['#00D0FF', '#00FF88', '#FFD600', '#D946EF', '#FF3366'],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 10, padding: 15 } }
                }
            }
        });
    }

    // 2. Loss Breakdown (Doughnut)
    if ($('chartLoss')) {
        dashCharts.loss = new Chart($('chartLoss'), {
            type: 'doughnut',
            data: {
                labels: cData.loss_labels,
                datasets: [{
                    data: cData.loss_data,
                    backgroundColor: ['#FF3366', '#FFD600', '#D946EF', '#475569'],
                    borderWidth: 0,
                    hoverOffset: 4
                }]
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: { position: 'bottom', labels: { boxWidth: 10, padding: 15 } }
                }
            }
        });
    }
}

function closeAnalyticsModal() {
    $('analyticsModal').style.display = 'none';
}

// Close modal on outside click
$('analyticsModal').addEventListener('click', (e) => {
    if (e.target === $('analyticsModal')) {
        closeAnalyticsModal();
    }
});

function updatePatternUI(pat, fullData) {
    if (!$('patWinsCard')) return;

    function renderCard(id, color, titleHtml, stats) {
        const c = $(id);
        if (!c) return;
        c.innerHTML = `
            <div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px;">
                ${titleHtml}
            </div>
            <div class="stat-bars">
                <div class="stat-bar-row"><span class="stat-bar-label">Avg ADX</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width: ${Math.min(100, stats.adx*2)}%; background: var(--${color});"></div></div><span class="stat-bar-val">${stats.adx}</span></div>
                <div class="stat-bar-row"><span class="stat-bar-label">Avg RSI</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width: ${Math.min(100, stats.rsi)}%; background: var(--${color});"></div></div><span class="stat-bar-val">${stats.rsi}</span></div>
                <div class="stat-bar-row"><span class="stat-bar-label">Avg Stoch K</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width: ${Math.min(100, stats.stoch)}%; background: var(--${color});"></div></div><span class="stat-bar-val">${stats.stoch}</span></div>
                <div class="stat-bar-row"><span class="stat-bar-label">Avg CCI</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width: ${Math.min(100, Math.abs(stats.cci))}%; background: var(--${color});"></div></div><span class="stat-bar-val">${stats.cci}</span></div>
                <div class="stat-bar-row"><span class="stat-bar-label">ATR scale</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width: ${Math.min(100, stats.atr)}%; background: var(--${color});"></div></div><span class="stat-bar-val">${(stats.atr/100).toFixed(2)}</span></div>
                <div class="stat-bar-row"><span class="stat-bar-label">Conf avg</span><div class="stat-bar-track"><div class="stat-bar-fill" style="width: ${Math.min(100, stats.conf)}%; background: var(--${color});"></div></div><span class="stat-bar-val">${stats.conf}</span></div>
            </div>
        `;
    }

    renderCard('patWinsCard', 'green', `
        <span style="background: rgba(0, 255, 136, 0.1); color: var(--green); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">MACD agreed ${pat.wins.macd_pct}%</span>
        <span style="background: rgba(0, 255, 136, 0.1); color: var(--green); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">Support 2: ${pat.support.s2_wr}% WR</span>
    `, pat.wins);

    renderCard('patWrongCard', 'red', `
        <span style="background: rgba(255, 51, 102, 0.1); color: var(--red); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">MACD agreed only ${pat.wrong.macd_pct}%</span>
        <span style="background: rgba(255, 51, 102, 0.1); color: var(--red); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">Wrong Analysis</span>
    `, pat.wrong);

    renderCard('patLateCard', 'yellow', `
        <span style="background: rgba(255, 214, 0, 0.1); color: var(--yellow); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">MACD agreed ${pat.late.macd_pct}%</span>
        <span style="background: rgba(255, 214, 0, 0.1); color: var(--yellow); padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">Late Entry</span>
    `, pat.late);

    // Support Chart
    if ($('patSupportChart')) {
        const s1_w = Math.round(pat.support.s1_t * pat.support.s1_wr / 100);
        const s1_l = pat.support.s1_t - s1_w;
        const s2_w = Math.round(pat.support.s2_t * pat.support.s2_wr / 100);
        const s2_l = pat.support.s2_t - s2_w;

        $('patSupportChart').innerHTML = `
            <div style="display: flex; flex-direction: column; align-items: center; width: 60px; gap: 8px; cursor: pointer;" title="SUPPORT = 1\nTotal Trades: ${pat.support.s1_t}\nWin Rate: ${pat.support.s1_wr}%\nWins: ${s1_w}\nLosses: ${s1_l}">
                <div style="width: 100%; height: ${(100 - pat.support.s1_wr)}px; background: var(--red); border-top-left-radius: 4px; border-top-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>
                <div style="width: 100%; height: ${pat.support.s1_wr}px; background: var(--green); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>
                <span style="font-size: 0.75rem; color: var(--text-dim); white-space: nowrap; margin-top: 4px;">Support = 1 (${pat.support.s1_t})</span>
            </div>
            <div style="display: flex; flex-direction: column; align-items: center; width: 60px; gap: 8px; cursor: pointer;" title="SUPPORT = 2\nTotal Trades: ${pat.support.s2_t}\nWin Rate: ${pat.support.s2_wr}%\nWins: ${s2_w}\nLosses: ${s2_l}">
                <div style="width: 100%; height: ${(100 - pat.support.s2_wr)}px; background: var(--red); border-top-left-radius: 4px; border-top-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>
                <div style="width: 100%; height: ${pat.support.s2_wr}px; background: var(--green); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>
                <span style="font-size: 0.75rem; color: var(--text-dim); white-space: nowrap; margin-top: 4px;">Support = 2 (${pat.support.s2_t})</span>
            </div>
        `;
    }

    // Support Split Chart
    if ($('patMacdChart')) {
        if (pat.support_split) {
            const m_w = pat.support_split.macd_only.wins || 0;
            const m_wr = pat.support_split.macd_only.wrong || 0;
            const m_l = pat.support_split.macd_only.late || 0;
            const m_t = m_w + m_wr + m_l;

            const s_w = pat.support_split.stoch_only.wins || 0;
            const s_wr = pat.support_split.stoch_only.wrong || 0;
            const s_l = pat.support_split.stoch_only.late || 0;
            const s_t = s_w + s_wr + s_l;

            const b_w = pat.support_split.both.wins || 0;
            const b_wr = pat.support_split.both.wrong || 0;
            const b_l = pat.support_split.both.late || 0;
            const b_t = b_w + b_wr + b_l;

            const maxT = Math.max(1, m_t, s_t, b_t);

            // Normalize heights (120px max)
            const hm_t = (m_t / maxT) * 120;
            const hs_t = (s_t / maxT) * 120;
            const hb_t = (b_t / maxT) * 120;

            const hm_w = m_t > 0 ? (m_w / m_t) * hm_t : 0;
            const hm_wr = m_t > 0 ? (m_wr / m_t) * hm_t : 0;
            const hm_l = hm_t - hm_w - hm_wr;

            const hs_w = s_t > 0 ? (s_w / s_t) * hs_t : 0;
            const hs_wr = s_t > 0 ? (s_wr / s_t) * hs_t : 0;
            const hs_l = hs_t - hs_w - hs_wr;

            const hb_w = b_t > 0 ? (b_w / b_t) * hb_t : 0;
            const hb_wr = b_t > 0 ? (b_wr / b_t) * hb_t : 0;
            const hb_l = hb_t - hb_w - hb_wr;

            $('patMacdChart').innerHTML = `
                <div style="display: flex; flex-direction: column; align-items: center; width: 68px; gap: 4px; cursor: pointer;" title="CCI+RSI + MACD (${m_t} Trades)\nWins: ${m_w} (${m_t?Math.round(m_w/m_t*100):0}%)\nWrong Analysis: ${m_wr}\nLate Entry: ${m_l}">
                    ${m_t === 0 ? `<div style="width: 100%; height: 2px; background: rgba(255,255,255,0.1); border-radius: 4px;"></div>` : ''}
                    ${hm_l > 0 ? `<div style="width: 100%; height: ${Math.max(2, hm_l)}px; background: var(--yellow); border-top-left-radius: 4px; border-top-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    ${hm_wr > 0 ? `<div style="width: 100%; height: ${Math.max(2, hm_wr)}px; background: var(--red); transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    ${hm_w > 0 ? `<div style="width: 100%; height: ${Math.max(2, hm_w)}px; background: var(--green); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    <span style="font-size: 0.65rem; color: var(--text-dim); white-space: nowrap; margin-top: 4px; text-align: center; line-height: 1.2;">CCI+RSI +<br>MACD (${m_t})</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; width: 68px; gap: 4px; cursor: pointer;" title="CCI+RSI + STOCH (${s_t} Trades)\nWins: ${s_w} (${s_t?Math.round(s_w/s_t*100):0}%)\nWrong Analysis: ${s_wr}\nLate Entry: ${s_l}">
                    ${s_t === 0 ? `<div style="width: 100%; height: 2px; background: rgba(255,255,255,0.1); border-radius: 4px;"></div>` : ''}
                    ${hs_l > 0 ? `<div style="width: 100%; height: ${Math.max(2, hs_l)}px; background: var(--yellow); border-top-left-radius: 4px; border-top-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    ${hs_wr > 0 ? `<div style="width: 100%; height: ${Math.max(2, hs_wr)}px; background: var(--red); transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    ${hs_w > 0 ? `<div style="width: 100%; height: ${Math.max(2, hs_w)}px; background: var(--green); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    <span style="font-size: 0.65rem; color: var(--text-dim); white-space: nowrap; margin-top: 4px; text-align: center; line-height: 1.2;">CCI+RSI +<br>Stoch (${s_t})</span>
                </div>
                <div style="display: flex; flex-direction: column; align-items: center; width: 68px; gap: 4px; cursor: pointer;" title="CCI+RSI + BOTH (${b_t} Trades)\nWins: ${b_w} (${b_t?Math.round(b_w/b_t*100):0}%)\nWrong Analysis: ${b_wr}\nLate Entry: ${b_l}">
                    ${b_t === 0 ? `<div style="width: 100%; height: 2px; background: rgba(255,255,255,0.1); border-radius: 4px;"></div>` : ''}
                    ${hb_l > 0 ? `<div style="width: 100%; height: ${Math.max(2, hb_l)}px; background: var(--yellow); border-top-left-radius: 4px; border-top-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    ${hb_wr > 0 ? `<div style="width: 100%; height: ${Math.max(2, hb_wr)}px; background: var(--red); transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    ${hb_w > 0 ? `<div style="width: 100%; height: ${Math.max(2, hb_w)}px; background: var(--green); border-bottom-left-radius: 4px; border-bottom-right-radius: 4px; transition: opacity 0.2s;" onmouseover="this.style.opacity=0.8" onmouseout="this.style.opacity=1"></div>` : ''}
                    <span style="font-size: 0.65rem; color: var(--text-dim); white-space: nowrap; margin-top: 4px; text-align: center; line-height: 1.2;">CCI+RSI +<br>Both (${b_t})</span>
                </div>
            `;
        } else {
            $('patMacdChart').innerHTML = `<div style="width: 100%; text-align: center; color: var(--red); font-size: 0.8rem; padding-bottom: 20px;">Please restart server.py to view this chart</div>`;
        }
    }
}

// ══════════════════════════════════════════════
// ADAPTIVE LEARNING STATUS
// ══════════════════════════════════════════════
function fetchAdaptiveStatus() {
    fetch('/api/adaptive-status')
        .then(r => r.json())
        .then(data => {
            const badge = $('adaptiveBadge');
            const content = $('adaptiveContent');
            if (!badge || !content) return;
            
            if (!data.learned) {
                badge.textContent = 'NOT ACTIVE (< 5 trades)';
                badge.style.background = 'rgba(255,255,255,0.1)';
                badge.style.color = 'var(--text-dim)';
                content.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); padding: 20px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); text-align: center;">
                        <div style="font-size: 2rem; margin-bottom: 8px;">🔒</div>
                        <div style="font-weight: 600; color: #fff; margin-bottom: 4px;">Adaptive Learning Not Active</div>
                        <div style="font-size: 0.85rem; color: var(--text-dim);">Need minimum 5 trades today to activate learning. Bot runs with default thresholds.</div>
                    </div>
                `;
                return;
            }
            
            const blockCount = data.total_blocks || 0;
            badge.textContent = `${blockCount} ACTIVE BLOCK${blockCount !== 1 ? 'S' : ''}`;
            badge.style.background = blockCount > 0 ? 'rgba(0, 255, 136, 0.15)' : 'rgba(255,255,255,0.1)';
            badge.style.color = blockCount > 0 ? 'var(--green)' : 'var(--text-dim)';
            
            if (blockCount === 0) {
                content.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); padding: 20px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); text-align: center;">
                        <div style="font-size: 2rem; margin-bottom: 8px;">✅</div>
                        <div style="font-weight: 600; color: #fff; margin-bottom: 4px;">Learning Active — No Blocks Triggered</div>
                        <div style="font-size: 0.85rem; color: var(--text-dim);">All trades are passing adaptive filters. No loss patterns detected yet.</div>
                    </div>
                `;
                return;
            }
            
            // Render blocks
            let html = '';
            
            // Raw thresholds
            const raw = data.raw || {};
            html += `<div style="display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px;">`;
            html += `<span style="background: rgba(0,208,255,0.1); color: var(--cyan); padding: 3px 8px; border-radius: 4px; font-size: 0.75rem;">RSI mult: ${raw.rsi_min_delta_mult?.toFixed(1) || '1.0'}x</span>`;
            html += `<span style="background: rgba(0,208,255,0.1); color: var(--cyan); padding: 3px 8px; border-radius: 4px; font-size: 0.75rem;">CCI min: ${raw.cci_min_delta || 15}</span>`;
            html += `<span style="background: rgba(0,208,255,0.1); color: var(--cyan); padding: 3px 8px; border-radius: 4px; font-size: 0.75rem;">ADX floor: ${raw.adx_floor?.toFixed(1) || '15.0'}</span>`;
            html += `<span style="background: rgba(0,208,255,0.1); color: var(--cyan); padding: 3px 8px; border-radius: 4px; font-size: 0.75rem;">HTF min: ${raw.htf_min_adx?.toFixed(1) || '15.0'}</span>`;
            html += `</div>`;
            
            // Learned patterns
            const patterns = data.patterns || [];
            if (patterns.length > 0) {
                html += `<div style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px;">`;
                patterns.forEach(p => {
                    html += `<span style="background: rgba(255,51,102,0.1); color: var(--red); padding: 2px 6px; border-radius: 3px; font-size: 0.7rem; font-family: var(--font-mono);">${p}</span>`;
                });
                html += `</div>`;
            }
            
            // Block cards
            data.blocks.forEach(block => {
                const colorVar = `var(--${block.color})`;
                const bgColor = block.color === 'red' ? 'rgba(255,51,102,0.05)' :
                                block.color === 'yellow' ? 'rgba(255,214,0,0.05)' :
                                block.color === 'magenta' ? 'rgba(217,70,239,0.05)' : 
                                block.color === 'green' ? 'rgba(0,255,136,0.05)' : 'rgba(255,255,255,0.03)';
                const borderColor = block.color === 'red' ? 'rgba(255,51,102,0.15)' :
                                   block.color === 'yellow' ? 'rgba(255,214,0,0.15)' :
                                   block.color === 'magenta' ? 'rgba(217,70,239,0.15)' : 
                                   block.color === 'green' ? 'rgba(0,255,136,0.15)' : 'rgba(255,255,255,0.05)';
                html += `
                    <div style="background: ${bgColor}; padding: 14px 16px; border-radius: 8px; border: 1px solid ${borderColor};">
                        <div style="font-weight: 600; margin-bottom: 3px; color: ${colorVar}; font-size: 0.9rem; display: flex; align-items: center; gap: 6px;">
                            <span style="width: 6px; height: 6px; border-radius: 50%; background: ${colorVar}; display: inline-block;"></span>
                            ${block.name}
                        </div>
                        <div style="font-size: 0.8rem; color: var(--text-dim); line-height: 1.4;">${block.desc}</div>
                    </div>
                `;
            });
            
            content.innerHTML = html;
        })
        .catch(err => {
            const content = $('adaptiveContent');
            if (content) content.innerHTML = `<div style="padding: 10px; color: var(--text-dim); font-size: 0.85rem;">Could not load adaptive status</div>`;
        });
}

// ══════════════════════════════════════════════
// DATE DETAILS MODAL
// ══════════════════════════════════════════════
function openDateDetails(date) {
    // Hide the daily stats modal
    $('analyticsModal').style.display = 'none';
    
    // Show the new modal
    $('dateDetailsModal').style.display = 'flex';
    $('dateDetailsTitle').innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
        TRADE DETAILS: ${date}
    `;
    $('dateDetailsBody').innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-dim);">Loading trades...</div>';
    
    fetch(`/api/daily-trades/${date}`)
        .then(r => r.json())
        .then(data => {
            const trades = data.trades || [];
            if (trades.length === 0) {
                $('dateDetailsBody').innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-dim);">No trades found for this date.</div>';
                return;
            }
            
            $('dateDetailsBody').innerHTML = trades.map(t => {
                const isWin = t.result === 'WIN';
                const profitCls = isWin ? 'positive' : 'negative';
                const profitStr = isWin ? `+₹${(t.profit || 0).toFixed(2)}` : `-₹${Math.abs(t.profit || 0).toFixed(2)}`;
                
                let timeStr = '';
                if (t.entry_time) {
                    const parts = t.entry_time.split(' ');
                    timeStr = parts.length > 1 ? parts[1].slice(0, 5) : '';
                }
                
                const dirCls = (t.direction || '').toLowerCase();
                const dirTxt = (t.direction || '').toUpperCase();
                
                // Extract diagnosis/reason
                let reason = '';
                let reasonCls = '';
                if (!isWin) {
                    const diag = Array.isArray(t.diagnosis) ? t.diagnosis.join(', ') : t.diagnosis || '';
                    const resType = t.trade_result_type || '';
                    if (resType.includes('LATE_ENTRY') || diag.toLowerCase().includes('sudden reversal')) {
                        reason = 'Late Entry / Reversal';
                        reasonCls = 'color:var(--yellow)';
                    } else if (resType.includes('WRONG_ANALYSIS') || diag.toLowerCase().includes('wrong analysis')) {
                        reason = 'Wrong Analysis';
                        reasonCls = 'color:var(--magenta)';
                    } else {
                        reason = 'Loss';
                        reasonCls = 'color:var(--red)';
                    }
                } else {
                    reason = 'Win';
                    reasonCls = 'color:var(--green)';
                }

                // Extract indicator directions
                const getDir = (gradual) => {
                    if (!gradual) return '—';
                    if (gradual.toLowerCase() === 'increasing') return 'Up \u2191';
                    if (gradual.toLowerCase() === 'decreasing') return 'Down \u2193';
                    return gradual;
                };
                const getColor = (gradual) => {
                    if (!gradual) return '';
                    if (gradual.toLowerCase() === 'increasing') return 'color:var(--green)';
                    if (gradual.toLowerCase() === 'decreasing') return 'color:var(--red)';
                    return '';
                };
                
                const rsiDir = getDir(t.rsi_gradual);
                const cciDir = getDir(t.cci_gradual);
                const macdDir = getDir(t.macd_gradual);
                const stochDir = getDir(t.stoch_gradual);
                
                const rsiCol = getColor(t.rsi_gradual);
                const cciCol = getColor(t.cci_gradual);
                const macdCol = getColor(t.macd_gradual);
                const stochCol = getColor(t.stoch_gradual);

                const regimeStr = t.regime || '—';
                const regimeCls = (t.regime || '').toLowerCase();
                const trendStr = t.trend || '—';
                const htfStr = t.htf_trend ? `(HTF: ${t.htf_trend.toUpperCase()})` : '';

                return `
                    <div class="details-item-wrapper">
                        <div class="details-row">
                            <span class="d-no">${t.trade_no || '-'}</span>
                            <span class="d-time">${timeStr}</span>
                            <span class="d-asset" title="${t.asset}">${t.asset}</span>
                            <span class="d-dir ${dirCls}">${dirTxt}</span>
                            <span class="d-conf">${t.confidence || '-'}%</span>
                            <span class="d-res" style="${reasonCls}">${reason}</span>
                            <span class="d-profit ${profitCls}">${profitStr}</span>
                        </div>
                        <div class="details-sub">
                            <span class="sub-badge regime-${regimeCls}">${regimeStr}</span>
                            <span class="sub-item">Trend: <span style="color:#fff">${trendStr} ${htfStr}</span></span>
                            <span class="sub-item">RSI: <span style="${rsiCol}">${rsiDir}</span></span>
                            <span class="sub-item">CCI: <span style="${cciCol}">${cciDir}</span></span>
                            <span class="sub-item">MACD: <span style="${macdCol}">${macdDir}</span></span>
                            <span class="sub-item">Stoch: <span style="${stochCol}">${stochDir}</span></span>
                        </div>
                    </div>
                `;
            }).join('');
        })
        .catch(err => {
            $('dateDetailsBody').innerHTML = '<div style="padding:20px; text-align:center; color:var(--red);">Error loading trades.</div>';
        });
}

function closeDateDetailsModal() {
    $('dateDetailsModal').style.display = 'none';
    $('analyticsModal').style.display = 'flex'; // Reopen analytics modal
}

$('dateDetailsModal').addEventListener('click', (e) => {
    if (e.target === $('dateDetailsModal')) {
        closeDateDetailsModal();
    }
});
