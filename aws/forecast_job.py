import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import boto3

from serviceforecast.model import build
from serviceforecast.source import fetch


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
    keys = s3.list_objects_v2(Bucket=bucket, Prefix='forecast/source.json', MaxKeys=1).get('Contents', [])
    exists = any(item['Key'] == 'forecast/source.json' for item in keys)
    previous = json.loads(s3.get_object(Bucket=bucket, Key='forecast/source.json')['Body'].read()) if exists else None
    source = fetch(previous=previous)
    report = build(source)
    data = json.dumps(report, allow_nan=False).encode()
    if event.get('failure_drill'):
        raise ValueError('Controlled forecast failure before publication')
    verify_lease()
    attempt = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    s3.put_object(Bucket=bucket, Key=f'forecast/runs/{attempt}/report.json', Body=data,
                  ContentType='application/json')
    s3.put_object(Bucket=bucket, Key='forecast/source.json', Body=json.dumps(source).encode(),
                  ContentType='application/json')
    s3.put_object(Bucket=website, Key='forecast/report.json', Body=data,
                  ContentType='application/json', CacheControl='no-cache, max-age=0, must-revalidate')
    metrics.put_metric_data(Namespace='ServiceForecast', MetricData=[
        {'MetricName': 'Published', 'Value': 1, 'Unit': 'Count',
         'Dimensions': [{'Name': 'Project', 'Value': 'serviceops-demo'}]},
        {'MetricName': 'SourceLagDays', 'Value': source['source']['reporting_lag_days'], 'Unit': 'Count',
         'Dimensions': [{'Name': 'Project', 'Value': 'serviceops-demo'}]}])
    return {'status': 'published', 'attempt': attempt, 'through': source['source']['data_through'],
            'series': len(report['series'])}
