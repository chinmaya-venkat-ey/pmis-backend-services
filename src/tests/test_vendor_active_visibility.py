"""Vendor active/inactive visibility regression.

Tester report: PATCHing a vendor's ``active`` flag from True to False
"didn't reflect" — the vendor disappeared from the list. Root cause
was the legacy ``GET /api/v3/vendors`` filter only returning
``active = True`` rows, so deactivating a vendor effectively hid it.

The fix:
  - ``GET /api/v3/vendors`` (and the master_data delegate) default to
    showing all live (non-soft-deleted) vendors, active and inactive
    alike. The FE management view sees the toggle on every row.
  - ``?active_only=true`` opts back into the legacy picker behaviour
    (FE dropdowns that only want active vendors).

Soft-deleted rows are still always hidden — same rule as before.
"""
from uuid import uuid4


def _vid_in(listing, vendor_id):
    return vendor_id in {item["id"] for item in listing["_embedded"]["elements"]}


class TestVendorActiveVisibility:
    def test_patch_active_false_persists_and_stays_visible(
        self, client, admin_headers,
    ):
        v = client.post(
            "/api/v3/vendors/create",
            headers=admin_headers,
            json={"name": f"Vis {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
        ).json()["data"]
        vid = v["id"]
        assert v["active"] is True

        # PATCH active=false (the FE payload pattern from the bug report).
        r = client.patch(
            f"/api/v3/vendors/{vid}",
            headers=admin_headers,
            json={"active": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["active"] is False

        # Direct GET — row reflects the change.
        g = client.get(f"/api/v3/vendors/{vid}", headers=admin_headers).json()["data"]
        assert g["active"] is False

        # Default list — inactive vendor still surfaces (this is the
        # bit the bug report flagged).
        listing = client.get("/api/v3/vendors", headers=admin_headers).json()["data"]
        assert _vid_in(listing, vid), (
            "inactive vendor must remain visible in default GET /vendors so "
            "the FE management view can render the toggle"
        )

    def test_active_only_query_param_filters_inactive_out(
        self, client, admin_headers,
    ):
        v = client.post(
            "/api/v3/vendors/create",
            headers=admin_headers,
            json={"name": f"PickerHide {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
        ).json()["data"]
        vid = v["id"]
        client.patch(
            f"/api/v3/vendors/{vid}",
            headers=admin_headers,
            json={"active": False},
        )

        # ?active_only=true returns only active rows — picker behaviour.
        listing = client.get(
            "/api/v3/vendors?active_only=true", headers=admin_headers,
        ).json()["data"]
        assert not _vid_in(listing, vid), (
            "inactive vendor must NOT appear when ?active_only=true is set "
            "(this preserves the legacy picker dropdown behaviour)"
        )

    def test_master_vendors_default_shows_inactive(
        self, client, admin_headers,
    ):
        """Master_data delegate must mirror the legacy endpoint's new default."""
        v = client.post(
            "/api/v3/master/vendors/create",
            headers=admin_headers,
            json={"name": f"Master {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
        ).json()["data"]
        vid = v["id"]
        client.patch(
            f"/api/v3/master/vendors/{vid}",
            headers=admin_headers,
            json={"active": False},
        )
        listing = client.get(
            "/api/v3/master/vendors", headers=admin_headers,
        ).json()["data"]
        assert _vid_in(listing, vid)

        # And the picker mode still works through the master surface.
        picker = client.get(
            "/api/v3/master/vendors?active_only=true", headers=admin_headers,
        ).json()["data"]
        assert not _vid_in(picker, vid)

    def test_soft_deleted_vendor_still_hidden_by_default(
        self, client, admin_headers,
    ):
        """The fix lifts the active filter, NOT the soft-delete filter.
        Soft-deleted vendors must still be excluded from the list."""
        v = client.post(
            "/api/v3/vendors/create",
            headers=admin_headers,
            json={"name": f"Del {uuid4().hex[:4]}", "phoneNumber": "+919999999999"},
        ).json()["data"]
        vid = v["id"]
        # Soft-delete the vendor.
        client.delete(f"/api/v3/vendors/{vid}", headers=admin_headers)

        listing = client.get("/api/v3/vendors", headers=admin_headers).json()["data"]
        assert not _vid_in(listing, vid)
