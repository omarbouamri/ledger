"""Drive real Dash callbacks over HTTP against a live JobScout process."""
import json
import os
import re
import sys

os.environ.setdefault("JOBSCOUT_SECRET_KEY", "test-key-" + "0" * 40)
sys.path.insert(0, os.path.abspath("."))

import app as appmod  # noqa: E402
from jobscout import repo  # noqa: E402

flask_app = appmod.app
client = flask_app.test_client()

# sign in (or sign up)
r = client.get("/signup")
tok = re.search(rb'name="_csrf" value="([^"]+)"', r.data)
if tok:
    client.post("/signup", data={"_csrf": tok.group(1).decode(), "name": "CB Tester",
                                 "email": "cb@example.com", "password": "a-long-enough-pass",
                                 "confirm": "a-long-enough-pass"})
if not repo.user_by_email("cb@example.com"):
    sys.exit("could not create the test account")
if "/app/" not in client.get("/app/").headers.get("Location", "/app/"):
    pass
r = client.get("/app/")
assert r.status_code == 200, ("not signed in", r.status_code)

deps = client.get("/app/_dash-dependencies").get_json()
by_output = {d["output"]: d for d in deps}
print(f"{len(deps)} callbacks registered\n")

failures = []
ran = 0

def _parse_one(piece):
    piece = piece.split("@")[0]
    raw_id, prop = piece.rsplit(".", 1)
    if raw_id.startswith("{"):
        return {"id": json.loads(raw_id), "property": prop}
    return {"id": raw_id, "property": prop}


def outputs_of(dep):
    """Turn Dash's combined output string back into the outputs payload."""
    out = dep["output"]
    if out.startswith(".."):
        return [_parse_one(x) for x in out.strip(".").split("...")]
    return _parse_one(out)




def fire(label, dep, inputs, state=None, changed=None):
    """POST one callback and assert it returns a 200 with no error payload."""
    global ran
    ran += 1
    wire = []
    for item in inputs:
        wire.append([item] if isinstance(item.get("id"), dict) else item)
    inputs = wire
    wire_state = []
    for item in (state or []):
        wire_state.append([item] if isinstance(item.get("id"), dict) else item)
    state = wire_state

    def prop_id(item):
        if isinstance(item, list):
            item = item[0]
        ident = item["id"]
        if isinstance(ident, dict):
            ident = json.dumps(ident, separators=(",", ":"), sort_keys=True)
        return f"{ident}.{item['property']}"

    payload = {
        "output": dep["output"],
        "outputs": outputs_of(dep),
        "inputs": inputs,
        "changedPropIds": changed or [prop_id(i) for i in inputs],
        "state": state or [],
    }
    r = client.post(
        "/app/_dash-update-component",
        data=json.dumps(payload),
        content_type="application/json",
    )
    body = r.get_data(as_text=True)
    ok = r.status_code == 200 and '"error"' not in body[:400].lower()
    if ok:
        print(f"  ok   {label}")
    else:
        print(f"  FAIL {label} [{r.status_code}] {body[:600]}")
        failures.append(label)
    return body


def find(fragment):
    if fragment in by_output:
        return by_output[fragment]
    for key, dep in by_output.items():
        if key == f"..{fragment}.." or key.split("@")[0] == fragment:
            return dep
    for key, dep in by_output.items():
        if fragment in key:
            return dep
    raise KeyError(fragment + " -- have: " + "; ".join(list(by_output)[:40]))


df = repo.employers_frame()
emp_id = df.iloc[0]["id"]
uid = repo.user_by_email("cb@example.com")["id"]

print("== shell ==")
shell = find("topbar-slot.children")
for path in ["/app/", "/app/directory", "/app/tracking", "/app/contact",
             "/app/assistant", "/app/deck", "/app/admin", "/app/bogus"]:
    for theme in ("light", "dark"):
        fire(
            f"router {path} ({theme})",
            shell,
            [{"id": "url", "property": "pathname", "value": path},
             {"id": "theme-store", "property": "data", "value": theme}],
        )

