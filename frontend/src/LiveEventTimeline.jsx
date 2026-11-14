import React, { useState } from 'react';
import { Clock, Filter, Trash2, AlertCircle } from 'lucide-react';

export function LiveEventTimeline({ events, onClearEvents }) {
  const [selectedCategory, setSelectedCategory] = useState('ALL');

  const categories = [
    { label: 'ALL EVENTS', value: 'ALL' },
    { label: 'CONSENSUS', value: 'CONSENSUS' },
    { label: 'REPLICATION', value: 'REPLICATION' },
    { label: 'LOCKS', value: 'LOCK' },
    { label: 'FAULTS', value: 'FAULT' },
    { label: 'WARNINGS', value: 'TELEMETRY_WARNING' }
  ];

  const filteredEvents = events.filter((e) => {
    if (selectedCategory === 'ALL') return true;
    if (selectedCategory === 'REPLICATION') {
      return e.category === 'REPLICATION' || e.action === 'FOLLOWER_REPLICATION_SUCCESS';
    }
    return e.category === selectedCategory;
  });

  const getActionBadgeColor = (action, category) => {
    if (action.includes('REJECTED') || action.includes('FAILED') || action.includes('ISOLATED') || action.includes('STOPPED')) {
      return { bg: 'rgba(239, 68, 68, 0.15)', text: '#f87171', border: 'rgba(239, 68, 68, 0.4)' };
    }
    if (action.includes('WON') || action.includes('COMMITTED') || action.includes('ACQUIRED') || action.includes('CONFIRMED') || action.includes('HEALED')) {
      return { bg: 'rgba(16, 185, 129, 0.15)', text: '#34d399', border: 'rgba(16, 185, 129, 0.4)' };
    }
    if (action.includes('OVERFLOW') || action.includes('WARNING') || action.includes('EXPIRED')) {
      return { bg: 'rgba(245, 158, 11, 0.15)', text: '#fbbf24', border: 'rgba(245, 158, 11, 0.4)' };
    }
    return { bg: 'rgba(59, 130, 246, 0.15)', text: '#60a5fa', border: 'rgba(59, 130, 246, 0.4)' };
  };

  const formatEventDescription = (evt) => {
    const act = evt.action || '';
    const d = evt.details || {};
    const n = evt.originating_node || evt.node_id || 'node';
    const term = evt.term !== undefined ? `in term ${evt.term}` : '';

    if (act === 'ELECTION_WON') {
      return `${n.toUpperCase()} elected leader ${term} (${d.duration_ms ? `${d.duration_ms}ms` : ''})`;
    }
    if (act === 'FOLLOWER_REPLICATION_SUCCESS') {
      return `${n.toUpperCase()} replicated log entry to ${d.follower_id || 'follower'} (index ${d.replicated_index})`;
    }
    if (act === 'COMMIT_ADVANCED') {
      return `Commit index advanced to ${d.new_commit} by majority quorum (${d.matches ? `${d.matches} match` : ''})`;
    }
    if (act === 'PROPOSAL_COMMITTED') {
      return `Proposal '${d.command}' committed at index ${d.index} ${term}`;
    }
    if (act === 'PROPOSAL_FAILED') {
      return `Proposal '${d.command}' failed: ${d.reason || 'Timeout/No Quorum'}`;
    }
    const seats = Array.isArray(d.seats) ? d.seats.join(', ') : '';

    if (act === 'LOCK_ACQUIRED' || act === 'RESERVE_SEATS_RESERVED') {
      const seatsStr = Array.isArray(d.seats) ? d.seats.join(', ') : 'seats';
      return `Reservation acquired for ${seatsStr} (Token: #${d.fencing_token})`;
    }
    if (act === 'RENEW_RESERVATION_RENEWED' || act === 'RESERVATION_RENEWED') {
      return `Reservation renewed for booking ${d.booking_id || ''} (New token: #${d.fencing_token})`;
    }
    if (act === 'RELEASE_RESERVATION_RELEASED' || act === 'RESERVATION_RELEASED') {
      return `Reservation released explicitly for booking ${d.booking_id || ''}`;
    }
    if (act === 'EXPIRE_LEASES_EXPIRED' || act === 'LEASE_EXPIRED') {
      const count = d.expired_count !== undefined ? `(${d.expired_count} leases)` : '';
      return `Lease expired automatically by leader check ${d.booking_id || count}`;
    }
    if (act === 'RENEW_RESERVATION_REJECTED_MAX_CEILING_REACHED') {
      return `Renewal rejected: Maximum 120-second lease ceiling reached (Booking: ${d.booking_id || ''})`;
    }
    if (act === 'RENEW_RESERVATION_REJECTED_STALE_TOKEN' || act === 'RELEASE_RESERVATION_REJECTED_STALE_TOKEN') {
      return `Operation rejected: Stale fencing token (Expected #${d.expected ?? 'valid'}, provided #${d.provided ?? 'none'})`;
    }
    if (act === 'LOCK_REJECTED' || act.includes('REJECTED')) {
      return `Reservation rejected: ${d.status || act} ${seats}`;
    }
    if (act === 'CONFIRM_BOOKING_CONFIRMED' || act === 'BOOKING_CONFIRMED') {
      return `Booking confirmed permanently for ${d.booking_id || ''} (Token: #${d.fencing_token})`;
    }
    if (act === 'CANCEL_BOOKING_CANCELLED' || act === 'BOOKING_CANCELLED') {
      return `Booking cancelled for ${d.booking_id || ''}`;
    }
    if (act === 'NODE_ISOLATED') {
      return `${n.toUpperCase()} isolated from cluster RPC network`;
    }
    if (act === 'NODE_HEALED') {
      return `${n.toUpperCase()} healed and reconnected to cluster RPC network`;
    }
    if (act === 'NODE_STOPPED') {
      return `${n.toUpperCase()} background consensus loop stopped`;
    }
    if (act === 'NODE_STARTED' || act === 'NODE_RESTARTED') {
      return `${n.toUpperCase()} started/recovered from persistent WAL`;
    }
    if (act === 'SUBSCRIBER_QUEUE_OVERFLOW') {
      return `Subscriber queue overflow: events dropped (${d.dropped_for_client || 0}). Re-synchronize snapshot.`;
    }

    return `${act} ${JSON.stringify(d)}`;
  };

  return (
    <section style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 600, color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Clock size={18} color="#3b82f6" />
          SECTION 2 — LIVE EVENT TIMELINE
        </h2>

        {/* Filter Pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
          <Filter size={14} color="#64748b" />
          {categories.map((c) => (
            <button
              key={c.value}
              onClick={() => setSelectedCategory(c.value)}
              style={{
                background: selectedCategory === c.value ? '#2563eb' : 'rgba(30, 41, 59, 0.6)',
                color: selectedCategory === c.value ? '#ffffff' : '#94a3b8',
                border: '1px solid ' + (selectedCategory === c.value ? '#3b82f6' : 'rgba(51, 65, 85, 0.4)'),
                borderRadius: '4px',
                padding: '3px 8px',
                fontSize: '0.72rem',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)'
              }}
            >
              {c.label}
            </button>
          ))}

          {events.length > 0 && (
            <button
              onClick={onClearEvents}
              title="Clear event feed"
              style={{
                background: 'transparent',
                border: 'none',
                color: '#64748b',
                cursor: 'pointer',
                marginLeft: '8px',
                display: 'flex',
                alignItems: 'center'
              }}
            >
              <Trash2 size={14} />
            </button>
          )}
        </div>
      </div>

      {/* Timeline Scrollable Box */}
      <div
        className="glass-panel"
        style={{
          maxHeight: '340px',
          overflowY: 'auto',
          padding: '12px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px'
        }}
      >
        {filteredEvents.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: '#64748b', fontSize: '0.82rem' }}>
            No live events received yet in this category. Perform cluster actions or reservations to see stream.
          </div>
        ) : (
          filteredEvents.map((evt, idx) => {
            const badgeStyle = getActionBadgeColor(evt.action || '', evt.category || '');
            const timeStr = evt.timestamp_utc ? new Date(evt.timestamp_utc).toLocaleTimeString() : '—';

            return (
              <div
                key={evt.timestamp_micros ? `${evt.timestamp_micros}-${idx}` : idx}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  background: 'rgba(15, 23, 42, 0.6)',
                  border: '1px solid rgba(51, 65, 85, 0.4)',
                  borderRadius: '6px',
                  padding: '8px 12px',
                  fontSize: '0.8rem',
                  gap: '12px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flex: 1, overflow: 'hidden' }}>
                  {/* Timestamp */}
                  <span style={{ color: '#64748b', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', flexShrink: 0 }}>
                    {timeStr}
                  </span>

                  {/* Node Origin Tag */}
                  <span style={{
                    background: 'rgba(51, 65, 85, 0.6)',
                    color: '#e2e8f0',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.7rem',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    flexShrink: 0
                  }}>
                    {evt.originating_node || evt.node_id || 'cluster'}
                  </span>

                  {/* Action Badge */}
                  <span style={{
                    background: badgeStyle.bg,
                    color: badgeStyle.text,
                    border: `1px solid ${badgeStyle.border}`,
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    padding: '2px 8px',
                    borderRadius: '4px',
                    flexShrink: 0
                  }}>
                    {evt.action}
                  </span>

                  {/* Human-Readable Event Description */}
                  <span style={{ color: '#f8fafc', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {formatEventDescription(evt)}
                  </span>
                </div>

                {/* Optional Latency Tag */}
                {evt.latency_ms !== null && evt.latency_ms !== undefined && (
                  <span style={{
                    color: '#10b981',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.72rem',
                    flexShrink: 0,
                    background: 'rgba(16, 185, 129, 0.1)',
                    padding: '2px 6px',
                    borderRadius: '4px'
                  }}>
                    {evt.latency_ms}ms
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>
    </section>
  );
}
