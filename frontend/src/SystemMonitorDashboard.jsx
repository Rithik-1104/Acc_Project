import React, { useState } from 'react';
import { useRaftTelemetry } from './useRaftTelemetry';
import { ClusterHeader } from './ClusterHeader';
import { RaftClusterStatus } from './RaftClusterStatus';
import { LiveEventTimeline } from './LiveEventTimeline';
import { DistributedLockMonitor } from './DistributedLockMonitor';
import { PerformanceAndFaultTesting } from './PerformanceAndFaultTesting';

export default function SystemMonitorDashboard({ onGoToCinema }) {
  const {
    nodeStates,
    events,
    connectionStates,
    warnings,
    connectedCount,
    participatingCount,
    quorumAvailable,
    currentLeader,
    highestTerm,
    clearEvents,
    clearWarnings
  } = useRaftTelemetry();

  const [faultToken, setFaultToken] = useState('dev-fault-insecure-local-token');

  return (
    <div style={{ maxWidth: '1440px', margin: '0 auto', padding: '24px 20px', minHeight: '100vh', color: '#f8fafc' }}>
      
      {/* Top Banner Navigation back to Cinema */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'linear-gradient(90deg, #1e1b4b, #0f172a)',
        border: '1px solid #4338ca',
        borderRadius: '10px',
        padding: '10px 18px',
        marginBottom: '20px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '1.2rem' }}>🎬</span>
          <span style={{ fontSize: '0.9rem', color: '#cbd5e1' }}>
            System Monitor active (route: <code>/monitor</code>). Need to test customer bookings?
          </span>
        </div>
        <button
          onClick={onGoToCinema}
          style={{
            background: 'linear-gradient(135deg, #e11d48, #be123c)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            padding: '6px 14px',
            fontSize: '0.85rem',
            fontWeight: 700,
            cursor: 'pointer'
          }}
        >
          Go to Cinema Booking App →
        </button>
      </div>

      {/* Top Header - Cluster Overview */}
      <ClusterHeader
        connectedCount={connectedCount}
        participatingCount={participatingCount}
        quorumAvailable={quorumAvailable}
        currentLeader={currentLeader}
        highestTerm={highestTerm}
        warnings={warnings}
        faultToken={faultToken}
        setFaultToken={setFaultToken}
        onClearWarnings={clearWarnings}
      />

      {/* Section 1 - Raft Cluster Status (3 Node Cards) */}
      <RaftClusterStatus
        nodeStates={nodeStates}
        connectionStates={connectionStates}
      />

      {/* Section 2 - Live Event Timeline */}
      <LiveEventTimeline
        events={events}
        onClearEvents={clearEvents}
      />

      {/* Section 3 - Distributed Lock Monitor (50 Seats) */}
      <DistributedLockMonitor
        nodeStates={nodeStates}
        currentLeader={currentLeader}
      />

      {/* Section 4 - Performance Metrics & Fault Testing Controls */}
      <PerformanceAndFaultTesting
        nodeStates={nodeStates}
        currentLeader={currentLeader}
        faultToken={faultToken}
      />

      {/* Footer */}
      <footer style={{
        textAlign: 'center',
        padding: '16px 0',
        fontSize: '0.75rem',
        color: '#64748b',
        borderTop: '1px solid rgba(51, 65, 85, 0.4)',
        marginTop: '20px'
      }}>
        Fault-Tolerant Distributed Lock Service using Raft Consensus (Quorum: 2/3) • Engineering Dashboard
      </footer>
    </div>
  );
}
