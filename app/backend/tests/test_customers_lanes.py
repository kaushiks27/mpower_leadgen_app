"""S-MS1 multi-source lane adapters — output mappers proven against the REAL
sample record from each actor's doc (verified live, see smoke/RESULTS.md), and
defensive against missing/odd-typed keys. Pure (no network)."""

from __future__ import annotations

from app.customers import lanes

SAMPLES = {
    "maps": {"title": "Drone Amplified", "website": "http://droneamplified.com/",
             "phone": "(531) 333-2828", "countryCode": "US", "categoryName": "Manufacturer",
             "url": "https://www.google.com/maps/place/x"},
    "linkedin": {"name": "AirSight", "website": "http://airsight.com",
                 "phone": {"number": "866-618-2267", "extension": None},
                 "locations": [{"parsed": {"country": "United States"}}],
                 "linkedinUrl": "https://www.linkedin.com/company/airsight/"},
    "indiamart": {"company_name": "Enestock Private Limited", "product_name": "Drone Battery",
                  "phone": "7949220146", "city": "Mumbai", "state": "Maharashtra",
                  "gst_number": "27AAAA0000A1Z5", "catalog_url": "https://www.indiamart.com/enestock/"},
    "thomasnet": {"name": "Advance Energy Inc./Thunder Power RC", "type": "Manufacturer",
                  "primaryPhone": "(702) 228-8883", "website": "https://www.thunderpowerrc.com",
                  "address": {"city": "Las Vegas", "state": "NV"}, "sourceUrl": "https://thomasnet.com/x"},
    "europages": {"name": "Smart Battery Solutions GmbH", "website": "https://smart-battery-solutions.de",
                  "phone": "+4960279908130", "email": None, "country": "Germany", "country_code": "DE",
                  "supplier_type": "Manufacturer", "source_url": "https://europages.com/x"},
    "wlw": {"name": "VOLTRONIC Vertriebs- & Service GmbH", "website": "https://voltronic.de",
            "phone": "+492181495260", "email": "info@voltronic.de", "country": "DE",
            "supplier_type": "Hersteller", "detail_url": "https://wlw.de/firma/voltronic"},
}

# (name, website-present, domain, phone-present, email-present)
EXPECT = {
    "maps":      ("Drone Amplified", True, "droneamplified.com", True, False),
    "linkedin":  ("AirSight", True, "airsight.com", True, False),
    "indiamart": ("Enestock Private Limited", False, None, True, False),
    "thomasnet": ("Advance Energy Inc./Thunder Power RC", True, "thunderpowerrc.com", True, False),
    "europages": ("Smart Battery Solutions GmbH", True, "smart-battery-solutions.de", True, False),
    "wlw":       ("VOLTRONIC Vertriebs- & Service GmbH", True, "voltronic.de", True, True),
}


def test_final_lane_set_is_six_no_kompass_no_mic():
    assert set(lanes.LANES) == {"maps", "linkedin", "indiamart", "thomasnet", "europages", "wlw"}
    assert "kompass" not in lanes.LANES and "mic" not in lanes.LANES


def test_each_lane_maps_its_doc_sample():
    for lane, sample in SAMPLES.items():
        c = lanes.map_items(lane, [sample])[0]
        name, has_web, domain, has_phone, has_email = EXPECT[lane]
        assert c["name"] == name, lane
        assert (c["website"] is not None) == has_web, lane
        assert c["domain"] == domain, lane
        assert (c["phone"] is not None) == has_phone, lane
        assert (c["email"] is not None) == has_email, lane
        assert c["discovery_source"] == lane
        assert c["category"] is None and c["ctype"] is None  # classifier fills these
        assert c["source_url"], lane


def test_linkedin_phone_dict_reduced_to_string():
    c = lanes.map_items("linkedin", [SAMPLES["linkedin"]])[0]
    assert c["phone"] == "866-618-2267"  # not the raw {number,...} dict


def test_marketplace_lanes_have_no_domain():
    for lane in ("indiamart",):
        c = lanes.map_items(lane, [SAMPLES[lane]])[0]
        assert c["website"] is None and c["domain"] is None


def test_empty_and_odd_typed_keys_never_raise():
    for lane in lanes.LANES:
        assert lanes.map_items(lane, []) == []
        c = lanes.map_items(lane, [{}])[0]
        assert c["name"] is None and c["discovery_source"] == lane
        lanes.map_items(lane, [{"name": None, "website": 123, "locations": "oops", "phone": []}])


def test_build_input_keys_proxy_and_caps():
    qs = ["drone battery manufacturer", "UAV battery supplier"]
    assert lanes.build_input("maps", qs, "India", 50)["searchStringsArray"] == qs
    assert lanes.build_input("indiamart", qs, "Maharashtra", 999)["maxResultsPerQuery"] == 200
    assert lanes.build_input("linkedin", qs, None, 50)["searchQuery"] == qs[0]
    assert lanes.build_input("thomasnet", qs, "CA", 50)["query"] == qs[0]
    assert lanes.build_input("europages", qs, "FR", 50)["searchQuery"] == qs[0]
    assert lanes.build_input("wlw", qs, "DE", 50)["keyword"] == qs[0]
    # residential proxy ONLY for thomasnet
    assert "proxyConfiguration" in lanes.build_input("thomasnet", qs, "NA", 10)
    assert "proxyConfiguration" not in lanes.build_input("europages", qs, "FR", 10)
