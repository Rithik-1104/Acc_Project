import React from 'react';
import { Lock, AlertCircle, ArrowRight, CheckCircle, ShieldCheck } from 'lucide-react';

export function SeatSelectionView({
  seats,
  activeLocks,
  activeReservations,
  selectedSeats,
  onToggleSeat,
  onProceedToBook,
  loading,
  isBooking
}) {
  const rows = ['A', 'B', 'C', 'D', 'E'];
  const seatsPerRow = 10;

  // Determine actual backend seat status
  const getSeatState = (seatCode) => {
    const seatId = `seat-${seatCode}`;
    const dbSeat = seats.find((s) => s.seat_code === seatCode || s.id === seatId);

    // 1. Permanent booked in database or state machine
    if (dbSeat?.status === 'BOOKED') {
      return { status: 'BOOKED', label: 'Booked' };
    }

    // 2. Active temporary lease in distributed lock state machine
    const lock = activeLocks[seatCode] || activeLocks[seatId];
    if (lock) {
      if (lock.status === 'BOOKED') return { status: 'BOOKED', label: 'Booked' };
      if (lock.status === 'RESERVED') {
        const remaining = lock.remaining_seconds ? ` (${lock.remaining_seconds}s)` : '';
        return { status: 'RESERVED', label: `Reserved${remaining}`, lock };
      }
    }

    // 3. Check active reservations array
    for (const res of activeReservations) {
      if (res.seat_ids?.includes(seatCode) || res.seat_ids?.includes(seatId)) {
        return { status: 'RESERVED', label: 'Reserved', reservation: res };
      }
    }

    // 4. Client-side local selection
    if (selectedSeats.includes(seatCode)) {
      return { status: 'SELECTED', label: 'Selected' };
    }

    return { status: 'AVAILABLE', label: 'Available' };
  };

  const getSeatStyle = (state) => {
    switch (state.status) {
      case 'SELECTED':
        return {
          background: 'linear-gradient(135deg, #10b981, #059669)',
          border: '1px solid #34d399',
          color: '#ffffff',
          cursor: 'pointer',
          boxShadow: '0 0 10px rgba(16, 185, 129, 0.5)'
        };
      case 'RESERVED':
        return {
          background: 'rgba(245, 158, 11, 0.25)',
          border: '1px solid #f59e0b',
          color: '#fbbf24',
          cursor: 'not-allowed',
          opacity: 0.85
        };
      case 'BOOKED':
        return {
          background: 'rgba(239, 68, 68, 0.25)',
          border: '1px solid #ef4444',
          color: '#f87171',
          cursor: 'not-allowed',
          opacity: 0.6
        };
      case 'AVAILABLE':
      default:
        return {
          background: 'rgba(15, 23, 42, 0.7)',
          border: '1px solid #334155',
          color: '#cbd5e1',
          cursor: 'pointer'
        };
    }
  };

  // Price calculation
  const totalAmount = selectedSeats.reduce((sum, seatCode) => {
    const row = seatCode[0];
    return sum + (row === 'A' || row === 'B' ? 300.00 : 180.00);
  }, 0);

  return (
    <div className="glass-panel" style={{ padding: '24px', marginBottom: '28px' }}>
      
      {/* Title & Legend Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h2 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
            Select Seats (Screen 1 - 50 Seats)
          </h2>
          <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
            Rows A &amp; B: VIP (₹300.00) • Rows C, D, E: Standard (₹180.00) • Max 10 seats per booking
          </span>
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '0.75rem', color: '#94a3b8' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '12px', height: '12px', background: 'rgba(15, 23, 42, 0.7)', border: '1px solid #334155', borderRadius: '3px' }} />
            Available
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '12px', height: '12px', background: '#10b981', borderRadius: '3px' }} />
            Selected
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '12px', height: '12px', background: '#f59e0b', borderRadius: '3px' }} />
            Temporarily Reserved
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '12px', height: '12px', background: '#ef4444', borderRadius: '3px' }} />
            Booked
          </span>
        </div>
      </div>

      {/* Screen Curved Indicator */}
      <div style={{ margin: '0 auto 28px auto', maxWidth: '560px', textAlign: 'center' }}>
        <div style={{
          height: '6px',
          borderRadius: '50%',
          background: 'linear-gradient(90deg, transparent, #3b82f6, transparent)',
          boxShadow: '0 0 16px rgba(59, 130, 246, 0.6)',
          marginBottom: '8px'
        }} />
        <span style={{ fontSize: '0.7rem', color: '#64748b', letterSpacing: '0.2em', textTransform: 'uppercase' }}>
          ALL EYES THIS WAY • CINEMA SCREEN
        </span>
      </div>

      {/* 50-Seat Grid */}
      <div style={{
        maxWidth: '680px',
        margin: '0 auto 24px auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '10px'
      }}>
        {rows.map((row) => (
          <div key={row} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ width: '24px', fontSize: '0.82rem', fontWeight: 700, color: '#64748b', fontFamily: 'var(--font-mono)' }}>
              {row}
            </span>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(10, 1fr)', gap: '8px', flex: 1 }}>
              {Array.from({ length: seatsPerRow }, (_, i) => {
                const seatCode = `${row}${i + 1}`;
                const seatState = getSeatState(seatCode);
                const styleObj = getSeatStyle(seatState);

                return (
                  <button
                    key={seatCode}
                    disabled={seatState.status === 'RESERVED' || seatState.status === 'BOOKED'}
                    onClick={() => onToggleSeat(seatCode, seatState)}
                    title={`Seat ${seatCode} - ${seatState.label}`}
                    style={{
                      ...styleObj,
                      padding: '8px 2px',
                      borderRadius: '6px',
                      fontSize: '0.75rem',
                      fontWeight: 600,
                      fontFamily: 'var(--font-mono)',
                      textAlign: 'center',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    {seatCode}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Action Bar (Proceed to Book) */}
      <div style={{
        borderTop: '1px solid rgba(51, 65, 85, 0.5)',
        paddingTop: '16px',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: '16px'
      }}>
        <div>
          <div style={{ fontSize: '0.85rem', color: '#cbd5e1' }}>
            Selected Seats: <strong style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>{selectedSeats.length > 0 ? selectedSeats.join(', ') : 'None'}</strong>
          </div>
          <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
            Total Amount: <strong style={{ color: '#f8fafc', fontSize: '1rem' }}>₹{totalAmount.toFixed(2)}</strong> ({selectedSeats.length} seats)
          </div>
        </div>

        <button
          className="btn btn-primary"
          disabled={selectedSeats.length === 0 || isBooking}
          onClick={onProceedToBook}
          style={{
            background: 'linear-gradient(135deg, #e11d48, #be123c)',
            padding: '10px 24px',
            fontSize: '0.9rem',
            fontWeight: 700,
            boxShadow: '0 0 16px rgba(225, 29, 72, 0.4)'
          }}
        >
          {isBooking ? 'Acquiring Distributed Lock...' : 'Proceed to Book'}
          <ArrowRight size={16} />
        </button>
      </div>

    </div>
  );
}
