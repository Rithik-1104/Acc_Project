import React, { useState } from 'react';
import { Gauge, Zap, AlertTriangle, ShieldAlert, RotateCcw, Power, Bug, CheckCircle2, XCircle } from 'lucide-react';

export function PerformanceAndFaultTesting({
  nodeStates,
  currentLeader,
  faultToken
}) {
  const [selectedNode, setSelectedNode] = useState('node2');
  const [actionLoading, setActionLoading] = useState(false);
  const [lastActionResult, setLastActionResult] = useState(null);
  const [confirmDialog, setConfirmDialog] = useState(null);

  // Find metrics from leader or first connected node
  const activeState = currentLeader ? nodeStates[currentLeader] : Object.values(nodeStates)[0];
  const m = activeState?.metrics || {};

  const executeFaultAction = async (endpoint, payload, actionName, explanation) => {
    // Determine target host port
    const portMap = { node1: 9001, node2: 9002, node3: 9003 };
    const targetPort = portMap[selectedNode] || 9002;
    const host = typeof window !== 'undefined' ? (window.location.hostname || 'localhost') : 'localhost';
    const targetUrl = `http://${host}:${targetPort}/api/fault/${endpoint}`;

    setActionLoading(true);
    setLastActionResult({ status: 'SUBMITTING', message: `Submitting ${actionName} to ${selectedNode}...` });

    try {
      const headers = { 'Content-Type': 'application/json' };
      if (faultToken) {
        headers['X-Fault-Token'] = faultToken;
      }

      const res = await fetch(targetUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (res.ok) {
        setLastActionResult({
          status: 'SUCCESS',
          message: `${actionName} confirmed by ${selectedNode}`,
          details: data
        });
      } else {
        setLastActionResult({
          status: 'ERROR',
          message: data.detail || `Action failed with HTTP ${res.status}`,
          details: data
        });
      }
    } catch (err) {
      setLastActionResult({
        status: 'ERROR',
        message: `Network error contacting ${selectedNode} at port ${targetPort}: ${err.message}`
      });
    } finally {
      setActionLoading(false);
      setConfirmDialog(null);
    }
  };

  const handleActionClick = (endpoint, payload, actionName, explanation) => {
    setConfirmDialog({
      actionName,
      explanation,
      onConfirm: () => executeFaultAction(endpoint, payload, actionName, explanation)
    });
  };

  return (
    <section style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Gauge size={18} color="#3b82f6" />
          SECTION 4 — PERFORMANCE &amp; FAULT TESTING
        </h2>
        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
          Real Measurements from MetricsEngine &amp; Multi-Node Fault Injection Controls
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1.2fr) minmax(320px, 1fr)', gap: '16px' }}>
        
        {/* Performance Metrics Panel */}
        <div className="glass-panel" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '0.88rem', fontWeight: 600, color: '#f8fafc', margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Zap size={16} color="#10b981" />
              Consensus &amp; Application Latency Metrics
            </h3>
            <span style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
              Window: 1000 samples | Samples: <strong style={{ color: '#f8fafc' }}>{m.sample_count ?? 0}</strong>
            </span>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '10px', marginBottom: '14px' }}>
            <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '10px', borderRadius: '6px' }}>
              <div style={{ color: '#64748b', fontSize: '0.7rem' }}>TOTAL PROPOSALS</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#f8fafc', fontSize: '1.1rem' }}>
                {m.total_requests ?? 0}
              </div>
            </div>

            <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '10px', borderRadius: '6px' }}>
              <div style={{ color: '#64748b', fontSize: '0.7rem' }}>COMMITTED</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#10b981', fontSize: '1.1rem' }}>
                {m.successful_requests ?? 0}
              </div>
            </div>

            <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '10px', borderRadius: '6px' }}>
              <div style={{ color: '#64748b', fontSize: '0.7rem' }}>REJECTED / FAILED</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: '#ef4444', fontSize: '1.1rem' }}>
                {m.rejected_requests ?? 0}
              </div>
            </div>
          </div>

          {/* Latency Percentile Cards */}
          <div style={{
            background: 'rgba(8, 13, 26, 0.4)',
            border: '1px solid rgba(51, 65, 85, 0.4)',
            borderRadius: '8px',
            padding: '12px',
            marginBottom: '10px'
          }}>
            <div style={{ fontSize: '0.72rem', color: '#94a3b8', marginBottom: '8px', fontWeight: 600 }}>
              PROPOSAL-TO-QUORUM-COMMIT LATENCY (Primary)
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', textAlign: 'center' }}>
              <div>
                <div style={{ fontSize: '0.68rem', color: '#64748b' }}>p50</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#38bdf8' }}>
                  {m.latency_p50_ms !== undefined ? `${m.latency_p50_ms}ms` : '—'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.68rem', color: '#64748b' }}>p95</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fbbf24' }}>
                  {m.latency_p95_ms !== undefined ? `${m.latency_p95_ms}ms` : '—'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.68rem', color: '#64748b' }}>p99</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#f87171' }}>
                  {m.latency_p99_ms !== undefined ? `${m.latency_p99_ms}ms` : '—'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: '0.68rem', color: '#64748b' }}>AVG</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#10b981' }}>
                  {m.latency_avg_ms !== undefined ? `${m.latency_avg_ms}ms` : '—'}
                </div>
              </div>
            </div>
          </div>

          {/* State Machine Application Latency */}
          <div style={{
            background: 'rgba(8, 13, 26, 0.4)',
            border: '1px solid rgba(51, 65, 85, 0.4)',
            borderRadius: '8px',
            padding: '10px 12px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '0.75rem'
          }}>
            <span style={{ color: '#94a3b8' }}>State-Machine Application Latency (Separate):</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#cbd5e1' }}>
              p50: <strong style={{ color: '#60a5fa' }}>{m.apply_latency_p50_ms ?? 0}ms</strong> | Avg: <strong style={{ color: '#60a5fa' }}>{m.apply_latency_avg_ms ?? 0}ms</strong> ({m.apply_sample_count ?? 0} samples)
            </span>
          </div>
        </div>

        {/* Fault Injection Controls Panel */}
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
            <h3 style={{ fontSize: '0.88rem', fontWeight: 600, color: '#f8fafc', margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <ShieldAlert size={16} color="#ef4444" />
              Secured Fault-Injection Controls
            </h3>

            {/* Target Node Selector */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Target:</span>
              <select
                value={selectedNode}
                onChange={(e) => setSelectedNode(e.target.value)}
                style={{
                  background: 'rgba(15, 23, 42, 0.9)',
                  color: '#f8fafc',
                  border: '1px solid #475569',
                  borderRadius: '4px',
                  padding: '3px 8px',
                  fontSize: '0.75rem',
                  fontFamily: 'var(--font-mono)'
                }}
              >
                <option value="node1">node1 (Port 9001)</option>
                <option value="node2">node2 (Port 9002)</option>
                <option value="node3">node3 (Port 9003)</option>
              </select>
            </div>
          </div>

          {/* Action Buttons Grid */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '14px' }}>
            <button
              className="btn btn-danger"
              disabled={actionLoading}
              onClick={() => handleActionClick(
                'isolate',
                { node_id: selectedNode },
                `Isolate ${selectedNode}`,
                `Drops all inbound and outbound RPC packets for ${selectedNode}. Other nodes will retain quorum if 2 remain.`
              )}
            >
              <AlertTriangle size={14} />
              Isolate Node
            </button>

            <button
              className="btn btn-success"
              disabled={actionLoading}
              onClick={() => handleActionClick(
                'heal',
                { node_id: selectedNode },
                `Heal ${selectedNode}`,
                `Restores bidirectional network RPCs for ${selectedNode}. It will catch up its log from the leader.`
              )}
            >
              <RotateCcw size={14} />
              Heal Node
            </button>

            <button
              className="btn btn-danger"
              disabled={actionLoading}
              onClick={() => handleActionClick(
                'stop_node',
                { node_id: selectedNode },
                `Stop Node ${selectedNode}`,
                `Gracefully cancels background election and heartbeat tasks on ${selectedNode}. HTTP monitor remains active.`
              )}
            >
              <Power size={14} />
              Stop Node
            </button>

            <button
              className="btn btn-secondary"
              disabled={actionLoading}
              onClick={() => handleActionClick(
                'start_node',
                { node_id: selectedNode },
                `Start Node ${selectedNode}`,
                `Restarts ${selectedNode} from its persistent WAL and rejoins the consensus cluster.`
              )}
            >
              <Power size={14} color="#10b981" />
              Start Node
            </button>

            <button
              className="btn btn-secondary"
              disabled={actionLoading}
              style={{ gridColumn: 'span 2' }}
              onClick={() => handleActionClick(
                'inject_stale_token',
                { stale_token: 1, action: 'RENEW' },
                `Inject Stale Fencing Token (Token #1)`,
                `Submits an operation using stale fencing token #1 to test distributed state machine rejection.`
              )}
            >
              <Bug size={14} color="#fbbf24" />
              Inject Stale Fencing-Token Request
            </button>
          </div>

          {/* Result Notification Display */}
          {lastActionResult && (
            <div style={{
              background: lastActionResult.status === 'SUCCESS' ? 'rgba(16, 185, 129, 0.12)' : lastActionResult.status === 'ERROR' ? 'rgba(239, 68, 68, 0.12)' : 'rgba(59, 130, 246, 0.12)',
              border: `1px solid ${lastActionResult.status === 'SUCCESS' ? 'rgba(16, 185, 129, 0.4)' : lastActionResult.status === 'ERROR' ? 'rgba(239, 68, 68, 0.4)' : 'rgba(59, 130, 246, 0.4)'}`,
              borderRadius: '6px',
              padding: '8px 12px',
              fontSize: '0.75rem',
              marginTop: 'auto'
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 600, color: lastActionResult.status === 'SUCCESS' ? '#34d399' : lastActionResult.status === 'ERROR' ? '#f87171' : '#60a5fa' }}>
                {lastActionResult.status === 'SUCCESS' ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {lastActionResult.message}
              </div>
              {lastActionResult.details && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: '#94a3b8', marginTop: '4px' }}>
                  {JSON.stringify(lastActionResult.details)}
                </div>
              )}
            </div>
          )}
        </div>

      </div>

      {/* Confirmation Modal Dialog */}
      {confirmDialog && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{ maxWidth: '440px', width: '100%', padding: '24px', border: '1px solid #475569' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
              <AlertTriangle size={22} color="#f59e0b" />
              <h3 style={{ fontSize: '1rem', fontWeight: 700, margin: 0, color: '#f8fafc' }}>
                Confirm Fault Injection
              </h3>
            </div>
            <p style={{ fontSize: '0.82rem', color: '#cbd5e1', marginBottom: '12px' }}>
              Are you sure you want to execute <strong>{confirmDialog.actionName}</strong>?
            </p>
            <div style={{
              background: 'rgba(15, 23, 42, 0.8)',
              padding: '10px',
              borderRadius: '6px',
              border: '1px solid #334155',
              fontSize: '0.76rem',
              color: '#94a3b8',
              marginBottom: '18px'
            }}>
              {confirmDialog.explanation}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
              <button className="btn btn-secondary" onClick={() => setConfirmDialog(null)}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={confirmDialog.onConfirm}>
                Confirm &amp; Execute
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
