import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

from deploy import deploy_stack, outputs
from release import zip_files
from release_forecast import package, release

ROOT = Path(__file__).resolve().parents[1]


def main():
    session = boto3.Session(profile_name='serviceops', region_name='us-east-1')
    config = json.loads((ROOT / 'deployment.local.json').read_text())
    cf, s3 = session.client('cloudformation'), session.client('s3')
    lease = session.client('dynamodb').get_item(TableName=config['RunTable'],
        Key={'pk': {'S': 'forecast-lock'}}, ConsistentRead=True).get('Item', {})
    if int(lease.get('expires', {}).get('N', '0')) > time.time():
        raise RuntimeError('A forecast is active; retry deployment after it completes')
    data = zip_files([(ROOT / 'aws/page_views.py', 'handler.py')])
    key = 'artifacts/usage/'+hashlib.sha256(data).hexdigest()[:16]+'.zip'
    s3.put_object(Bucket=config['DataBucket'], Key=key, Body=data)
    website = outputs(cf.describe_stacks(StackName='serviceops-demo-website')['Stacks'][0])
    origin = website['WebsiteUrl'].rstrip('/')
    usage = outputs(deploy_stack(cf, 'serviceops-demo-usage', ROOT / 'infrastructure/usage.yaml',
        {'DataBucket': config['DataBucket'], 'CodeKey': key, 'WebsiteOrigin': origin}))
    deploy_stack(cf, 'serviceops-demo-website', ROOT / 'infrastructure/website.yaml',
                 {'AnalyticsOrigin': usage['UsageOrigin']})
    forecast = cf.describe_stacks(StackName='serviceops-demo-forecast')['Stacks'][0]
    params = {p['ParameterKey']: p['ParameterValue'] for p in forecast['Parameters']}
    resource = outputs(forecast)
    enabled = session.client('events').describe_rule(Name=resource['ForecastSchedule'])['State']
    data = package()
    key = 'artifacts/forecast/'+hashlib.sha256(data).hexdigest()[:16]+'.zip'
    s3.put_object(Bucket=config['DataBucket'], Key=key, Body=data)
    params.update({'CodeKey': key, 'UsageTable': usage['UsageTable'], 'ScheduleState': enabled,
                   'UsageStartDate': params.get('UsageStartDate') or datetime.now(timezone.utc).date().isoformat()})
    deploy_stack(cf, 'serviceops-demo-forecast', ROOT / 'infrastructure/forecast.yaml', params)
    release(session, config)
    s3.put_object(Bucket=config['WebBucket'], Key='analytics-config.json',
        Body=json.dumps({'endpoint': usage['UsageEndpoint']}).encode(), ContentType='application/json',
        CacheControl='max-age=60, must-revalidate')
    for name in ('usage.js', 'app.js', 'index.html', 'resolution/index.html'):
        s3.put_object(Bucket=config['WebBucket'], Key=name, Body=(ROOT / 'dashboard' / name).read_bytes(),
            ContentType='text/javascript; charset=utf-8' if name.endswith('.js') else 'text/html; charset=utf-8',
            CacheControl='max-age=60, must-revalidate')
    result = {'usage': usage, 'usage_started': params['UsageStartDate'], 'forecast_schedule_preserved': enabled}
    (ROOT / 'build/monitoring-deployment.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