print("\n== directory ==")
d = find("dir-table.children")
dir_inputs = lambda search="", sector=None, sort="score", clicks=0, flags=None, open_id=None, page=1: [
    {"id": "dir-search", "property": "value", "value": search},
    {"id": "dir-sector", "property": "value", "value": sector},
    {"id": "dir-sort", "property": "value", "value": sort},
    {"id": "dir-dir", "property": "n_clicks", "value": clicks},
    {"id": "dir-flags", "property": "value", "value": flags or []},
    {"id": "dir-open", "property": "data", "value": open_id},
    {"id": "dir-page", "property": "data", "value": page},
    {"id": "dir-bump", "property": "data", "value": 0},
]
fire("render default", d, dir_inputs())
fire("render search", d, dir_inputs(search="agency"))
fire("render no match", d, dir_inputs(search="zzzzzzzz"))
fire("render sector filter", d, dir_inputs(sector=repo.sectors()[0]))
for sort in ("score", "name", "rating", "reviews", "sector"):
    fire(f"sort by {sort}", d, dir_inputs(sort=sort))
    fire(f"sort by {sort} reversed", d, dir_inputs(sort=sort, clicks=1))
fire("flag nosite", d, dir_inputs(flags=["nosite"]))
fire("flag priority", d, dir_inputs(flags=["priority"]))
fire("flag tracked", d, dir_inputs(flags=["tracked"]))
fire("all flags", d, dir_inputs(flags=["nosite", "priority", "tracked"]))
fire("page 3", d, dir_inputs(page=3))
fire("row expanded", d, dir_inputs(open_id=emp_id))
fire("sql-ish search is literal", d, dir_inputs(search="'; DROP TABLE employers;--"))
fire("regex chars are literal", d, dir_inputs(search="a(b[c"))

star = find("dir-bump.data")
fire(
    "star an employer",
    star,
    [{"id": {"id": emp_id, "type": "dir-star"}, "property": "n_clicks", "value": 1}],
    state=[{"id": "dir-bump", "property": "data", "value": 0}],
)
row = find("dir-open.data")
fire(
    "expand a row",
    row,
    [{"id": {"id": emp_id, "type": "dir-row"}, "property": "n_clicks", "value": 1}],
    state=[{"id": "dir-open", "property": "data", "value": None}],
)
arrow = find("dir-dir.children")
fire("arrow glyph", arrow, [{"id": "dir-dir", "property": "n_clicks", "value": 1},
                            {"id": "dir-sort", "property": "value", "value": "name"}])
reset = find("dir-search.value")
fire("reset filters", reset, [{"id": "dir-reset", "property": "n_clicks", "value": 1}])

print("\n== pipeline ==")
repo.toggle_star(uid, emp_id)
board = find("pipe-board.children")
for theme in (False, True):
    fire(f"board (dark={theme})", board,
         [{"id": "pipe-sel", "property": "data", "value": emp_id},
          {"id": "pipe-bump", "property": "data", "value": 0}],
         state=[{"id": "pipe-dark", "property": "data", "value": theme}])
fire("board, nothing selected", board,
     [{"id": "pipe-sel", "property": "data", "value": None},
      {"id": "pipe-bump", "property": "data", "value": 0}],
     state=[{"id": "pipe-dark", "property": "data", "value": False}])
fire("board, stale selection", board,
     [{"id": "pipe-sel", "property": "data", "value": "does-not-exist"},
      {"id": "pipe-bump", "property": "data", "value": 0}],
     state=[{"id": "pipe-dark", "property": "data", "value": False}])

save = [d for k, d in by_output.items() if "pipe-save" in json.dumps(d.get("inputs", []))]
if save:
    fire("save a record", save[0],
         [{"id": "pipe-save", "property": "n_clicks", "value": 1}],
         state=[{"id": "pipe-sel", "property": "data", "value": emp_id},
                {"id": "pipe-stage", "property": "value", "value": "interview"},
                {"id": "pipe-contact-name", "property": "value", "value": "Sam"},
                {"id": "pipe-contact-email", "property": "value", "value": "sam@example.com"},
                {"id": "pipe-notes", "property": "value", "value": "Spoke Tuesday."},
                {"id": "pipe-bump", "property": "data", "value": 0}])
    t = repo.tracking_for(uid).get(emp_id, {})
    print(f"       -> stage={t.get('stage')} contact={t.get('contact_name')}")

print("\n== outreach ==")
tpl = repo.templates_for(uid)[0]
tpl_dep = next(d for k, d in by_output.items()
               if any(i["id"] == "out-template" for i in d["inputs"]))
fire("template -> composer", tpl_dep, [{"id": "out-template", "property": "value", "value": tpl["id"]}])

fill_dep = next(d for k, d in by_output.items()
                if any(i["id"] == "out-fill" for i in d["inputs"]))
