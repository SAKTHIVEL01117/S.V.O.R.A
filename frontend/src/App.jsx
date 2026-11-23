import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getMaintenanceRecommendation, healthCheck, uploadAnalyticsFile } from './api/client';
import PanelCard from './components/PanelCard';

// ─── Helper: decision class ───────────────────────────────────────────────────
function getDecisionClass(decision) {
  switch (decision) {
    case 'CLEARED_TO_FLY': return 'fly-cleared';
    case 'FLY_WITH_MONITORING': return 'fly-monitor';
    case 'MAINTENANCE_REQUIRED_BEFORE_FLIGHT': return 'fly-maint';
    case 'GROUND_AIRCRAFT': return 'fly-ground';
    default: return '';
  }
}

// ─── Helper: status dot class ─────────────────────────────────────────────────
function getStatusDotClass(statusText) {
  const s = (statusText || '').toLowerCase();
  if (s.includes('online') || s.includes('ready')) return 'dot-online';
  if (s.includes('offline')) return 'dot-offline';
  return 'dot-pending';
}

// ─── Helper: health badge ─────────────────────────────────────────────────────
function getHealthBadgeClass(status) {
  switch ((status || '').toUpperCase()) {
    case 'MONITOR': return 'monitor';
    case 'OK':
    case 'NORMAL':
    case 'SAFE': return 'ok';
    case 'CRITICAL':
    case 'ALERT':
    case 'MAINTENANCE REQUIRED':
    case 'GROUND AIRCRAFT': return 'critical';
    default: return 'monitor';
  }
}

// ─── Helper: risk badge ───────────────────────────────────────────────────────
function getRiskBadgeClass(level) {
  switch ((level || '').toUpperCase()) {
    case 'LOW': return 'risk-low';
    case 'MEDIUM': return 'risk-medium';
    case 'HIGH':
    case 'CRITICAL': return 'risk-high';
    case 'UNKNOWN': return 'risk-unknown';
    default: return 'risk-medium';
  }
}

// ─── Helper: trend arrow ──────────────────────────────────────────────────────
function getTrendArrow(direction) {
  switch (direction) {
    case 'INCREASING': return '↑';
    case 'DECREASING': return '↓';
    case 'STABLE': return '→';
    default: return '·';
  }
}

// ─── Helper: gauge level ──────────────────────────────────────────────────────
function getGaugeLevel(value, warn, max) {
  const pct = (value / max) * 100;
  if (value >= warn) return 'level-warn';
  if (pct > 85) return 'level-danger';
  return 'level-ok';
}

// ─── AI Loading Steps ─────────────────────────────────────────────────────────
const AI_STEPS = [
  { label: 'Reading telemetry data', delay: 0 },
  { label: 'Consulting maintenance manual', delay: 2500 },
  { label: 'Generating maintenance decision', delay: 5000 },
];

