import build_city
import geo


def area(name, center, r=150):
    return {"type": "Feature", "properties": {"osm": "way/" + name, "name": name},
            "geometry": {"type": "Polygon", "coordinates": [geo.circle(center, r)]}}


def test_match_area_inside_and_by_name():
    areas = [area("Heritage One", (77.0891, 28.4027)), area("Skyon", (77.0966, 28.3995))]
    g = build_city.Grid(areas, lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
    p = {"name": "Conscient Heritage One", "lng": 77.0893, "lat": 28.4030}
    assert build_city.match_area(p, g)["properties"]["name"] == "Heritage One"
    near = {"name": "Ireo Skyon", "lng": 77.0966 + 0.0025, "lat": 28.3995}  # ~245 m east, outside
    assert build_city.match_area(near, g)["properties"]["name"] == "Skyon"
    far = {"name": "Random Homes", "lng": 77.2, "lat": 28.5}
    assert build_city.match_area(far, g) is None


def test_dedupe_merges_phases_close_by():
    a = {"name": "Heritage One", "lng": 77.0890, "lat": 28.4034, "url": "a"}
    b = {"name": "Heritage One", "lng": 77.0891, "lat": 28.4021, "url": "b"}
    c = {"name": "Heritage One", "lng": 77.2, "lat": 28.5, "url": "c"}
    out = build_city.dedupe([a, b, c])
    assert len(out) == 2 and out[0]["merged"] == ["b"]


def test_dedupe_keeps_arrival_order_and_leaves_a_wholly_generic_name_alone():
    rows = [{"name": "Heritage One", "lng": 77.0890, "lat": 28.4034, "url": "h1"},
            {"name": "DLF The Primus", "lng": 77.0500, "lat": 28.4100, "url": "p1"},
            {"name": "Heritage One", "lng": 77.0891, "lat": 28.4021, "url": "h2"},  # ~144 m from h1
            {"name": "The Towers", "lng": 77.0600, "lat": 28.4200, "url": "t1"},
            {"name": "The Towers", "lng": 77.0600, "lat": 28.4200, "url": "t2"}]
    out = build_city.dedupe(rows)
    # grouping by name must not reorder the city: the web JSON and both CSVs are written in this order
    assert [p["url"] for p in out] == ["h1", "p1", "t1", "t2"]
    assert out[0]["merged"] == ["h2"]
    # "The Towers" is generic words only, so there is no name left to match on and neither one is merged away
    assert build_city.tokens("The Towers") == set()


def test_dedupe_keeps_a_named_block_apart_from_its_neighbour():
    # real Gurugram merges: RWA Pocket B (1,100 homes) was merged into Pocket E 180 m away, and both
    # DLF Building 10 and Ultra Premium Floors Sector 22 and 23 disappeared into their neighbours
    rows = [{"name": "RWA Pocket E", "lng": 77.0860, "lat": 28.4700, "url": "e"},
            {"name": "RWA Pocket B", "lng": 77.0878, "lat": 28.4702, "url": "b"},  # ~180 m
            {"name": "DLF Building 9", "lng": 77.0920, "lat": 28.4950, "url": "b9"},
            {"name": "DLF Building 10", "lng": 77.0921, "lat": 28.4951, "url": "b10"},  # ~15 m
            {"name": "Ultra Premium Floors Sector 22", "lng": 77.0700, "lat": 28.4800, "url": "s22"},
            {"name": "Ultra Premium Floors Sector 23", "lng": 77.0701, "lat": 28.4801, "url": "s23"}]
    out = build_city.dedupe(rows)
    assert [p["url"] for p in out] == ["e", "b", "b9", "b10", "s22", "s23"]
    assert not any("merged" in p for p in out)


def test_dedupe_still_merges_a_number_written_two_ways():
    # the other half of the same rule: "II" and "2" are one mark, so these two are still one society
    rows = [{"name": "DLF Beverly Park II", "lng": 77.0920, "lat": 28.4760, "url": "r"},
            {"name": "Dlf Beverly Park 2", "lng": 77.0925, "lat": 28.4762, "url": "a"},  # ~50 m
            {"name": "DLF Beverly Park", "lng": 77.0924, "lat": 28.4761, "url": "u"}]  # unnumbered: merges either way
    out = build_city.dedupe(rows)
    assert [p["url"] for p in out] == ["r"] and out[0]["merged"] == ["a", "u"]


def test_marks_reads_only_the_part_tokens_drops():
    assert build_city.marks("RWA Pocket B") == {"b"}
    assert build_city.marks("M3M Antalya Hills Phase I") == {1}  # "m3m" is 3 chars, so it is a name token
    assert build_city.marks("Dlf Beverly Park 2") == build_city.marks("DLF Beverly Park II") == {2}
    assert build_city.marks("Heritage One") == set()  # "one" is a word here, not a phase number


def test_kind_of():
    assert build_city.kind_of({"config_text": "2, 3, 4 BHK Multistorey Apartments"}) == "apartment"
    assert build_city.kind_of({"config_text": "Residential Plot"}) == "plot"
    assert build_city.kind_of({"config_text": "4 BHK Villa"}) == "villa"


def test_neighbourhood_sized_area_is_not_a_society_site():
    big = area("DLF Phase 4", (77.08, 28.46), r=700)  # ~1.5 km2
    g = build_city.Grid([big], lambda a: geo.centroid(a["geometry"]["coordinates"][0]))
    p = {"name": "Some Apartments", "lng": 77.08, "lat": 28.46, "acres": 5}
    assert build_city.match_area(p, g) is None


def test_kind_from_unit_codes_when_text_missing():
    assert build_city.kind_of({"configs": {"units": [{"kind": "10000"}]}}) == "plot"
    assert build_city.kind_of({"configs": {"units": [{"kind": "10008"}, {"kind": "10002"}]}}) == "apartment"
    assert build_city.kind_of({}) == "apartment~"


def test_kind_from_card_type_codes():
    assert build_city.kind_of({"type_codes": ["10000"]}) == "plot"
    assert build_city.kind_of({"card_units": [{"kind": "10003", "bhk": 3, "sqft": 1900.0}]}) == "builder floor"


def test_infer_kind_from_name():
    assert build_city.kind_of({"name": "Sai Ram Apartment"}) == "apartment~"
    assert build_city.kind_of({"name": "Rzone Land Plot"}) == "plot~"
    assert build_city.kind_of({"name": "Emaar Business District 114"}) == "commercial~"
    assert build_city.kind_of({"name": "Ashiana Villas"}) == "villa~"


def test_match_verified_needs_whole_name_and_sector():
    ps = [{"mb_id": 1, "name": "M3M", "locality": "Sector 65"},
          {"mb_id": 2, "name": "M3M Heights", "locality": "Sector 65"},
          {"mb_id": 3, "name": "M3M St Andrews at SCDA", "locality": "Sector 113"},
          {"mb_id": 4, "name": "M3M St. Andrews", "locality": "Sector 65"}]
    assert build_city.match_verified({"match": ["M3M Heights"], "sector": "65"}, ps)["mb_id"] == 2
    assert build_city.match_verified({"match": ["M3M St Andrews"], "sector": "65"}, ps)["mb_id"] == 4
    assert build_city.match_verified({"match": ["M3M Heights"], "sector": "65"}, ps, taken={2}) is None
