import React from 'react';
import { Calendar, Clock, MapPin, Sparkles, Star, Award, Shield } from 'lucide-react';

export function MovieHero({ onSelectShow }) {
  return (
    <div style={{
      position: 'relative',
      borderRadius: '16px',
      overflow: 'hidden',
      marginBottom: '28px',
      border: '1px solid rgba(51, 65, 85, 0.6)',
      boxShadow: '0 20px 50px rgba(0, 0, 0, 0.5)',
      background: 'linear-gradient(135deg, #0b1329 0%, #172554 100%)'
    }}>
      {/* Background Graphic Accent */}
      <div style={{
        position: 'absolute',
        top: 0,
        right: 0,
        bottom: 0,
        width: '55%',
        backgroundImage: 'radial-gradient(circle at 70% 40%, rgba(59, 130, 246, 0.25) 0%, transparent 70%)',
        pointerEvents: 'none'
      }} />

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(200px, 280px) 1fr',
        gap: '32px',
        padding: '32px',
        position: 'relative',
        zIndex: 2,
        alignItems: 'center'
      }}>
        
        {/* Movie Poster Card */}
        <div style={{
          borderRadius: '12px',
          overflow: 'hidden',
          boxShadow: '0 12px 36px rgba(0, 0, 0, 0.6)',
          border: '1px solid rgba(255, 255, 255, 0.1)',
          background: '#030712',
          position: 'relative',
          aspectRatio: '2/3',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'flex-end'
        }}>
          {/* Stylized Poster Backdrop */}
          <div style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: 'radial-gradient(circle at 50% 30%, #1e3a8a 0%, #030712 90%)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
            textAlign: 'center'
          }}>
            <div style={{
              width: '80px',
              height: '80px',
              borderRadius: '50%',
              border: '2px solid rgba(147, 197, 253, 0.4)',
              boxShadow: '0 0 30px rgba(59, 130, 246, 0.5)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              marginBottom: '16px'
            }}>
              <Sparkles size={36} color="#93c5fd" />
            </div>
            <div style={{ fontSize: '1.4rem', fontWeight: 900, letterSpacing: '0.15em', color: '#f8fafc', textTransform: 'uppercase' }}>
              INTERSTELLAR
            </div>
            <div style={{ fontSize: '0.75rem', color: '#94a3b8', letterSpacing: '0.1em', marginTop: '6px' }}>
              CHRISTOPHER NOLAN
            </div>
          </div>

          <div style={{
            position: 'relative',
            zIndex: 3,
            background: 'linear-gradient(to top, rgba(0,0,0,0.95), transparent)',
            padding: '16px',
            textAlign: 'center'
          }}>
            <span style={{
              background: 'rgba(234, 179, 8, 0.2)',
              color: '#facc15',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '0.75rem',
              fontWeight: 700,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px'
            }}>
              <Star size={12} fill="#facc15" /> 8.7 / 10 IMDb
            </span>
          </div>
        </div>

        {/* Movie Info & Details */}
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
            <span className="badge badge-leader" style={{ background: 'rgba(225, 29, 72, 0.2)', color: '#fb7185', borderColor: 'rgba(225, 29, 72, 0.4)' }}>
              IMAX EXCLUSIVE
            </span>
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Sci-Fi / Adventure • 2h 49m • English</span>
          </div>

          <h1 style={{ fontSize: '2.5rem', fontWeight: 800, letterSpacing: '-0.03em', color: '#ffffff', margin: '0 0 12px 0' }}>
            Interstellar
          </h1>

          <p style={{ fontSize: '0.92rem', color: '#cbd5e1', lineHeight: 1.6, maxWidth: '680px', marginBottom: '20px' }}>
            A team of explorers travel through a newly discovered wormhole in an effort to ensure humanity’s survival as Earth faces catastrophic environmental collapse. Directed by Christopher Nolan.
          </p>

          {/* Show Selection Card */}
          <div style={{
            background: 'rgba(15, 23, 42, 0.85)',
            border: '1px solid rgba(59, 130, 246, 0.4)',
            borderRadius: '10px',
            padding: '16px 20px',
            maxWidth: '620px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '16px'
          }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.82rem', color: '#f8fafc', fontWeight: 600 }}>
                <MapPin size={15} color="#3b82f6" />
                Stellar PVR: Screen 1 Laser Theatre (50 Seats)
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '0.76rem', color: '#94a3b8' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Calendar size={13} /> Today, Prime Show
                </span>
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Clock size={13} /> 08:30 PM (IST)
                </span>
                <span style={{ color: '#10b981', fontWeight: 600 }}>
                  VIP ₹300.00 | Standard ₹180.00
                </span>
              </div>
            </div>

            <button
              className="btn btn-primary"
              onClick={onSelectShow}
              style={{
                background: 'linear-gradient(135deg, #2563eb, #1d4ed8)',
                padding: '10px 20px',
                fontSize: '0.88rem',
                fontWeight: 600,
                boxShadow: '0 0 16px rgba(37, 99, 235, 0.4)'
              }}
            >
              Select Seats
            </button>
          </div>

        </div>

      </div>
    </div>
  );
}
