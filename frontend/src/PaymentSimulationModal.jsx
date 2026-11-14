import React, { useState, useEffect } from 'react';
import { Clock, ShieldCheck, RefreshCw, XCircle, CreditCard, AlertTriangle } from 'lucide-react';

export function PaymentSimulationModal({
  reservation,
  onConfirmPayment,
  onRenewLease,
  onCancelReservation,
  isProcessing
}) {
  const [secondsRemaining, setSecondsRemaining] = useState(60);
  const [isRenewing, setIsRenewing] = useState(false);

  // Derive remaining lease countdown from backend expires_at timestamp
  useEffect(() => {
    if (!reservation?.expires_at) return;

    const targetTime = new Date(reservation.expires_at).getTime();
    if (isNaN(targetTime)) return;

    const updateTimer = () => {
      const now = Date.now();
      const diffSec = Math.max(0, Math.ceil((targetTime - now) / 1000));
      setSecondsRemaining(diffSec);
    };

    updateTimer();
    const interval = setInterval(updateTimer, 500);

    return () => clearInterval(interval);
  }, [reservation?.expires_at]);

  const isExpired = secondsRemaining <= 0;

  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0, 0, 0, 0.85)',
      backdropFilter: 'blur(8px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 200,
      padding: '20px'
    }}>
      <div className="glass-panel" style={{
        maxWidth: '520px',
        width: '100%',
        padding: '28px',
        border: '1px solid #3b82f6',
        boxShadow: '0 0 40px rgba(59, 130, 246, 0.3)'
      }}>
        
        {/* Header with Countdown */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '18px' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <ShieldCheck size={20} color="#10b981" />
              <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: '#f8fafc', margin: 0 }}>
                Distributed Lock Granted
              </h2>
            </div>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
              Quorum committed by Raft cluster • Fencing Token #{reservation.fencing_token}
            </span>
          </div>

          {/* Lease Countdown Badge */}
          <div style={{
            background: isExpired ? 'rgba(239, 68, 68, 0.2)' : 'rgba(245, 158, 11, 0.15)',
            border: `1px solid ${isExpired ? '#ef4444' : '#f59e0b'}`,
            color: isExpired ? '#f87171' : '#fbbf24',
            padding: '6px 12px',
            borderRadius: '8px',
            fontFamily: 'var(--font-mono)',
            fontSize: '0.85rem',
            fontWeight: 700,
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}>
            <Clock size={16} />
            {isExpired ? 'EXPIRED' : `${secondsRemaining}s`}
          </div>
        </div>

        {/* Warning if lease expired */}
        {isExpired && (
          <div style={{
            background: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid rgba(239, 68, 68, 0.4)',
            padding: '10px 14px',
            borderRadius: '6px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            color: '#f87171',
            fontSize: '0.8rem'
          }}>
            <AlertTriangle size={18} />
            <span>Reservation lease has expired on the backend. Please restart booking.</span>
          </div>
        )}

        {/* Reservation Summary */}
        <div style={{
          background: 'rgba(15, 23, 42, 0.8)',
          border: '1px solid rgba(51, 65, 85, 0.6)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '20px',
          fontSize: '0.82rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px'
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
            <span>Movie &amp; Show:</span>
            <strong style={{ color: '#f8fafc' }}>Interstellar (IMAX Laser)</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
            <span>Reserved Seats:</span>
            <strong style={{ color: '#10b981', fontFamily: 'var(--font-mono)' }}>
              {reservation.seat_ids?.map((s) => s.replace('seat-', '')).join(', ')}
            </strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
            <span>Customer Profile:</span>
            <strong style={{ color: '#60a5fa' }}>{reservation.owner_id}</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8' }}>
            <span>Booking Reference:</span>
            <span style={{ fontFamily: 'var(--font-mono)', color: '#cbd5e1' }}>
              BK-{reservation.booking_id?.slice(0, 8).toUpperCase()}
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#94a3b8', borderTop: '1px solid #334155', paddingTop: '8px', marginTop: '4px' }}>
            <span>Total Payable:</span>
            <strong style={{ color: '#f8fafc', fontSize: '1.1rem' }}>
              ₹{(
                reservation.total_amount !== undefined
                  ? Number(reservation.total_amount)
                  : (reservation.seat_ids || []).reduce((acc, sid) => {
                      const code = sid.replace('seat-', '');
                      const row = code[0];
                      return acc + (row === 'A' || row === 'B' ? 300.00 : 180.00);
                    }, 0)
              ).toFixed(2)}
            </strong>
          </div>
        </div>

        {/* Simulated Payment Method Display */}
        <div style={{
          background: 'rgba(30, 41, 59, 0.4)',
          border: '1px dashed #475569',
          borderRadius: '6px',
          padding: '10px 14px',
          marginBottom: '20px',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '0.78rem',
          color: '#94a3b8'
        }}>
          <CreditCard size={18} color="#60a5fa" />
          <div>
            <div style={{ color: '#f8fafc', fontWeight: 600 }}>Simulated Instant Payment (UPI / Card)</div>
            <div>Demonstration mode: No actual money processed. Distributed token verified on confirmation.</div>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              className="btn btn-secondary"
              disabled={isProcessing || isExpired}
              onClick={async () => {
                setIsRenewing(true);
                await onRenewLease();
                setIsRenewing(false);
              }}
              title="Renew reservation lease (+30s, up to 120s ceiling)"
              style={{ fontSize: '0.78rem' }}
            >
              <RefreshCw size={13} className={isRenewing ? 'spin' : ''} />
              Renew (+30s)
            </button>

            <button
              className="btn btn-danger"
              disabled={isProcessing}
              onClick={onCancelReservation}
              style={{ fontSize: '0.78rem' }}
            >
              <XCircle size={13} />
              Release Lock
            </button>
          </div>

          <button
            className="btn btn-primary"
            disabled={isProcessing || isExpired}
            onClick={onConfirmPayment}
            style={{
              background: 'linear-gradient(135deg, #10b981, #059669)',
              padding: '10px 24px',
              fontWeight: 700,
              fontSize: '0.9rem',
              boxShadow: '0 0 16px rgba(16, 185, 129, 0.4)'
            }}
          >
            {isProcessing ? 'Validating Fencing Token...' : 'Pay Now & Confirm'}
          </button>
        </div>

      </div>
    </div>
  );
}
