# FINAL DEMO GUIDE: Fault-Tolerant Distributed Lock Service Using Raft Consensus Algorithm

**Project:** Fault-Tolerant Distributed Lock Service Using Raft Consensus Algorithm  
**Application Demo:** Cinema Seat-Booking & System Telemetry Monitor  
**Workspace Directory:** `C:\Users\rithi\Downloads\acc_project_2`

---

## 1. Project Directory Structure

```text
acc_project_2/
├── backend/
│   ├── api/
│   │   ├── cinema_routes.py      # Booking, seat reservation, renewal, confirmation & cancellation endpoints
│   │   ├── fault_routes.py       # Fault injection (network isolate, heal, stop, restart, stale token)
│   │   └── telemetry_routes.py   # WebSocket telemetry stream & cluster metrics
│   ├── consensus/
│   │   ├── config.py             # Raft timing & topology configurations
│   │   ├── lease_manager.py      # Background leader lease expiration monitor
│   │   ├── lock_models.py        # Pydantic schemas for locks, bookings, and payloads
│   │   ├── lock_state_machine.py # Distributed Lock Replicated State Machine (60s initial, +30s renewal, 120s ceiling)
│   │   ├── models.py             # Raft RPC models (RequestVote, AppendEntries, LogEntry)
│   │   ├── node.py               # Raft Node consensus engine (Leader, Follower, Candidate, WAL persistence)
│   │   ├── rpc.py                # Inter-node HTTP/REST RPC client
│   │   ├── state_machine.py      # Generic state machine interface
│   │   └── wal.py                # Write-Ahead Log (WAL) and metadata durability engine
│   ├── db/
│   │   ├── init_db.py            # PostgreSQL initialization (50 seats, single showtime, movies)
│   │   ├── models.py             # SQLAlchemy models (Movie, Show, Seat, Booking, BookingSeat)
│   │   └── session.py            # Async PostgreSQL database engine and session maker
│   ├── services/
│   │   ├── booking_coordinator.py# Leader transactional reconciliation to PostgreSQL 16
│   │   ├── event_bus.py          # Bounded in-memory event bus and telemetry stream
│   │   └── metrics.py            # Raft metrics tracking (latency, proposals, terms)
│   ├── Dockerfile                # Python 3.11-slim Raft node container definition
│   └── main.py                   # FastAPI application entry point
├── frontend/
│   ├── src/
│   │   ├── App.jsx               # Main cinema reservation layout & customer session coordinator
│   │   ├── BookingHistoryView.jsx# Customer booking history & cancellation view
│   │   ├── ClusterHeader.jsx     # Cluster health & leader connection status badge
│   │   ├── CustomerNavbar.jsx    # Predefined customer profile switcher (Customer A / B)
│   │   ├── DigitalTicketView.jsx # Confirmed tickets with QR and seat designations
│   │   ├── LiveEventTimeline.jsx # Real-time Raft event timeline stream
│   │   ├── MovieHero.jsx         # Movie banner and show details
│   │   ├── PaymentSimulationModal.jsx # Distributed lock granted countdown & payment simulation
│   │   ├── PerformanceAndFaultTesting.jsx # Chaos injection controls (stop, isolate, heal)
│   │   ├── SeatSelectionView.jsx # Interactive 50-seat grid with live lock sync
│   │   ├── SystemMonitorDashboard.jsx # Real-time Raft cluster dashboard
│   │   ├── useCinemaSync.js      # WebSocket/HTTP hook for live seat lock updates
│   │   └── useRaftTelemetry.js   # Multi-node WebSocket hook for telemetry
│   ├── package.json              # Frontend dependencies
│   └── vite.config.js            # Vite bundler configuration
├── tests/
│   ├── test_cinema_booking_app.py# End-to-end cinema booking, pricing & renewal tests (Tests 1-6)
│   ├── test_consensus_cluster.py # Raft multi-node election and consensus tests
│   ├── test_consensus_unit.py    # Unit tests for log append and state transitions
│   ├── test_distributed_locks.py # Multi-seat atomic locks & token fencing tests
│   ├── test_event_bus_and_metrics.py
│   ├── test_fault_isolation_and_security.py
│   └── test_telemetry_websocket.py
├── docker-compose.yml            # PostgreSQL 16 + 3 Raft nodes (9001, 9002, 9003)
├── pytest.ini                    # Pytest configuration
├── requirements.txt              # Backend Python dependencies
└── FINAL_DEMO_GUIDE.md           # This handover documentation
```

---

## 2. VS Code Startup Instructions

Follow these exact steps from the **VS Code Integrated Terminal** (`Ctrl + ~`):

### Terminal 1: Start Docker Services (PostgreSQL + 3 Raft Nodes)

```powershell
# Ensure you are in the project root directory
cd C:\Users\rithi\Downloads\acc_project_2

# Start all containers in the background (Postgres + Node1 + Node2 + Node3)
docker compose up -d

# Verify all 4 containers are running and healthy
docker compose ps
```

