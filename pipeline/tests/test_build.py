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


def test_in_city_uses_the_configured_bbox():
    gurgaon = {"bbox": [28.33, 76.88, 28.55, 77.16]}
    hyderabad = {"bbox": [17.20, 78.20, 17.65, 78.70]}
    assert build_city.in_city({"lat": 28.4027, "lng": 77.0891}, gurgaon)
    assert build_city.in_city({"lat": 17.4401, "lng": 78.3489}, hyderabad)  # Gachibowli
    # every city used to be filtered against Gurugram's box, so no other city had any project on the map
    assert not build_city.in_city({"lat": 17.4401, "lng": 78.3489}, gurgaon)
    assert not build_city.in_city({"lat": 28.4027, "lng": 77.0891}, hyderabad)
    assert not build_city.in_city({"lat": None, "lng": None}, gurgaon)


def test_in_city_pad_keeps_the_surrounding_district():
    gurgaon = {"bbox": [28.33, 76.88, 28.55, 77.16]}
    assert build_city.in_city({"lat": 28.1901, "lng": 77.1003}, gurgaon)  # Sohna, outside the bbox
    assert not build_city.in_city({"lat": 27.90, "lng": 77.1003}, gurgaon)  # well beyond the pad


def test_city_tokens_never_count_towards_a_name_match():
    assert "gurugram" in build_city.city_tokens("gurgaon", {"name": "Gurugram"})
    assert "gurgaon" in build_city.city_tokens("gurgaon", {"name": "Gurugram"})
    cfg = {"name": "Hyderabad", "tokens": ["Secunderabad", "HITEC"]}
    assert {"hyderabad", "secunderabad", "hitec"} <= build_city.city_tokens("hyderabad", cfg)


def test_plan_urls_do_not_depend_on_string_hashing():
    ai = {"https://img/b.jpg": {}, "https://img/a.jpg": {}}
    ocr = {"https://img/c.jpg": {}, "https://img/a.jpg": {}}
    assert build_city.plan_urls(ai, ocr) == ["https://img/a.jpg", "https://img/b.jpg", "https://img/c.jpg"]
    # the union used to be iterated as a set, so a rebuild reordered unit_types and churned the data files
    assert build_city.plan_urls(ocr, ai) == build_city.plan_urls(ai, ocr)
    assert build_city.plan_urls({}, {}) == []


def test_sources_credit_the_portal_only_when_it_supplied_a_page(tmp_path):
    crawled = [{"url": "https://www.magicbricks.com/propertyDetails/x"}]
    seeded = [{"url": "https://www.openstreetmap.org/way/245966543"}, {"url": None}]
    cfg = {"name": "Hyderabad"}
    assert build_city.sources_for("hyderabad", cfg, tmp_path, crawled)[0] == "Magicbricks project pages"
    # a seed-built city has never been crawled, so naming the portal would claim a provenance it does not have
    assert build_city.sources_for("hyderabad", cfg, tmp_path, seeded) == ["OpenStreetMap contributors"]


def test_sources_name_rera_only_with_the_file_to_back_it(tmp_path):
    cfg = {"name": "Gurugram", "rera": "HRERA Gurugram"}
    assert "HRERA Gurugram" not in build_city.sources_for("gurgaon", cfg, tmp_path)
    (tmp_path / "gurgaon-hrera.json").write_text("[]")
    assert "HRERA Gurugram" in build_city.sources_for("gurgaon", cfg, tmp_path)
    # Hyderabad has no Telangana RERA script, so it must not inherit Haryana's line
    assert build_city.sources_for("hyderabad", {"name": "Hyderabad"}, tmp_path) == ["OpenStreetMap contributors"]


def test_match_verified_needs_whole_name_and_sector():
    ps = [{"mb_id": 1, "name": "M3M", "locality": "Sector 65"},
          {"mb_id": 2, "name": "M3M Heights", "locality": "Sector 65"},
          {"mb_id": 3, "name": "M3M St Andrews at SCDA", "locality": "Sector 113"},
          {"mb_id": 4, "name": "M3M St. Andrews", "locality": "Sector 65"}]
    assert build_city.match_verified({"match": ["M3M Heights"], "sector": "65"}, ps)["mb_id"] == 2
    assert build_city.match_verified({"match": ["M3M St Andrews"], "sector": "65"}, ps)["mb_id"] == 4
    assert build_city.match_verified({"match": ["M3M Heights"], "sector": "65"}, ps, taken={2}) is None
