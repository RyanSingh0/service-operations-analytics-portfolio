import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import boto3

from serviceforecast.model import build
from serviceforecast.source import fetch
from serviceforecast.monitor import record_publication, update
from serviceforecast.weather import fetch_weather
from usage_summary import summarize


def handler(event, context):
    ddb = boto3.client('dynamodb')
    table, owner = os.environ['RUN_TABLE'], context.aws_request_id
    ddb.put_item(TableName=table, Item={'pk': {'S': 'forecast-lock'}, 'owner': {'S': owner},
        'expires': {'N': str(int(time.time())+1200)}},
        ConditionExpression='attribute_not_exists(pk) OR expires < :now',
        ExpressionAttributeValues={':now': {'N': str(int(time.time()))}})
    try:
        return run(event, lambda: assert_owner(ddb, table, owner))
    finally:
        ddb.delete_item(TableName=table, Key={'pk': {'S': 'forecast-lock'}},
            ConditionExpression='#owner = :owner', ExpressionAttributeNames={'#owner': 'owner'},
            ExpressionAttributeValues={':owner': {'S': owner}})


def assert_owner(ddb, table, owner):
    item = ddb.get_item(TableName=table, Key={'pk': {'S': 'forecast-lock'}}, ConsistentRead=True).get('Item', {})
    if item.get('owner', {}).get('S') != owner or int(item.get('expires', {}).get('N', '0')) <= time.time():
        raise ValueError('Forecast lease lost before publication')


def run(event, verify_lease):
    s3 = boto3.client('s3')
    metrics = boto3.client('cloudwatch')
    bucket, website = os.environ['DATA_BUCKET'], os.environ['WEB_BUCKET']
    def read_optional(key):
        keys = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1).get('Contents', [])
        return json.loads(s3.get_object(Bucket=bucket, Key=key)['Body'].read()) if any(item['Key'] == key for item in keys) else None
    previous = read_optional('forecast/source.json')
    source = fetch(previous=previous)
    weather = None
    try:
        weather = fetch_weather(source, read_optional('forecast/weather.json'))
    except Exception as error:
        print('Optional weather unavailable:', type(error).__name__)
    report = build(source, weather=weather)
    if event.get('failure_drill'):
        raise ValueError('Controlled forecast failure before publication')
    verify_lease()
    state, monitoring = update(read_optional('forecast/monitor-state.json'), source, previous)
    report['monitoring'] = monitoring
    try:
        report['usage'] = summarize(boto3.client('dynamodb'))
    except Exception as error:
        report['usage'] = {'status': 'Usage temporarily unavailable', 'total_views': None}
        print('Usage summary unavailable:', type(error).__name__)
    data = json.dumps(report, allow_nan=False).encode()
    attempt = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    s3.put_object(Bucket=bucket, Key=f'forecast/runs/{attempt}/report.json', Body=data,
                  ContentType='application/json')
    s3.put_object(Bucket=bucket, Key='forecast/source.json', Body=json.dumps(source).encode(),
                  ContentType='application/json')
    s3.put_object(Bucket=website, Key='forecast/report.json', Body=data,
                  ContentType='application/json', CacheControl='no-cache, max-age=0, must-revalidate')
    # Only register predictions after the public write succeeds. A retry keeps the first daily issue.
    state = record_publication(state, report)
    s3.put_object(Bucket=bucket, Key='forecast/monitor-state.json', Body=json.dumps(state).encode(), ContentType='application/json')
    if weather:
        s3.put_object(Bucket=bucket, Key='forecast/weather.json', Body=json.dumps(weather).encode(), ContentType='application/json')
    metrics.put_metric_data(Namespace='ServiceForecast', MetricData=[
        {'MetricName': 'Undercoverage', 'Value': sum(s['status'] == 'Undercoverage warning' for s in monitoring['series'].values()),
         'Unit': 'Count', 'Dimensions': [{'Name': 'Project', 'Value': 'serviceops-demo'}]},
        {'MetricName': 'Published', 'Value': 1, 'Unit': 'Count',
         'Dimensions': [{'Name': 'Project', 'Value': 'serviceops-demo'}]},
        {'MetricName': 'SourceLagDays', 'Value': source['source']['reporting_lag_days'], 'Unit': 'Count',
         'Dimensions': [{'Name': 'Project', 'Value': 'serviceops-demo'}]}])
    return {'status': 'published', 'attempt': attempt, 'through': source['source']['data_through'],
            'series': len(report['series'])}
