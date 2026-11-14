import React, { useState } from 'react';
import { CustomerNavbar } from './CustomerNavbar';
import { MovieHero } from './MovieHero';
import { SeatSelectionView } from './SeatSelectionView';
import { PaymentSimulationModal } from './PaymentSimulationModal';
import { DigitalTicketView } from './DigitalTicketView';
import BookingHistoryView from './BookingHistoryView';
import SystemMonitorDashboard from './SystemMonitorDashboard';
import { useCinemaSync } from './useCinemaSync';

const PREDEFINED_CUSTOMERS = [
  { id: 'customer_a', name: 'Customer A' },
  { id: 'customer_b', name: 'Customer B' }
];

export default function App() {
  // Navigation route: 'cinema' | 'history' | 'monitor'
  const [currentRoute, setCurrentRoute] = useState(() => {
    if (window.location.pathname.startsWith('/monitor')) {
      return 'monitor';
    }
    return 'cinema';
  });

  // Session-isolated customer profile (uses sessionStorage so tab A and tab B can be distinct customers)
  const [currentCustomer, setCurrentCustomer] = useState(() => {
    const saved = sessionStorage.getItem('cinema_active_customer');
    if (saved) {
      try {
        return JSON.parse(saved);
      } catch (e) {
        // ignore
      }
    }
    return PREDEFINED_CUSTOMERS[0];
  });

  // Independent seat selections per customer profile
  const [customerSelections, setCustomerSelections] = useState({
    customer_a: [],
    customer_b: []
  });
  const [isBooking, setIsBooking] = useState(false);
  const [bookingError, setBookingError] = useState(null);

  // Active selected seats for current profile
  const selectedSeats = customerSelections[currentCustomer.id] || [];

  // Active reservation flow state (once distributed lock is acquired)
  const [activeReservation, setActiveReservation] = useState(null);
  const [isProcessingPayment, setIsProcessingPayment] = useState(false);
  const [confirmedBooking, setConfirmedBooking] = useState(null);

  // Real-time seat synchronization hook
  const {
    seats,
    activeLocks,
    activeReservations,
    loading: seatsLoading,
    leaderUrl,
    refreshSeats
  } = useCinemaSync('show-screen-1-prime');

  // Handle customer switch without resetting selections or application state
  const handleCustomerChange = (customer) => {
    if (customer.id === currentCustomer.id) return;
    setCurrentCustomer(customer);
    sessionStorage.setItem('cinema_active_customer', JSON.stringify(customer));
    setBookingError(null);
  };

  // Toggle seat selection (Frontend only - lock is NOT acquired yet)
  const handleToggleSeat = (seatCode) => {
    setBookingError(null);
    setCustomerSelections((prev) => {
      const currentList = prev[currentCustomer.id] || [];
      if (currentList.includes(seatCode)) {
        return {
          ...prev,
          [currentCustomer.id]: currentList.filter(s => s !== seatCode)
        };
      } else {
        if (currentList.length >= 10) {
          alert("Maximum 10 seats allowed per booking.");
          return prev;
        }
        return {
          ...prev,
          [currentCustomer.id]: [...currentList, seatCode]
        };
      }
    });
  };

  // Proceed to book -> Actual Distributed Lock Acquisition via Raft Consensus Leader
  const handleProceedToBook = async () => {
    if (selectedSeats.length === 0) return;
    setIsBooking(true);
    setBookingError(null);

    const bookingId = `bk-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 6)}`;
    const idempotencyKey = `idemp-${bookingId}`;
    const seatIds = selectedSeats.map(code => `seat-${code}`);

    try {
      const response = await fetch(`${leaderUrl}/api/cinema/reserve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          booking_id: bookingId,
          show_id: 'show-screen-1-prime',
          owner_id: currentCustomer.id,
          seat_ids: seatIds,
          ttl_seconds: 60,
          idempotency_key: idempotencyKey
        })
      });

      const data = await response.json();

      if (!response.ok || data.status === 'error') {
        const errorMsg = formatErrorMessage("Reservation Rejected", data);
        setBookingError(errorMsg);
        await refreshSeats();
        return;
      }

      // Successful Lock Acquisition!
      setActiveReservation({
        ...data,
        seatCodes: selectedSeats,
        customerName: currentCustomer.name
      });
      // Clear current customer's selection on successful lock
      setCustomerSelections((prev) => ({
        ...prev,
        [currentCustomer.id]: []
      }));
      await refreshSeats();
    } catch (err) {
      console.error("Lock acquisition error:", err);
      setBookingError(`Connection Error: ${err.message}. Leader may be electing or isolating.`);
      await refreshSeats();
    } finally {
      setIsBooking(false);
    }
  };

  // Helper to format structured backend error details cleanly (never show [object Object])
  const formatErrorMessage = (prefix, errorPayload) => {
    if (!errorPayload) return `${prefix}: Unknown error`;
    if (typeof errorPayload === 'string') return `${prefix}: ${errorPayload}`;

    // FastAPI HTTPException with dict detail: e.g. { status: "REJECTED_STALE_TOKEN", expected: 1033, provided: null }
    const d = errorPayload.detail || errorPayload;
    if (typeof d === 'string') return `${prefix}: ${d}`;

    if (typeof d === 'object') {
      if (d.status === 'REJECTED_SEAT_LOCKED') {
        const seat = d.conflict_seat ? ` (${d.conflict_seat.replace('seat-', '')})` : '';
        return "This seat has just been reserved by another customer. Please select a different seat.";
      }
      if (d.status === 'REJECTED_SEAT_BOOKED') {
        const seat = d.conflict_seat ? ` (${d.conflict_seat.replace('seat-', '')})` : '';
        return `This seat${seat} is already booked permanently. Please select a different seat.`;
      }
      if (d.status === 'REJECTED_BOOKING_EXISTS') {
        return `${prefix}: Booking reference already exists.`;
      }
      if (d.status === 'REJECTED_STALE_TOKEN') {
        return `${prefix}: Stale fencing token. Expected token ${d.expected ?? 'none'}, received ${d.provided ?? 'none'}.`;
      }
      if (d.status === 'REJECTED_EXPIRED') {
        return `${prefix}: Reservation lease has already expired.`;
      }
      if (d.status === 'REJECTED_MAX_CEILING_REACHED') {
        return `${prefix}: Maximum 120-second lease ceiling reached.`;
      }
      if (d.status === 'REJECTED_OWNER_MISMATCH') {
        return `${prefix}: Customer profile does not match reservation owner.`;
      }
      if (d.status === 'REJECTED_NOT_FOUND') {
        return `${prefix}: Reservation not found in cluster.`;
      }
      if (d.status === 'REJECTED_INVALID_STATUS') {
        return `${prefix}: Reservation is not in a releasable pending state.`;
      }
      if (d.message) return `${prefix}: ${d.message}`;
      if (d.status) return `${prefix}: ${d.status}`;
      try {
        return `${prefix}: ${JSON.stringify(d)}`;
      } catch {
        return `${prefix}: Operation rejected by backend`;
      }
    }
    return `${prefix}: ${String(errorPayload)}`;
  };

  // Renew lease (+30s)
  const handleRenewLease = async () => {
    if (!activeReservation) return;
    const idempotencyKey = `renew-${activeReservation.booking_id}-${Date.now()}`;

    try {
      const response = await fetch(`${leaderUrl}/api/cinema/renew`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          booking_id: activeReservation.booking_id,
          owner_id: currentCustomer.id,
          current_token: activeReservation.fencing_token,
          extension_seconds: 30,
          idempotency_key: idempotencyKey
        })
      });

      const data = await response.json();
      if (!response.ok || data.status === 'error') {
        const errorMsg = formatErrorMessage("Lease renewal rejected", data);
        alert(errorMsg);
        return;
      }

      // Successful renewal committed through Raft
      setActiveReservation(prev => ({
        ...prev,
        expires_at: data.expires_at,
        fencing_token: data.fencing_token || prev.fencing_token,
        ttl_remaining_seconds: data.ttl_remaining_seconds
      }));
      await refreshSeats();
    } catch (err) {
      alert(`Lease renewal failed: ${err.message}`);
    }
  };

  // Release reservation / lock
  const handleCancelReservation = async () => {
    if (!activeReservation) return;
    const idempotencyKey = `release-${activeReservation.booking_id}-${Date.now()}`;

    try {
      const response = await fetch(`${leaderUrl}/api/cinema/release`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          booking_id: activeReservation.booking_id,
          owner_id: currentCustomer.id,
          current_token: activeReservation.fencing_token,
          idempotency_key: idempotencyKey
        })
      });

      const data = await response.json();
      if (!response.ok || data.status === 'error') {
        const errorMsg = formatErrorMessage("Lock release failed", data);
        alert(errorMsg);
        return;
      }

      // Confirmed committed through Raft state machine
      setActiveReservation(null);
      await refreshSeats();
    } catch (e) {
      console.error("Release error:", e);
      alert(`Lock release failed: ${e.message}`);
    }
  };

  // Confirm booking & validate fencing token
  const handleConfirmPayment = async () => {
    if (!activeReservation) return;
    setIsProcessingPayment(true);
    const idempotencyKey = `confirm-${activeReservation.booking_id}-${Date.now()}`;

    try {
      const response = await fetch(`${leaderUrl}/api/cinema/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          booking_id: activeReservation.booking_id,
          owner_id: currentCustomer.id,
          fencing_token: activeReservation.fencing_token,
          idempotency_key: idempotencyKey
        })
      });

      const data = await response.json();
      if (!response.ok || data.status === 'error') {
        const errorMsg = formatErrorMessage("Booking confirmation failed", data);
        alert(errorMsg);
        return;
      }

      // Extract seat codes reliably
      const confirmedSeatCodes = (data.seats && data.seats.length > 0)
        ? data.seats.map(s => s.seat_code || s.seat_id?.replace('seat-', '') || s)
        : (activeReservation.seatCodes || (activeReservation.seat_ids || []).map(s => s.replace('seat-', '')));

      const finalAmount = data.total_amount !== undefined
        ? data.total_amount
        : (activeReservation.total_amount || 0);

      // Show digital ticket
      setConfirmedBooking({
        ...data,
        booking_id: activeReservation.booking_id,
        seat_codes: confirmedSeatCodes,
        seats: confirmedSeatCodes,
        movie_title: 'Interstellar',
        customer_name: currentCustomer.name,
        customer_id: currentCustomer.id,
        owner_id: currentCustomer.id,
        screen_name: 'Screen 1 (IMAX Laser)',
        show_name: 'Prime Evening 7:30 PM',
        fencing_token: activeReservation.fencing_token,
        total_amount: finalAmount,
        confirmed_at: data.confirmed_at || new Date().toISOString()
      });

      setActiveReservation(null);
      await refreshSeats();
    } catch (err) {
      alert(`Confirmation Error: ${err.message}`);
    } finally {
      setIsProcessingPayment(false);
    }
  };

  const navigateTo = (view) => {
    setCurrentRoute(view);
    if (view === 'monitor') {
      window.history.pushState(null, '', '/monitor');
    } else {
      window.history.pushState(null, '', '/');
    }
  };

  if (currentRoute === 'monitor') {
    return <SystemMonitorDashboard onGoToCinema={() => navigateTo('cinema')} />;
  }

  return (
    <div style={{ minHeight: '100vh', background: '#020617', color: '#f8fafc', fontFamily: 'Inter, -apple-system, BlinkMacSystemFont, sans-serif' }}>
      
      {/* Top Customer Navigation Bar */}
      <CustomerNavbar
        currentCustomer={currentCustomer}
        onSelectCustomer={handleCustomerChange}
        activeView={currentRoute}
        onNavigate={navigateTo}
      />

      <div style={{ maxWidth: '1200px', margin: '0 auto', padding: '24px 20px' }}>
        {currentRoute === 'history' ? (
          <BookingHistoryView
            customer={currentCustomer}
            leaderUrl={leaderUrl}
            onBackToCinema={() => navigateTo('cinema')}
            onBookingCancelled={() => refreshSeats()}
          />
        ) : confirmedBooking ? (
          <DigitalTicketView
            ticket={confirmedBooking}
            onBackToBooking={() => {
              setConfirmedBooking(null);
              refreshSeats();
            }}
          />
        ) : (
          <main>
            {/* Movie Presentation */}
            <MovieHero onSelectShow={() => {
              document.getElementById('seat-matrix')?.scrollIntoView({ behavior: 'smooth' });
            }} />

            {/* Error Notification Banner if Lock Acquisition Rejected */}
            {bookingError && (
              <div style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid #ef4444',
                color: '#fca5a5',
                padding: '14px 20px',
                borderRadius: '10px',
                marginBottom: '20px',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}>
                <div>
                  <strong>Distributed Lock Failure: </strong>
                  {bookingError}
                </div>
                <button
                  onClick={() => setBookingError(null)}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: '#fca5a5',
                    cursor: 'pointer',
                    fontSize: '1rem',
                    fontWeight: 700
                  }}
                >
                  ✕
                </button>
              </div>
            )}

            {/* Interactive 50-Seat Layout */}
            <div id="seat-matrix">
              <SeatSelectionView
                seats={seats}
                activeLocks={activeLocks}
                activeReservations={activeReservations}
                selectedSeats={selectedSeats}
                onToggleSeat={handleToggleSeat}
                onProceedToBook={handleProceedToBook}
                loading={seatsLoading}
                isBooking={isBooking}
              />
            </div>
          </main>
        )}
      </div>

      {/* Payment Simulation & Lease Management Modal */}
      {activeReservation && (
        <PaymentSimulationModal
          reservation={activeReservation}
          onConfirmPayment={handleConfirmPayment}
          onRenewLease={handleRenewLease}
          onCancelReservation={handleCancelReservation}
          isProcessing={isProcessingPayment}
        />
      )}

      {/* Footer */}
      <footer style={{
        textAlign: 'center',
        padding: '24px 0',
        fontSize: '0.8rem',
        color: '#64748b',
        borderTop: '1px solid #1e293b',
        background: '#090d16',
        marginTop: '40px'
      }}>
        Fault-Tolerant Distributed Lock Service using Raft Consensus (Quorum: 2/3) • Cinema Ticketing Application
      </footer>
    </div>
  );
}
