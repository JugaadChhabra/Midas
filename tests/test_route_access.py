"""Who may reach which route (team tracker #145), through the HTTP seam:
TestClient over the app, with the users, sessions and channels in a FakeSupabase.

Two guards and the isolation tests:

  * The route-coverage guard walks ``app.routes`` and fails on any route with
    neither an access dependency (``app/access.py``, ``access_rule``) nor an
    allowlist entry. A route added later fails here until it is scoped.
  * Every route whose path has a ``{channel_id}`` depends on ``require_channel``.
  * Manager A gets 404 on every such route for manager B's channel; exec, and A
    on A's own channel, get through.
"""
import sys
from unittest.mock import patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import access, db, main, session
from tests.fakes import FakeSupabase

# ── the route-coverage guard ─────────────────────────────────────────────────

#: Reachable by any signed-in user (or by anyone) with no access rule, because
#: they show no channel's data.
OPEN_ROUTES = {
    # app/session.py PUBLIC_PATHS: no session needed.
    ("GET", "/login"),
    ("POST", "/session/login"),
    ("GET", "/health"),
    # Signed in, no channel data.
    ("POST", "/session/logout"),   # ends the caller's own session
    ("GET", "/"),                  # static HTML; its data comes from scoped routes
    ("GET", "/channel"),           # static HTML; its data comes from scoped routes
}

#: Not APIRoutes: FastAPI's docs and the static mount, behind the gate.
NON_API_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/static"}

#: PENDING (expand–contract): routes this ticket leaves unscoped. Each later
#: ticket removes its routes as it scopes them; the list may only shrink, and the
#: guard fails if a route here turns out to be scoped. #146 scoped the object-id
#: routes; empty and deleted by #147.
PENDING = {
    # #147: list and global routes are filtered, or become admin-only.
    ("GET", "/auth/login"),
    ("GET", "/auth/callback"),
    ("GET", "/quota"),
    ("GET", "/quota-cost-preview"),
    ("GET", "/health/jobs"),
    ("GET", "/health/channels"),
    ("POST", "/measurement/evaluate"),
    ("GET", "/dashboard"),
    ("POST", "/shorts/jobs"),
    ("GET", "/shorts/jobs"),
    ("POST", "/shorts/cut"),
    ("GET", "/shorts/languages"),
    ("POST", "/shorts/jobs/clear-failed"),
    ("POST", "/autoshorts/jobs"),
    ("GET", "/autoshorts"),
}


def _api_routes():
    return [r for r in main.app.routes if isinstance(r, APIRoute)]


def _keys(route):
    return {(m, route.path) for m in route.methods}


def _calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _calls(dep)


def _access_calls(route):
    return [c for c in _calls(route.dependant) if getattr(c, "access_rule", False)]


def test_every_route_has_an_access_rule_or_an_allowlist_entry():
    unguarded = sorted(
        key for route in _api_routes() if not _access_calls(route)
        for key in _keys(route)
        if key not in OPEN_ROUTES and key not in PENDING)
    assert unguarded == [], (
        "routes with no access dependency (app/access.py) and no allowlist entry: "
        f"{unguarded}. Scope them with require_channel, a resolver, require_role or "
        "current_user + visible_channel_ids.")


def test_pending_routes_are_still_unscoped_and_still_exist():
    """The PENDING list may only shrink: a scoped route must leave it."""
    by_key = {key: route for route in _api_routes() for key in _keys(route)}
    missing = sorted(k for k in PENDING if k not in by_key)
    scoped = sorted(k for k in PENDING if k in by_key and _access_calls(by_key[k]))
    assert missing == [], f"PENDING routes that no longer exist: {missing}"
    assert scoped == [], f"PENDING routes now scoped; remove them from PENDING: {scoped}"


def test_open_routes_exist_and_carry_no_channel():
    keys = {key for route in _api_routes() for key in _keys(route)}
    assert OPEN_ROUTES <= keys
    assert not any("{" in path for _, path in OPEN_ROUTES)


def test_the_only_non_api_routes_are_the_docs_and_static():
    others = {r.path for r in main.app.routes if not isinstance(r, APIRoute)}
    assert others == NON_API_PATHS


def _channel_routes():
    return sorted(key for route in _api_routes() if "{channel_id}" in route.path
                  for key in _keys(route))


