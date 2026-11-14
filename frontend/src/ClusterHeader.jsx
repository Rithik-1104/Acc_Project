import React, { useState } from 'react';
import { Activity, ShieldCheck, ShieldAlert, Wifi, Server, Key, AlertTriangle, Eye, EyeOff } from 'lucide-react';

export function ClusterHeader({
  connectedCount,
  participatingCount,
  quorumAvailable,
  currentLeader,
  highestTerm,
  warnings,
  faultToken,
  setFaultToken,
  onClearWarnings
}) {
  const [showTokenSettings, setShowTokenSettings] = useState(false);
  const [showTokenValue, setShowTokenValue] = useState(false);

  const activeCount = participatingCount !== undefined ? participatingCount : connectedCount;

  const getStatusBadge = () => {
    if (activeCount === 3) {
      return (
        <span className="badge badge-live" title="All 3 nodes actively participating in consensus">
          <span className="status-dot green"></span>
          LIVE (3/3 NODES)
        </span>
      );
    }
    if (activeCount === 2) {
      return (
        <span className="badge badge-live" title="Majority quorum available (2/3 participating)">
          <span className="status-dot green"></span>
          DEGRADED MAJORITY (2/3 PARTICIPATING)
        </span>
      );
    }
    if (activeCount === 1) {
      return (
        <span className="badge badge-danger" title="Majority quorum lost (1/3 participating)">
          <span className="status-dot red"></span>
          QUORUM LOST (1/3 PARTICIPATING)
        </span>
      );
    }
    return (
      <span className="badge badge-danger" title="No participating nodes">
        <span className="status-dot red"></span>
        DISCONNECTED (0/3 NODES)
      </span>
    );
  };

  return (
    <header className="glass-panel" style={{ padding: '16px 24px', marginBottom: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
        
        {/* Title & System Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div style={{
            background: 'linear-gradient(135deg, #1e3a8a, #3b82f6)',
            padding: '10px',
            borderRadius: '10px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 16px rgba(59, 130, 246, 0.3)'
          }}>
            <Activity size={24} color="#ffffff" />
          </div>
          <div>
            <h1 style={{ fontSize: '1.25rem', fontWeight: 700, letterSpacing: '-0.02em', color: '#f8fafc', margin: 0 }}>
              RAFT DISTRIBUTED LOCK MONITOR
            </h1>
            <p style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0 }}>
              Real-Time Consensus Telemetry, State Machine Reconciler &amp; Fault Engineering
            </p>
          </div>
        </div>

        {/* Global Cluster State Overview */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '18px', flexWrap: 'wrap' }}>
          {getStatusBadge()}

          {/* Quorum status */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {quorumAvailable ? (
              <span className="badge badge-live" title="Majority quorum (>=2 nodes) healthy">
                <ShieldCheck size={14} style={{ marginRight: '4px' }} />
                QUORUM AVAILABLE
              </span>
            ) : (
              <span className="badge badge-danger" title="Majority quorum lost (<2 nodes)">
                <ShieldAlert size={14} style={{ marginRight: '4px' }} />
                QUORUM LOST
              </span>
            )}
          </div>

          {/* Leader Indicator */}
          <div style={{
            background: 'rgba(15, 23, 42, 0.8)',
            padding: '4px 12px',
            borderRadius: '6px',
            border: '1px solid #334155',
            fontSize: '0.82rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span style={{ color: '#94a3b8' }}>Leader:</span>
            {currentLeader ? (
              <strong style={{ color: '#fbbf24', fontFamily: 'var(--font-mono)' }}>{currentLeader}</strong>
            ) : (
              <strong style={{ color: '#ef4444', fontFamily: 'var(--font-mono)' }}>ELECTING...</strong>
            )}
          </div>

          {/* Current Term */}
          <div style={{
            background: 'rgba(15, 23, 42, 0.8)',
            padding: '4px 12px',
            borderRadius: '6px',
            border: '1px solid #334155',
            fontSize: '0.82rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span style={{ color: '#94a3b8' }}>Term:</span>
            <strong style={{ color: '#60a5fa', fontFamily: 'var(--font-mono)' }}>{highestTerm}</strong>
          </div>

          {/* Protected Fault Token Toggle */}
          <button
            className="btn btn-secondary"
            onClick={() => setShowTokenSettings(!showTokenSettings)}
            title="Local Protected Fault Injection Token Settings"
            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
          >
            <Key size={14} />
            Auth Token
          </button>
        </div>
      </div>

      {/* Expandable Protected Local Dev Fault Token Settings */}
      {showTokenSettings && (
        <div style={{
          marginTop: '16px',
          padding: '12px 16px',
          borderRadius: '8px',
          background: 'rgba(15, 23, 42, 0.95)',
          border: '1px solid #3b82f6',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: '12px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Key size={16} color="#3b82f6" />
            <div>
              <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#f8fafc' }}>
                Protected Local Fault Authorization (Browser Memory Only)
              </div>
              <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                Never committed, logged or bundled. Used strictly for HTTP header X-Fault-Token on secured APIs.
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <input
              type={showTokenValue ? 'text' : 'password'}
              value={faultToken}
              onChange={(e) => setFaultToken(e.target.value)}
              placeholder="Enter local dev token..."
              style={{
                background: '#080d1a',
                border: '1px solid #475569',
                color: '#f8fafc',
                padding: '6px 10px',
                borderRadius: '6px',
                fontSize: '0.8rem',
                fontFamily: 'var(--font-mono)',
                width: '260px'
              }}
            />
            <button
              className="btn btn-secondary"
              onClick={() => setShowTokenValue(!showTokenValue)}
              style={{ padding: '6px 10px' }}
            >
              {showTokenValue ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </div>
      )}

      {/* Telemetry Warning Banners (e.g. Queue Overflow) */}
      {warnings.length > 0 && (
        <div style={{
          marginTop: '12px',
          padding: '10px 14px',
          borderRadius: '8px',
          background: 'rgba(245, 158, 11, 0.12)',
          border: '1px solid rgba(245, 158, 11, 0.4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={16} color="#f59e0b" />
            <span style={{ fontSize: '0.82rem', color: '#fbbf24' }}>
              <strong>Telemetry Notice:</strong> {warnings[0].message}
            </span>
          </div>
          <button
            onClick={onClearWarnings}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              cursor: 'pointer',
              fontSize: '0.75rem',
              textDecoration: 'underline'
            }}
          >
            Dismiss
          </button>
        </div>
      )}
    </header>
  );
}
