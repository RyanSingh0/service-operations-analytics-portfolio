"""Publish shared visual assets using the existing local administration session."""
import json
import time
from pathlib import Path

import boto3

from release_forecast import release

ROOT = Path(__file__).resolve().parents[1]


def main():
    session = boto3.Session(profile_name='serviceops', region_name='us-east-1')
    config = json.loads((ROOT/'deployment.local.json').read_text())
    if session.client('sts').get_caller_identity()['Account'] != '344717726518':
        raise ValueError('Unexpected deployment account')
    lease = session.client('dynamodb').get_item(TableName=config['RunTable'],
        Key={'pk': {'S': 'forecast-lock'}}, ConsistentRead=True).get('Item', {})
    if int(lease.get('expires', {}).get('N', '0')) > time.time():
        raise RuntimeError('Forecast active; retry after completion')
    s3 = session.client('s3')
    def upload(name):
        content_type = {'.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html',
                        '.png': 'image/png'}[Path(name).suffix]
        s3.put_object(Bucket=config['WebBucket'], Key=name, Body=(ROOT/'dashboard'/name).read_bytes(),
                      ContentType=content_type, CacheControl='max-age=60, must-revalidate')
    for name in ('charts.js', 'theme.css', 'health.js', 'social-preview.png'):
        upload(name)
    release(session, config)
    for name in ('app.js', 'index.html', 'resolution/app.js', 'resolution/index.html'):
        upload(name)
    report = s3.get_object(Bucket=config['WebBucket'], Key='forecast/report.json')['Body'].read()
    parsed = json.loads(report)
    assert all(len(s['diagnostics']['heatmap']) == 21 for s in parsed['series'].values())
    (ROOT/'build/forecast/report.json').write_bytes(report)
    for name in ('source.json', 'weather.json'):
        (ROOT/'build/forecast'/name).write_bytes(s3.get_object(
            Bucket=config['DataBucket'], Key='forecast/'+name)['Body'].read())
    print('Published shared assets and verified six forecast diagnostic series.')


if __name__ == '__main__':
    main()
