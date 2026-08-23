import pytest

from harzplan import rank

TIME = {
    "walk_speed_kmh": 5.0,
    "climb_min_per_100m": 10.0,
    "gentle_descent_min_per_300m": -10.0,
}


def test_walk_minutes_naismith_with_langmuir_descent():
    # 10 km at 5 km/h = 120 min, +30 min for 300 m up, -10 min for 300 m down
    assert rank.walk_minutes(10.0, 300.0, TIME) == pytest.approx(140.0)


def test_osrm_table_url_puts_home_first_as_source():
    url = rank.osrm_table_url(
        "https://router.project-osrm.org",
        [(10.335800, 51.808100), (10.500000, 51.900000)],
    )
    assert url == (
        "https://router.project-osrm.org/table/v1/driving/"
        "10.335800,51.808100;10.500000,51.900000"
        "?sources=0&annotations=duration,distance"
    )


def test_rank_trips_orders_by_drive_time_and_numbers_them():
    trips = [
        {"stamps": [9], "drive_min": 30.0},
        {"stamps": [1], "drive_min": 10.0},
        {"stamps": [5], "drive_min": 20.0},
    ]
    ranked = rank.rank_trips(trips)
    assert [t["stamps"][0] for t in ranked] == [1, 5, 9]
    assert [t["trip"] for t in ranked] == [1, 2, 3]


def test_stamps_in_first_n_trips():
    trips = [{"stamps": [1, 2, 3]}, {"stamps": [4]}, {"stamps": [5, 6]}]
    assert rank.stamps_in_first_n(trips, 2) == 4
    assert rank.stamps_in_first_n(trips, 10) == 6


def test_rank_trips_can_continue_numbering_after_finished_trips():
    trips = [{"stamps": [9], "drive_min": 30.0}, {"stamps": [1], "drive_min": 10.0}]
    ranked = rank.rank_trips(trips, start=3)
    assert [t["trip"] for t in ranked] == [3, 4]
