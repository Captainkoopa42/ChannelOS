from __future__ import annotations

import pytest

from channelos.ad_catalog import (
    AdCatalogStore, AdCatalogValidationError, AdCollection, BreakProfile,
    ChannelAdAssignment,
)


class Library:
    def __init__(self, assets):
        self.assets = assets

    def online_locations_for_assets(self, asset_ids):
        return {key: [self.assets[key]] for key in asset_ids if key in self.assets}


def test_catalog_profile_assignment_persist_and_resolve(tmp_path):
    path = tmp_path / "ads.sqlite"
    store = AdCatalogStore(path)
    store.save_collection(AdCollection("summer", "Summer", ("a", "b")))
    store.save_profile(BreakProfile("default", "Default", {
        "enabled": True, "strategy": "sequential", "interval_seconds": 600,
        "timing_policy": "smoosh", "transition_behavior": "fade", "triggers": ["interval"],
    }))
    store.assign_channel(ChannelAdAssignment(7, "summer", "default", {"priority": 10}))
    result = AdCatalogStore(path).resolve_channel(7, Library({"a": "A", "b": "B"}))
    assert result.settings["strategy"] == "sequential"
    assert result.settings["priority"] == 10
    assert result.ad_media == ("A", "B")


def test_profile_defaults_and_channel_override(tmp_path):
    store = AdCatalogStore(tmp_path / "ads.sqlite")
    store.save_profile(BreakProfile("p", "Profile", {"enabled": True, "priority": 1, "strategy": "largest"}))
    store.assign_channel(ChannelAdAssignment(1, profile_id="p", overrides={"priority": 9}))
    result = store.resolve_channel(1, Library({}))
    assert result.settings["strategy"] == "largest" and result.settings["priority"] == 9


def test_duplicate_and_empty_collection_assets_rejected():
    with pytest.raises(AdCatalogValidationError, match="duplicate"):
        AdCollection("x", "X", ("a", "a"))
    with pytest.raises(AdCatalogValidationError, match="at least one"):
        AdCollection("x", "X", ())


def test_unknown_references_rejected(tmp_path):
    store = AdCatalogStore(tmp_path / "ads.sqlite")
    with pytest.raises(AdCatalogValidationError, match="unknown collection"):
        store.assign_channel(ChannelAdAssignment(1, collection_id="missing"))


def test_offline_asset_is_reported(tmp_path):
    store = AdCatalogStore(tmp_path / "ads.sqlite")
    store.save_collection(AdCollection("x", "X", ("offline",)))
    store.save_profile(BreakProfile("p", "P", {"enabled": True}))
    store.assign_channel(ChannelAdAssignment(1, "x", "p"))
    with pytest.raises(AdCatalogValidationError, match="offline"):
        store.resolve_channel(1, Library({}))


def test_reference_does_not_enable_legacy_channel(tmp_path):
    store = AdCatalogStore(tmp_path / "ads.sqlite")
    store.save_collection(AdCollection("x", "X", ("a",)))
    store.assign_channel(ChannelAdAssignment(1, collection_id="x"))
    result = store.resolve_channel(1, Library({"a": "A"}))
    assert result.settings["enabled"] is False and result.ad_media == ()


def test_channels_are_independent(tmp_path):
    store = AdCatalogStore(tmp_path / "ads.sqlite")
    store.save_collection(AdCollection("a", "A", ("asset-a",)))
    store.save_collection(AdCollection("b", "B", ("asset-b",)))
    store.save_profile(BreakProfile("p1", "P1", {"enabled": True, "priority": 1}))
    store.save_profile(BreakProfile("p2", "P2", {"enabled": True, "priority": 2}))
    store.assign_channel(ChannelAdAssignment(1, "a", "p1"))
    store.assign_channel(ChannelAdAssignment(2, "b", "p2"))
    library = Library({"asset-a": "A", "asset-b": "B"})
    one, two = store.resolve_channel(1, library), store.resolve_channel(2, library)
    assert one.ad_media == ("A",) and two.ad_media == ("B",)
    assert one.settings["priority"] == 1 and two.settings["priority"] == 2
