from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from backend.db.session import AsyncSessionLocal, init_db
from backend.db.models import Movie, Show, Seat, RaftAppliedProgress

async def seed_cinema_data():
    """
    Seed sample movie, showtime, and exactly 50 seats:
    Rows A, B, C, D, E with 10 seats each (A1-A10, B1-B10, C1-C10, D1-D10, E1-E10).
    Idempotent: Does not recreate seats if already present, preserving existing reservations.
    """
    await init_db()

    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Initialize Raft applied progress tracker if not present
            stmt_p = select(RaftAppliedProgress).where(RaftAppliedProgress.cluster_id == "cluster")
            res_p = await session.execute(stmt_p)
            if not res_p.scalar_one_or_none():
                session.add(RaftAppliedProgress(cluster_id="cluster", last_applied_index=0, last_applied_term=0))

            # Check or create movie
            stmt_m = select(Movie).where(Movie.id == "movie-interstellar")
            res_m = await session.execute(stmt_m)
            movie = res_m.scalar_one_or_none()
            if not movie:
                movie = Movie(
                    id="movie-interstellar",
                    title="Interstellar",
                    duration_minutes=169,
                    genre="Sci-Fi / Adventure",
                    description="A team of explorers travel through a wormhole in space in an attempt to ensure humanity's survival."
                )
                session.add(movie)
                await session.flush()

            # Check or create show
            stmt_s = select(Show).where(Show.id == "show-screen-1-prime")
            res_s = await session.execute(stmt_s)
            show = res_s.scalar_one_or_none()
            if not show:
                now = datetime.now(timezone.utc)
                show = Show(
                    id="show-screen-1-prime",
                    movie_id="movie-interstellar",
                    screen_name="IMAX Laser Theater 1",
                    start_time=now + timedelta(hours=2),
                    base_price=18.50
                )
                session.add(show)
                await session.flush()

            # Ensure all 50 seats (A1-E10) exist without modifying existing rows
            rows = ["A", "B", "C", "D", "E"]
            for row in rows:
                for idx in range(1, 11):
                    seat_id = f"seat-{row}{idx}"
                    stmt_seat = select(Seat).where(Seat.id == seat_id)
                    res_seat = await session.execute(stmt_seat)
                    existing_seat = res_seat.scalar_one_or_none()
                    if not existing_seat:
                        seat = Seat(
                            id=seat_id,
                            show_id="show-screen-1-prime",
                            seat_code=f"{row}{idx}",
                            row_label=row,
                            seat_index=idx,
                            seat_tier="VIP" if row in ["A", "B"] else "STANDARD",
                            current_status="AVAILABLE",
                            last_fencing_token=0
                        )
                        session.add(seat)