def test_every_channel_id_route_requires_the_channel():
    by_key = {key: route for route in _api_routes() for key in _keys(route)}
    unscoped = [k for k in _channel_routes()
                if access.require_channel not in list(_calls(by_key[k].dependant))]
    assert unscoped == []


# ── users, sessions, channels ────────────────────────────────────────────────

ADMIN, EXEC, MANAGER_A, MANAGER_B = 1, 2, 3, 4
TOKENS = {ADMIN: "tok-admin", EXEC: "tok-exec", MANAGER_A: "tok-a", MANAGER_B: "tok-b"}
CH_A, CH_B, CH_NONE = "UC_channel_A", "UC_channel_B", "UC_channel_unmapped"


def _user(uid, role, active=True):
    return {"id": uid, "email": f"u{uid}@example.com", "name": f"User {uid}",
            "role": role, "is_active": active, "password_hash": "unused"}


@pytest.fixture
def store():
    """One FakeSupabase for every module that reads the database, so no route
    reaches a real client: an endpoint reading a table not described here raises
    UnstubbedTable (a 500), never a socket."""
    sb = FakeSupabase({
        "app_users": [_user(ADMIN, "admin"), _user(EXEC, "exec"),
                      _user(MANAGER_A, "manager"), _user(MANAGER_B, "manager"),
                      _user(5, "manager", active=False)],
        "app_sessions": [{"token_hash": session.hash_token(t), "user_id": uid,
                          "expires_at": "2999-01-01T00:00:00+00:00"}
                         for uid, t in TOKENS.items()],
        "channels": [
            {"id": CH_A, "name": "A", "manager_id": MANAGER_A},
            {"id": CH_B, "name": "B", "manager_id": MANAGER_B},
            {"id": CH_NONE, "name": "Unmapped", "manager_id": None},
        ],
    })
    patches = [patch.object(mod, "supabase", return_value=sb)
               for name, mod in list(sys.modules.items())
               if name.startswith("app") and getattr(mod, "supabase", None) is db.supabase]
    for p in patches:
        p.start()
    try:
        yield sb
    finally:
        for p in reversed(patches):
            p.stop()


def _as(uid):
    return TestClient(main.app, raise_server_exceptions=False,
                      cookies={session.COOKIE: TOKENS[uid]})


def _request(client, method, path, channel_id):
    url = path.replace("{channel_id}", channel_id)
    url = url.replace("{version_id}", "1")
    assert "{" not in url, f"fill the path parameters of {path}"
    return client.request(method, url)


def _access_404(response):
    return (response.status_code == 404
            and response.headers.get("content-type", "").startswith("application/json")
            and response.json().get("detail") == access.CHANNEL_NOT_FOUND)


# ── isolation: every channel-id route ────────────────────────────────────────

@pytest.mark.parametrize("method,path", _channel_routes())
def test_manager_gets_404_on_another_managers_channel(store, method, path):
    r = _request(_as(MANAGER_A), method, path, CH_B)
    assert _access_404(r), (r.status_code, r.text)


@pytest.mark.parametrize("method,path", _channel_routes())
def test_manager_gets_404_on_a_channel_with_no_manager(store, method, path):
    r = _request(_as(MANAGER_A), method, path, CH_NONE)
    assert _access_404(r), (r.status_code, r.text)


@pytest.mark.parametrize("method,path", _channel_routes())
def test_exec_gets_through_on_any_channel(store, method, path):
    for channel in (CH_B, CH_NONE):
        r = _request(_as(EXEC), method, path, channel)
        assert not _access_404(r), (channel, r.status_code, r.text)


@pytest.mark.parametrize("method,path",
                         [k for k in _channel_routes() if k[1] != "/channels/{channel_id}/manager"])
def test_manager_gets_through_on_their_own_channel(store, method, path):
    r = _request(_as(MANAGER_A), method, path, CH_A)
    assert not _access_404(r), (r.status_code, r.text)
    assert r.status_code != 403, r.text


def test_access_404_says_nothing_about_whether_the_channel_exists(store):
    known = _as(MANAGER_A).get(f"/channels/{CH_B}/videos")
    unknown = _as(MANAGER_A).get("/channels/UC_no_such_channel/videos")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())


# ── channel lists ────────────────────────────────────────────────────────────

