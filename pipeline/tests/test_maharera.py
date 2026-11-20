import maharera

ROW = '''<div class="row shadow p-3 mb-5 bg-body rounded"> <div class="col-xl-4"> <p class="p-0"># {reg}</p>
<h4 class="title4"><strong>{name}</strong></h4> <p class="darkBlue bold ">KASHIMIRA CERAMIC PRODUCTS LLP</p>
<ul class="listingList"><li><a href="https://www.google.com/maps/search/?api=1&amp;query={lat},{lng}"> Thane </a></li></ul></div>
<div class="col-xl-4"> <div class="greyColor">Pincode</div> <p>401104</p> </div>
<div class="col-xl-4"> <div class="greyColor">District</div> <p>Thane</p> </div>
<div class="col-xl-4"> <div class="greyColor">Last Modified</div> <p>2021-09-08</p> </div>
<a href="https://maharerait.maharashtra.gov.in/public/project/view/9755" title="View Details">View Details</a></div>'''


def page(*rows):
    return "<html>" + "".join(ROW.format(**r) for r in rows) + " of 3 </html>"


def test_parse_rows_reads_every_field():
    rows = maharera.parse_rows(page({"reg": "P51800008105", "name": "Hiraco Eminence Phase 1", "lat": 19.2371877, "lng": 72.8441358},
                                    {"reg": "PC1330002602700", "name": "Haware Rise", "lat": 19.1, "lng": 72.9}))
    assert [r["reg"] for r in rows] == ["P51800008105", "PC1330002602700"]
    r = rows[0]
    assert r["name"] == "Hiraco Eminence Phase 1" and r["promoter"] == "KASHIMIRA CERAMIC PRODUCTS LLP"
    assert (r["lat"], r["lng"], r["pincode"], r["district"], r["last_modified"]) == (19.2371877, 72.8441358, "401104", "Thane", "2021-09-08")
    assert r["url"] == "https://maharerait.maharashtra.gov.in/public/project/view/9755"
    assert maharera.total_pages(page()) == 3


def test_reg_ids_splits_portal_field():
    assert maharera.reg_ids("P51800008104 / P51800008105") == {"P51800008104", "P51800008105"}
    assert maharera.reg_ids(None) == set()


def test_match_prefers_rera_number_then_name_and_distance():
    a = {"reg": "P51800008105", "name": "Hiraco Eminence Phase 1", "lat": 19.2372, "lng": 72.8441}
    b = {"reg": "P51800009999", "name": "Sunshine Heights Wing A", "lat": 19.2900, "lng": 72.8700}
    far = {"reg": "P51800001111", "name": "Sunshine Heights", "lat": 19.4000, "lng": 72.8000}
    regs, by_reg = [a, b, far], {r["reg"]: r for r in (a, b, far)}
    s = {"name": "Tanvi Eminence", "rera_id": "P51800008104 / P51800008105", "lat": 19.24, "lng": 72.85}
    assert maharera.match(s, regs, by_reg) == ([a], "rera number")
    s = {"name": "Sunshine Heights", "rera_id": None, "lat": 19.2905, "lng": 72.8702}
    assert maharera.match(s, regs, by_reg) == ([b], "name and location")  # the far one with the same name is not taken
    s = {"name": "Unknown Towers", "rera_id": None, "lat": 19.2905, "lng": 72.8702}
    assert maharera.match(s, regs, by_reg) == ([], None)


def test_relocate_uses_rera_number_then_unique_exact_name():
    box = (19.235, 72.82, 19.34, 72.91)
    a = {"reg": "P51700000053", "name": "Ostwal Paradise", "lat": 19.28, "lng": 72.87}
    b = {"reg": "P51700000054", "name": "Sai Krupa", "lat": 19.29, "lng": 72.86}
    c = {"reg": "P51700000055", "name": "Sai Krupa", "lat": 19.31, "lng": 72.84}  # same name 2+ km away: ambiguous
    regs = [a, b, c]
    by_reg = {r["reg"]: r for r in regs}
    placeholder = {"lat": 18.9582347, "lng": 72.8319514}
    assert maharera.relocate({**placeholder, "name": "Anything", "rera_id": "P51700000053"}, regs, by_reg, box)[:2] == (19.28, 72.87)
    assert maharera.relocate({**placeholder, "name": "Ostwal Paradise", "rera_id": None}, regs, by_reg, box)[:2] == (19.28, 72.87)
    assert maharera.relocate({**placeholder, "name": "Sai Krupa", "rera_id": None}, regs, by_reg, box) is None
    assert maharera.relocate({**placeholder, "name": "Ostwal", "rera_id": None}, regs, by_reg, box) is None  # subset is not enough


def test_names_must_keep_building_type_and_wing():
    regs = [{"reg": "P1", "name": "KRISHNA HEIGHTS", "lat": 19.29, "lng": 72.86},
            {"reg": "P2", "name": "Sector 2A - Wing C", "lat": 19.29, "lng": 72.86},
            {"reg": "P3", "name": "CODENAME ENDGAME - TOWER 1", "lat": 19.29, "lng": 72.86},
            {"reg": "P4", "name": "Apna Ghar Phase-II Plot-A", "lat": 19.29, "lng": 72.86}]
    by_reg = {r["reg"]: r for r in regs}
    near = {"lat": 19.2901, "lng": 72.8601, "rera_id": None}
    assert maharera.match({**near, "name": "Krishna Tower"}, regs, by_reg) == ([], None)
    assert maharera.match({**near, "name": "Sector 2A Wing A"}, regs, by_reg) == ([], None)
    assert maharera.match({**near, "name": "JP Codename Endgame"}, regs, by_reg) == ([], None)  # builder prefix not in the filing
    assert maharera.match({**near, "name": "Codename Endgame"}, regs, by_reg)[0] == [regs[2]]
    assert maharera.match({**near, "name": "Apna Ghar Phase 3"}, regs, by_reg) == ([], None)
    box = (19.235, 72.82, 19.34, 72.91)
    assert maharera.relocate({"lat": 18.95, "lng": 72.83, "rera_id": None, "name": "Krishna Tower"}, regs, by_reg, box) is None
