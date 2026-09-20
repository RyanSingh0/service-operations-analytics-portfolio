import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import boto3

from deploy import deploy_stack, outputs


def main():
    parser = argparse.ArgumentParser(description="Configure repository-scoped OIDC and deployment variables")
    parser.add_argument("--repo", required=True, help="Owner/repository explicitly authorized for AWS releases")
    parser.add_argument("--profile", default="serviceops")
    parser.add_argument("--stack", default="serviceops-demo")
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN")
    if not token:
        credential = subprocess.run(["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True, check=True,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        fields = dict(line.split("=", 1) for line in credential.stdout.splitlines() if "=" in line)
        token = fields["password"]

    def api(path, method="GET", body=None):
        request = urllib.request.Request("https://api.github.com/repos/" + args.repo + path,
            method=method, data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "User-Agent": "serviceops-setup"})
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            return json.loads(content) if content else {}

    repo = api("")
    subject = f"repository_id:{repo['id']}:repository_owner_id:{repo['owner']['id']}:ref:refs/heads/main"
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    cf = session.client("cloudformation")
    config = outputs(cf.describe_stacks(StackName=args.stack)["Stacks"][0])
    parameters = {key: config[key] for key in ["DataBucket", "WebBucket", "CoordinatorName",
                  "GlueJob", "GlueRoleArn", "RunTable", "WorkflowArn"]}
    parameters["Subject"] = subject
    deployed = outputs(deploy_stack(cf, args.stack + "-github", Path(__file__).resolve().parents[1]
                                    / "infrastructure/github-deploy.yaml", parameters))
    api("/actions/oidc/customization/sub", "PUT", {"use_default": False,
        "include_claim_keys": ["repository_id", "repository_owner_id", "ref"]})
    variables = {"AWS_DEPLOY_ROLE": deployed["DeployRoleArn"], "DATA_BUCKET": config["DataBucket"],
        "WEB_BUCKET": config["WebBucket"], "COORDINATOR_NAME": config["CoordinatorName"],
        "GLUE_JOB": config["GlueJob"], "RUN_TABLE": config["RunTable"], "WORKFLOW_ARN": config["WorkflowArn"]}
    for name, value in variables.items():
        try:
            api("/actions/variables/" + name)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            api("/actions/variables", "POST", {"name": name, "value": value})
        else:
            api("/actions/variables/" + name, "PATCH", {"name": name, "value": value})
    print(json.dumps({"repository": args.repo, "subject": subject,
                      "deploy_role": deployed["DeployRoleArn"], "variables_configured": list(variables)}))


if __name__ == "__main__":
    main()
