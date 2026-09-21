import base64
import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

PAGES = {'it', 'forecast', 'resolution'}


def handler(event, context):
    body = event.get('body') or ''
    if event.get('isBase64Encoded'):
        try:
            body = base64.b64decode(body, validate=True).decode()
        except (ValueError, UnicodeDecodeError):
            return {'statusCode': 400, 'body': ''}
    if len(body) > 100:
        return {'statusCode': 400, 'body': ''}
    try:
        data = json.loads(body)
        page = data['page']
        if not isinstance(page, str) or page not in PAGES or set(data) != {'page'}:
            raise ValueError('Invalid page')
    except (ValueError, KeyError, TypeError):
        return {'statusCode': 400, 'body': ''}
    origin = event.get('headers', {}).get('origin')
    if origin != os.environ['WEBSITE_ORIGIN']:
        return {'statusCode': 403, 'body': ''}
    now = datetime.now(timezone.utc)
    try:
        boto3.client('dynamodb').update_item(TableName=os.environ['USAGE_TABLE'],
            Key={'day': {'S': now.date().isoformat()}},
            UpdateExpression='SET expires = if_not_exists(expires, :expiry) ADD #page :one, #total :one',
            ConditionExpression='attribute_not_exists(#total) OR #total < :cap',
            ExpressionAttributeNames={'#page': page, '#total': 'total'},
            ExpressionAttributeValues={':expiry': {'N': str(int((now+timedelta(days=90)).timestamp()))},
                ':one': {'N': '1'}, ':cap': {'N': '10000'}})
    except ClientError as error:
        if error.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return {'statusCode': 429, 'body': ''}
        raise
    return {'statusCode': 204, 'headers': {'Cache-Control': 'no-store'}, 'body': ''}
