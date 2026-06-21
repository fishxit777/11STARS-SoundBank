#!/usr/bin/env python3
"""Read-only Render raw log watch for the standalone SoundBank service."""

import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


RENDER_LOGS_URL = "https://api.render.com/v1/logs"
DEFAULT_OWNER_ID = "tea-d7eh34q8qa3s73aif1g0"
DEFAULT_SERVICE_ID = "srv-d8rjsk0js32c73c4uhpg"
HTTP_5XX_STATUS_CODES = [str(code) for code in range(500, 600)]


class Runner:
    def __init__(self):
        self.passes = 0
        self.warnings = []
        self.failures = []

    def pass_(self, message):
        self.passes += 1
        print("[PASS] " + message)

    def warn(self, message):
        self.warnings.append(message)
        print("[WARN] " + message)

    def fail(self, message):
        self.failures.append(message)
        print("[FAIL] " + message)

    def expect_zero(self, count, message):
        if count == 0:
            self.pass_(message + ": 0")
        else:
            self.fail(message + ": " + str(count))


def utc_iso(hours_back):
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours_back)
    return start.isoformat().replace("+00:00", "Z"), now.isoformat().replace("+00:00", "Z")


def sanitize_message(message):
    text = str(message or "")
    patterns = [
        r"(?i)(access_token=)[^&\s\"]+",
        r"(?i)(admin_token=)[^&\s\"]+",
        r"(?i)(token=)[^&\s\"]+",
        r"(?i)(HashKey|HashIV|API_KEY|SECRET|PASSWORD|ADMIN_TOKEN)=[^&\s\"]+",
    ]
    for pattern in patterns:
        text = re.sub(pattern, r"\1[redacted]", text)
    return text[:260] + ("..." if len(text) > 260 else "")


def request_logs(api_key, owner_id, service_id, start_time, end_time, filters, timeout):
    params = {
        "ownerId": owner_id,
        "resource": service_id,
        "startTime": start_time,
        "endTime": end_time,
        "direction": "backward",
        "limit": "100",
    }
    params.update(filters)
    query = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        RENDER_LOGS_URL + "?" + query,
        headers={
            "Authorization": "Bearer " + api_key,
            "Accept": "application/json",
            "User-Agent": "11STARS-SoundBank-Standalone-RenderLogWatch/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            logs = data.get("logs") or []
            return resp.status, logs, bool(data.get("hasMore"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, [{"message": body, "timestamp": ""}], False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        return 0, [{"message": "transport failure: " + str(exc), "timestamp": ""}], False


def status_code_from_message(message):
    match = re.search(r"HTTP/[^\"]+\"\s+(\d{3})\s", str(message or ""))
    if not match:
        return None
    return int(match.group(1))


def main():
    parser = argparse.ArgumentParser(description="Read-only Render raw log watch for standalone SoundBank")
    parser.add_argument("--api-key", default=os.environ.get("RENDER_API_KEY", ""))
    parser.add_argument("--owner-id", default=os.environ.get("RENDER_OWNER_ID", DEFAULT_OWNER_ID))
    parser.add_argument("--service-id", default=os.environ.get("RENDER_SERVICE_ID", DEFAULT_SERVICE_ID))
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--show-samples", action="store_true")
    args = parser.parse_args()

    runner = Runner()
    if not args.api_key:
        runner.fail("--api-key or RENDER_API_KEY is required")
        print("Summary: passes=0 warnings=0 failures=1")
        return 1
    if args.hours <= 0:
        runner.fail("--hours must be greater than 0")
        print("Summary: passes=0 warnings=0 failures=1")
        return 1

    start_time, end_time = utc_iso(args.hours)
    checks = [
        ("error-level logs", {"level": "error"}),
        ("HTTP 5xx logs", {"statusCode": HTTP_5XX_STATUS_CODES}),
        ("Traceback logs", {"text": "Traceback"}),
        ("Exception logs", {"text": "Exception"}),
        ("CheckMac logs", {"text": "CheckMac"}),
    ]

    summary = {}
    for label, filters in checks:
        status, logs, has_more = request_logs(
            args.api_key,
            args.owner_id,
            args.service_id,
            start_time,
            end_time,
            filters,
            args.timeout,
        )
        if status != 200:
            runner.fail("Render logs API returned " + str(status) + " for " + label)
            if logs:
                runner.fail("Render logs API detail: " + sanitize_message(logs[0].get("message")))
            continue
        count = len(logs)
        summary[label] = count
        runner.expect_zero(count, label)
        if has_more and count:
            runner.warn(label + " has additional pages; investigate in dashboard/API")
        if args.show_samples and logs:
            for row in logs[:5]:
                print("[SAMPLE] " + str(row.get("timestamp") or "") + " " + sanitize_message(row.get("message")))

    status, ecpay_logs, ecpay_has_more = request_logs(
        args.api_key,
        args.owner_id,
        args.service_id,
        start_time,
        end_time,
        {"text": "ECPay"},
        args.timeout,
    )
    if status == 200:
        ecpay_5xx = [row for row in ecpay_logs if (status_code_from_message(row.get("message")) or 0) >= 500]
        runner.pass_("ECPay-related log matches fetched: " + str(len(ecpay_logs)))
        runner.expect_zero(len(ecpay_5xx), "ECPay-related HTTP 5xx samples")
        if ecpay_has_more:
            runner.warn("ECPay log query has additional pages; review dashboard/API for complete samples")
        if args.show_samples:
            for row in ecpay_logs[:5]:
                print("[SAMPLE] " + str(row.get("timestamp") or "") + " " + sanitize_message(row.get("message")))
    else:
        runner.fail("Render logs API returned " + str(status) + " for ECPay text query")

    print("Window: " + start_time + " to " + end_time)
    print("Counts: " + json.dumps(summary, ensure_ascii=True, sort_keys=True))
    print(
        "Summary: passes="
        + str(runner.passes)
        + " warnings="
        + str(len(runner.warnings))
        + " failures="
        + str(len(runner.failures))
    )
    return 1 if runner.failures else 0


if __name__ == "__main__":
    sys.exit(main())
