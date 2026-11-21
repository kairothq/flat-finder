import build_city
import gujrera_crawl as gj

CFG = {"bbox": [22.20, 73.06, 22.42, 73.32]}
ROW = {"projectRegId": 80, "projectName": "SARVA RESIDENCY-1", "promoterName": "SARVA DEVELOPERS", "project_status": "Ongoing",
       "endDate": "10-October-2019", "regNo": "PR/GJ/VADODARA/VADODARA/Others/RAA00056/010917", "approvedOn": "01-September-2017",
       "projectType": "Residential/Group Housing", "total_est_cost_of_proj": "145682622.00",
       "pr_mobile_no": "9999999999", "pmtr_email_id": "someone@example.com", "prmtr_pan_no": "AC###9#36#"}
LOC = {"projectId": 80, "coordinates": [{"lat": "22.3461", "lang": "73.2117"}, {"lat": "22.3461", "lang": "73.2117"},
                                        {"lat": "22.3462", "lang": "73.2124"}, {"lat": "22.3465", "lang": "73.2124"}]}
DET = {"projectDetail": {"moje": "Harni", "tPNo": 1, "tPName": "harini", "totAreaOfLand": 2195.0,
                         "totCarpetAreaForProjectUnderReg": 4336.4, "projectDesc": "RESIDENTIAL APPARTMENTS ALL 2BHK",
                         "projectAddress": "NR. HARNI WATER TANK", "projectAddress2": "HARNI"}}


def test_site_ring_dedupes_and_closes():
    ring = gj.site_ring(LOC["coordinates"])
    assert ring[0] == ring[-1] == [73.2117, 22.3461]
    assert len(ring) == 4  # repeated point dropped, ring closed
    assert gj.site_ring([{"lat": "22.3", "lang": "73.2"}]) is None
    assert gj.site_ring([{"lat": None, "lang": "x"}] * 5) is None


def test_to_project_shape_contact_and_no_ids():
    p = gj.to_project(ROW, LOC, DET, CFG)
    assert p["mb_id"] == "gj80" and p["name"] == "Sarva Residency-1" and p["locality"] == "Harni"
    assert 22.346 < p["lat"] < 22.347 and 73.211 < p["lng"] < 73.213
    assert p["kind"] == "apartment" and p["acres"] == 0.54 and p["tp_scheme"] == "TP 1 Harini"
    assert p["status"] == "Not marked complete on GujRERA" and p["possession"] == "2019"
    assert p["contact"] == {"phone": "+91 9999999999", "email": "someone@example.com"}
    assert "AC###" not in repr(p)  # PAN never kept


def test_contact_cleans_or_drops_bad_values():
    assert gj.contact({"pr_mobile_no": "+91-94260 04671", "pmtr_email_id": " Sales@Builder.IN "}) == \
        {"phone": "+91 9426004671", "email": "sales@builder.in"}
    assert gj.contact({"pr_mobile_no": "123", "pmtr_email_id": "not an email"}) is None


def test_site_outside_city_is_not_a_location():
    far = {"coordinates": [{"lat": "23.0", "lang": "72.5"}, {"lat": "23.0", "lang": "72.51"}, {"lat": "23.01", "lang": "72.51"}]}
    p = gj.to_project(ROW, far, DET, CFG)
    assert p["lat"] is None and p["site_ring"] is None


def test_kind_from_source_wins_over_name():
    assert build_city.kind_of({"kind": "plot", "name": "Sarva Towers"}) == "plot"
    assert build_city.kind_of({"kind": "commercial", "config_text": "Commercial"}) == "commercial"


def test_rera_ring_used_as_site():
    s = {"id": "sgj80", "kind": "apartment", "lng": 73.212, "lat": 22.3462, "towers": None, "units": None, "acres": 0.54}
    ring = gj.site_ring(LOC["coordinates"])
    empty = build_city.Grid([], lambda b: (0, 0))
    feats, shape = build_city.shapes_for(s, None, empty, 0, ring)
    assert shape == "rera-site"
    assert feats[0]["properties"]["role"] == "site" and feats[0]["geometry"]["coordinates"] == [ring]


NAMES = gj.area_names({"Bill", "Gotri", "Sevasi", "Vadsar", "Vadodara", "Harni"})


def test_area_from_address_skips_roads_and_landmarks():
    assert gj.area_from_address("Nr. Royal Green, B/H, Bill bong high school, Vadsar", NAMES) == "Vadsar"
    assert gj.area_from_address("ZYDEX OFFICE ROAD NEW ALKAPURI", NAMES) == "New Alkapuri"
    assert gj.area_from_address("NEAR GURUKUL CHAR RASTA WAGHODIA ROAD", NAMES) == "Waghodia Road"
    assert gj.area_from_address("STAR CITY III NEAR VASNA BHAYLI CROSSING, TANDALJA SUNPHARMA ROAD", NAMES) == "Tandalja"
    assert gj.area_from_address("Bhayali TP 2, Vadodara", NAMES) == "Bhayli"  # spelling alias


def test_area_from_address_road_only_and_nothing():
    assert gj.area_from_address("SAMPATRAO COLONY, JETALPUR ROAD", NAMES) == "Jetalpur Road"
    assert gj.area_from_address("VIRSANI POLE, GHADIYALI POLE", NAMES) is None


def test_locality_order_village_then_tp_then_address():
    assert gj.locality({"moje": "Harni"}, {}, NAMES) == ("Harni", "village")
    assert gj.locality({"moje": "Vadodara", "tPName": "( Manjalpur )"}, {}, NAMES) == ("Manjalpur", "TP scheme")
    assert gj.locality({"moje": "Vadodara Kasba", "tPName": "Vadodara Kasba", "projectAddress": "Near Cross Word Circle,Alkapuri"},
                       {}, NAMES) == ("Alkapuri", "address")
    assert gj.locality({"moje": "Vadodara", "projectAddress": "GHADIYALI POLE"}, {}, NAMES) == ("Vadodara", "village")


def test_ring_with_a_stray_point_is_not_used_as_outline():
    good = [[73.2117, 22.3461], [73.2124, 22.3462], [73.2124, 22.3465], [73.2117, 22.3465], [73.2117, 22.3461]]
    ring, pt, note = gj.check_ring(good, 2195.0)
    assert ring == good and note is None
    stray = good[:3] + [[73.30, 22.40]] + good[3:]  # one point ~11 km away
    ring, pt, note = gj.check_ring(stray, 2195.0)
    assert ring is None and pt is not None and "stray" in note
    assert 73.211 < pt[0] < 73.213
    scattered = [[73.20, 22.30], [73.25, 22.33], [73.29, 22.36], [73.22, 22.39], [73.20, 22.30]]
    assert gj.check_ring(scattered, 2195.0) == (None, None, "GujRERA site map is not usable")
