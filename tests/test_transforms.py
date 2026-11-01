from firmable.ingest import transforms as T
from firmable.ontology import abn_valid, acn_valid


def run(steps, v):
    return T.apply(steps, v)


def test_checksums():
    assert abn_valid("51824753556")          # ATO's published example
    assert not abn_valid("51824753557")
    assert acn_valid("000000019") and acn_valid("090444714")
    assert not acn_valid("090444715")


def test_abn_acn_reject_wrong_kind():
    assert run([{"op": "abn"}], "51 824 753 556") == "51824753556"
    assert run([{"op": "abn"}], "ACN 090444714") is None      # 9 digits is not an ABN
    assert run([{"op": "acn"}], "ACN 090444714") == "090444714"
    assert run([{"op": "acn"}], "51824753556") is None        # never derive ACN from ABN


def test_dates_and_enums():
    assert run([{"op": "parse_date", "args": {"formats": ["%d/%m/%Y"]}}], "04/10/2010") == "2010-10-04"
    assert run([{"op": "parse_date", "args": {"formats": ["%d/%m/%Y"]}}], "2010-10-04") is None
    m = {"op": "map_values", "args": {"mapping": {"APPR": "active"}}}
    assert run([m], "appr") == "active" and run([m], "XXXX") is None


def test_address_parts():
    assert run([{"op": "au_postcode"}], "BIRTINYA, QLD, 4575") == "4575"
    assert run([{"op": "au_state"}], "BIRTINYA, QLD, 4575") == "QLD"
    assert run([{"op": "au_state"}], "Level 2, Sydney New South Wales") == "NSW"
    assert run([{"op": "pick_part", "args": {"sep": ",", "index": 0}}], "BIRTINYA, QLD, 4575") == "BIRTINYA"


def test_entity_type_from_name_does_not_guess():
    f = [{"op": "entity_type_from_name"}]
    assert run(f, "1205 PTY LTD") == "company"
    assert run(f, "NOVARTIS PHARMACEUTICALS AUST P/L") == "company"
    assert run(f, "Smith Family Trust") == "trust"
    assert run(f, "Shane Anthony Rolfe") is None             # a person: no guess


def test_split_makes_multiple_values():
    assert run([{"op": "split", "args": {"sep": r";|\|"}}], "A Cafe; B Bar|C") == ["A Cafe", "B Bar", "C"]


def test_zfill_restores_leading_zeros():
    assert run([{"op": "zfill", "args": {"width": 9}}, {"op": "acn"}], "90444714") == "090444714"
    assert run([{"op": "zfill", "args": {"width": 9}}], "ACN 090 444 714") == "090444714"
