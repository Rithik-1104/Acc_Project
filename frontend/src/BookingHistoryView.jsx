import React, { useState, useEffect } from 'react';

export default function BookingHistoryView({ customer, leaderUrl, onBackToCinema, onBookingCancelled }) {
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [cancellingId, setCancellingId] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);

  const baseUrl = leaderUrl || `http://${window.location.hostname}:9001`;

  const fetchBookings = async () => {
    try {
      setLoading(true);
      setErrorMsg(null);
      const res = await fetch(`${baseUrl}/api/cinema/bookings/customer/${customer.id}`);
      if (!res.ok) {
        throw new Error(`Failed to load bookings: HTTP ${res.status}`);
      }
      const data = await res.json();
      const bookingList = Array.isArray(data) ? data : (data.bookings || []);
      setBookings(bookingList);
    } catch (err) {
      console.error("Failed to load booking history:", err);
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchBookings();
  }, [customer.id, baseUrl]);

  const handleCancel = async (bookingId) => {
    if (!window.confirm("Are you sure you want to cancel this booking? Reserved seats will be released back to the pool.")) {
      return;
    }
    setCancellingId(bookingId);
    setErrorMsg(null);
    setSuccessMsg(null);

    try {
      const idempotencyKey = `cancel-${bookingId}-${Date.now()}`;
      const res = await fetch(`${baseUrl}/api/cinema/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          booking_id: bookingId,
          owner_id: customer.id,
          idempotency_key: idempotencyKey
        })
      });

      const data = await res.json();
      if (!res.ok || data.status === 'error') {
        const detail = typeof data.detail === 'object' ? JSON.stringify(data.detail) : (data.detail || data.message || "Cancellation failed");
        throw new Error(detail);
      }

      setSuccessMsg(`Booking ${bookingId.slice(0, 8)}... successfully cancelled. Seats released.`);
      await fetchBookings();
      if (onBookingCancelled) {
        onBookingCancelled();
      }
    } catch (err) {
      console.error("Cancellation error:", err);
      setErrorMsg(`Cancellation failed: ${err.message}`);
    } finally {
      setCancellingId(null);
    }
  };

  const getStatusBadge = (status) => {
    switch (status?.toUpperCase()) {
      case 'CONFIRMED':
        return <span style={{ background: 'rgba(16, 185, 129, 0.2)', color: '#34d399', border: '1px solid #059669', padding: '3px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 700 }}>CONFIRMED</span>;
      case 'CANCELLED':
        return <span style={{ background: 'rgba(239, 68, 68, 0.2)', color: '#f87171', border: '1px solid #dc2626', padding: '3px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 700 }}>CANCELLED</span>;
      case 'PENDING':
        return <span style={{ background: 'rgba(245, 158, 11, 0.2)', color: '#fbbf24', border: '1px solid #d97706', padding: '3px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 700 }}>RESERVED (PENDING)</span>;
      default:
        return <span style={{ background: 'rgba(100, 116, 139, 0.2)', color: '#cbd5e1', border: '1px solid #64748b', padding: '3px 10px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: 700 }}>{status}</span>;
    }
  };

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '2rem 1.5rem', color: '#f8fafc' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: '1.8rem', fontWeight: 800, margin: 0, color: '#f8fafc' }}>
            My Bookings
          </h2>
          <div style={{ fontSize: '0.85rem', color: '#94a3b8', marginTop: '0.25rem' }}>
            Logged in as <strong style={{ color: '#38bdf8' }}>{customer.name}</strong> ({customer.id}) • Live PostgreSQL History
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            onClick={fetchBookings}
            style={{
              background: '#1e293b',
              color: '#94a3b8',
              border: '1px solid #334155',
              borderRadius: '8px',
              padding: '0.5rem 1rem',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.85rem'
            }}
          >
            Refresh
          </button>
          <button
            onClick={onBackToCinema}
            style={{
              background: 'linear-gradient(135deg, #3b82f6, #2563eb)',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '0.5rem 1.25rem',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.85rem'
            }}
          >
            ← Back to Cinema
          </button>
        </div>
      </div>

      {errorMsg && (
        <div style={{
          background: 'rgba(239, 68, 68, 0.15)',
          border: '1px solid rgba(239, 68, 68, 0.4)',
          color: '#fca5a5',
          borderRadius: '8px',
          padding: '0.75rem 1rem',
          marginBottom: '1.25rem',
          fontSize: '0.85rem'
        }}>
          {errorMsg}
        </div>
      )}

      {successMsg && (
        <div style={{
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid rgba(16, 185, 129, 0.4)',
          color: '#6ee7b7',
          borderRadius: '8px',
          padding: '0.75rem 1rem',
          marginBottom: '1.25rem',
          fontSize: '0.85rem'
        }}>
          {successMsg}
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '4rem', color: '#94a3b8' }}>
          <div style={{ fontSize: '1.1rem', marginBottom: '0.5rem' }}>Loading verified booking history...</div>
          <div style={{ fontSize: '0.8rem', color: '#64748b' }}>Querying cluster leader and PostgreSQL replica</div>
        </div>
      ) : bookings.length === 0 ? (
        <div style={{
          background: '#0f172a',
          border: '1px solid #1e293b',
          borderRadius: '12px',
          padding: '3rem',
          textAlign: 'center'
        }}>
          <div style={{ fontSize: '2.5rem', marginBottom: '1rem' }}>🎟️</div>
          <h3 style={{ fontSize: '1.2rem', margin: '0 0 0.5rem 0', color: '#f8fafc' }}>No bookings found for {customer.name}</h3>
          <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '1.5rem' }}>
            You haven't reserved or booked any tickets yet under this customer session profile.
          </p>
          <button
            onClick={onBackToCinema}
            style={{
              background: 'linear-gradient(135deg, #e11d48, #be123c)',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              padding: '0.6rem 1.5rem',
              fontWeight: 700,
              cursor: 'pointer'
            }}
          >
            Select Seats Now
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          {bookings.map((b) => {
            const bookingId = b.id || b.booking_id;
            const seatsList = (b.seats || []).map(s => s.seat_code || s.seat_number || s.seat_id?.replace('seat-', '') || s).join(', ');
            const isConfirmed = b.status?.toUpperCase() === 'CONFIRMED';
            const formattedDate = b.created_at ? new Date(b.created_at).toLocaleString() : 'N/A';

            return (
              <div
                key={bookingId}
                style={{
                  background: 'linear-gradient(180deg, #1e293b 0%, #0f172a 100%)',
                  border: '1px solid #334155',
                  borderRadius: '12px',
                  padding: '1.25rem 1.5rem',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.3)'
                }}
              >
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '1.1rem', fontWeight: 800, color: '#f8fafc' }}>
                      {b.movie_title || 'Interstellar'}
                    </span>
                    {getStatusBadge(b.status)}
                    {b.fencing_token && (
                      <span style={{
                        background: '#091e3a',
                        color: '#60a5fa',
                        border: '1px solid #1e3a8a',
                        padding: '2px 8px',
                        borderRadius: '6px',
                        fontSize: '0.7rem',
                        fontWeight: 600
                      }}>
                        Fencing Token #{b.fencing_token}
                      </span>
                    )}
                  </div>

                  <div style={{ fontSize: '0.85rem', color: '#cbd5e1', marginBottom: '0.35rem' }}>
                    <strong>Show:</strong> {b.show_name || 'Prime Evening 7:30 PM'} • <strong>Screen:</strong> {b.screen_name || 'Screen 1 (IMAX Laser)'}
                  </div>

                  <div style={{ fontSize: '0.85rem', color: '#cbd5e1', marginBottom: '0.35rem' }}>
                    <strong>Seats:</strong> <span style={{ color: '#fbbf24', fontWeight: 700 }}>{seatsList || 'N/A'}</span>
                    {' '}({(b.seats || []).length} seat{(b.seats || []).length > 1 ? 's' : ''})
                    {' '}• <strong>Total:</strong> ₹{b.total_amount ? Number(b.total_amount).toFixed(2) : '0.00'}
                  </div>

                  <div style={{ fontSize: '0.75rem', color: '#64748b' }}>
                    Ref: <code>{b.booking_reference || bookingId}</code> • Booked at: {formattedDate}
                  </div>
                </div>

                <div>
                  {isConfirmed && (
                    <button
                      onClick={() => handleCancel(bookingId)}
                      disabled={cancellingId === bookingId}
                      style={{
                        background: 'rgba(239, 68, 68, 0.15)',
                        color: '#f87171',
                        border: '1px solid #dc2626',
                        borderRadius: '8px',
                        padding: '0.5rem 1rem',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        cursor: cancellingId === b.booking_id ? 'not-allowed' : 'pointer',
                        transition: 'all 0.2s'
                      }}
                    >
                      {cancellingId === b.booking_id ? 'Releasing...' : 'Cancel Booking'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
