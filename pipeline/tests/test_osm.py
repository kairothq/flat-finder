import osm_fetch


def g(*pts):
    return [{"lon": x, "lat": y} for x, y in pts]


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


def test_transit_features_kinds_status_and_line_names():
    import osm_fetch
    g = [{"lat": 19.28, "lon": 72.86}, {"lat": 19.29, "lon": 72.87}]
    data = {"elements": [
        {"type": "way", "id": 1, "tags": {"railway": "subway"}, "geometry": g},
        {"type": "way", "id": 2, "tags": {"railway": "construction", "construction": "subway", "name": "Line 10"}, "geometry": g},
        {"type": "way", "id": 3, "tags": {"railway": "rail"}, "geometry": g},
        {"type": "way", "id": 4, "tags": {"railway": "construction", "construction": "road"}, "geometry": g},  # not transit
        {"type": "relation", "id": 9, "tags": {"route": "train", "name": "Rajdhani Express", "colour": "#ff0000"}, "members": [{"type": "way", "ref": 1}, {"type": "way", "ref": 3}]},
        {"type": "relation", "id": 10, "tags": {"route": "subway", "name": "Line 9 (Dahisar (East) → Kashigaon)", "colour": "#e53935"}, "members": [{"type": "way", "ref": 1}]},
    ]}
    f = {x["properties"]["name"]: x["properties"] for x in osm_fetch.transit_features(data)}
    assert set(f) == {"Line 9", "Line 10", "Rajdhani Express"}
    assert f["Line 9"] == {"kind": "metro", "status": "open", "name": "Line 9", "ref": None, "colour": "#e53935"}  # metro route wins
    assert f["Line 10"]["kind"] == "metro" and f["Line 10"]["status"] == "construction"
    assert f["Rajdhani Express"]["kind"] == "rail"
