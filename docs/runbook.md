# Operations runbook

## Open the system

[Public dashboard](https://d17q1whdf7htno.cloudfront.net). CloudFront serves it independently of the laptop. The page checks for a newer aggregate report every five minutes and offers a Refresh button. A visit never starts a paid processing job.

## Run locally

From the repository root, create `.venv`, install `.[dev,aws]`, and download the source with `serviceops download`. On the prepared Windows project:

```powershell
./scripts/start-local.ps1 -Port 8766
```

This runs the incremental replay and serves `build/incremental`. With no cutoff argument, it reuses the locally committed cutoff or starts at 1 May 2016. The generated `index.html` also opens offline.

```powershell
./.venv/Scripts/python scripts/replay.py --as-of "2016-05-08 23:59:59"
./.venv/Scripts/python scripts/exercise_batches.py
```

Cloud and local outputs are independent. Use a fresh `--output` directory to inspect an older historical cutoff; a current directory rejects moving backward. Data, build outputs, environments, and credentials are excluded from Git.

## AWS access and infrastructure

Region: us-east-1. Stacks:

- `serviceops-demo-storage`: private data and artifact storage.
- `serviceops-demo`: processing, catalog, lease, schedule, alerts, and budget.
- `serviceops-demo-website`: private static origin and public HTTPS distribution.
- `serviceops-demo-github`: OIDC provider and restricted release role.

Use short-lived access from an authorized development identity. The initial bootstrap used the account session; ongoing GitHub releases use a restricted role. Prefer IAM Identity Center for future interactive administration.

```powershell
./scripts/aws.ps1 login --profile serviceops --region us-east-1
./.venv/Scripts/python scripts/deploy.py deploy --alert-email YOUR_EMAIL
./.venv/Scripts/python scripts/setup_github.py --repo YOUR_OWNER/YOUR_REPOSITORY
```

Infrastructure deployment disables the weekly schedule for validation. Re-enable it after verification. `setup_github.py` uses an existing authorized GitHub credential or `GH_TOKEN` in the environment; it does not save the credential. Its subject requires repository ID, owner ID, and main branch.

The OIDC provider is account-global. This account had no existing provider at setup. In another account with an existing provider, reference that provider rather than creating a duplicate.

## Automated application releases

Pushes to main run tests, linting, template checks, OIDC authentication, application release, and a cloud smoke execution at the current cutoff. Pull requests run validation without cloud deployment. Unchanged application artifacts are reused; an already-committed smoke request skips Glue.

The deployment role can update only the project coordinator/Glue job, upload artifacts and web assets, manage the pipeline lock key, read the committed pointer, and run named smoke executions. It cannot create infrastructure or administer IAM. CloudFormation changes remain an authorized administrative operation.

If a release conflicts with scheduled processing, rerun it after the active execution completes. Do not delete a live lease. Main-branch authors can change application behavior through service roles, so repository write access should remain limited to trusted maintainers.

## Schedule and monitoring

Weekly processing runs Monday at 15:00 UTC: 11 a.m. Eastern during daylight saving time and 10 a.m. standard time. Each success advances seven historical days. Daily monitoring checks whether pending batches exist and publication is over nine days old. Separate alarms watch failures and timeouts.

The SNS email subscription must be confirmed to receive pipeline alerts. Budget notifications are separate and do not cap spending.

```powershell
./.venv/Scripts/python scripts/deploy.py status
./.venv/Scripts/python scripts/deploy.py run --as-of "2016-05-15 23:59:59"
./.venv/Scripts/python scripts/deploy.py disable
./.venv/Scripts/python scripts/deploy.py enable
```

An explicit cloud cutoff cannot precede the committed cutoff. The fixed extract eventually reaches its final batch. The website then displays Replay complete and stays online; new real incidents require a source connector.

## Register new deliveries

Follow the [data contract](data-contract.md), preserving event identity and increasing revisions for corrections:

```powershell
./.venv/Scripts/python scripts/submit_batch.py delivery.jsonl.gz --batch-id delivery-001 --available-as-of "2016-05-15 23:59:59" --rows 100
```

Registration verifies content and conditionally updates the registry to prevent lost concurrent writes. If the registry condition fails, rerun after reading the updated state. Content-addressed batch objects can be reused. Delivery is scheduled, not immediately triggered by an upload.

## Failure and recovery

```powershell
./.venv/Scripts/python scripts/exercise_cloud.py --as-of "2016-05-15 23:59:59"
```

This intentionally fails before publication, verifies preservation of the committed pointer/public report, checks lease cleanup, recovers successfully, and verifies duplicate suppression. It consumes real Glue compute and advances the cutoff on recovery. Choose a cutoff at or after the current one.

For an unexpected failure:

1. Read Step Functions history and the failed task's error.
2. Inspect the attempt's private quality/quarantine files and Glue logs.
3. Correct input or code while preserving source/revision evidence.
4. Check `internal/committed.json`, the authoritative ingestion checkpoint.
5. Repeat the request. A committed run with a failed public copy is repaired without rerunning Glue.
6. Inspect catalog snapshot metadata if interruption happened during catalog updates. Multi-table catalog publication is not atomic.

The lease lasts one hour and belongs to the execution. Remove an abandoned lease only after verifying that its owner stopped, using a conditional owner match. Never force-remove a live lease.

## Verify and measure

First run the matching cutoff locally, then:

```powershell
./.venv/Scripts/python scripts/verify_deployment.py
./.venv/Scripts/python scripts/measure_cost.py
```

Verification compares summary, daily series, groups, profile, and cumulative quality counts. Last-run delivery statistics may differ after a code-only rebuild. Athena independently checks keys, dimension joins, durations, current history rows, and daily balance. Website checks confirm aggregate parity and blocked private paths.

## Connect a custom domain later

No domain was purchased. The CloudFront address is stable while the distribution remains deployed. For a domain you own:

1. Request an ACM certificate in us-east-1 and validate ownership using the supplied DNS record.
2. Add the domain to the distribution's `Aliases` and configure its ACM certificate, SNI, and TLS minimum in `website.yaml`.
3. Deploy the website stack and wait for completion.
4. Point a subdomain CNAME, or a supported apex ALIAS/ANAME, at the CloudFront hostname.
5. Verify HTTPS and update the README and launcher. Keep the origin private.

GitHub Pages is not required, and the repository can remain private while this website is public.

## Stop or remove

Disable the schedule to stop routine Glue runs. For full removal, disable/remove the distribution, remove the project stacks, and separately review retained buckets. Retain policies mean deleting stacks does not erase those objects. Confirm required retention before deleting data. If the OIDC provider is reused later, inspect dependent roles before removing it.
