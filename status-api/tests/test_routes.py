from fastapi.testclient import TestClient

import status_api


def _reset(name):
    status_api._CACHES[name]["value"] = None
    status_api._CACHES[name]["expires"] = 0.0


def test_skills_learned_route(tmp_path, monkeypatch):
    tree = tmp_path / "skills" / "capture"
    tree.mkdir(parents=True)
    (tree / "SKILL.md").write_text("x", encoding="utf-8")
    monkeypatch.setattr(status_api, "skill_trees", lambda: [str(tmp_path / "skills")])
    monkeypatch.setattr(status_api, "BUNDLED_SKILL_TREES", [])
    monkeypatch.setattr(status_api, "SKILLS_LEDGER", str(tmp_path / "state" / "ledger.json"))
    _reset("skills")
    body = TestClient(status_api.app).get("/skills-learned").json()
    assert body["total"] == 1 and body["latest"] == "capture"


def test_skills_learned_route_survives_errors(monkeypatch):
    def boom(*_args):
        raise OSError("disk gone")

    monkeypatch.setattr(status_api.skills_learned, "build_skills_learned", boom)
    _reset("skills")
    resp = TestClient(status_api.app).get("/skills-learned")
    assert resp.status_code == 200
    body = resp.json()
    assert "disk gone" in body["error"]
    assert body["total"] == 0 and body["latest_label"] == "none yet"


def test_second_brain_route(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("# A\n\nBody.\n", encoding="utf-8")
    monkeypatch.setattr(status_api, "SECOND_BRAIN_DIR", str(tmp_path))
    _reset("brain")
    resp = TestClient(status_api.app).get("/second-brain")
    assert resp.status_code == 200
    assert resp.json()["note_title"] == "A"


def test_second_brain_route_missing_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(status_api, "SECOND_BRAIN_DIR", str(tmp_path / "moved"))
    _reset("brain")
    resp = TestClient(status_api.app).get("/second-brain")
    assert resp.status_code == 200
    body = resp.json()
    assert "vault not found" in body["error"]
    assert body["items"][0]["name"] == "Vault unavailable"
