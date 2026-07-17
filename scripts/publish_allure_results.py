#!/usr/bin/env python3
"""Upload raw Allure result JSON from CI to the test-management platform."""
import argparse
import io
import json
from pathlib import Path
import sys
import zipfile

import requests


def build_archive(results_dir: Path) -> bytes:
    result_files = sorted(results_dir.rglob("*-result.json"))
    if not result_files:
        raise ValueError("No Allure *-result.json files found in %s" % results_dir)

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in result_files:
            archive.write(path, path.relative_to(results_dir).as_posix())
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload Allure results to test management")
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-number", default="")
    parser.add_argument("--workflow", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--commit-sha", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--report-url", default="")
    parser.add_argument("--env-config-id", default="")
    parser.add_argument("--module-name", default="API 自动化回归")
    parser.add_argument("--domain-name", default="GitHub CI")
    parser.add_argument("--test-type", default="integration")
    parser.add_argument("--return-code", default="")
    args = parser.parse_args()

    archive = build_archive(Path(args.results_dir))
    metadata = {
        "repository": args.repository,
        "run_id": args.run_id,
        "run_number": args.run_number,
        "workflow": args.workflow,
        "ref": args.ref,
        "commit_sha": args.commit_sha,
        "base_url": args.base_url,
        "report_url": args.report_url,
        "env_config_id": args.env_config_id,
        "module_name": args.module_name,
        "domain_name": args.domain_name,
        "test_type": args.test_type,
        "return_code": args.return_code,
    }
    response = requests.post(
        args.endpoint,
        data={"metadata": json.dumps(metadata, ensure_ascii=False)},
        files={"report_file": ("allure-results.zip", archive, "application/zip")},
        headers={"X-CI-Report-Token": args.token},
        timeout=90,
    )
    if not response.ok:
        raise RuntimeError("Report upload failed: HTTP %s %s" % (response.status_code, response.text[:1000]))

    payload = response.json()
    if payload.get("code") != 20000:
        raise RuntimeError("Report upload rejected: %s" % payload)
    data = payload.get("data") or {}
    print(
        "Allure report uploaded: record_id=%s created=%s total=%s failed=%s"
        % (data.get("id"), data.get("created"), data.get("total_count"), data.get("failed_count"))
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Failed to publish Allure results: %s" % exc, file=sys.stderr)
        raise SystemExit(1)
