import psycopg2
import json
import httpx
from datetime import datetime, timezone

def inspect():
    print("=== 1. CLUSTER TOPOLOGY ===")
    for p in [9001, 9002, 9003]:
        try:
            r = httpx.get(f"http://127.0.0.1:{p}/api/cluster/topology", timeout=2.0)
            d = r.json()
            nid = d.get("node_id")
            role = d.get("role")
            leader = d.get("current_leader")
            term = d.get("current_term")
            commit = d.get("commit_index")
            print(f"Port {p} ({nid}): role={role} leader={leader} term={term} commit_index={commit}")
        except Exception as e:
            print(f"Port {p}: {e}")

    print("\n=== 2. ACTIVE STATE MACHINE BOOKINGS & LOCKS ===")
    for p in [9001, 9002, 9003]:
        try:
            r = httpx.get(f"http://127.0.0.1:{p}/api/cluster/topology", timeout=2.0)
            d = r.json()
            sm = d.get("state_machine", {})
            print(f"Port {p} SM: active_locks_count={sm.get('active_locks_count')} bookings_count={sm.get('bookings_count')}")
            if sm.get("seat_locks"):
                print(f"   Seat Locks: {sm.get('seat_locks')}")
            if sm.get("bookings"):
                for bid, binfo in sm.get("bookings").items():
                    print(f"   Booking {bid}: status={binfo.get('status')} seats={binfo.get('seat_ids')} owner={binfo.get('owner_id')} token={binfo.get('fencing_token')} created_utc={binfo.get('created_at_utc')} exp_utc={binfo.get('expires_at_utc')}")
            if sm.get("fencing_audit_sample"):
                print("   Fencing Audit Sample:")
                for item in sm.get("fencing_audit_sample")[-5:]:
                    print(f"     {item}")
            break # all nodes have same state machine state
        except Exception as e:
            print(f"Error reading state machines: {e}")

    print("\n=== 3. POSTGRESQL RECORDS ===")
    try:
        conn = psycopg2.connect("postgresql://postgres:postgres@127.0.0.1:5435/cinema_db")
        cur = conn.cursor()
        cur.execute("SELECT id, booking_reference, owner_id, status, fencing_token, created_at, expires_at FROM bookings ORDER BY created_at DESC LIMIT 6;")
        rows = cur.fetchall()
        for row in rows:
            print(f"DB Booking: id={row[0]} ref={row[1]} owner={row[2]} status={row[3]} token={row[4]} created={row[5]} expires={row[6]}")

        cur.execute("SELECT id, booking_id, seat_id, fencing_token FROM booking_seats ORDER BY fencing_token DESC LIMIT 6;")
        bs_rows = cur.fetchall()
        print("\nBooking Seats allocations:")
        for bs in bs_rows:
            print(f"   id={bs[0]} seat={bs[2]} booking_id={bs[1]} token={bs[3]}")

        cur.execute("SELECT id, resource_id, proposed_token, accepted_token, decision, created_at FROM fencing_audit_logs ORDER BY id DESC LIMIT 10;")
        audit_rows = cur.fetchall()
        print("\nFencing Audit Logs:")
        for a in audit_rows:
            print(f"   id={a[0]} res={a[1]} proposed={a[2]} accepted={a[3]} decision={a[4]} time={a[5]}")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

if __name__ == "__main__":
    inspect()
