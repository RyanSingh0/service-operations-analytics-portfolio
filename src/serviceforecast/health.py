"""Small application run ledger; no additional monitoring permissions required."""
import json
import math


def summarize(rows):
    recent = sorted(rows, key=lambda r: r['started_at'])[-30:]
    complete = [r for r in recent if r['status'] in ('SUCCEEDED', 'FAILED')]
    durations = sorted(r['duration_seconds'] for r in complete)
    def percentile(p):
        return durations[max(0, math.ceil(len(durations) * p) - 1)] if durations else None
    return {'worker': 'NYC daily forecast', 'runs': recent,
            'completed': len(complete), 'success_rate_pct': round(100 * sum(r['status'] == 'SUCCEEDED'
                for r in complete) / len(complete), 1) if complete else None,
            'p50_seconds': percentile(.5), 'p95_seconds': percentile(.95),
            'note': 'Latest 30 recorded attempts before this publication. Started-only attempts have unknown outcomes; '
                    'lease rejections and failures before the ledger write are excluded. Runtime includes application work, '
                    'not Lambda initialization. Current run appears on the next successful publication.'}


def read(s3, bucket, exclude=None):
    keys = []
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix='forecast/health/'):
        keys.extend(row['Key'] for row in page.get('Contents', []))
    rows = [json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read()) for key in sorted(keys)[-31:]]
    return summarize([r for r in rows if r['id'] != exclude])


def write(s3, bucket, row):
    key = 'forecast/health/' + row['started_at'].replace(':', '') + '-' + row['id'] + '.json'
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(row).encode(), ContentType='application/json')
