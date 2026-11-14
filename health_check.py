import asyncio
import json
import httpx
import psycopg2
import websockets

NODES = [
    ("node1", "http://127.0.0.1:9001", "ws://127.0.0.1:9001/ws/telemetry"),
    ("node2", "http://127.0.0.1:9002", "ws://127.0.0.1:9002/ws/telemetry"),
    ("node3", "http://127.0.0.1:9003", "ws://127.0.0.1:9003/ws/telemetry")
]

def check_cluster_topology():
    print("=== 1. RAFT CLUSTER TOPOLOGY & CONSISTENCY ===")
    for nid, url, _ in NODES:
        try:
            r = httpx.get(f"{url}/api/cluster/topology", timeout=3.0)
            d = r.json()
            role = d.get("role")
            term = d.get("current_term")
            leader = d.get("current_leader")
            commit_idx = d.get("commit_index")
            applied_idx = d.get("last_applied")
            log_idx = d.get("last_log_index")
            print(f"[{nid}] role={role:<9} term={term:<3} leader={leader:<6} commit_idx={commit_idx:<4} applied_idx={applied_idx:<4} log_idx={log_idx:<4}")
        except Exception as e:
            print(f"[{nid}] ERROR: {e}")

def check_postgres():
    print("\n=== 2. POSTGRESQL & CINEMA SEAT CONFIGURATION ===")
    try:
        conn = psycopg2.connect("postgresql://postgres:postgres@127.0.0.1:5435/cinema_db")
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM seats WHERE show_id = 'show-screen-1-prime';")
        seat_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM bookings;")
        booking_count = cur.fetchone()[0]
        cur.execute("SELECT row_label, count(*) FROM seats WHERE show_id = 'show-screen-1-prime' GROUP BY row_label ORDER BY row_label;")
        rows = cur.fetchall()
        print(f"PostgreSQL Status: HEALTHY (Port 5435)")
        print(f"Screen 1 Total Seats: {seat_count} seats (Expected: 50)")
        row_str = ", ".join([f"Row {r[0]}: {r[1]} seats" for r in rows])
        print(f"Seat Distribution: {row_str}")
        print(f"Preserved Historical Bookings: {booking_count} bookings preserved")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"PostgreSQL ERROR: {e}")

def check_cinema_api():
    print("\n=== 3. CINEMA BACKEND APIS HEALTH ===")
    for nid, url, _ in NODES:
        try:
            r_seats = httpx.get(f"{url}/api/cinema/seats/show-screen-1-prime", timeout=3.0)
            seats_len = len(r_seats.json()) if r_seats.status_code == 200 else -1
            print(f"[{nid}] GET /api/cinema/seats/show-screen-1-prime -> HTTP {r_seats.status_code} ({seats_len} seats returned)")
        except Exception as e:
            print(f"[{nid}] API ERROR: {e}")

async def check_websockets():
    print("\n=== 4. WEBSOCKET TELEMETRY CONNECTIVITY ===")
    for nid, _, ws_url in NODES:
        try:
            async with websockets.connect(ws_url) as ws:
                raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                data = json.loads(raw)
                msg_type = data.get("type")
                term = data.get("current_term")
                locks_count = len(data.get("active_locks", {}))
                print(f"[{nid}] {ws_url} -> CONNECTED (Type: {msg_type}, Term: {term}, Active Locks: {locks_count})")
        except Exception as e:
            print(f"[{nid}] {ws_url} -> ERROR: {e}")

def check_frontend():
    print("\n=== 5. FRONTEND ROUTES (PORT 3000) ===")
    for path in ["/", "/monitor"]:
        try:
            r_fe = httpx.get(f"http://127.0.0.1:3000{path}", timeout=3.0)
            print(f"Route http://127.0.0.1:3000{path} -> HTTP {r_fe.status_code} (HTML bytes: {len(r_fe.text)})")
        except Exception as e:
            print(f"Route http://127.0.0.1:3000{path} -> ERROR: {e}")

if __name__ == "__main__":
    check_cluster_topology()
    check_postgres()
    check_cinema_api()
    asyncio.run(check_websockets())
    check_frontend()
