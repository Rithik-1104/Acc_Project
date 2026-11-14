import { useState, useEffect, useRef, useCallback } from 'react';

const NODES = [
  { id: 'node1', port: 9001 },
  { id: 'node2', port: 9002 },
  { id: 'node3', port: 9003 }
];

export function useCinemaSync(showId = "show-screen-1-prime") {
  const [seats, setSeats] = useState([]);
  const [activeLocks, setActiveLocks] = useState({});
  const [activeReservations, setActiveReservations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [leaderUrl, setLeaderUrl] = useState('http://localhost:9001');
  const [lastSyncTime, setLastSyncTime] = useState(Date.now());
  const isMounted = useRef(true);
  const wsRefs = useRef({});

  // 1. Fetch database seats from whichever node is available
  const fetchSeats = useCallback(async () => {
    const host = typeof window !== 'undefined' ? (window.location.hostname || 'localhost') : 'localhost';
    for (const node of NODES) {
      try {
        const res = await fetch(`http://${host}:${node.port}/api/cinema/seats/${showId}`);
        if (res.ok) {
          const data = await res.json();
          if (isMounted.current && Array.isArray(data)) {
            setSeats(data);
            setLoading(false);
            setLastSyncTime(Date.now());
            return data;
          }
        }
      } catch (e) {
        // try next node
      }
    }
  }, [showId]);

  // 2. Fetch cluster topology to identify active leader URL
  const updateLeader = useCallback(async () => {
    const host = typeof window !== 'undefined' ? (window.location.hostname || 'localhost') : 'localhost';
    for (const node of NODES) {
      try {
        const res = await fetch(`http://${host}:${node.port}/api/cluster/topology`);
        if (res.ok) {
          const topo = await res.json();
          const currentLeader = topo.current_leader;
          const portMap = { node1: 9001, node2: 9002, node3: 9003 };
          const p = portMap[currentLeader] || 9001;
          if (isMounted.current) {
            setLeaderUrl(`http://${host}:${p}`);
          }
          return;
        }
      } catch (e) {
        // try next
      }
    }
  }, []);

  // 3. Connect to telemetry WebSockets to listen for lock, reservation, and booking events in real-time
  useEffect(() => {
    isMounted.current = true;
    fetchSeats();
    updateLeader();

    const host = typeof window !== 'undefined' ? (window.location.hostname || 'localhost') : 'localhost';

    let cancelInit = false;

    // Use a microtask/timer to avoid React 18 StrictMode instant-abort warning
    const connectTimer = setTimeout(() => {
      if (cancelInit) return;
      NODES.forEach((node) => {
        const wsUrl = `ws://${host}:${node.port}/ws/telemetry`;
        try {
          const ws = new WebSocket(wsUrl);
          wsRefs.current[node.id] = ws;

          ws.onmessage = (event) => {
            if (!isMounted.current) return;
            try {
              const data = JSON.parse(event.data);
              if (data.type === 'snapshot') {
                if (data.active_locks) {
                  setActiveLocks(data.active_locks);
                }
                if (data.active_reservations) {
                  setActiveReservations(data.active_reservations);
                }
              } else if (data.type === 'event') {
                if (data.category === 'LOCK' || data.action === 'COMMIT_ADVANCED' || data.action?.includes('RESERVE')) {
                  fetchSeats();
                }
              }
            } catch (e) {}
          };
        } catch (e) {}
      });
    }, 50);

    // Periodic safety poll every 2.5s to ensure synchronized seats across tabs
    const pollInterval = setInterval(() => {
      fetchSeats();
      updateLeader();
    }, 2500);

    return () => {
      cancelInit = true;
      isMounted.current = false;
      clearTimeout(connectTimer);
      clearInterval(pollInterval);
      Object.keys(wsRefs.current).forEach((k) => {
        try {
          const ws = wsRefs.current[k];
          if (ws) {
            // Remove listeners so closing does not log errors
            ws.onopen = null;
            ws.onmessage = null;
            ws.onerror = null;
            ws.onclose = null;
            if (ws.readyState === WebSocket.OPEN) {
              ws.close(1000, "Component unmounted");
            } else if (ws.readyState === WebSocket.CONNECTING) {
              // Wait for open before closing if connecting to avoid browser console warning
              ws.onopen = () => {
                try { ws.close(1000, "Component unmounted"); } catch(e) {}
              };
            }
          }
        } catch (e) {}
      });
    };
  }, [fetchSeats, updateLeader]);

  return {
    seats,
    activeLocks,
    activeReservations,
    loading,
    leaderUrl,
    lastSyncTime,
    refreshSeats: fetchSeats
  };
}