fire("fill placeholders", fill_dep,
     [{"id": "out-fill", "property": "n_clicks", "value": 1}],
     state=[{"id": "out-employer", "property": "value", "value": emp_id},
            {"id": "out-subject", "property": "value", "value": tpl["subject"]},
            {"id": "out-body", "property": "value", "value": tpl["body"]},
            {"id": "out-sender", "property": "value", "value": "CB Tester"},
            {"id": "out-contact", "property": "value", "value": "Sam"}])
fire("fill without an employer", fill_dep,
     [{"id": "out-fill", "property": "n_clicks", "value": 1}],
     state=[{"id": "out-employer", "property": "value", "value": None},
            {"id": "out-subject", "property": "value", "value": "x"},
            {"id": "out-body", "property": "value", "value": "y"},
            {"id": "out-sender", "property": "value", "value": ""},
            {"id": "out-contact", "property": "value", "value": ""}])

prev_dep = next(d for k, d in by_output.items()
                if any(i["id"] == "out-preview" for i in d["inputs"]))
fire("preview", prev_dep,
     [{"id": "out-preview", "property": "n_clicks", "value": 1}],
     state=[{"id": "out-employer", "property": "value", "value": emp_id},
            {"id": "out-to", "property": "value", "value": "sam@example.com"},
            {"id": "out-subject", "property": "value", "value": "Hi {name}"},
            {"id": "out-body", "property": "value", "value": "About {sector}. {sender_name}"},
            {"id": "out-sender", "property": "value", "value": "CB"},
            {"id": "out-contact", "property": "value", "value": "Sam"}])

send_dep = next(d for k, d in by_output.items()
                if any(i["id"] == "out-send" for i in d["inputs"]))
send_state = lambda to: [
    {"id": "out-employer", "property": "value", "value": emp_id},
    {"id": "out-to", "property": "value", "value": to},
    {"id": "out-subject", "property": "value", "value": "Hi {name}"},
    {"id": "out-body", "property": "value", "value": "Body {sector}"},
    {"id": "out-sender", "property": "value", "value": "CB"},
    {"id": "out-contact", "property": "value", "value": "Sam"},
    {"id": "out-dark", "property": "data", "value": False},
]
before = len(repo.emails_for(uid))
fire("send (dry run)", send_dep, [{"id": "out-send", "property": "n_clicks", "value": 1}],
     state=send_state("sam@example.com"))
print(f"       -> emails logged: {before} -> {len(repo.emails_for(uid))}")
fire("send to a bad address", send_dep, [{"id": "out-send", "property": "n_clicks", "value": 1}],
     state=send_state("not-an-email"))

savetpl_dep = next(d for k, d in by_output.items()
                   if any(i["id"] == "out-save-tpl" for i in d["inputs"]))
fire("save a template", savetpl_dep,
     [{"id": "out-save-tpl", "property": "n_clicks", "value": 1}],
     state=[{"id": "out-subject", "property": "value", "value": "My subject"},
            {"id": "out-body", "property": "value", "value": "My body"}])

log_dep = find("out-log.children")
fire("sent log", log_dep, [{"id": "out-bump", "property": "data", "value": 0}])

prefill_dep = find("out-employer.value")
fire("deep link ?employer=", prefill_dep,
     [{"id": "out-url", "property": "search", "value": f"?employer={emp_id}"}])
fire("deep link, no query", prefill_dep,
     [{"id": "out-url", "property": "search", "value": ""}])
fire("deep link, junk query", prefill_dep,
     [{"id": "out-url", "property": "search", "value": "?employer=%%%&x=1"}])

print("\n== assistant ==")
asst = find("asst-answers.children")
fire("ask with no key", asst,
     [{"id": "asst-send", "property": "n_clicks", "value": 1},
      {"id": "asst-clear", "property": "n_clicks", "value": 0}],
     state=[{"id": "asst-q", "property": "value", "value": "Which sectors first?"},
            {"id": "asst-history", "property": "data", "value": []}],
     changed=["asst-send.n_clicks"])
fire("ask with an empty question", asst,
     [{"id": "asst-send", "property": "n_clicks", "value": 1},
      {"id": "asst-clear", "property": "n_clicks", "value": 0}],
     state=[{"id": "asst-q", "property": "value", "value": "   "},
            {"id": "asst-history", "property": "data", "value": []}],
     changed=["asst-send.n_clicks"])
fire("clear history", asst,
     [{"id": "asst-send", "property": "n_clicks", "value": 1},
      {"id": "asst-clear", "property": "n_clicks", "value": 1}],
     state=[{"id": "asst-q", "property": "value", "value": "x"},
            {"id": "asst-history", "property": "data", "value": [{"q": "a", "a": "b", "ok": True}]}],
     changed=["asst-clear.n_clicks"])