def _listed(uid):
    r = _as(uid).get("/auth/channels")
    assert r.status_code == 200, r.text
    return sorted(c["id"] for c in r.json())


def test_auth_channels_lists_a_managers_own_channels_only(store):
    assert _listed(MANAGER_A) == [CH_A]
    assert _listed(MANAGER_B) == [CH_B]


def test_auth_channels_lists_every_channel_for_admin_and_exec(store):
    assert _listed(ADMIN) == sorted([CH_A, CH_B, CH_NONE])
    assert _listed(EXEC) == sorted([CH_A, CH_B, CH_NONE])


def test_visible_channel_ids_follow_the_mapping(store):
    users = {u["id"]: u for u in store.rows("app_users")}
    assert access.visible_channel_ids(users[MANAGER_A]) == {CH_A}
    assert access.visible_channel_ids(users[EXEC]) == {CH_A, CH_B, CH_NONE}
    assert access.visible_channel_ids(users[5]) == set()


# ── PATCH /channels/{id}/manager ─────────────────────────────────────────────

def _channel(store, cid):
    return next(c for c in store.rows("channels") if c["id"] == cid)


def test_admin_maps_a_channel_to_a_manager_and_it_shows_up_for_them(store):
    r = _as(ADMIN).patch(f"/channels/{CH_NONE}/manager", json={"manager_id": MANAGER_A})

    assert r.status_code == 200, r.text
    assert r.json() == {"id": CH_NONE, "manager_id": MANAGER_A}
    assert _channel(store, CH_NONE)["manager_id"] == MANAGER_A
    assert _listed(MANAGER_A) == sorted([CH_A, CH_NONE])


def test_handing_a_channel_over_moves_it_between_managers(store):
    r = _as(ADMIN).patch(f"/channels/{CH_B}/manager", json={"manager_id": MANAGER_A})

    assert r.status_code == 200
    assert _listed(MANAGER_A) == sorted([CH_A, CH_B])
    assert _listed(MANAGER_B) == []
    assert _access_404(_as(MANAGER_B).get(f"/channels/{CH_B}/videos"))


def test_admin_clears_a_mapping_with_null(store):
    r = _as(ADMIN).patch(f"/channels/{CH_A}/manager", json={"manager_id": None})

    assert r.status_code == 200
    assert _channel(store, CH_A)["manager_id"] is None
    assert _listed(MANAGER_A) == []


@pytest.mark.parametrize("uid,status,detail", [
    (EXEC, 403, access.FORBIDDEN),
    (MANAGER_A, 403, access.FORBIDDEN),          # their own channel
    (MANAGER_B, 404, access.CHANNEL_NOT_FOUND),  # not theirs: not even revealed
])
def test_only_the_admin_maps_channels(store, uid, status, detail):
    r = _as(uid).patch(f"/channels/{CH_A}/manager", json={"manager_id": MANAGER_B})

    assert r.status_code == status
    assert r.json() == {"detail": detail}
    assert _channel(store, CH_A)["manager_id"] == MANAGER_A
    assert [w for w in store.writes if w[0] == "channels"] == []


@pytest.mark.parametrize("manager_id", [EXEC, ADMIN, 5, 999])
def test_the_mapping_names_an_active_manager(store, manager_id):
    r = _as(ADMIN).patch(f"/channels/{CH_A}/manager", json={"manager_id": manager_id})

    assert r.status_code == 400
    assert _channel(store, CH_A)["manager_id"] == MANAGER_A


def test_mapping_an_unknown_channel_is_404(store):
    r = _as(ADMIN).patch("/channels/UC_no_such_channel/manager",
                         json={"manager_id": MANAGER_A})

    assert r.status_code == 404
    assert r.json() == {"detail": access.CHANNEL_NOT_FOUND}


def test_the_channel_settings_patch_cannot_set_the_manager(store):
    """The settings PATCH a manager may use on their own channel has no
    manager_id field: a manager can't hand a channel to themselves."""
    _as(MANAGER_A).patch(f"/auth/channels/{CH_B}", json={"manager_id": MANAGER_A})
    _as(MANAGER_A).patch(f"/auth/channels/{CH_A}", json={"manager_id": MANAGER_B})

    assert _channel(store, CH_A)["manager_id"] == MANAGER_A
    assert _channel(store, CH_B)["manager_id"] == MANAGER_B


