import argparse
import json
import shutil
from pathlib import Path

from serviceforecast.model import build
from serviceforecast.source import fetch
from serviceforecast.weather import fetch_weather
from serviceforecast.monitor import update

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description='Train and evaluate daily NYC 311 demand forecasts')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--output', default='build/forecast')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    source_file = output / 'source.json'
    source = fetch() if args.refresh or not source_file.exists() else json.loads(source_file.read_text())
    weather = None
    try:
        weather = fetch_weather(source)
    except Exception as error:
        print('Optional weather unavailable:', type(error).__name__, flush=True)
    report = build(source, weather=weather)
    _, report['monitoring'] = update(None, source)
    report['monitoring']['contract'] += ' Local generation does not count as a public issuance.'
    source_file.write_text(json.dumps(source))
    temporary = output / 'report.tmp'
    temporary.write_text(json.dumps(report, allow_nan=False))
    temporary.replace(output / 'report.json')
    for name in ('index.html', 'app.js'):
        if (ROOT / 'dashboard/forecast' / name).exists():
            shutil.copyfile(ROOT / 'dashboard/forecast' / name, output / name)
    print(json.dumps({'through': report['source']['data_through'],
        'series': {k: {'model': v['selected_model'], 'test': v['test_metrics'][v['selected_model']],
                      'coverage': v['test_interval_coverage_pct']} for k, v in report['series'].items()}}, indent=2))


if __name__ == '__main__':
    main()
