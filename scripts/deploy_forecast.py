import argparse
import hashlib
import json
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from deploy import deploy_stack
from release_forecast import package, release

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description='Provision and validate the daily forecast extension')
    parser.add_argument('--profile', default='serviceops')
    parser.add_argument('--enable', action='store_true')
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name='us-east-1')
    config = json.loads((ROOT / 'deployment.local.json').read_text())
    data = package()
    key = 'artifacts/forecast/'+hashlib.sha256(data).hexdigest()[:16]+'.zip'
    session.client('s3').put_object(Bucket=config['DataBucket'], Key=key, Body=data)
    resources = session.client('cloudformation').describe_stack_resources(StackName='serviceops-demo')['StackResources']
    topic = next(r['PhysicalResourceId'] for r in resources if r['LogicalResourceId'] == 'Alerts')
    cf = session.client('cloudformation')
    usage = {}
    try:
        old = cf.describe_stacks(StackName='serviceops-demo-forecast')['Stacks'][0]
    except ClientError as error:
        if 'does not exist' not in str(error):
            raise
    else:
        usage = {p['ParameterKey']: p['ParameterValue'] for p in old['Parameters']
                 if p['ParameterKey'] in {'UsageTable', 'UsageStartDate'}}
        if old['StackStatus'] == 'ROLLBACK_COMPLETE':
            remnants = cf.describe_stack_resources(StackName='serviceops-demo-forecast')['StackResources']
            if any(item['ResourceStatus'] != 'DELETE_COMPLETE' for item in remnants):
                raise ValueError('Failed stack still contains resources; inspect before removal')
            cf.delete_stack(StackName='serviceops-demo-forecast')
            cf.get_waiter('stack_delete_complete').wait(StackName='serviceops-demo-forecast')
    deploy_stack(session.client('cloudformation'), 'serviceops-demo-forecast', ROOT / 'infrastructure/forecast.yaml',
        {'DataBucket': config['DataBucket'], 'WebBucket': config['WebBucket'], 'CodeKey': key,
         'AlertTopicArn': topic, 'RunTable': config['RunTable'], 'ScheduleState': 'DISABLED', **usage})
    seed = ROOT / 'build/forecast/source.json'
    existing = session.client('s3').list_objects_v2(Bucket=config['DataBucket'], Prefix='forecast/source.json').get('Contents', [])
    if seed.exists() and not any(item['Key'] == 'forecast/source.json' for item in existing):
        session.client('s3').put_object(Bucket=config['DataBucket'], Key='forecast/source.json', Body=seed.read_bytes())
    release(session, config)
    if args.enable:
        resources = session.client('cloudformation').describe_stack_resources(StackName='serviceops-demo-forecast')['StackResources']
        name = next(r['PhysicalResourceId'] for r in resources if r['LogicalResourceId'] == 'Schedule')
        session.client('events').enable_rule(Name=name)
        assert session.client('events').describe_rule(Name=name)['State'] == 'ENABLED'
        print('Daily forecast schedule enabled at 18:00 UTC.')


if __name__ == '__main__':
    main()
