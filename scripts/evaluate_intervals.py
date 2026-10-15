"""Compare band calibration on four chronological 28-day windows."""
import argparse
import json
from datetime import date
from pathlib import Path

from serviceforecast.intervals import compare
from serviceforecast.model import select_model


def evaluate(source):
    days = [date.fromisoformat(d) for d in source['dates']]
    n = len(days)
    if n < 500:
        raise ValueError('At least 500 daily observations required for the four-window study')
    result = {}
    for name, values in source['series'].items():
        windows = []
        for end in range(n-84, n+1, 28):
            start = end-28
            chosen, _, _ = select_model(values, days, start-84)
            windows.append({'start': days[start].isoformat(), 'end': days[end-1].isoformat(),
                            'model': chosen, **compare(chosen, values, days, start, end)})
        result[name] = windows
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('build/forecast/source.json'))
    parser.add_argument('--output', type=Path, default=Path('build/forecast/interval-study.json'))
    args = parser.parse_args()
    results = evaluate(json.loads(args.source.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, allow_nan=False), encoding='utf-8')
    print(f'Saved interval comparison to {args.output}')
