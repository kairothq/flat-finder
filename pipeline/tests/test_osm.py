import json

import osm_fetch
import pytest


def g(*pts):
    return [{"lon": x, "lat": y} for x, y in pts]


class Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return json.dumps(self.body).encode()


def serve(monkeypatch, tmp_path, bodies):
    """Point the cache at tmp_path and answer each request with the next body."""
    asked = []
    monkeypatch.setattr(osm_fetch, "CACHE", tmp_path)
    monkeypatch.setattr(osm_fetch.time, "sleep", lambda s: None)

    def urlopen(req, **kw):
        asked.append(req.data.decode())
        return Resp(bodies[min(len(asked) - 1, len(bodies) - 1)])

    monkeypatch.setattr(osm_fetch.urllib.request, "urlopen", urlopen)
    return asked


def test_a_wider_bbox_is_fetched_instead_of_served_from_the_narrow_one(monkeypatch, tmp_path):
    narrow = {"elements": [{"id": 1}]}
    wide = {"elements": [{"id": 1}, {"id": 2}]}
    asked = serve(monkeypatch, tmp_path, [narrow, wide])
    assert osm_fetch.overpass("way[building](28,76,29,77);", "buildings") == narrow
    assert osm_fetch.overpass("way[building](27,75,30,78);", "buildings") == wide  # same name, new bbox
    assert len(asked) == 2 and len({*tmp_path.iterdir()}) == 2


def test_the_same_query_is_asked_for_once(monkeypatch, tmp_path):
    asked = serve(monkeypatch, tmp_path, [{"elements": [{"id": 1}]}])
    q = "way[building](28,76,29,77);"
    assert osm_fetch.overpass(q, "buildings") == osm_fetch.overpass(q, "buildings")
    assert len(asked) == 1


def test_a_timed_out_answer_is_not_cached_and_not_built_on(monkeypatch, tmp_path):
    timeout = {"version": 0.6, "remark": "runtime error: Query timed out in \"query\" at line 1"}
    good = {"elements": [{"id": 1}]}
    asked = serve(monkeypatch, tmp_path, [timeout, good])
    # HTTP 200 with no elements: parsing it gave an empty city and reported success
    assert osm_fetch.overpass("way[building](28,76,29,77);", "buildings") == good
    assert len(asked) == 2 and len({*tmp_path.iterdir()}) == 1  # only the good answer is on disk
    with pytest.raises(osm_fetch.Overpass):
        osm_fetch.checked(timeout)
    with pytest.raises(osm_fetch.Overpass):
        osm_fetch.checked({"version": 0.6})


def test_every_mirror_failing_stops_the_run(monkeypatch, tmp_path):
    serve(monkeypatch, tmp_path, [{"remark": "server load too high"}])
    with pytest.raises(SystemExit):
        osm_fetch.overpass("way[building](28,76,29,77);", "buildings")
    assert list(tmp_path.iterdir()) == []


def test_ring_from_relation_joins_reversed_segments():
    el = {"members": [
        {"role": "outer", "geometry": g((0, 0), (1, 0), (1, 1))},
        {"role": "outer", "geometry": g((0, 0), (0, 1), (1, 1))},  # reversed direction
        {"role": "inner", "geometry": g((0.2, 0.2), (0.3, 0.2))},
    ]}
    rings = osm_fetch.ring_from_relation(el)
    assert len(rings) == 1
    assert rings[0][0] == rings[0][-1] and len(rings[0]) == 5


def test_height_of():
    assert osm_fetch.height_of({"height": "60 m"}) == 60
    assert osm_fetch.height_of({"building:levels": "10"}) == 32
    assert osm_fetch.height_of({}) is None
