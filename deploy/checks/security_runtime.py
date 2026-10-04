"""Non-destructive HTTPS security checks using a dedicated test account.

Requires httpx. Creates and deletes one synthetic card; never prints credentials.
The optional rate-limit check consumes the test peer's WebAuthn finish quota.
"""

import argparse
import csv
import io
import json
import ssl
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", type=Path, required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--url", default="https://127.0.0.1")
    parser.add_argument("--hostname", default="meishidb.test")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check-rate-limit", action="store_true")
    args = parser.parse_args()
    account = json.loads(args.accounts.read_text())
    checks = []

    def check(name, passed, response):
        checks.append(dict(name=name, passed=bool(passed), status=response.status_code))

    with httpx.Client(
        base_url=args.url, headers={"Host": args.hostname},
        verify=ssl.create_default_context(cafile=str(args.ca)), timeout=120,
    ) as client:
        def request(method, path, **kwargs):
            return client.request(method, "/api" + path,
                                  extensions={"sni_hostname": args.hostname}, **kwargs)

        response = request("POST", "/auth/login", json={
            "email": account["admin_email"], "password": account["password"],
        })
        response.raise_for_status()
        check("secure_session_cookie", all(value in response.headers.get("set-cookie", "")
              for value in ("Secure", "HttpOnly", "SameSite=lax")), response)
        response = request("GET", "/auth/me")
        check("private_api_no_store", "no-store" in response.headers.get("cache-control", ""), response)
        response = request("POST", "/cards", json={"fields": {
            "person_name": "Runtime security synthetic", "company": "=1+1",
            "title": "Engineer\r\nX-INJECTED:yes",
        }})
        response.raise_for_status()
        path = "/cards/" + response.json()["id"]
        try:
            for name, headers in (
                ("untrusted_origin", {"Origin": "https://untrusted.example"}),
                ("untrusted_referer", {"Referer": "https://untrusted.example/page"}),
                ("cross_site_fetch", {"Sec-Fetch-Site": "cross-site"}),
            ):
                response = request("PATCH", path, headers=headers,
                                   json={"fields": {"person_name": "Forbidden"}})
                check(name, response.status_code == 403, response)
            for name, value in (("nul_rejected", "test\0value"), ("surrogate_rejected", "test\ud800")):
                # Send escaped JSON, since httpx correctly refuses invalid UTF-8 strings.
                response = request("PATCH", path, content=json.dumps({"fields": {"company": value}}),
                                   headers={"Content-Type": "application/json"})
                check(name, response.status_code == 422, response)
            response = request("POST", path + "/image",
                               files={"image": ("fake.png", b"not an image", "image/png")},
                               data={"side": "front", "run_ocr": "false"})
            check("invalid_image_rejected", response.status_code == 400, response)
            response = request("GET", path)
            check("rejected_writes_preserve_data", response.status_code == 200 and
                  response.json()["fields"]["person_name"] == "Runtime security synthetic", response)
            for suffix in ("", "/image", "/memos"):
                response = request("GET", path + suffix, headers={"Cookie": ""})
                check("anonymous_rejected" + suffix, response.status_code == 401, response)
            for fmt in ("csv", "vcard"):
                response = request("GET", "/export/cards", params={"ids": path.split("/")[-1], "format": fmt})
                if fmt == "csv":
                    rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
                    safe = response.status_code == 200 and rows[0]["company"] == "'=1+1"
                else:
                    safe = response.status_code == 200 and "\r\nX-INJECTED:" not in response.text
                check(fmt + "_injection_prevented", safe, response)
            if args.check_rate_limit:
                responses = [request("POST", "/webauthn/login/finish", json={}) for _ in range(21)]
                response = responses[-1]
                check("authentication_rate_limit", response.status_code == 429 and
                      int(response.headers.get("retry-after", "0")) > 0, response)
        finally:
            response = request("DELETE", path)
            response.raise_for_status()
    result = dict(passed=sum(row["passed"] for row in checks), total=len(checks), checks=checks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] == result["total"] else 1)


if __name__ == "__main__":
    main()
