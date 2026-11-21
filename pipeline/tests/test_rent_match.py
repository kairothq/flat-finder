import rent_match as rm

P = [{"name": "Nilamber Bellissimo Iii", "locality": "Bhayli", "lat": 22.2830, "lng": 73.1310},
     {"name": "Nilamber Bellissimo Ii", "locality": "Bhayli", "lat": 22.2840, "lng": 73.1320},
     {"name": "Darshanam Clublife", "locality": "Gorva", "lat": 22.3300, "lng": 73.1500},
     {"name": "Omkar Residency", "locality": "Koyli", "lat": 22.3600, "lng": 73.1000},
     {"name": "Sharnam", "locality": "Bapod", "lat": 22.3100, "lng": 73.2400}]


def L(society, lat=None, lng=None, locality=None, **kw):
    base = {"society": society, "lat": lat, "lng": lng, "locality": locality, "bhk": 2, "price": 18000, "sqft": 1200,
            "floor": "3", "furnished": "Semi-Furnished", "posted": "2026-11-20", "posted_by": "Owner", "tenants": "Family",
            "url": "https://www.magicbricks.com/x", "kind": "Apartment", "mb_society_id": "9"}
    return {**base, **kw}


def test_phase_and_spelling():
    m = rm.Matcher([dict(p) for p in P])
    p, _ = m.match(L("Nilamber Group  Bellissimo 3", 22.2832, 73.1309))
    assert p["name"] == "Nilamber Bellissimo Iii"
    assert m.match(L("Nilamber Bellissimo", 22.2832, 73.1309))[0]["name"] == "Nilamber Bellissimo Iii"  # its map point picks the phase
    assert m.match(L("Nilamber Bellissimo", 22.2900, 73.1400)) == (None, "phase unclear")
    assert m.match(L("Nilamber Bellissimo", locality="Bhayli")) == (None, "phase unclear")
    assert m.match(L("Darshanam Club Life", 22.3301, 73.1502))[0]["name"] == "Darshanam Clublife"


def test_no_match_on_shared_word_or_far_one_word_name():
    m = rm.Matcher([dict(p) for p in P])
    assert m.match(L("Omkar Green", 22.3601, 73.1001))[0] is None
    assert m.match(L("Sharnam Villa", 22.3100, 73.2537))[0] is None  # ~1.4 km
    assert m.match(L("Sharnam Villa", 22.3101, 73.2401))[0]["name"] == "Sharnam"


def test_attach_reposts_and_rental_only():
    projects = [dict(p) for p in P]
    ls = [L("Darshanam Club Life", 22.3301, 73.1502), L("Darshanam Club Life", 22.3301, 73.1502),  # repost
          L("Darshanam Club Life", 22.3301, 73.1502, price=21000, tenants="Bachelors"),
          L("Shangri La", 22.3200, 73.1600, mb_society_id="77"), L(None)]
    extra, counts = rm.attach(projects, ls)
    club = next(p for p in projects if p["name"] == "Darshanam Clublife")
    assert club["rent_count"] == 2 and club["rent_tenants"] == {"Family": 1, "Bachelors": 1}
    assert [e["name"] for e in extra] == ["Shangri La"] and extra[0]["mb_id"] == "mbs77"
    assert counts["no society named"] == 1


def test_poster_shows_owner_initial_and_agent_firm():
    import mb_rent
    assert mb_rent.poster({"userType": "Owner", "oname": "RAKESH kumar SHAH"}) == "R. Shah"
    assert mb_rent.poster({"userType": "Owner", "oname": "Prisha"}) == "Prisha"
    assert mb_rent.poster({"userType": "Agent", "oname": "Amit", "caCompNameD": "SHREE REALTY"}) == "Shree Realty"


def test_listing_url_uses_property_details_path():
    import mb_rent
    r = {"encId": "x", "price": 18000, "url": "2-BHK-1344-Sq-ft-FOR-Rent-in-Vadodara&id=4d42", "seoURL": "propertyDetails-2-BHK&id=BQ7"}
    assert mb_rent.to_listing(r)["url"] == "https://www.magicbricks.com/propertyDetails/2-BHK-1344-Sq-ft-FOR-Rent-in-Vadodara&id=4d42"
