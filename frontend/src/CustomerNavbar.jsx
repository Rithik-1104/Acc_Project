import React from 'react';
import { User, Users, Film, Activity, Ticket } from 'lucide-react';

export function CustomerNavbar({
  currentCustomer,
  onSelectCustomer,
  activeView,
  onNavigate,
  myBookingsCount = 0
}) {
  return (
    <nav style={{
      background: 'rgba(8, 13, 26, 0.85)',
      backdropFilter: 'blur(16px)',
      borderBottom: '1px solid rgba(51, 65, 85, 0.5)',
      padding: '12px 28px',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: '16px'
    }}>
      {/* Brand & Title */}
      <div
        onClick={() => onNavigate('booking')}
        style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer' }}
      >
        <div style={{
          background: 'linear-gradient(135deg, #e11d48, #be123c)',
          padding: '8px 10px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 0 16px rgba(225, 29, 72, 0.4)'
        }}>
          <Film size={22} color="#ffffff" />
        </div>
        <div>
          <div style={{ fontSize: '1.15rem', fontWeight: 800, letterSpacing: '-0.02em', color: '#f8fafc', display: 'flex', alignItems: 'center', gap: '6px' }}>
            STELLAR CINEMAS
            <span style={{ fontSize: '0.65rem', background: 'rgba(225, 29, 72, 0.2)', color: '#fb7185', border: '1px solid rgba(225, 29, 72, 0.4)', padding: '1px 6px', borderRadius: '4px', textTransform: 'uppercase' }}>
              Raft Consensus Powered
            </span>
          </div>
          <div style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
            Fault-Tolerant Distributed Seat Reservation Service
          </div>
        </div>
      </div>

      {/* Navigation & Customer Identity Selector */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
        
        {/* Customer Identity Profile Switcher (Session-specific) */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          background: 'rgba(15, 23, 42, 0.9)',
          border: '1px solid #334155',
          borderRadius: '24px',
          padding: '3px 4px'
        }}>
          <span style={{ fontSize: '0.72rem', color: '#64748b', padding: '0 8px', fontWeight: 600 }}>
            PROFILE:
          </span>
          <button
            type="button"
            onClick={() => {
              if (currentCustomer.id !== 'customer_a') {
                onSelectCustomer({ id: 'customer_a', name: 'Customer A' });
              }
            }}
            style={{
              background: currentCustomer.id === 'customer_a' ? 'linear-gradient(135deg, #2563eb, #1d4ed8)' : 'transparent',
              color: currentCustomer.id === 'customer_a' ? '#ffffff' : '#94a3b8',
              border: currentCustomer.id === 'customer_a' ? '1px solid #3b82f6' : '1px solid transparent',
              borderRadius: '20px',
              padding: '5px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              cursor: currentCustomer.id === 'customer_a' ? 'default' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: currentCustomer.id === 'customer_a' ? '0 0 12px rgba(37, 99, 235, 0.5)' : 'none',
              transition: 'all 0.15s ease'
            }}
          >
            <User size={13} />
            Customer A
          </button>
          <button
            type="button"
            onClick={() => {
              if (currentCustomer.id !== 'customer_b') {
                onSelectCustomer({ id: 'customer_b', name: 'Customer B' });
              }
            }}
            style={{
              background: currentCustomer.id === 'customer_b' ? 'linear-gradient(135deg, #2563eb, #1d4ed8)' : 'transparent',
              color: currentCustomer.id === 'customer_b' ? '#ffffff' : '#94a3b8',
              border: currentCustomer.id === 'customer_b' ? '1px solid #3b82f6' : '1px solid transparent',
              borderRadius: '20px',
              padding: '5px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              cursor: currentCustomer.id === 'customer_b' ? 'default' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              boxShadow: currentCustomer.id === 'customer_b' ? '0 0 12px rgba(37, 99, 235, 0.5)' : 'none',
              transition: 'all 0.15s ease'
            }}
          >
            <Users size={13} />
            Customer B
          </button>
        </div>

        {/* View Switch: Book Seats vs My Bookings */}
        <button
          onClick={() => onNavigate('booking')}
          style={{
            background: activeView === 'booking' ? 'rgba(51, 65, 85, 0.8)' : 'transparent',
            color: activeView === 'booking' ? '#f8fafc' : '#94a3b8',
            border: '1px solid ' + (activeView === 'booking' ? '#475569' : 'transparent'),
            borderRadius: '6px',
            padding: '6px 12px',
            fontSize: '0.8rem',
            fontWeight: 500,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
        >
          <Film size={14} />
          Book Tickets
        </button>

        <button
          onClick={() => onNavigate('history')}
          style={{
            background: activeView === 'history' ? 'rgba(51, 65, 85, 0.8)' : 'transparent',
            color: activeView === 'history' ? '#f8fafc' : '#94a3b8',
            border: '1px solid ' + (activeView === 'history' ? '#475569' : 'transparent'),
            borderRadius: '6px',
            padding: '6px 12px',
            fontSize: '0.8rem',
            fontWeight: 500,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
        >
          <Ticket size={14} />
          My Bookings ({myBookingsCount})
        </button>

        {/* Dedicated Route Navigation to System Monitor */}
        <button
          onClick={() => onNavigate('monitor')}
          style={{
            background: activeView === 'monitor' ? 'rgba(37, 99, 235, 0.2)' : 'rgba(15, 23, 42, 0.8)',
            color: activeView === 'monitor' ? '#60a5fa' : '#94a3b8',
            border: '1px solid ' + (activeView === 'monitor' ? '#3b82f6' : '#334155'),
            borderRadius: '6px',
            padding: '6px 12px',
            fontSize: '0.8rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '6px'
          }}
        >
          <Activity size={14} color="#3b82f6" />
          System Monitor
        </button>

      </div>
    </nav>
  );
}
