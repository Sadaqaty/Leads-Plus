from flask import Flask, render_template_string, jsonify
import subprocess
import re
from datetime import datetime

app = Flask(__name__)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LeadPulse Fleet Command Center</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f111a;
            color: #c3ccdc;
            padding: 24px;
            min-height: 100vh;
        }
        .container { max-width: 1700px; margin: 0 auto; }

        /* Header */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            flex-wrap: wrap;
            gap: 16px;
        }
        .header-title h1 {
            font-size: 28px;
            font-weight: 800;
            background: linear-gradient(135deg, #6366f1, #a855f7, #ec4899);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }
        .header-title p {
            font-size: 13px;
            color: #64748b;
            margin-top: 2px;
        }
        .live-badge {
            background: rgba(34, 197, 94, 0.1);
            border: 1px solid rgba(34, 197, 94, 0.3);
            padding: 8px 18px;
            border-radius: 40px;
            font-size: 13px;
            font-weight: 600;
            color: #4ade80;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .pulse-dot {
            width: 8px;
            height: 8px;
            background: #4ade80;
            border-radius: 50%;
            box-shadow: 0 0 10px #4ade80;
            animation: pulse 1.5s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(74, 222, 128, 0.7); }
            70% { transform: scale(1); box-shadow: 0 0 0 8px rgba(74, 222, 128, 0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(74, 222, 128, 0); }
        }

        /* Fleet Progress Bar */
        .fleet-progress-card {
            background: #181b29;
            border: 1px solid #282d43;
            border-radius: 16px;
            padding: 20px 24px;
            margin-bottom: 28px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.3);
        }
        .fleet-progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            font-size: 14px;
            font-weight: 600;
        }
        .fleet-progress-title { color: #f8fafc; display: flex; align-items: center; gap: 8px; }
        .fleet-progress-pct { color: #818cf8; font-size: 18px; font-weight: 700; }
        .progress-track {
            background: #0f111a;
            height: 12px;
            border-radius: 20px;
            overflow: hidden;
            border: 1px solid #282d43;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #6366f1, #a855f7, #ec4899);
            border-radius: 20px;
            transition: width 0.5s ease-in-out;
        }

        /* Summary Stats Grid */
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 28px;
        }
        .stat-card {
            background: #181b29;
            padding: 18px 20px;
            border-radius: 14px;
            border: 1px solid #282d43;
            box-shadow: 0 4px 12px rgba(0,0,0,0.25);
            transition: transform 0.2s;
        }
        .stat-card:hover { transform: translateY(-2px); }
        .stat-card .label { font-size: 12px; color: #94a3b8; text-transform: uppercase; font-weight: 600; letter-spacing: 0.6px; }
        .stat-card .value { font-size: 30px; font-weight: 800; margin-top: 6px; letter-spacing: -0.5px; }
        .stat-card.leads .value { color: #f472b6; }
        .stat-card.queries .value { color: #818cf8; }
        .stat-card.remaining .value { color: #fbbf24; }
        .stat-card.active .value { color: #4ade80; }
        .stat-card.stuck .value { color: #f87171; }

        /* Worker Grid */
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
            gap: 22px;
        }

        /* Individual Worker Card */
        .worker-card {
            background: #181b29;
            border-radius: 16px;
            padding: 20px;
            border: 1px solid #282d43;
            transition: all 0.2s ease;
            box-shadow: 0 4px 16px rgba(0,0,0,0.2);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .worker-card:hover { border-color: #475569; transform: translateY(-3px); }
        
        .worker-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }
        .worker-name {
            font-size: 17px;
            font-weight: 700;
            color: #f1f5f9;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .status-pill {
            padding: 4px 12px;
            border-radius: 30px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .status-pill.active { background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); }
        .status-pill.stuck { background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
        .status-pill.inactive { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
        .status-pill.dead { background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); }

        /* Worker Progress */
        .worker-progress-box { margin-bottom: 14px; }
        .worker-progress-info {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #94a3b8;
            margin-bottom: 6px;
        }
        .worker-progress-info strong { color: #f1f5f9; }

        .worker-stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin-bottom: 14px;
        }
        .stat-item {
            background: #0f111a;
            padding: 8px 12px;
            border-radius: 8px;
            border: 1px solid #23283e;
            font-size: 12px;
        }
        .stat-item .lbl { color: #64748b; font-size: 10px; text-transform: uppercase; font-weight: 600; }
        .stat-item .val { color: #f1f5f9; font-weight: 700; font-size: 14px; margin-top: 2px; }

        .query-box {
            background: #0f111a;
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 12px;
            color: #c084fc;
            margin-bottom: 10px;
            border: 1px solid #23283e;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .url-box {
            background: #0f111a;
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 11px;
            color: #38bdf8;
            word-break: break-all;
            margin-bottom: 12px;
            border: 1px solid #23283e;
            font-family: monospace;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .log-box {
            background: #090a10;
            border-radius: 8px;
            padding: 10px;
            max-height: 85px;
            overflow-y: auto;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 11px;
            color: #64748b;
            border: 1px solid #23283e;
        }
        .log-line {
            padding: 2px 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .highlight-crawl { color: #38bdf8; }
        .highlight-store { color: #4ade80; }
        .highlight-error { color: #f87171; }

        .timestamp { font-size: 11px; color: #64748b; margin-top: 14px; text-align: right; }

        /* Scrollbar */
        .log-box::-webkit-scrollbar { width: 4px; }
        .log-box::-webkit-scrollbar-track { background: #0f111a; }
        .log-box::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }

        @media (max-width: 600px) {
            .grid { grid-template-columns: 1fr; }
            .summary { grid-template-columns: 1fr 1fr; }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="header-title">
            <h1>📡 LeadPulse Fleet Command Center</h1>
            <p>24/7 Autonomous Lead Generation Engine & VPS Monitoring</p>
        </div>
        <div class="live-badge">
            <div class="pulse-dot"></div>
            <span>LIVE</span> | <span id="update-time">Syncing...</span>
        </div>
    </div>

    <!-- Fleet Progress Card -->
    <div class="fleet-progress-card">
        <div class="fleet-progress-header">
            <span class="fleet-progress-title">🚀 Total Workload Completion</span>
            <span class="fleet-progress-pct" id="fleet-pct">0.0%</span>
        </div>
        <div class="progress-track">
            <div class="progress-fill" id="fleet-progress-bar" style="width: 0%;"></div>
        </div>
    </div>

    <!-- Summary Stats -->
    <div class="summary" id="summary">
        <div class="stat-card leads">
            <div class="label">📈 Total Leads</div>
            <div class="value" id="total-leads">0</div>
        </div>
        <div class="stat-card queries">
            <div class="label">🎯 Queries Processed</div>
            <div class="value" id="total-queries-done">0</div>
        </div>
        <div class="stat-card remaining">
            <div class="label">⏳ Queries Remaining</div>
            <div class="value" id="total-queries-left">0</div>
        </div>
        <div class="stat-card active">
            <div class="label">🟢 Active Workers</div>
            <div class="value" id="total-active">0</div>
        </div>
        <div class="stat-card stuck">
            <div class="label">🔴 Stuck Workers</div>
            <div class="value" id="total-stuck">0</div>
        </div>
    </div>

    <!-- Workers Grid -->
    <div class="grid" id="worker-grid">
        <!-- Dynamic Cards -->
    </div>

    <div class="timestamp">Server Time: <span id="server-time">{{ now }}</span></div>
</div>

<script>
    async function fetchData() {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            updateUI(data);
        } catch(e) {
            console.error("Failed to fetch fleet status:", e);
        }
    }

    function updateUI(data) {
        // Fleet level
        document.getElementById('total-leads').textContent = (data.summary.total_leads || 0).toLocaleString();
        document.getElementById('total-queries-done').textContent = (data.summary.total_queries_completed || 0).toLocaleString();
        document.getElementById('total-queries-left').textContent = (data.summary.total_queries_remaining || 0).toLocaleString();
        document.getElementById('total-active').textContent = data.summary.active || 0;
        document.getElementById('total-stuck').textContent = data.summary.stuck || 0;
        document.getElementById('update-time').textContent = new Date().toLocaleTimeString();

        // Overall progress bar
        const fleetPct = data.summary.overall_fleet_pct || 0;
        document.getElementById('fleet-pct').textContent = fleetPct + '%';
        document.getElementById('fleet-progress-bar').style.width = fleetPct + '%';

        // Workers Grid
        const grid = document.getElementById('worker-grid');
        grid.innerHTML = '';
        
        for (const [name, w] of Object.entries(data.workers)) {
            const card = document.createElement('div');
            card.className = 'worker-card';

            const statusClass = w.status_class || 'dead';
            const statusText = w.status_text || 'UNKNOWN';

            // Logs
            let logsHtml = '';
            if (w.last_logs && w.last_logs.length > 0) {
                logsHtml = w.last_logs.map(line => {
                    let cls = '';
                    if (line.includes('Deep crawling')) cls = 'highlight-crawl';
                    else if (line.includes('Stored lead') || line.includes('Extracted')) cls = 'highlight-store';
                    else if (line.includes('ERROR') || line.includes('error')) cls = 'highlight-error';
                    return `<div class="log-line ${cls}">${line}</div>`;
                }).join('');
            } else {
                logsHtml = '<div class="log-line" style="color:#64748b;">No logs captured.</div>';
            }

            const queryIdx = w.current_query_idx || 0;
            const queryTotal = w.total_assigned_queries || 0;
            const queryLeft = w.queries_remaining || 0;
            const queryPct = w.progress_pct || 0;

            card.innerHTML = `
                <div>
                    <div class="worker-top">
                        <span class="worker-name">⚙️ ${name}</span>
                        <span class="status-pill ${statusClass}">${statusText}</span>
                    </div>

                    <div class="worker-progress-box">
                        <div class="worker-progress-info">
                            <span>Query Progress: <strong>${queryIdx} / ${queryTotal}</strong></span>
                            <span><strong>${queryPct}%</strong></span>
                        </div>
                        <div class="progress-track" style="height: 6px;">
                            <div class="progress-fill" style="width: ${queryPct}%;"></div>
                        </div>
                    </div>

                    <div class="worker-stats-grid">
                        <div class="stat-item">
                            <div class="lbl">📦 Leads Extracted</div>
                            <div class="val" style="color:#f472b6;">${(w.extracted_count || 0).toLocaleString()}</div>
                        </div>
                        <div class="stat-item">
                            <div class="lbl">⏳ Queries Left</div>
                            <div class="val" style="color:#fbbf24;">${queryLeft.toLocaleString()}</div>
                        </div>
                        <div class="stat-item">
                            <div class="lbl">⏱️ Last Activity</div>
                            <div class="val">${w.age_min} min ago</div>
                        </div>
                        <div class="stat-item">
                            <div class="lbl">📅 Timestamp</div>
                            <div class="val" style="font-size:11px;">${w.last_activity ? w.last_activity.split(' ')[1] : 'N/A'}</div>
                        </div>
                    </div>

                    <div class="query-box" title="${w.current_query_name || 'Idle'}">
                        🎯 <strong>Query:</strong> ${w.current_query_name || 'Preparing query task...'}
                    </div>

                    <div class="url-box" title="${w.current_url || 'Idle'}">
                        ${w.current_url ? '🔗 Crawling: ' + w.current_url : '💤 Waiting for next lead URL...'}
                    </div>
                </div>

                <div class="log-box">
                    ${logsHtml}
                </div>
            `;
            grid.appendChild(card);
        }

        document.getElementById('server-time').textContent = data.server_time || 'N/A';
    }

    fetchData();
    setInterval(fetchData, 4000);
</script>
</body>
</html>
"""

def get_active_tmux_workers():
    """Auto-discover all active worker tmux sessions (e.g. worker_0, worker_1, worker0...)."""
    try:
        output = subprocess.check_output(["tmux", "list-sessions"], text=True)
        workers = []
        for line in output.splitlines():
            sess = line.split(":")[0].strip()
            if sess.startswith("worker"):
                workers.append(sess)
        if workers:
            return sorted(workers)
    except Exception:
        pass
    return ["worker_0", "worker_1", "worker_2", "worker_3", "worker_4", "worker_5", "worker_6", "worker_7"]

def get_worker_status(worker_name):
    check = subprocess.run(["tmux", "has-session", "-t", worker_name], capture_output=True)
    if check.returncode != 0:
        return {
            "status_text": "DEAD",
            "status_class": "dead",
            "last_activity": None,
            "age_min": "N/A",
            "extracted_count": 0,
            "current_query_idx": 0,
            "total_assigned_queries": 0,
            "queries_remaining": 0,
            "progress_pct": 0,
            "current_query_name": "Session Dead",
            "current_url": None,
            "last_logs": ["Session not found."]
        }

    try:
        output = subprocess.check_output(["tmux", "capture-pane", "-t", worker_name, "-p", "-S", "-100"], text=True)
        lines = [l.strip() for l in output.strip().split('\n') if l.strip()]
        
        # 1. Latest timestamp
        timestamps = re.findall(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', output)
        last_time_str = timestamps[-1] if timestamps else None

        # 2. Extracted count
        extract_matches = re.findall(r'Successfully extracted \[(\d+)/UNLIMITED\]: (.*?)(?:\n|$)', output)
        if extract_matches:
            last_extract_count, _ = extract_matches[-1]
            extracted_count = int(last_extract_count)
        else:
            extracted_count = 0

        # 3. Query Progress Parsing
        # Pattern: Processing query [42/2403]: Dentist in New York, United States
        query_matches = re.findall(r'Processing query \[(\d+)/(\d+)\]: (.*?)(?:\n|$)', output)
        if query_matches:
            curr_q, total_q, q_name = query_matches[-1]
            current_query_idx = int(curr_q)
            total_assigned_queries = int(total_q)
            current_query_name = q_name.strip()
        else:
            current_query_idx = 0
            total_assigned_queries = 0
            current_query_name = "Starting..."

        queries_remaining = max(0, total_assigned_queries - current_query_idx)
        progress_pct = round((current_query_idx / total_assigned_queries * 100), 1) if total_assigned_queries > 0 else 0.0

        # 4. Current URL (Deep crawling website: ...)
        url_matches = re.findall(r'Deep crawling website: (.*?)(?:\n|$)', output)
        current_url = url_matches[-1] if url_matches else None

        # 5. Last 4 log lines for visual clarity
        last_logs = lines[-4:] if len(lines) >= 4 else lines

        # --- Status Logic ---
        age_min = 999
        if last_time_str:
            last_dt = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            age_min = round((now - last_dt).total_seconds() / 60, 1)

        last_crawl_idx = -1
        last_store_idx = -1
        for i, line in enumerate(lines):
            if "Deep crawling" in line:
                last_crawl_idx = i
            if "Stored lead" in line or "Merged lead" in line:
                last_store_idx = i

        is_stuck = False
        if last_crawl_idx != -1 and (last_store_idx == -1 or last_store_idx < last_crawl_idx):
            if age_min > 3:
                is_stuck = True

        if is_stuck:
            status_text = "🔴 STUCK"
            status_class = "stuck"
        elif age_min > 15:
            status_text = "🟡 INACTIVE"
            status_class = "inactive"
        else:
            status_text = "🟢 ACTIVE"
            status_class = "active"

        return {
            "status_text": status_text,
            "status_class": status_class,
            "last_activity": last_time_str,
            "age_min": age_min,
            "extracted_count": extracted_count,
            "current_query_idx": current_query_idx,
            "total_assigned_queries": total_assigned_queries,
            "queries_remaining": queries_remaining,
            "progress_pct": progress_pct,
            "current_query_name": current_query_name,
            "current_url": current_url,
            "last_logs": last_logs
        }

    except Exception as e:
        return {
            "status_text": "ERROR",
            "status_class": "dead",
            "last_activity": None,
            "age_min": "N/A",
            "extracted_count": 0,
            "current_query_idx": 0,
            "total_assigned_queries": 0,
            "queries_remaining": 0,
            "progress_pct": 0,
            "current_query_name": "Error",
            "current_url": None,
            "last_logs": [f"Error: {str(e)}"]
        }

@app.route('/')
def dashboard():
    return render_template_string(HTML_TEMPLATE, now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/api/status')
def api_status():
    workers_list = get_active_tmux_workers()
    workers_data = {}
    total_leads = 0
    total_queries_completed = 0
    total_queries_assigned = 0
    active = stuck = inactive = dead = 0

    for w in workers_list:
        data = get_worker_status(w)
        workers_data[w] = data

        if data.get('extracted_count'):
            total_leads += data['extracted_count']
        
        total_queries_completed += data.get('current_query_idx', 0)
        total_queries_assigned += data.get('total_assigned_queries', 0)

        cls = data.get('status_class')
        if cls == 'active': active += 1
        elif cls == 'stuck': stuck += 1
        elif cls == 'inactive': inactive += 1
        else: dead += 1

    total_queries_remaining = max(0, total_queries_assigned - total_queries_completed)
    overall_fleet_pct = round((total_queries_completed / total_queries_assigned * 100), 1) if total_queries_assigned > 0 else 0.0

    return jsonify({
        "server_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "workers": workers_data,
        "summary": {
            "total_leads": total_leads,
            "total_queries_completed": total_queries_completed,
            "total_queries_assigned": total_queries_assigned,
            "total_queries_remaining": total_queries_remaining,
            "overall_fleet_pct": overall_fleet_pct,
            "active": active,
            "stuck": stuck,
            "inactive": inactive,
            "dead": dead
        }
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
