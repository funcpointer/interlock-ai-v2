"""Sprint 5b — coupled-effect family map + claim lookup tests."""

from __future__ import annotations


def test_coupled_families_for_impedance_returns_dependents() -> None:
    from interlock.detect.coupled import coupled_families_for
    out = coupled_families_for("impedance_pct")
    assert "fault_current_a" in out
    assert "relay_pickup_a" in out


def test_coupled_families_for_unknown_returns_empty() -> None:
    from interlock.detect.coupled import coupled_families_for
    assert coupled_families_for("nonexistent_family") == []


def test_coupled_families_for_none_returns_empty() -> None:
    from interlock.detect.coupled import coupled_families_for
    assert coupled_families_for(None) == []


def test_coupled_families_returned_list_is_copy() -> None:
    """Caller mutations must not affect the static map."""
    from interlock.detect.coupled import COUPLED_FAMILIES, coupled_families_for
    out = coupled_families_for("impedance_pct")
    out.append("HACKED")
    fresh = coupled_families_for("impedance_pct")
    assert "HACKED" not in fresh
    assert "HACKED" not in COUPLED_FAMILIES["impedance_pct"]


def test_coupled_families_covers_canonical_seed_families() -> None:
    """Every parameter family the seed clauses.yaml registers as
    applicable_families must have a coupled-effect entry (or explicit
    omission). This is a curation-discipline test."""
    from interlock.detect.coupled import COUPLED_FAMILIES
    canonical = {
        "impedance_pct", "fault_current_a", "fault_current_ka",
        "transformer_rating_va", "voltage_v", "voltage_kv",
        "motor_fla_a", "relay_pickup_a", "fuse_amps",
        "breaker_interrupting_ka",
    }
    missing = canonical - set(COUPLED_FAMILIES)
    assert not missing, f"missing coupled entries for: {missing}"


def test_coupled_families_is_transitive_for_primary_pairs() -> None:
    """If relay_pickup_a is listed as a dependent of impedance_pct, then
    relay_pickup_a itself should have entries in the map (the graph is
    walkable past the first hop)."""
    from interlock.detect.coupled import COUPLED_FAMILIES
    # Pick one canonical first-hop pair.
    first_hop = COUPLED_FAMILIES["impedance_pct"]
    assert "relay_pickup_a" in first_hop
    # Now relay_pickup_a must itself be a key.
    assert "relay_pickup_a" in COUPLED_FAMILIES
    second_hop = COUPLED_FAMILIES["relay_pickup_a"]
    assert isinstance(second_hop, list)
    assert len(second_hop) > 0


def test_coupled_claims_for_none_family_returns_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """No family → no claims, no store query."""
    from interlock.detect import coupled as c
    spy_called = {"n": 0}

    def _spy(_attr: str):  # type: ignore[no-untyped-def]
        spy_called["n"] += 1
        return []

    monkeypatch.setattr(c, "claims_for_attribute", _spy)
    assert c.coupled_claims_for(None) == []
    assert spy_called["n"] == 0


def test_coupled_claims_for_returns_persisted_matches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """When the store has a persisted claim matching a dependent family,
    coupled_claims_for() returns it."""
    from interlock.detect import coupled as c
    from interlock.extract.entities import Claim, Entity
    from interlock.extract.parameters import ParameterRecord

    rec = ParameterRecord(
        doc_id="d", page=1, bbox=(0, 0, 100, 10), section=None,
        span_text="2400 A", name="fault_current_a", raw_value="2400 A",
        normalized_magnitude=2400.0, normalized_unit="ampere",
    )
    fake_entity = Entity(id="xfmr_001", type="transformer", label="XFMR-001")
    fake_claim = Claim(
        entity=fake_entity,
        attribute="fault_current_a",
        raw_value="2400 A",
        source_record=rec,
    )

    def _by_attr(attr: str):  # type: ignore[no-untyped-def]
        if attr == "fault_current_a":
            return [fake_claim]
        return []

    monkeypatch.setattr(c, "claims_for_attribute", _by_attr)
    out = c.coupled_claims_for("impedance_pct")
    assert len(out) >= 1
    assert any(cl.attribute == "fault_current_a" for cl in out)


def test_coupled_claims_for_empty_store_returns_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Empty store → empty list, no exception."""
    from interlock.detect import coupled as c
    monkeypatch.setattr(c, "claims_for_attribute", lambda _attr: [])
    assert c.coupled_claims_for("impedance_pct") == []


def test_coupled_claims_for_handles_store_exception(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Store query raises → silent skip per-family; final result empty."""
    from interlock.detect import coupled as c

    def _boom(_attr: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("store unreachable")

    monkeypatch.setattr(c, "claims_for_attribute", _boom)
    assert c.coupled_claims_for("impedance_pct") == []
