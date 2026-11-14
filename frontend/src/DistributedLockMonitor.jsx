import React from 'react';
import { Lock, CheckSquare, Clock, User, Shield, Info } from 'lucide-react';

export function DistributedLockMonitor({ nodeStates, currentLeader }) {
  // Authoritative lock state from current leader's snapshot, or any available connected node
  const leaderState = currentLeader ? nodeStates[currentLeader] : Object.values(nodeStates)[0];

  const activeReservations = leaderState?.active_reservations || [];
  const confirmedBookings = leaderState?.confirmed_bookings || [];
  const activeLocks = leaderState?.active_locks || {};
  const fencingCounter = leaderState?.fencing_counter || 1000;

  // Generate 50 cinema seats: Rows A-E, Seats 1-10
  const rows = ['A', 'B', 'C', 'D', 'E'];
  const seatsPerRow = 10;

  const getSeatStatus = (seatCode) => {
    // Check active locks
    const lock = activeLocks[seatCode] || activeLocks[`seat-${seatCode}`];
    if (lock) {
      if (lock.status === 'BOOKED') return { status: 'BOOKED', lock };
      if (lock.status === 'RESERVED') return { status: 'RESERVED', lock };
    }

    // Check reservations list
    for (const res of activeReservations) {
      if (res.seat_ids?.includes(seatCode) || res.seat_ids?.includes(`seat-${seatCode}`)) {
        return { status: 'RESERVED', reservation: res };
      }
    }

    // Check confirmed bookings
    for (const b of confirmedBookings) {
      if (b.seat_ids?.includes(seatCode) || b.seat_ids?.includes(`seat-${seatCode}`)) {
        return { status: 'BOOKED', booking: b };
      }
    }

    return { status: 'AVAILABLE' };
  };

  const getSeatColor = (status) => {
    switch (status) {
      case 'RESERVED':
        return { bg: 'rgba(245, 158, 11, 0.25)', border: '#f59e0b', text: '#fbbf24' };
      case 'BOOKED':
        return { bg: 'rgba(59, 130, 246, 0.25)', border: '#3b82f6', text: '#60a5fa' };
      case 'EXPIRED':
        return { bg: 'rgba(239, 68, 68, 0.2)', border: '#ef4444', text: '#f87171' };
      case 'AVAILABLE':
      default:
        return { bg: 'rgba(15, 23, 42, 0.6)', border: '#334155', text: '#94a3b8' };
    }
  };

  return (
    <section style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Lock size={18} color="#3b82f6" />
          SECTION 3 — DISTRIBUTED LOCK MONITOR (50-SEAT CONFIGURATION)
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '0.75rem' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '10px', height: '10px', background: '#334155', borderRadius: '2px', display: 'inline-block' }}></span>
            Available
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '10px', height: '10px', background: '#f59e0b', borderRadius: '2px', display: 'inline-block' }}></span>
            Active Lease (Reserved)
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ width: '10px', height: '10px', background: '#3b82f6', borderRadius: '2px', display: 'inline-block' }}></span>
            Confirmed (Booked)
          </span>
          <span style={{ color: '#64748b', fontFamily: 'var(--font-mono)' }}>
            Fencing Monotonic Seq: <strong style={{ color: '#10b981' }}>#{fencingCounter}</strong>
          </span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 1.2fr) minmax(280px, 0.8fr)', gap: '16px' }}>
        
        {/* 50-Seat Grid Visualization */}
        <div className="glass-panel" style={{ padding: '16px' }}>
          <div style={{
            textAlign: 'center',
            fontSize: '0.72rem',
            color: '#64748b',
            letterSpacing: '0.1em',
            marginBottom: '14px',
            borderBottom: '1px dashed #334155',
            paddingBottom: '6px'
          }}>
            CINEMA SCREEN (FRONT)
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {rows.map((row) => (
              <div key={row} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <span style={{ width: '18px', fontSize: '0.75rem', fontWeight: 700, color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                  {row}
                </span>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(10, 1fr)', gap: '6px', flex: 1 }}>
                  {Array.from({ length: seatsPerRow }, (_, i) => {
                    const seatCode = `${row}${i + 1}`;
                    const seatInfo = getSeatStatus(seatCode);
                    const colorStyle = getSeatColor(seatInfo.status);

                    return (
                      <div
                        key={seatCode}
                        title={`Seat ${seatCode}: ${seatInfo.status}`}
                        style={{
                          background: colorStyle.bg,
                          border: `1px solid ${colorStyle.border}`,
                          color: colorStyle.text,
                          borderRadius: '4px',
                          padding: '6px 2px',
                          textAlign: 'center',
                          fontSize: '0.72rem',
                          fontFamily: 'var(--font-mono)',
                          fontWeight: 600,
                          transition: 'all 0.15s ease'
                        }}
                      >
                        {seatCode}
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Active Leases & Bookings Panel */}
        <div className="glass-panel" style={{ padding: '16px', display: 'flex', flexDirection: 'column' }}>
          <h3 style={{ fontSize: '0.88rem', fontWeight: 600, color: '#f8fafc', marginBottom: '10px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <Clock size={16} color="#fbbf24" />
            Active Leases &amp; Fencing Tokens ({activeReservations.length})
          </h3>

          <div style={{ flex: 1, overflowY: 'auto', maxHeight: '220px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {activeReservations.length === 0 ? (
              <div style={{ padding: '24px', textAlign: 'center', color: '#64748b', fontSize: '0.78rem' }}>
                No active temporary reservations at this moment. All seats available or permanently confirmed.
              </div>
            ) : (
              activeReservations.map((res) => (
                <div
                  key={res.booking_id}
                  style={{
                    background: 'rgba(15, 23, 42, 0.8)',
                    border: '1px solid rgba(245, 158, 11, 0.4)',
                    borderRadius: '6px',
                    padding: '8px 10px',
                    fontSize: '0.75rem'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                    <span style={{ fontWeight: 600, color: '#fbbf24' }}>
                      Seats: {res.seat_ids?.join(', ')}
                    </span>
                    <span style={{
                      background: 'rgba(245, 158, 11, 0.15)',
                      color: '#fbbf24',
                      padding: '2px 6px',
                      borderRadius: '4px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 600
                    }}>
                      {res.remaining_seconds}s left
                    </span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px', color: '#94a3b8', fontSize: '0.7rem' }}>
                    <div>
                      Token: <strong style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>#{res.fencing_token}</strong>
                    </div>
                    <div>
                      Owner: <strong style={{ color: '#e2e8f0' }}>{res.owner_id}</strong>
                    </div>
                    <div style={{ gridColumn: 'span 2', color: '#64748b', fontFamily: 'var(--font-mono)' }}>
                      ID: {res.booking_id}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Confirmed Bookings Counter */}
          <div style={{ borderTop: '1px solid rgba(51, 65, 85, 0.4)', paddingTop: '10px', marginTop: '10px', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8' }}>
            <span>Permanent Confirmed Bookings:</span>
            <strong style={{ color: '#60a5fa', fontFamily: 'var(--font-mono)' }}>{confirmedBookings.length}</strong>
          </div>
        </div>

      </div>
    </section>
  );
}