# ── isolation: every object-id route (#146) ──────────────────────────────────
#
# A route addressed by a video, audit, intervention, Short-link recommendation,
# Shorts job or clip id resolves the object to its channel and applies the same
# check: manager A gets 404 for manager B's object, and the same 404 for an id
# that doesn't exist. The objects on B's channel are shaped so a user who gets
# through stops at the route's own refusal (a private video, an applied audit
# with no before-state, a human intervention, a `set` recommendation, an
# uploaded clip): nothing reaches YouTube or a model.

V_A, V_B, V_NONE = "vid_A", "vid_B", "vid_unmapped"
AUDIT_A, AUDIT_B = 10, 11
INTERVENTION_A, INTERVENTION_B = 20, 21
REC_A, REC_B, REC_B_NO_CHANNEL = 30, 31, 32
JOB_A, JOB_B = 40, 41
CLIP_A, CLIP_B = 50, 51

#: Path parameter → (resolver, the 404 detail, A's object, B's object, an unknown id).
OBJECTS = {
    "video_id": (access.require_video, access.VIDEO_NOT_FOUND, V_A, V_B, "vid_none"),
    "audit_id": (access.require_audit, access.AUDIT_NOT_FOUND, AUDIT_A, AUDIT_B, 999),
    "intervention_id": (access.require_intervention, access.INTERVENTION_NOT_FOUND,
                        INTERVENTION_A, INTERVENTION_B, 999),
    "recommendation_id": (access.require_short_link, access.SHORT_LINK_NOT_FOUND,
                          REC_A, REC_B, 999),
    "job_id": (access.require_shorts_job, access.SHORTS_JOB_NOT_FOUND, JOB_A, JOB_B, 999),
    "clip_id": (access.require_shorts_clip, access.SHORTS_CLIP_NOT_FOUND, CLIP_A, CLIP_B, 999),
}

#: Every route addressed by one of those ids (the #146 list), with its id.
OBJECT_ROUTES = [
    ("GET", "/videos/{video_id}"),
    ("POST", "/videos/{video_id}/audit"),
    ("GET", "/videos/{video_id}/audits"),
    ("POST", "/videos/{video_id}/short"),
    ("POST", "/audits/{audit_id}/apply"),
    ("POST", "/audits/{audit_id}/revert"),
    ("GET", "/audits/{audit_id}/measurement"),
    ("POST", "/interventions/{intervention_id}/revert"),
    ("POST", "/short-links/{recommendation_id}/set"),
    ("POST", "/short-links/{recommendation_id}/dismiss"),
    ("GET", "/shorts/jobs/{job_id}"),
    ("GET", "/shorts/clips/{clip_id}/file"),
    ("POST", "/shorts/clips/{clip_id}/upload"),
]


def _param(path):
    names = [n for n in OBJECTS if "{" + n + "}" in path]
    assert len(names) == 1, path
    return names[0]


def _object_rows(owner, channel, video, audit, intervention, rec, job, clip):
    return {
        "videos": {"id": video, "channel_id": channel, "title": f"Video {owner}",
                   "privacy_status": "private", "tags": []},
        "audits": {"id": audit, "video_id": video, "status": "applied",
                   "title_before": None, "description_before": None},
        "interventions": {"id": intervention, "video_id": video, "channel_id": channel,
                          "lever": "backlinks", "origin": "human", "arm": "n/a",
                          "status": "applied"},
        "short_link_recommendations": {"id": rec, "channel_id": channel, "short_id": video,
                                       "target_video_id": video, "status": "set",
                                       "intervention_id": None},
        "shorts_jobs": {"id": job, "channel_id": channel, "status": "DONE"},
        "shorts_clips": {"id": clip, "job_id": job, "local_path": None, "rank": 1,
                         "upload_status": "UPLOADED"},
    }


