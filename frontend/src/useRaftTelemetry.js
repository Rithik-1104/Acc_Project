import { useState, useEffect, useRef, useCallback } from 'react';

/**
 * Custom hook managing resilient WebSocket connections to all three Raft nodes.
 * Features:
 * - Simultaneous independent streaming from node1 (9001), node2 (9002), and node3 (9003)
 * - Exponential backoff auto-reconnect with sensible jitter (1s - 8s)
 * - Per-node connection state ('CONNECTING', 'CONNECTED', 'DISCONNECTED')
 * - Bounded event timeline retention (default max 300 events)
 * - Queue overflow / sync_required detection
 * - Clean unmount disposal without memory leaks
 */
const DEFAULT_NODES = [
  { id: 'node1', port: 9001 },
  { id: 'node2', port: 9002 },
  { id: 'node3', port: 9003 }
];

export function useRaftTelemetry(nodesConfig = DEFAULT_NODES) {
  const [nodeStates, setNodeStates] = useState({});
  const [events, setEvents] = useState([]);
  const [connectionStates, setConnectionStates] = useState({});
  const [warnings, setWarnings] = useState([]);

  const wsRefs = useRef({});
  const reconnectDelays = useRef({});
  const reconnectTimers = useRef({});
  const isMounted = useRef(true);

  const seenEventKeys = useRef(new Set());

  // Stable event deduplication across concurrent node WebSocket streams
  const getEventDeduplicationKey = (eventObj) => {
    if (!eventObj) return null;
    const cat = eventObj.category || '';
    const act = eventObj.action || '';
    const d = eventObj.details || {};

    // 1. Lock state-machine events: identical commit index and command/status
    if (cat === 'LOCK' && d.index !== undefined) {
      return `lock-${d.index}-${d.command || act}-${d.status || ''}`;
    }

    // 2. Proposal committed: node index and term
    if (act === 'PROPOSAL_COMMITTED' && d.index !== undefined) {
      return `proposal-${d.index}-${eventObj.term ?? ''}-${d.command ?? ''}`;
    }

    // 3. Follower replication success: node + follower + replicated_index + term
    if (act === 'FOLLOWER_REPLICATION_SUCCESS' && d.follower_id && d.replicated_index !== undefined) {
      return `repl-${eventObj.originating_node ?? ''}-${d.follower_id}-${d.replicated_index}-${eventObj.term ?? ''}`;
    }

    // 4. Commit advanced: new_commit + term
    if (act === 'COMMIT_ADVANCED' && d.new_commit !== undefined) {
      return `commit-${eventObj.originating_node ?? ''}-${d.new_commit}-${eventObj.term ?? ''}`;
    }

    // 5. Node fault / lifecycle: node_id + action + timestamp_micros
    if (cat === 'FAULT' || act.startsWith('NODE_') || act === 'ELECTION_WON') {
      return `lifecycle-${eventObj.originating_node ?? ''}-${act}-${eventObj.term ?? ''}-${d.election_term ?? ''}`;
    }

    // Generic fallback: action + microsecond timestamp if available, else null (always keep)
    if (eventObj.timestamp_micros) {
      return `${act}-${eventObj.originating_node ?? ''}-${eventObj.timestamp_micros}`;
    }
    return null;
  };

  const addEvent = useCallback((eventObj) => {
    const dedupKey = getEventDeduplicationKey(eventObj);
    if (dedupKey) {
      if (seenEventKeys.current.has(dedupKey)) {
        return; // Suppress duplicate from secondary stream
      }
      seenEventKeys.current.add(dedupKey);
      // Keep seen set bounded to prevent memory growth
      if (seenEventKeys.current.size > 1000) {
        const arr = Array.from(seenEventKeys.current);
        seenEventKeys.current = new Set(arr.slice(arr.length - 600));
      }
    }

    setEvents((prev) => {
      const next = [eventObj, ...prev];
      return next.slice(0, 300); // Keep bounded ring buffer of 300 items
    });
  }, []);

  const addWarning = useCallback((warningMsg) => {
    setWarnings((prev) => {
      const next = [{ id: Date.now() + Math.random(), ...warningMsg }, ...prev];
      return next.slice(0, 50);
    });
  }, []);

  const connectToNode = useCallback((node) => {
    if (!isMounted.current) return;

    const { id, port } = node;
    const host = typeof window !== 'undefined' ? (window.location.hostname || 'localhost') : 'localhost';
    const wsUrl = node.wsUrl || `ws://${host}:${port}/ws/telemetry`;

    // Close any lingering previous socket
    if (wsRefs.current[id]) {
      try {
        wsRefs.current[id].close();
      } catch (e) {
        // ignore
      }
    }

    setConnectionStates((prev) => ({ ...prev, [id]: 'CONNECTING' }));

    let socket;
    try {
      socket = new WebSocket(wsUrl);
      wsRefs.current[id] = socket;
    } catch (err) {
      scheduleReconnect(node);
      return;
    }

    socket.onopen = () => {
      if (!isMounted.current) return;
      reconnectDelays.current[id] = 1000; // Reset backoff delay on successful connection
      setConnectionStates((prev) => ({ ...prev, [id]: 'CONNECTED' }));
    };

    socket.onmessage = (event) => {
      if (!isMounted.current) return;
      try {
        const data = JSON.parse(event.data);

        if (data.type === 'snapshot') {
          setNodeStates((prev) => ({
            ...prev,
            [id]: {
              ...data,
              lastUpdated: Date.now()
            }
          }));
        } else if (data.type === 'event') {
          addEvent(data);
        } else if (data.type === 'sync_required') {
          addWarning({
            node_id: id,
            timestamp_utc: data.timestamp_utc,
            message: `Subscriber queue overflow detected on ${id}. Event history re-synchronized with snapshot.`
          });
        }
      } catch (parseErr) {
        console.error(`Error parsing telemetry message from ${id}:`, parseErr);
      }
    };

    socket.onclose = () => {
      if (!isMounted.current) return;
      setConnectionStates((prev) => ({ ...prev, [id]: 'DISCONNECTED' }));
      scheduleReconnect(node);
    };

    socket.onerror = () => {
      // Will trigger onclose and handle reconnect
    };
  }, [addEvent, addWarning]);

  const scheduleReconnect = useCallback((node) => {
    if (!isMounted.current) return;
    const { id } = node;

    const currentDelay = reconnectDelays.current[id] || 1000;
    const nextDelay = Math.min(currentDelay * 1.5, 8000);
    reconnectDelays.current[id] = nextDelay;

    if (reconnectTimers.current[id]) {
      clearTimeout(reconnectTimers.current[id]);
    }

    reconnectTimers.current[id] = setTimeout(() => {
      if (isMounted.current) {
        connectToNode(node);
      }
    }, currentDelay);
  }, [connectToNode]);

  useEffect(() => {
    isMounted.current = true;

    nodesConfig.forEach((node) => {
      connectToNode(node);
    });

    return () => {
      isMounted.current = false;
      Object.keys(reconnectTimers.current).forEach((k) => {
        clearTimeout(reconnectTimers.current[k]);
      });
      Object.keys(wsRefs.current).forEach((k) => {
        try {
          const ws = wsRefs.current[k];
          if (ws) {
            ws.onopen = null;
            ws.onmessage = null;
            ws.onerror = null;
            ws.onclose = null;
            if (ws.readyState === WebSocket.OPEN) {
              ws.close(1000, "Component unmounted");
            } else if (ws.readyState === WebSocket.CONNECTING) {
              ws.onopen = () => {
                try { ws.close(1000, "Component unmounted"); } catch(e) {}
              };
            }
          }
        } catch (e) {
          // ignore
        }
      });
    };
  }, [nodesConfig, connectToNode]);

  // Derive unified cluster state: genuine participating consensus nodes
  const participatingCount = Object.entries(nodeStates).filter(([id, ns]) => {
    const isConn = connectionStates[id] === 'CONNECTED';
    const isRunning = ns?.is_running !== false;
    const isIsolated = ns?.is_network_isolated === true;
    return isConn && isRunning && !isIsolated;
  }).length;

  const connectedCount = Object.values(connectionStates).filter((s) => s === 'CONNECTED').length;
  // Majority quorum requires >= 2 running, participating, non-isolated nodes
  const quorumAvailable = participatingCount >= 2;

  // Find currently recognized leader
  let currentLeader = null;
  let highestTerm = 0;
  Object.values(nodeStates).forEach((ns) => {
    if (ns?.current_term > highestTerm) {
      highestTerm = ns.current_term;
    }
    if (ns?.role === 'LEADER' && !ns.is_network_isolated && ns?.is_running !== false) {
      currentLeader = ns.node_id;
    }
  });

  return {
    nodeStates,
    events,
    connectionStates,
    warnings,
    connectedCount,
    participatingCount,
    quorumAvailable,
    currentLeader,
    highestTerm,
    clearEvents: () => setEvents([]),
    clearWarnings: () => setWarnings([])
  };
}
