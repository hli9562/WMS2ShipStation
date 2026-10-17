import hashlib

from fastapi.testclient import TestClient

from tests.test_imports import upload, workbook
from wms2ship.config import Settings
from wms2ship.main import create_app


def test_fingerprints_find_renamed_copies_and_changed_or_invalid_files(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        headers = {"x-csrf-token": client.app.state.csrf_token}
        valid = workbook()
        invalid = workbook(order="INVALID", quantity=0)

        def digest(data):
            return hashlib.sha256(data).hexdigest()

        hashes = [digest(valid), digest(invalid), "0" * 64]
        assert client.post("/api/imports/check", json={"hashes": hashes}).status_code == 403
        before = client.post("/api/imports/check", json={"hashes": hashes}, headers=headers).json()
        assert [f["status"] for f in before["files"]] == ["new", "new", "new"]
        batch = upload(client, valid, "original.xlsx").json()
        bad_batch = upload(client, invalid, "needs-review.xlsx").json()
        after = client.post("/api/imports/check", json={"hashes": hashes}, headers=headers).json()
        assert after["files"][0]["status"] == "imported"
        assert after["files"][0]["batch_id"] == batch["id"]
        assert after["files"][1]["status"] == "needs_review"
        assert after["files"][1]["batch_id"] == bad_batch["id"]
        assert after["files"][2]["status"] == "new"
        # Status follows bytes, not filename. Existing order protection still applies.
        renamed = upload(client, valid, "renamed.xlsx").json()
        assert renamed["created"] == 0 and renamed["duplicates"] == 1
        assert len(client.get("/api/orders").json()) == 1
        assert client.get("/api/history").json() == []
        changed = workbook(order="NEW-ORDER")
        assert (
            client.post(
                "/api/imports/check", json={"hashes": [digest(changed)]}, headers=headers
            ).json()["files"][0]["status"]
            == "new"
        )
        assert client.post("/api/imports/check", json={"hashes": []}, headers=headers).json() == {
            "files": []
        }
        for payload in (
            {"hashes": ["bad-hash"]},
            {"hashes": ["0" * 64] * 201},
            {"hashes": hashes, "path": "/tmp"},
        ):
            assert (
                client.post("/api/imports/check", json=payload, headers=headers).status_code == 422
            )
        repeated = client.post(
            "/api/imports/check", json={"hashes": [hashes[0], hashes[0]]}, headers=headers
        ).json()
        assert len(repeated["files"]) == 1