sugg = find("asst-q.value")
fire("suggestion button", sugg,
     [{"id": {"i": 2, "type": "asst-sugg"}, "property": "n_clicks", "value": 1}])

print("\n== deck ==")
slide = find("deck-slide.children")
for i in range(9):
    for theme in (False, True) if i == 0 else (False,):
        fire(f"slide {i + 1} (dark={theme})", slide,
             [{"id": "deck-i", "property": "data", "value": i}],
             state=[{"id": "deck-dark", "property": "data", "value": theme}])
fire("slide index out of range", slide,
     [{"id": "deck-i", "property": "data", "value": 99}],
     state=[{"id": "deck-dark", "property": "data", "value": False}])
nav = find("deck-i.data")
fire("deck next", nav, [{"id": "deck-prev", "property": "n_clicks", "value": 0},
                        {"id": "deck-next", "property": "n_clicks", "value": 1},
                        {"id": {"i": 0, "type": "deck-dot"}, "property": "n_clicks", "value": 0}],
     state=[{"id": "deck-i", "property": "data", "value": 0}],
     changed=["deck-next.n_clicks"])
fire("deck dot jump", nav, [{"id": "deck-prev", "property": "n_clicks", "value": 0},
                            {"id": "deck-next", "property": "n_clicks", "value": 0},
                            {"id": {"i": 5, "type": "deck-dot"}, "property": "n_clicks", "value": 1}],
     state=[{"id": "deck-i", "property": "data", "value": 0}],
     changed=['{"i":5,"type":"deck-dot"}.n_clicks'])

print("\n== admin ==")
adm = find("adm-users.children")
fire("admin tables", adm, [{"id": "adm-bump", "property": "data", "value": 0}])

create_dep = next(d for k, d in by_output.items()
                  if any(i["id"] == "adm-create" for i in d["inputs"]))
fire("create an account", create_dep,
     [{"id": "adm-create", "property": "n_clicks", "value": 1}],
     state=[{"id": "adm-new-name", "property": "value", "value": "Made By Admin"},
            {"id": "adm-new-email", "property": "value", "value": "made@example.com"},
            {"id": "adm-new-pass", "property": "value", "value": "a-long-password-x"},
            {"id": "adm-new-role", "property": "value", "value": "scout"},
            {"id": "adm-bump", "property": "data", "value": 0}])
print(f"       -> created: {repo.user_by_email('made@example.com') is not None}")
fire("create with a weak password", create_dep,
     [{"id": "adm-create", "property": "n_clicks", "value": 1}],
     state=[{"id": "adm-new-name", "property": "value", "value": "X Y"},
            {"id": "adm-new-email", "property": "value", "value": "weak@example.com"},
            {"id": "adm-new-pass", "property": "value", "value": "short"},
            {"id": "adm-new-role", "property": "value", "value": "scout"},
            {"id": "adm-bump", "property": "data", "value": 0}])
print(f"       -> rejected: {repo.user_by_email('weak@example.com') is None}")
fire("create with a privileged role", create_dep,
     [{"id": "adm-create", "property": "n_clicks", "value": 1}],
     state=[{"id": "adm-new-name", "property": "value", "value": "Root Esc"},
            {"id": "adm-new-email", "property": "value", "value": "esc@example.com"},
            {"id": "adm-new-pass", "property": "value", "value": "a-long-password-y"},
            {"id": "adm-new-role", "property": "value", "value": "superuser"},
            {"id": "adm-bump", "property": "data", "value": 0}])
esc = repo.user_by_email("esc@example.com")
print(f"       -> unknown role coerced to: {esc and esc['role']}")

made_id = repo.user_by_email("made@example.com")["id"]
action_dep = next(d for k, d in by_output.items()
                  if any("adm-role" in json.dumps(i["id"]) for i in d["inputs"]))
act_inputs = lambda kind, value: [
    {"id": {"id": made_id, "type": "adm-role"}, "property": "n_clicks",
     "value": value if kind == "adm-role" else None},
    {"id": {"id": made_id, "type": "adm-active"}, "property": "n_clicks",
     "value": value if kind == "adm-active" else None},
    {"id": {"id": made_id, "type": "adm-reset"}, "property": "n_clicks",
     "value": value if kind == "adm-reset" else None},
    {"id": {"id": made_id, "type": "adm-delete"}, "property": "n_clicks",
     "value": value if kind == "adm-delete" else None},
]
for kind in ("adm-role", "adm-active", "adm-reset"):
    fire(f"user action {kind}", action_dep, act_inputs(kind, 1),
         state=[{"id": "adm-bump", "property": "data", "value": 0}],
         changed=[json.dumps({"id": made_id, "type": kind}, separators=(",", ":")) + ".n_clicks"])