@pytest.fixture
def objects(store):
    """Each object type once on A's channel and once on B's; an unmapped video;
    and a recommendation on B's Short with no channel_id (the column is
    nullable: its channel is the Short's)."""
    rows = [_object_rows("A", CH_A, V_A, AUDIT_A, INTERVENTION_A, REC_A, JOB_A, CLIP_A),
            _object_rows("B", CH_B, V_B, AUDIT_B, INTERVENTION_B, REC_B, JOB_B, CLIP_B)]
    for table in rows[0]:
        store._tables[table] = [r[table] for r in rows]
    store._tables["videos"].append({"id": V_NONE, "channel_id": CH_NONE,
                                    "privacy_status": "private", "tags": []})
    store._tables["short_link_recommendations"].append(
        {"id": REC_B_NO_CHANNEL, "channel_id": None, "short_id": V_B,
         "target_video_id": V_B, "status": "set", "intervention_id": None})
    return store


def _object_request(client, method, path, object_id):
    url = path.replace("{" + _param(path) + "}", str(object_id))
    assert "{" not in url, f"fill the path parameters of {path}"
    return client.request(method, url)


def _object_404(response, detail):
    return (response.status_code == 404
            and response.headers.get("content-type", "").startswith("application/json")
            and response.json() == {"detail": detail})


def test_the_object_routes_are_every_route_addressed_by_an_object_id():
    keys = {key for route in _api_routes() for key in _keys(route)}
    by_param = sorted(k for k in keys
                      if "{channel_id}" not in k[1]
                      and any("{" + n + "}" in k[1] for n in OBJECTS))
    assert by_param == sorted(OBJECT_ROUTES)


@pytest.mark.parametrize("method,path", OBJECT_ROUTES)
def test_every_object_route_uses_its_resolver(method, path):
    by_key = {key: route for route in _api_routes() for key in _keys(route)}
    resolver = OBJECTS[_param(path)][0]
    assert resolver in list(_calls(by_key[(method, path)].dependant))


@pytest.mark.parametrize("method,path", OBJECT_ROUTES)
def test_manager_gets_404_for_another_managers_object(objects, method, path):
    _, detail, _, theirs, _ = OBJECTS[_param(path)]
    r = _object_request(_as(MANAGER_A), method, path, theirs)
    assert _object_404(r, detail), (r.status_code, r.text)


@pytest.mark.parametrize("method,path", OBJECT_ROUTES)
def test_manager_gets_the_same_404_for_an_unknown_object(objects, method, path):
    _, detail, _, theirs, unknown = OBJECTS[_param(path)]
    r = _object_request(_as(MANAGER_A), method, path, unknown)
    other = _object_request(_as(MANAGER_A), method, path, theirs)
    assert _object_404(r, detail), (r.status_code, r.text)
    assert (r.status_code, r.json()) == (other.status_code, other.json())


@pytest.mark.parametrize("method,path", OBJECT_ROUTES)
def test_exec_gets_through_to_any_object(objects, method, path):
    _, detail, _, theirs, _ = OBJECTS[_param(path)]
    r = _object_request(_as(EXEC), method, path, theirs)
    assert not _object_404(r, detail), (r.status_code, r.text)


@pytest.mark.parametrize("method,path", OBJECT_ROUTES)
def test_manager_gets_through_to_their_own_object(objects, method, path):
    _, detail, mine, _, _ = OBJECTS[_param(path)]
    r = _object_request(_as(MANAGER_A), method, path, mine)
    assert not _object_404(r, detail), (r.status_code, r.text)
    assert r.status_code != 403, r.text


def test_manager_gets_404_for_a_video_on_a_channel_with_no_manager(objects):
    r = _as(MANAGER_A).get(f"/videos/{V_NONE}")
    assert _object_404(r, access.VIDEO_NOT_FOUND), (r.status_code, r.text)
    assert _as(EXEC).get(f"/videos/{V_NONE}").status_code == 200


def test_a_recommendation_with_no_channel_takes_its_shorts_channel(objects):
    """`short_link_recommendations.channel_id` is nullable (S2.4): the Short's
    channel decides."""
    for path in ("/short-links/{id}/set", "/short-links/{id}/dismiss"):
        url = path.format(id=REC_B_NO_CHANNEL)
        assert _object_404(_as(MANAGER_A).post(url), access.SHORT_LINK_NOT_FOUND)
        assert not _object_404(_as(MANAGER_B).post(url), access.SHORT_LINK_NOT_FOUND)


def test_a_refused_object_route_writes_nothing(objects):
    before = len(objects.writes)
    for method, path in OBJECT_ROUTES:
        _object_request(_as(MANAGER_A), method, path, OBJECTS[_param(path)][3])
    assert objects.writes[before:] == []