*Expected output:*
- `cinema-postgres` — Up (healthy), port 5435
- `raft-node-1` — Up, port 9001
- `raft-node-2` — Up, port 9002
- `raft-node-3` — Up, port 9003

---

### Terminal 2: Start Frontend Application

Open a second terminal tab in VS Code (`Ctrl + Shift + 5` or click `+`):

```powershell
# Navigate to frontend directory
cd C:\Users\rithi\Downloads\acc_project_2\frontend

# Start Vite development server on port 3000
npm run dev -- --host 127.0.0.1 --port 3000
```
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force


*Expected output:*
```text
  VITE v8.3.5  ready in ~800 ms

  ➜  Local:   http://127.0.0.1:3000/
```

---

## 3. Application URLs

| Interface | URL | Purpose |
| :--- | :--- | :--- |
| **Cinema Seat Booking Application** | [http://127.0.0.1:3000/](http://127.0.0.1:3000/) | Customer seat booking, renewal (+30s), live locks, simulated instant payment & digital tickets |
| **System Monitor Dashboard** | [http://127.0.0.1:3000/monitor](http://127.0.0.1:3000/monitor) | Real-time 3-node cluster topology, Raft terms, commit indices, live event timeline & fault injection controls |
| **Raft Node 1 API** | [http://127.0.0.1:9001/docs](http://127.0.0.1:9001/docs) | Swagger OpenAPI docs for Node 1 |
| **Raft Node 2 API** | [http://127.0.0.1:9002/docs](http://127.0.0.1:9002/docs) | Swagger OpenAPI docs for Node 2 |
| **Raft Node 3 API** | [http://127.0.0.1:9003/docs](http://127.0.0.1:9003/docs) | Swagger OpenAPI docs for Node 3 |

---

## 4. How to Stop Everything

When your demonstration is complete:

1. In the **Frontend Terminal**, press `Ctrl + C` and type `y` to terminate the Vite dev server.
2. In the **Main Terminal**, stop the Docker containers gracefully:
   ```powershell
   cd C:\Users\rithi\Downloads\acc_project_2
   docker compose stop
   ```

> [!CAUTION]
> **NEVER run `docker compose down -v`**. Using `-v` deletes the named Docker volumes and resets the PostgreSQL database and Raft persistent WAL logs!

---

## 5. College Demonstration Walkthrough & Key Features

### Feature 1: Distributed Lock Acquisition & Monotonic Fencing Token
1. Open [http://127.0.0.1:3000/](http://127.0.0.1:3000/).
2. Select any available seat (e.g., `A1` VIP ₹300 or `C1` Standard ₹180).
3. Click **Reserve Selected Seats**.
4. A distributed lock proposal (`RESERVE_SEATS`) commits via Raft quorum consensus across the cluster.
5. The modal displays:
   - "Distributed Lock Granted"
   - Monotonic Fencing Token (e.g. `#1094`)
   - Initial 60-second lease countdown.

### Feature 2: Lease Renewal (+30s) up to 120s Ceiling
1. When the countdown reaches ~40 seconds, click **Renew (+30s)**.
2. The Raft leader extends the lease by 30 seconds.
3. The countdown reflects approximately **70 seconds remaining** (not reset to 30s).
4. The fencing token rotates monotonically to a higher sequence number.
5. Repeated renewals up to 120s total lease duration ceiling; subsequent renewals are strictly rejected.

### Feature 3: Live Seat Synchronization & Conflict Prevention
1. Open a second browser window (e.g. Incognito or separate tab) and switch customer profile to **Customer B**.
2. Notice the seat reserved by Customer A is highlighted red in real time across tabs via WebSocket synchronization.
3. If Customer B attempts to reserve the same seat, the Raft state machine immediately rejects the collision (`REJECTED_SEAT_LOCKED`).

### Feature 4: Fault Tolerance & Leader Election
1. Open [http://127.0.0.1:3000/monitor](http://127.0.0.1:3000/monitor).
2. Note the current leader (e.g., `node1`).
3. Click **Stop Node** on `node1`.
4. Observe the remaining 2 nodes initiate an election, advance term, and elect a new leader within milliseconds.
5. The Cinema Booking application automatically switches to the new leader with zero downtime.

---

## 6. Troubleshooting Commands

If any service behaves unexpectedly during preparation:

- **Check cluster status & leader:**
  ```powershell
  Invoke-RestMethod -Uri "http://127.0.0.1:9001/api/cluster/topology"
  ```
- **Check Docker container logs:**
  ```powershell
  docker compose logs --tail=50 raft-node-1
  ```
- **Run automated test suite:**
  ```powershell
  $env:PYTHONPATH="."; pytest tests/test_cinema_booking_app.py tests/test_distributed_locks.py
  ```