# the self-protection path: acting on your own account
self_inputs = [
    {"id": {"id": uid, "type": "adm-role"}, "property": "n_clicks", "value": 1},
    {"id": {"id": uid, "type": "adm-active"}, "property": "n_clicks", "value": None},
    {"id": {"id": uid, "type": "adm-reset"}, "property": "n_clicks", "value": None},
    {"id": {"id": uid, "type": "adm-delete"}, "property": "n_clicks", "value": None},
]
fire("cannot demote yourself", action_dep, self_inputs,
     state=[{"id": "adm-bump", "property": "data", "value": 0}],
     changed=[json.dumps({"id": uid, "type": "adm-role"}, separators=(",", ":")) + ".n_clicks"])
print(f"       -> still admin: {repo.user_by_id(uid)['role'] == 'admin'}")

maint_dep = next(d for k, d in by_output.items()
                 if any(i["id"] == "adm-rescore" for i in d["inputs"]))
fire("re-score", maint_dep,
     [{"id": "adm-rescore", "property": "n_clicks", "value": 1},
      {"id": "adm-reseed", "property": "n_clicks", "value": 0}],
     state=[{"id": "adm-bump", "property": "data", "value": 0}],
     changed=["adm-rescore.n_clicks"])
fire("re-seed", maint_dep,
     [{"id": "adm-rescore", "property": "n_clicks", "value": 0},
      {"id": "adm-reseed", "property": "n_clicks", "value": 1}],
     state=[{"id": "adm-bump", "property": "data", "value": 0}],
     changed=["adm-reseed.n_clicks"])
print(f"       -> employers after re-seed: {len(repo.employers_frame(force=True))}")

test_dep = find("adm-test-out.children")
fire("test mail", test_dep, [{"id": "adm-test-send", "property": "n_clicks", "value": 1}],
     state=[{"id": "adm-test-to", "property": "value", "value": "me@example.com"}])
fire("test mail, bad address", test_dep,
     [{"id": "adm-test-send", "property": "n_clicks", "value": 1}],
     state=[{"id": "adm-test-to", "property": "value", "value": "nope"}])
sug_dep = find("adm-new-pass.value")
fire("suggest a password", sug_dep, [{"id": "adm-suggest", "property": "n_clicks", "value": 1}])

print("\n== non-admin cannot run admin callbacks ==")
c2 = flask_app.test_client()
r = c2.get("/signup")
t = re.search(rb'name="_csrf" value="([^"]+)"', r.data).group(1).decode()
c2.post("/signup", data={"_csrf": t, "name": "Plain Jane", "email": "jane@example.com",
                         "password": "jane-long-password", "confirm": "jane-long-password"})
jane = repo.user_by_email("jane@example.com")
payload = {
    "output": create_dep["output"],
    "outputs": outputs_of(create_dep),
    "inputs": [{"id": "adm-create", "property": "n_clicks", "value": 1}],
    "changedPropIds": ["adm-create.n_clicks"],
    "state": [{"id": "adm-new-name", "property": "value", "value": "Sneaky"},
              {"id": "adm-new-email", "property": "value", "value": "sneaky@example.com"},
              {"id": "adm-new-pass", "property": "value", "value": "a-long-password-z"},
              {"id": "adm-new-role", "property": "value", "value": "admin"},
              {"id": "adm-bump", "property": "data", "value": 0}],
}
r = c2.post("/app/_dash-update-component", data=json.dumps(payload),
            content_type="application/json")
blocked = repo.user_by_email("sneaky@example.com") is None
ran += 1
if blocked:
    print("  ok   non-admin create_user blocked server-side")
else:
    print("  FAIL non-admin created an account!")
    failures.append("non-admin create blocked")

print("\n== anonymous cannot run callbacks ==")
c3 = flask_app.test_client()
r = c3.post("/app/_dash-update-component", data=json.dumps(payload),
            content_type="application/json")
ran += 1
if r.status_code == 401:
    print("  ok   anonymous callback returns 401")
else:
    print(f"  FAIL anonymous callback returned {r.status_code}")
    failures.append("anonymous callback blocked")

print(f"\n{'=' * 60}\n{ran - len(failures)}/{ran} callback checks passed")
if failures:
    print("FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("ALL GREEN")
