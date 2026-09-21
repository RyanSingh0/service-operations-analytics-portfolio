import base64
import hashlib
import json
import os
from pathlib import Path

import boto3
from botocore.config import Config

from release import zip_files

ROOT = Path(__file__).resolve().parents[1]
FUNCTION = 'serviceops-demo-forecast'


def package():
    files = [(p, 'serviceforecast/'+p.name) for p in sorted((ROOT / 'src/serviceforecast').glob('*.py'))]
    return zip_files([(ROOT / 'aws/forecast_job.py', 'handler.py'),
                      (ROOT / 'aws/usage_summary.py', 'usage_summary.py'), *files])


def release(session, config):
    data = package()
    digest = hashlib.sha256(data).digest()
    key = 'artifacts/forecast/'+digest.hex()[:16]+'.zip'
    s3 = session.client('s3')
    s3.put_object(Bucket=config['DataBucket'], Key=key, Body=data)
    function = session.client('lambda', config=Config(read_timeout=930, retries={'max_attempts': 0}))
    current = function.get_function_configuration(FunctionName=FUNCTION)
    if current['CodeSha256'] != base64.b64encode(digest).decode():
        function.update_function_code(FunctionName=FUNCTION, S3Bucket=config['DataBucket'], S3Key=key)
        function.get_waiter('function_updated').wait(FunctionName=FUNCTION)
    result = function.invoke(FunctionName=FUNCTION, Payload=b'{}')
    payload = json.loads(result['Payload'].read())
    if result.get('FunctionError') or payload.get('status') != 'published':
        raise RuntimeError(payload)
    report = json.loads(s3.get_object(Bucket=config['WebBucket'], Key='forecast/report.json')['Body'].read())
    if len(report['series']) != 6 or not all(report['quality'][key] for key in
            ('unique_date_borough', 'complete_borough_days', 'nonnegative_counts', 'city_totals_reconcile')):
        raise ValueError('Forecast publication failed validation')
    for name, content_type in [('index.html', 'text/html; charset=utf-8'), ('app.js', 'text/javascript; charset=utf-8')]:
        s3.put_object(Bucket=config['WebBucket'], Key='forecast/'+name,
            Body=(ROOT / 'dashboard/forecast' / name).read_bytes(), ContentType=content_type,
            CacheControl='max-age=60, must-revalidate')
    print(json.dumps({'function': FUNCTION, 'version': digest.hex()[:16], **payload}), flush=True)


if __name__ == '__main__':
    release(boto3.Session(region_name='us-east-1'), {key: os.environ[key] for key in ('DataBucket', 'WebBucket')})
