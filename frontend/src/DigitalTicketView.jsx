import React from 'react';
import { CheckCircle2, Ticket, Calendar, Clock, MapPin, Printer, ArrowLeft, ShieldCheck, QrCode } from 'lucide-react';

export function DigitalTicketView({ ticket, onBackToBooking }) {
  if (!ticket) return null;

  const handlePrint = () => {
    window.print();
  };

  return (
    <div style={{ maxWidth: '640px', margin: '0 auto 40px auto' }}>
      
      {/* Back action */}
      <button
        onClick={onBackToBooking}
        style={{
          background: 'transparent',
          border: 'none',
          color: '#94a3b8',
          fontSize: '0.85rem',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          cursor: 'pointer',
          marginBottom: '16px'
        }}
      >
        <ArrowLeft size={16} />
        Back to Cinema Booking
      </button>

      {/* Ticket Container */}
      <div className="glass-panel" style={{
        padding: '0',
        overflow: 'hidden',
        border: '1px solid rgba(16, 185, 129, 0.5)',
        boxShadow: '0 20px 50px rgba(0, 0, 0, 0.6)'
      }}>
        
        {/* Ticket Header Banner */}
        <div style={{
          background: 'linear-gradient(135deg, #065f46, #047857)',
          padding: '24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          color: '#ffffff'
        }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
              <CheckCircle2 size={24} color="#34d399" />
              <h2 style={{ fontSize: '1.3rem', fontWeight: 800, margin: 0, letterSpacing: '-0.02em' }}>
                BOOKING CONFIRMED
              </h2>
            </div>
            <span style={{ fontSize: '0.78rem', opacity: 0.9 }}>
              Consensus verified and durably stored in PostgreSQL
            </span>
          </div>

          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.7rem', opacity: 0.8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Booking Reference
            </span>
            <div style={{ fontSize: '1.1rem', fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
              BK-{ticket.booking_id?.slice(0, 8).toUpperCase()}
            </div>
          </div>
        </div>

        {/* Ticket Body Details */}
        <div style={{ padding: '28px' }}>
          
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
            <div>
              <span className="badge badge-leader" style={{ background: 'rgba(59, 130, 246, 0.2)', color: '#60a5fa', borderColor: 'rgba(59, 130, 246, 0.4)', marginBottom: '8px' }}>
                IMAX LASER 2D
              </span>
              <h3 style={{ fontSize: '1.6rem', fontWeight: 800, color: '#f8fafc', margin: '4px 0' }}>
                Interstellar
              </h3>
              <p style={{ fontSize: '0.8rem', color: '#94a3b8', margin: 0 }}>
                English • Sci-Fi / Adventure • 169 mins
              </p>
            </div>

            {/* Stylized QR Code Badge */}
            <div style={{
              background: '#ffffff',
              padding: '8px',
              borderRadius: '8px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <QrCode size={54} color="#0f172a" />
            </div>
          </div>

          {/* Info Grid */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '16px',
            background: 'rgba(15, 23, 42, 0.7)',
            padding: '16px 20px',
            borderRadius: '10px',
            border: '1px solid #334155',
            marginBottom: '24px'
          }}>
            <div>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>THEATRE &amp; SCREEN</span>
              <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#f8fafc' }}>
                Stellar Cinemas Laser 1
              </div>
            </div>

            <div>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>DATE &amp; SHOWTIME</span>
              <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#f8fafc' }}>
                Today, 08:30 PM (IST)
              </div>
            </div>

            <div>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>SEAT NUMBERS</span>
              <div style={{ fontSize: '1.1rem', fontWeight: 800, color: '#10b981', fontFamily: 'var(--font-mono)' }}>
                {ticket.seats?.join(', ')}
              </div>
            </div>

            <div>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>CUSTOMER IDENTITY</span>
              <div style={{ fontSize: '0.88rem', fontWeight: 600, color: '#60a5fa' }}>
                {ticket.customer_name ? `${ticket.customer_name} (${ticket.owner_id || ticket.customer_id || ''})` : (ticket.owner_id || ticket.customer_id || 'Customer')}
              </div>
            </div>

            <div>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>FENCING TOKEN (ACID)</span>
              <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#fbbf24', fontFamily: 'var(--font-mono)' }}>
                #{ticket.fencing_token}
              </div>
            </div>

            <div>
              <span style={{ fontSize: '0.72rem', color: '#64748b' }}>PAYMENT STATUS</span>
              <div style={{ fontSize: '0.88rem', fontWeight: 700, color: '#10b981' }}>
                SIMULATED SUCCESS (₹{ticket.total_amount?.toFixed(2) || '0.00'})
              </div>
            </div>
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              className="btn btn-secondary"
              onClick={handlePrint}
              style={{ display: 'flex', alignItems: 'center', gap: '8px' }}
            >
              <Printer size={15} />
              Print Ticket
            </button>

            <button
              className="btn btn-primary"
              onClick={onBackToBooking}
              style={{ background: '#2563eb' }}
            >
              Book Another Ticket
            </button>
          </div>

        </div>

      </div>
    </div>
  );
}
