"""HTTP smoke tests against a running container, including authorization negatives. Stdlib only.

    python scripts/smoke_test.py [--base http://127.0.0.1:3000] [--accounts secrets/accounts.txt]

--accounts is the "email password" file written by `scripts/set_password.py --generate --all`.
"""
import argparse
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
import uuid

NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://r2m.demo/seed")
MERIDIAN = uuid.uuid5(NS, "org:meridian")
failures = []


def client():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def call(opener, base, method, path, body=None, headers=None):
    req = urllib.request.Request(base + "/api/v1" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json", "x-r2m-csrf": "1", **(headers or {})})
    try:
        with opener.open(req, timeout=30) as r:  # Aiven round trips can stall for seconds
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, ok):
    print(("PASS " if ok else "FAIL ") + name)
    if not ok:
        failures.append(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:3000")
    ap.add_argument("--accounts", default="secrets/accounts.txt")
    args = ap.parse_args()
    base = args.base
    with open(args.accounts) as f:
        passwords = dict(line.split(maxsplit=1) for line in f.read().splitlines() if line.strip())

    def creds(email):
        return {"email": email, "password": passwords[email]}

    anon = client()
    check("live", call(anon, base, "GET", "/health/live")[0] == 200)
    check("ready", call(anon, base, "GET", "/health/ready")[0] == 200)
    check("me requires session", call(anon, base, "GET", "/me")[0] == 401)
    check("ingest requires SDK token", call(anon, base, "POST", "/ingest/events", {"events": []})[0] == 401)
    check("authorize rejects wrong token",
          call(anon, base, "POST", "/actions/authorize", {}, {"authorization": "Bearer nope"})[0] == 401)
    check("write without CSRF header refused",
          call(anon, base, "POST", "/auth/session", creds("ops@meridian.demo"), {"x-r2m-csrf": ""})[0] == 403)
    check("forged SDK token refused",
          call(anon, base, "POST", "/ingest/events", {"events": []}, {"authorization": "Bearer r2m_sdk_" + "0" * 32 + "_" + "f" * 64})[0] == 401)
    check("unknown account refused", call(anon, base, "POST", "/auth/session", {"email": "x@evil.test", "password": "x"})[0] == 401)
    check("wrong password refused",
          call(anon, base, "POST", "/auth/session", {"email": "ops@meridian.demo", "password": "wrong-password"})[0] == 401)

    meridian = client()
    check("meridian login", call(meridian, base, "POST", "/auth/session", creds("security@meridian.demo"))[0] == 200)
    status, agents = call(meridian, base, "GET", "/agents")
    check("meridian sees only its installations",
          status == 200 and agents["agents"] and all(a["customer_name"] == "Meridian Financial" for a in agents["agents"]))
    check("meridian overview", call(meridian, base, "GET", f"/organizations/{MERIDIAN}/overview")[0] == 200)

    northwind = client()
    call(northwind, base, "POST", "/auth/session", creds("security@northwind.demo"))
    check("northwind cannot read meridian overview", call(northwind, base, "GET", f"/organizations/{MERIDIAN}/overview")[0] == 404)
    if agents.get("agents"):
        inst = agents["agents"][0]
        check("northwind cannot read meridian evidence",
              call(northwind, base, "GET", f"/agents/{inst['agent_id']}/evidence?installation_id={inst['installation_id']}")[0] == 404)
    print(f"\n{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
