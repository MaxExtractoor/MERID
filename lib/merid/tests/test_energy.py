from merid_core import create_energy


def test_create_energy_structure():
    e = create_energy("srcA", "payloadX")
    assert isinstance(e, dict)
    assert e["source"] == "srcA"
    assert e["payload"] == "payloadX"
    assert "meta" in e
