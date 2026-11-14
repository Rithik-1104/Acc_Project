import React from 'react';
import { Server, Crown, Wifi, WifiOff, Disc, CheckCircle, Database } from 'lucide-react';

export function RaftClusterStatus({ nodeStates, connectionStates }) {
  const nodes = [
    { id: 'node1', port: 9001 },
    { id: 'node2', port: 9002 },
    { id: 'node3', port: 9003 }
  ];

  return (
    <section style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Server size={18} color="#3b82f6" />
          SECTION 1 — RAFT CLUSTER STATUS
        </h2>
        <span style={{ fontSize: '0.75rem', color: '#64748b' }}>
          Real-time individual node views via independent WebSocket streams
        </span>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
        gap: '16px'
      }}>
        {nodes.map(({ id, port }) => {
          const state = nodeStates[id];
          const conn = connectionStates[id] || 'DISCONNECTED';
          const isLeader = state?.role === 'LEADER';
          const isFollower = state?.role === 'FOLLOWER';
          const isCandidate = state?.role === 'CANDIDATE';
          const isIsolated = state?.is_network_isolated;
          const isRunning = state?.is_running !== false;

          const getRoleBadge = () => {
            if (!isRunning) {
              return <span className="badge badge-danger">STOPPED</span>;
            }
            if (isIsolated) {
              return <span className="badge badge-danger">ISOLATED</span>;
            }
            if (isLeader) {
              return (
                <span className="badge badge-leader">
                  <Crown size={12} style={{ marginRight: '4px' }} />
                  LEADER
                </span>
              );
            }
            if (isCandidate) {
              return <span className="badge badge-candidate">CANDIDATE</span>;
            }
            if (isFollower) {
              return <span className="badge badge-follower">FOLLOWER</span>;
            }
            return <span className="badge badge-warn">UNKNOWN</span>;
          };

          return (
            <div
              key={id}
              className="glass-panel"
              style={{
                padding: '18px',
                position: 'relative',
                overflow: 'hidden',
                border: isLeader
                  ? '1px solid rgba(245, 158, 11, 0.6)'
                  : isIsolated || !isRunning
                  ? '1px solid rgba(239, 68, 68, 0.5)'
                  : '1px solid var(--bg-card-border)',
                boxShadow: isLeader
                  ? '0 0 20px rgba(245, 158, 11, 0.15)'
                  : 'none'
              }}
            >
              {/* Leader top accent glow bar */}
              {isLeader && (
                <div style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  height: '3px',
                  background: 'linear-gradient(90deg, #f59e0b, #fbbf24)'
                }} />
              )}

              {/* Node Card Header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '8px',
                    background: isLeader ? 'rgba(245, 158, 11, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    <Server size={18} color={isLeader ? '#fbbf24' : '#60a5fa'} />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600, margin: 0, color: '#f8fafc' }}>
                      {id.toUpperCase()}
                    </h3>
                    <span style={{ fontSize: '0.75rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                      Port: {port}
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {getRoleBadge()}
                  {conn === 'CONNECTED' ? (
                    <span title="WebSocket Live Stream Active">
                      <Wifi size={14} color="#10b981" />
                    </span>
                  ) : (
                    <span title={`WebSocket State: ${conn}`}>
                      <WifiOff size={14} color="#ef4444" />
                    </span>
                  )}
                </div>
              </div>

              {/* Node Metrics Grid */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '8px',
                marginBottom: '14px',
                fontSize: '0.8rem'
              }}>
                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div style={{ color: '#64748b', fontSize: '0.7rem' }}>CURRENT TERM</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#60a5fa', fontSize: '0.9rem' }}>
                    {state?.current_term ?? '—'}
                  </div>
                </div>

                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div style={{ color: '#64748b', fontSize: '0.7rem' }}>CURRENT LEADER</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#fbbf24', fontSize: '0.85rem' }}>
                    {state?.current_leader || 'None'}
                  </div>
                </div>

                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div style={{ color: '#64748b', fontSize: '0.7rem' }}>COMMIT INDEX</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#10b981', fontSize: '0.9rem' }}>
                    {state?.commit_index ?? '—'}
                  </div>
                </div>

                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px 10px', borderRadius: '6px' }}>
                  <div style={{ color: '#64748b', fontSize: '0.7rem' }}>APPLIED INDEX</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#e2e8f0', fontSize: '0.9rem' }}>
                    {state?.last_applied ?? '—'}
                  </div>
                </div>

                <div style={{ background: 'rgba(15, 23, 42, 0.6)', padding: '8px 10px', borderRadius: '6px', gridColumn: 'span 2' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ color: '#64748b', fontSize: '0.7rem' }}>LAST LOG ENTRY</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: '#94a3b8', fontSize: '0.75rem' }}>
                      Index: <strong style={{ color: '#f8fafc' }}>{state?.last_log_index ?? 0}</strong> | Term: <strong style={{ color: '#f8fafc' }}>{state?.last_log_term ?? 0}</strong>
                    </span>
                  </div>
                </div>
              </div>

              {/* Peer Connectivity Sub-Panel */}
              <div style={{ borderTop: '1px solid rgba(51, 65, 85, 0.4)', paddingTop: '10px' }}>
                <div style={{ fontSize: '0.72rem', color: '#64748b', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  PEER CONNECTIVITY
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {state?.peer_info && Object.keys(state.peer_info).length > 0 ? (
                    Object.values(state.peer_info).map((peer) => (
                      <div
                        key={peer.peer_id}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          fontSize: '0.75rem',
                          background: 'rgba(8, 13, 26, 0.4)',
                          padding: '4px 8px',
                          borderRadius: '4px'
                        }}
                      >
                        <span style={{ fontFamily: 'var(--font-mono)', color: '#cbd5e1' }}>
                          {peer.peer_id}
                        </span>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span style={{ fontSize: '0.7rem', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                            match: {peer.match_index}
                          </span>
                          {peer.connected ? (
                            <span style={{ color: '#10b981', display: 'flex', alignItems: 'center', gap: '3px' }}>
                              <span className="status-dot green" style={{ width: '6px', height: '6px' }}></span>
                              Reachable
                            </span>
                          ) : (
                            <span style={{ color: '#ef4444', display: 'flex', alignItems: 'center', gap: '3px' }}>
                              <span className="status-dot red" style={{ width: '6px', height: '6px' }}></span>
                              Unreachable
                            </span>
                          )}
                        </div>
                      </div>
                    ))
                  ) : (
                    <div style={{ fontSize: '0.75rem', color: '#64748b', fontStyle: 'italic' }}>
                      {conn === 'CONNECTED' ? 'No peer information available' : 'Waiting for connection...'}
                    </div>
                  )}
                </div>
              </div>

            </div>
          );
        })}
      </div>
    </section>
  );
}