function AiLoadingSteps() {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const timers = AI_STEPS.slice(1).map((step, i) =>
      setTimeout(() => setActiveStep(i + 1), step.delay)
    );
    return () => timers.forEach(clearTimeout);
  }, []);

  return (
    <div className="ai-steps">
      {AI_STEPS.map((step, i) => {
        const isDone = i < activeStep;
        const isActive = i === activeStep;
        const isPending = i > activeStep;
        return (
          <div
            key={step.label}
            className={`ai-step ${isDone ? 'step-done' : isActive ? 'step-active' : 'step-pending'}`}
          >
            <div className="ai-step-icon">
              {isDone ? '✓' : isActive ? '·' : '○'}
            </div>
            <span>{step.label}{isActive ? '...' : ''}</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Analytics Skeleton ───────────────────────────────────────────────────────
function AnalyticsSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div className="skeleton" style={{ height: 68, borderRadius: 'var(--radius-sm)' }} />
      <div className="skeleton" style={{ height: 120, borderRadius: 'var(--radius-sm)' }} />
      <div className="skeleton" style={{ height: 180, borderRadius: 'var(--radius-sm)' }} />
    </div>
  );
}

// ─── App ──────────────────────────────────────────────────────────────────────
function App() {
  const [excelFile, setExcelFile] = useState(null);
  const [status, setStatus] = useState('Checking backend connection...');
  const [isLoading, setIsLoading] = useState(false);
  const [loadingPhase, setLoadingPhase] = useState('');
  const [analyticsResult, setAnalyticsResult] = useState(null);
  const [recommendation, setRecommendation] = useState(null);
  const [error, setError] = useState('');
  const [checkedSteps, setCheckedSteps] = useState(new Set());
  const [dragOver, setDragOver] = useState(false);

  // ── Ping backend on mount ──
  useEffect(() => {
    const pingBackend = async () => {
      try {
        const result = await healthCheck();
        setStatus(`Backend online · ${result.service || 'API ready'}`);
      } catch (err) {
        setStatus('Backend offline. Start FastAPI on port 8000.');
        setError(err.message);
      }
    };
    pingBackend();
  }, []);

  // ── Checklist toggle ──
  const toggleStep = useCallback((idx) => {
    setCheckedSteps(prev => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }, []);

  // ── File drag handlers ──
  const handleDragOver = useCallback((e) => {
    e.preventDefault();
    setDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => setDragOver(false), []);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file && (file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
      setExcelFile(file);
    }
  }, []);

  // ── Analytics submit ──
  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!excelFile) {
      setError('Please upload an Excel file first.');
      return;
    }
    setIsLoading(true);
    setLoadingPhase('analytics');
    setError('');
    setRecommendation(null);
    try {
      const response = await uploadAnalyticsFile(excelFile);
      setAnalyticsResult(response);
      setStatus(`Analytics ready for ${response.aircraft_id || 'selected aircraft'}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
      setLoadingPhase('');
    }
  };

  // ── AI recommendation ──
  const handleRecommendation = async () => {
    if (!analyticsResult) {
      setError('Generate analytics first.');
      return;
    }
    setIsLoading(true);
    setLoadingPhase('ai');
    setError('');
    try {
      const response = await getMaintenanceRecommendation(analyticsResult);
      setRecommendation(response);
      setStatus('AI maintenance recommendation generated');
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
      setLoadingPhase('');
    }
  };

  // ── Work order export ──
  const handlePrintWorkOrder = () => window.print();

  const handleExportWorkOrder = useCallback(() => {
    if (!recommendationSummary?.work_order) return;
    const blob = new Blob([JSON.stringify(recommendationSummary.work_order, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `work-order-${recommendationSummary.work_order.aircraft_id || 'export'}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [/* depends on recommendationSummary at call time */]);

  // ── Derived data ──
  const currentRecord = analyticsResult?.summary?.current_record;
  const historicalAnalysis = analyticsResult?.summary?.historical_analysis || [];
  const recommendationSummary = recommendation?.report || null;

  const metrics = useMemo(() => {
    if (!analyticsResult?.summary) return [];
    const summary = analyticsResult.summary;
    const analysis = summary.historical_analysis || [];
    const riskSignal = analysis.find((item) => item.column === 'Risk_Score');
    const vibrationSignal = analysis.find((item) => item.column === 'Engine_Vibration');
    const rulSignal = analysis.find((item) => item.column === 'Remaining_Useful_Life');
    const record = summary.current_record || {};
    return [
      { icon: '✈', label: 'Aircraft', value: analyticsResult.aircraft_id || 'N/A', sub: record.Aircraft_Model || 'Unknown model', accent: 'cobalt' },
      { icon: '⚙', label: 'Engine', value: record.Engine_Model || 'N/A', sub: `Airport: ${record.Airport_Code || 'N/A'}`, accent: 'cobalt' },
      { icon: '🔄', label: 'Flight Cycle', value: summary.latest_flight_cycle || 'N/A', sub: `${record.Flight_Hours || 0} flight hours logged`, accent: 'cobalt' },
      { icon: '🔧', label: 'Since Overhaul', value: record.Cycles_Since_Overhaul || 'N/A', sub: `Last maintenance: ${record.Last_Maintenance_Date || 'N/A'}`, accent: 'cobalt' },
      { icon: '⚠', label: 'Risk Score', value: riskSignal ? riskSignal.latest_value : 'N/A', sub: riskSignal ? `${riskSignal.change_percent > 0 ? '+' : ''}${riskSignal.change_percent.toFixed(1)}% vs history` : '', accent: riskSignal && riskSignal.latest_value > 70 ? 'red' : riskSignal && riskSignal.latest_value > 50 ? 'amber' : 'lime' },
      { icon: '🛡', label: 'Remaining Life', value: rulSignal ? `${rulSignal.latest_value} cycles` : 'N/A', sub: rulSignal ? `${rulSignal.change_percent > 0 ? '+' : ''}${rulSignal.change_percent.toFixed(1)}% vs avg` : '', accent: rulSignal && rulSignal.latest_value < 30 ? 'red' : rulSignal && rulSignal.latest_value < 50 ? 'amber' : 'lime' },
      { icon: '📳', label: 'Vibration', value: vibrationSignal ? `${vibrationSignal.latest_value} mm/s` : 'N/A', sub: vibrationSignal ? vibrationSignal.trend_direction : '', accent: vibrationSignal && vibrationSignal.trend_direction === 'INCREASING' ? 'orange' : 'cobalt' },
      { icon: '📊', label: 'Signals', value: historicalAnalysis.length, sub: `Window: ${analyticsResult.summary.historical_window_size || 10} cycles`, accent: 'lime' },
      { icon: '🌡', label: 'Ambient', value: `${currentRecord?.Ambient_Temperature?.toFixed(1) || 'N/A'}°C`, sub: `Humidity: ${currentRecord?.Humidity || 'N/A'}%`, accent: 'cobalt' },
    ];
  }, [analyticsResult, currentRecord, historicalAnalysis.length]);

  const engineGauges = useMemo(() => {
    if (!currentRecord) return [];
    return [
      { label: 'Engine Temp', value: currentRecord.Engine_Temperature, unit: '°C', max: 900, warn: 750 },
      { label: 'EGT', value: currentRecord.Exhaust_Gas_Temperature, unit: '°C', max: 850, warn: 700 },
      { label: 'Oil Temp', value: currentRecord.Oil_Temperature, unit: '°C', max: 150, warn: 110 },
      { label: 'Oil Pressure', value: currentRecord.Oil_Pressure, unit: 'psi', max: 65, warn: 45 },
      { label: 'Engine RPM', value: currentRecord.Engine_RPM, unit: 'RPM', max: 12000, warn: 10500 },
      { label: 'Fuel Flow', value: currentRecord.Fuel_Flow, unit: 'kg/h', max: 3200, warn: 2800 },
      { label: 'Compressor', value: currentRecord.Compressor_Pressure, unit: 'psi', max: 55, warn: 48 },
      { label: 'Hydraulic', value: currentRecord.Hydraulic_Pressure, unit: 'psi', max: 3500, warn: 3200 },
    ];
  }, [currentRecord]);

  const workflowSteps = [
    { number: '1', title: 'Flight intake', description: 'Upload the landed-flight telemetry export for review.' },
    { number: '2', title: 'Condition review', description: 'Compare the current signals with recent historical behavior.' },
    { number: '3', title: 'Action guidance', description: 'Receive AI-backed maintenance direction grounded in the manual.' },
  ];

  const dotClass = getStatusDotClass(status);

  return (
    <div className="app-shell">
      {/* ── Header ── */}
      <header className="topbar" data-enter>
        <div className="topbar-glow" aria-hidden="true" />
        <div className="hero-copy">
          <p className="eyebrow">
            <span className="eyebrow-line" />
            Post-landing operational intelligence
            <span className="eyebrow-line" />
          </p>
          <h1>
            <span className="logo-mark" aria-hidden="true">
              <svg viewBox="0 0 36 36" width="36" height="36">
                <rect x="2" y="2" width="32" height="32" fill="none" stroke="var(--lime)" strokeWidth="1.5" />
                <line x1="2" y1="18" x2="34" y2="18" stroke="var(--cobalt)" strokeWidth="1" strokeDasharray="2 2" />
                <line x1="18" y1="2" x2="18" y2="34" stroke="var(--cobalt)" strokeWidth="1" strokeDasharray="2 2" />
                <text x="18" y="23" textAnchor="middle" fontSize="15" fill="var(--lime)" fontFamily="Times New Roman, serif">S</text>
              </svg>
            </span>
            <span className="title-text">S.V.O.R.A — Aircraft Maintenance Intelligence</span>
          </h1>
          <p className="hero-subtitle">
            Upload telemetry. Review 14 health signals. Get a maintenance decision grounded in the aircraft manual.
          </p>
          <div className="hero-tags">
            <span className="hero-tag">AI-Powered</span>
            <span className="hero-tag">Real-time Analytics</span>
            <span className="hero-tag">Manual-Grounded</span>
          </div>
        </div>
        <div className="status-pill">
          <span className={`status-dot ${dotClass}`} />
          {status}
        </div>
      </header>

      {/* ── Workflow Strip ── */}
      <section className="workflow-strip" aria-label="Dashboard workflow">
        {workflowSteps.map((step) => (
          <div key={step.title} className="workflow-step">
            <div className="step-number">{step.number}</div>
            <h4>{step.title}</h4>
            <p>{step.description}</p>
          </div>
        ))}
      </section>

      {/* ── Flight Track Card ── */}
      <section className="flight-track-card">
        <div className="track-copy">
          <p className="eyebrow">Live flight monitoring</p>
          <h3>
            {analyticsResult
              ? `Flight ${analyticsResult.aircraft_id} has landed and is being assessed.`
              : 'A landed flight is ready for assessment.'}
          </h3>
          <p>Compare the latest landed-flight telemetry with its historical baseline.</p>
        </div>
        <div className="track-visual" aria-hidden="true">
          <svg viewBox="0 0 340 120" role="presentation">
            <defs>
              <linearGradient id="trackGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stopColor="#1e3a8a" stopOpacity="0.4" />
                <stop offset="50%" stopColor="#d9f99d" stopOpacity="0.9" />
                <stop offset="100%" stopColor="#2563eb" stopOpacity="0.4" />
              </linearGradient>
            </defs>

            {/* Flight path arc */}
            <path d="M24 82 C70 20, 130 20, 170 55 S250 108, 316 32" className="track-arc" />

            {/* Airport nodes */}
            <circle cx="24" cy="82" r="5" className="track-node departure" />
            <circle cx="170" cy="55" r="5" className="track-node active" />
            <circle cx="316" cy="32" r="5" className="track-node landing" />

            {/* Animated plane on motion-path */}
            <g className="plane-group-motion">
              {/* Fuselage */}
              <ellipse cx="0" cy="0" rx="24" ry="5" className="plane-body" />
              {/* Nose */}
              <path d="M24 0 Q32 0 28 -2 Q24 -4 24 0 Z" className="plane-body" />
              {/* Main wing */}
              <path d="M-6 0 L-16 -16 L-12 -16 L4 -2 Z" className="plane-wing" />
              <path d="M-6 0 L-16 16 L-12 16 L4 2 Z" className="plane-wing" />
              {/* Tail fin */}
              <path d="M-24 0 L-30 -12 L-26 -12 L-22 -2 Z" className="plane-tail" />
              {/* Tail horizontal */}
              <path d="M-24 0 L-30 6 L-26 6 L-22 2 Z" className="plane-tail" />
              {/* Windows */}
              <circle cx="8" cy="-0.5" r="1.2" className="plane-window" />
              <circle cx="4" cy="-0.5" r="1.2" className="plane-window" />
              <circle cx="0" cy="-0.5" r="1.2" className="plane-window" />
              {/* Engine glow */}
              <line x1="-27" y1="0" x2="-34" y2="0" className="plane-engine-glow" />
            </g>
          </svg>
          <div className="track-labels">
            <span>Departure</span>
            <span>En route</span>
            <span>Landing</span>
          </div>
        </div>
      </section>

      {/* ── Dashboard Grid ── */}
      <div className="dashboard-grid">
        {/* ── Sidebar ── */}
        <aside className="sidebar">
          <PanelCard title="Flight Data Upload" subtitle="Upload the landed-flight telemetry export and begin the engineering review.">
            <form onSubmit={handleSubmit} className="upload-form">
              <label
                className={`file-field${dragOver ? ' drag-over' : ''}`}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
              >
                <span>Engineering Excel (.xlsx)</span>
                {excelFile ? (
                  <div className="file-selected">
                    <span className="file-selected-icon">✓</span>
                    <span>{excelFile.name}</span>
                  </div>
                ) : (
                  <input
                    type="file"
                    accept=".xlsx,.xls"
                    onChange={(e) => setExcelFile(e.target.files?.[0] || null)}
                  />
                )}
              </label>

              <p className="helper-text compact">
                Compare the latest landed-flight telemetry with its historical baseline.
              </p>

              <button type="submit" className="primary-btn" disabled={isLoading}>
                {isLoading && loadingPhase === 'analytics' ? 'Analyzing telemetry...' : 'Run analytics'}
              </button>
            </form>
          </PanelCard>

          <PanelCard
            title="Maintenance Guidance"
            subtitle="Use the analytics output and the aviation manual for action guidance."
            accent="ai"
            badge={
              <span className="panel-badge ai-badge">
                <span className="ai-sparkle">✨</span>
                AI Powered
              </span>
            }
          >
            <p className="helper-text compact">
              The aircraft manual is bundled server-side. Analytics must be run first.
            </p>

            <button
              className="primary-btn wide ai-btn"
              onClick={handleRecommendation}
              disabled={isLoading || !analyticsResult}
            >
              {isLoading && loadingPhase === 'ai' ? '✨ AI is analyzing...' : '✨ Run AI diagnosis'}
            </button>
          </PanelCard>
        </aside>

        {/* ── Main Content ── */}
        <main className="main-content">
          {/* Metric cards — only render when there are metrics */}
          {metrics.length > 0 && (
            <div className="metric-row">
              {metrics.map((metric) => (
                <div className={`metric-card ${metric.accent}`} key={metric.label}>
                  <span className="metric-icon">{metric.icon}</span>
                  <span className="metric-label">{metric.label}</span>
                  <strong className="metric-value">{metric.value}</strong>
                  <small className="metric-sub">{metric.sub}</small>
                </div>
              ))}
            </div>
          )}

          {error ? <div className="error-box">⚠ {error}</div> : null}

          <div className="split-view">
            {/* ─── Engineering Analytics ─── */}
            <PanelCard title="Engineering Analytics" subtitle="Operational health derived from the uploaded aircraft dataset">
              {isLoading && loadingPhase === 'analytics' ? (
                <AnalyticsSkeleton />
              ) : analyticsResult ? (
                <div className="analytics-panel">
                  {/* Aircraft overview header */}
                  <div className="aircraft-header">
                    <div className="aircraft-avatar">✈</div>
                    <div className="aircraft-info">
                      <h4>{analyticsResult.aircraft_id} — {currentRecord?.Aircraft_Model || 'Unknown'}</h4>
                      <div className="aircraft-meta">
                        <span>🔧 {currentRecord?.Engine_Model || 'N/A'}</span>
                        <span>📍 {currentRecord?.Airport_Code || 'N/A'}</span>
                        <span>🔄 Cycle {analyticsResult.summary.latest_flight_cycle}</span>
                      </div>
                    </div>
                  </div>

                  {/* Engine Gauges */}
                  <div className="gauge-grid">
                    {engineGauges.map((gauge) => {
                      const pct = Math.min(((gauge.value || 0) / gauge.max) * 100, 100);
                      const level = getGaugeLevel(gauge.value || 0, gauge.warn, gauge.max);
                      return (
                        <div className="gauge-card" key={gauge.label}>
                          <span className="gauge-label">{gauge.label}</span>
                          <div className="gauge-value-row">
                            <span className="gauge-value">{gauge.value?.toLocaleString() || 'N/A'}</span>
                            <span className="gauge-unit">{gauge.unit}</span>
                          </div>
                          <div className="gauge-bar-track">
                            <div className={`gauge-bar-fill ${level}`} style={{ width: `${pct}%` }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Signal Trends — proper <table> */}
                  <div className="signal-list">
                    <h4>
                      Signal Trends
                      <span className="signal-count">{historicalAnalysis.length} parameters</span>
                    </h4>
                    <table className="signal-table">
                      <thead>
                        <tr>
                          <th>Parameter</th>
                          <th>Current</th>
                          <th>Avg</th>
                          <th>Std Dev</th>
                          <th>Change</th>
                          <th>Trend</th>
                        </tr>
                      </thead>
                      <tbody>
                        {historicalAnalysis.map((item) => (
                          <tr key={item.column}>
                            <td className="signal-name">{item.column.replace(/_/g, ' ')}</td>
                            <td className="signal-value">{item.latest_value?.toLocaleString()}</td>
                            <td className="signal-value">{item.historical_average != null ? Number(item.historical_average).toFixed(2) : '—'}</td>
                            <td className="signal-value">{item.historical_std_dev != null ? Number(item.historical_std_dev).toFixed(2) : '—'}</td>
                            <td className={`signal-change ${item.change_percent >= 0 ? 'positive' : 'negative'}`}>
                              {item.change_percent > 0 ? '+' : ''}{item.change_percent?.toFixed(1)}%
                            </td>
                            <td>
                              <span className={`trend-badge ${item.trend_direction?.toLowerCase()}`}>
                                <span className="trend-arrow">{getTrendArrow(item.trend_direction)}</span>
                                {item.trend_direction}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : (
                <p className="empty-state">
                  <span className="empty-state-icon">📊</span>
                  Upload the Excel file and generate engineering analytics to view the aircraft health dashboard.
                </p>
              )}
            </PanelCard>

            {/* ─── AI Maintenance Recommendation ─── */}
            <PanelCard
              title="AI Maintenance Recommendation"
              subtitle="Intelligent guidance generated from analytics & maintenance manual"
              accent="ai"
              badge={
                <span className="panel-badge ai-badge">
                  <span className="ai-sparkle">✨</span>
                  AI Powered
                </span>
              }
            >
              {isLoading && loadingPhase === 'ai' ? (
                <AiLoadingSteps />
              ) : recommendationSummary ? (
                <div className="recommendation-panel">
                  {/* AI Header */}
                  <div className="ai-header">
                    <div className="ai-brain-icon">🧠</div>
                    <div>
                      <span className="ai-label">AI Analysis</span>
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                        {recommendationSummary.aircraft} · {recommendationSummary.aircraft_model}
                      </div>
                    </div>
                  </div>

                  {/* Health & Risk Status */}
                  <div className="status-banner">
                    <span className={`status-badge ${getHealthBadgeClass(recommendationSummary.health_status)}`}>
                      <span className="badge-dot" />
                      {recommendationSummary.health_status}
                    </span>
                    <span className={`status-badge ${getRiskBadgeClass(recommendationSummary.risk_level)}`}>
                      <span className="badge-dot" />
                      {recommendationSummary.risk_level} RISK
                    </span>
                    <span className={`status-badge ${recommendationSummary.safe_for_next_flight ? 'ok' : 'critical'}`}>
                      <span className="badge-dot" />
                      {recommendationSummary.safe_for_next_flight ? 'SAFE FOR FLIGHT' : 'GROUND AIRCRAFT'}
                    </span>
                  </div>

                  {/* Overall Summary */}
                  {recommendationSummary.overall_summary && (
                    <div className="overall-summary">
                      <p>{recommendationSummary.overall_summary}</p>
                    </div>
                  )}

                  {/* Flight Decision Banner — dominant element */}
                  {recommendationSummary.final_flight_decision && (() => {
                    const fd = recommendationSummary.final_flight_decision;
                    const decClass = getDecisionClass(fd.decision);
                    return (
                      <div className={`flight-decision ${decClass}`}>
                        <div className="decision-header">
                          <div className={`decision-icon ${fd.can_fly_now ? 'fly' : 'ground'}`}>
                            {fd.can_fly_now ? '✅' : '🚫'}
                          </div>
                          <div>
                            <div className="decision-title">{fd.decision?.replace(/_/g, ' ')}</div>
                            <div className="decision-subtitle">{fd.required_before_next_flight}</div>
                          </div>
                          <span className={`can-fly-pill ${fd.can_fly_now ? 'pill-fly' : 'pill-ground'}`}>
                            {fd.can_fly_now ? 'CAN FLY' : 'NO FLY'}
                          </span>
                        </div>
                        <div className="decision-statement">
                          {fd.ui_statement}
                        </div>
                        {fd.decision_rationale && (
                          <div className="decision-rationale">
                            💡 {fd.decision_rationale}
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Threshold Violations */}
                  {recommendationSummary.threshold_violations?.length > 0 && (
                    <div className="violations-section">
                      <h4>⚠ Threshold Violations</h4>
                      {recommendationSummary.threshold_violations.map((v, i) => (
                        <div className="violation-card" key={i}>
                          <div className="violation-header">
                            <span className="violation-param">{v.parameter?.replace(/_/g, ' ')}</span>
                            <span className="violation-severity">{v.severity}</span>
                          </div>
                          <div className="violation-values">
                            <div className="violation-val">
                              <label>Observed</label>
                              <span style={{ color: 'var(--red)' }}>{v.observed_value}</span>
                            </div>
                            <div className="violation-val">
                              <label>Threshold</label>
                              <span>{v.manual_threshold}</span>
                            </div>
                          </div>
                          {v.explanation && <div className="violation-explanation">{v.explanation}</div>}
                          {v.manual_reference && <span className="manual-ref">📖 {v.manual_reference}</span>}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Root Cause Analysis */}
                  {recommendationSummary.root_cause && (
                    <div className="root-cause-card">
                      <h4>🔍 Root Cause Analysis</h4>
                      <div className="cause-title">{recommendationSummary.root_cause.most_likely_cause}</div>
                      <ul className="evidence-list">
                        {(recommendationSummary.root_cause.supporting_evidence || []).map((e, i) => (
                          <li key={i}>{e}</li>
                        ))}
                      </ul>
                      {recommendationSummary.root_cause.manual_reference && (
                        <span className="manual-ref">📖 {recommendationSummary.root_cause.manual_reference}</span>
                      )}
                    </div>
                  )}

                  {/* Maintenance Actions */}
                  {recommendationSummary.maintenance_actions?.length > 0 && (
                    <div className="actions-list">
                      <h4>🔧 Maintenance Actions</h4>
                      {recommendationSummary.maintenance_actions.map((action, i) => (
                        <div className="action-item" key={i}>
                          <div className="action-priority">P{action.priority}</div>
                          <div className="action-content">
                            <div className="action-text">{action.action}</div>
                            <div className="action-reason">{action.reason}</div>
                            {action.manual_reference && <span className="manual-ref">📖 {action.manual_reference}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Inspection Checklist — interactive */}
                  {recommendationSummary.inspection_checklist?.length > 0 && (
                    <div className="checklist-section">
                      <h4>📋 Inspection Checklist</h4>
                      {recommendationSummary.inspection_checklist.map((item, i) => {
                        const isChecked = checkedSteps.has(i);
                        return (
                          <div
                            className={`checklist-item${isChecked ? ' checked' : ''}`}
                            key={i}
                            onClick={() => toggleStep(i)}
                            role="checkbox"
                            aria-checked={isChecked}
                            tabIndex={0}
                            onKeyDown={(e) => e.key === 'Enter' || e.key === ' ' ? toggleStep(i) : null}
                          >
                            <div className={`checklist-step${isChecked ? ' checked-step' : ''}`}>
                              {isChecked ? '✓' : item.step}
                            </div>
                            <div className="checklist-content">
                              <div className="check-title">{item.inspection_item}</div>
                              <div className="check-criteria">✓ {item.acceptance_criteria}</div>
                              {item.manual_reference && <span className="manual-ref">📖 {item.manual_reference}</span>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Confidence & Work Order Row */}
                  <div className="info-row">
                    <div className="info-card">
                      <span className="info-label">AI Confidence</span>
                      <span className="info-value" style={{ color: 'var(--purple)' }}>
                        {recommendationSummary.confidence?.score
                          ? `${(recommendationSummary.confidence.score * 100).toFixed(0)}%`
                          : 'N/A'}
                      </span>
                      <div className="confidence-bar-track">
                        <div
                          className="confidence-bar-fill"
                          style={{ width: `${(recommendationSummary.confidence?.score || 0) * 100}%` }}
                        />
                      </div>
                      {recommendationSummary.confidence?.rationale && (
                        <span className="info-sub">{recommendationSummary.confidence.rationale}</span>
                      )}
                    </div>
                    <div className="info-card">
                      <span className="info-label">Work Order Type</span>
                      <span className="info-value" style={{ color: 'var(--sky)' }}>
                        {recommendationSummary.work_order?.work_order_type || 'N/A'}
                      </span>
                      <span className="info-sub">Priority: {recommendationSummary.work_order?.priority || 'N/A'}</span>
                      <span className="info-sub">{recommendationSummary.work_order?.estimated_maintenance_category || ''}</span>
                    </div>
                  </div>

                  {/* Work Order Details */}
                  {recommendationSummary.work_order && (
                    <div className="work-order-card">
                      <h4>📝 Work Order — {recommendationSummary.work_order.title}</h4>
                      <div className="wo-meta">
                        <div className="wo-meta-item">
                          <label>Aircraft</label>
                          <span>{recommendationSummary.work_order.aircraft_id}</span>
                        </div>
                        <div className="wo-meta-item">
                          <label>Category</label>
                          <span>{recommendationSummary.work_order.estimated_maintenance_category}</span>
                        </div>
                      </div>

                      {recommendationSummary.work_order.tasks?.length > 0 && (
                        <ul className="wo-tasks">
                          {recommendationSummary.work_order.tasks.map((task, i) => (
                            <li key={i}>{task}</li>
                          ))}
                        </ul>
                      )}

                      {recommendationSummary.work_order.required_parts_or_tools?.length > 0 && (
                        <div className="wo-parts">
                          {recommendationSummary.work_order.required_parts_or_tools.map((part, i) => (
                            <span className="wo-part-tag" key={i}>{part}</span>
                          ))}
                        </div>
                      )}

                      {/* Work order actions */}
                      <div className="wo-actions">
                        <button className="wo-action-btn" onClick={handlePrintWorkOrder}>
                          🖨 Print work order
                        </button>
                        <button className="wo-action-btn" onClick={handleExportWorkOrder}>
                          ⬇ Export JSON
                        </button>
                      </div>
                    </div>
                  )}

                  {/* Missing Information */}
                  {recommendationSummary.confidence?.missing_information?.length > 0 && (
                    <div className="summary-box" style={{ borderColor: 'rgba(251, 191, 36, 0.15)' }}>
                      <h4 style={{ color: 'var(--amber)' }}>⚡ Missing Information</h4>
                      <ul style={{ listStyle: 'none', padding: 0, margin: '4px 0 0' }}>
                        {recommendationSummary.confidence.missing_information.map((info, i) => (
                          <li key={i} style={{ fontSize: '0.82rem', color: 'var(--text-muted)', padding: '3px 0', paddingLeft: '14px', position: 'relative' }}>
                            <span style={{ position: 'absolute', left: 0, color: 'var(--amber)' }}>·</span>
                            {info}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <p className="empty-state">
                  <span className="empty-state-icon">🧠</span>
                  Generate the AI recommendation to view the intelligent maintenance decision board.
                </p>
              )}
            </PanelCard>
          </div>
        </main>
      </div>

      {/* ── Footer ── */}
      <footer className="app-footer">
        S.V.O.R.A · Aircraft Maintenance Intelligence · Powered by Amazon Bedrock Nova Pro
      </footer>
    </div>
  );
}

export default App;
