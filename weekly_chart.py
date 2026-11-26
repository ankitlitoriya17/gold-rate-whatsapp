"""Sunday recap: 30-day chart image (24K gold + silver) with a weekly summary caption.

Needs matplotlib (installed by the workflow). Built only from stored IBJA history.
"""
import io
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from daily_message import money, signed_money, pct
from rate_history import last_n_days

WEEKLY_DAY = 6  # Sunday


def is_weekly_day(day):
    return day.weekday() == WEEKLY_DAY


def _week_change(points, as_of):
    week = [(d, v) for d, v in points if (as_of - d).days < 7]
    start = [(d, v) for d, v in points if (as_of - d).days >= 7]
    if not week:
        return None
    first = start[-1] if start else week[0]
    last = week[-1]
    values = [first[1]] + [v for _, v in week]
    return {'from': first[1], 'to': last[1], 'delta': last[1] - first[1],
            'pct': (last[1] - first[1]) / first[1] * 100,
            'high': max(values), 'low': min(values), 'last_day': last[0]}


def weekly_caption(history, as_of):
    gold = last_n_days(history, 'gold24', as_of, 40)
    silver = last_n_days(history, 'silverkg', as_of, 40)
    g = _week_change(gold, as_of)
    if not g:
        return None
    start = as_of - timedelta(days=6)
    lines = [f"📅 *Hafte ka hisaab* · {start.strftime('%d %b')} – {as_of.strftime('%d %b')}", '',
             f"🟡 *24K:* {money(g['from'])} → {money(g['to'])} "
             f"({signed_money(g['delta'])}, {pct(g['pct'], 1)})",
             f"      Hafte ka high {money(g['high'])} · low {money(g['low'])}"]
    s = _week_change(silver, as_of)
    if s:
        lines.append(f"⚪ *Chandi:* {money(s['from'])} → {money(s['to'])}/kg "
                     f"({signed_money(s['delta'])}, {pct(s['pct'], 1)})")
    if g['last_day'] != as_of:
        lines.append(f"(Aakhri published rate {g['last_day'].strftime('%d %b')} ka)")
    lines += ['', '📊 Graph: pichhle 30 din — 24K gold aur chandi (IBJA)',
              '_Source: IBJA national benchmark. Investment salah nahi._']
    return '\n'.join(lines)


def render_chart(history, as_of):
    """PNG bytes, or None if there is too little data or matplotlib is missing."""
    gold = last_n_days(history, 'gold24', as_of, 30)
    silver = last_n_days(history, 'silverkg', as_of, 30)
    if len(gold) < 3:
        return None
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.ticker import FuncFormatter
    except ImportError:
        print('WEEKLY CHART: matplotlib not installed')
        return None

    def inr(x, _pos=None):
        return money(Decimal(str(round(x))))

    rows = 2 if len(silver) >= 3 else 1
    fig, axes = plt.subplots(rows, 1, figsize=(8, 4.2 * rows), dpi=150, squeeze=False)
    plots = [(axes[0][0], gold, '24K Gold · ₹ per 10g', '#C9962B')]
    if rows == 2:
        plots.append((axes[1][0], silver, 'Silver · ₹ per kg', '#7A8794'))
    for ax, points, title, color in plots:
        xs = [d for d, _ in points]
        ys = [float(v) for _, v in points]
        ax.plot(xs, ys, color=color, linewidth=2.4, marker='o', markersize=3.5)
        ax.fill_between(xs, ys, min(ys) - (max(ys) - min(ys)) * 0.18, color=color, alpha=0.12)
        ax.set_title(title, loc='left', fontsize=13, fontweight='bold', color='#222')
        ax.yaxis.set_major_formatter(FuncFormatter(inr))
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d %b'))
        ax.grid(axis='y', alpha=0.25)
        for side in ('top', 'right'):
            ax.spines[side].set_visible(False)
        ax.margins(y=0.18)
        hi = max(range(len(ys)), key=ys.__getitem__)
        lo = min(range(len(ys)), key=ys.__getitem__)
        marks = ((hi, 'High'), (lo, 'Low')) if ys[hi] != ys[lo] else ()
        for idx, label in marks:
            ax.annotate(f'{label} {inr(ys[idx])}', (xs[idx], ys[idx]),
                        textcoords='offset points', xytext=(0, 8 if label == 'High' else -14),
                        ha='center', fontsize=8.5, color='#444')
        ax.annotate(inr(ys[-1]), (xs[-1], ys[-1]), textcoords='offset points',
                    xytext=(6, 0), fontsize=9.5, fontweight='bold', color=color, va='center')
    fig.suptitle(f"IBJA benchmark · last 30 days · till {as_of.strftime('%d %b %Y')}",
                 fontsize=10, color='#666', x=0.99, ha='right')
    fig.tight_layout()
    buffer = io.BytesIO()
    fig.savefig(buffer, format='png', facecolor='white')
    plt.close(fig)
    return buffer.getvalue()


def media_base(api_base):
    """GREEN-API media host: 7103.api.greenapi.com -> 7103.media.greenapi.com."""
    override = (os.environ.get('GREEN_API_MEDIA_URL') or '').strip().rstrip('/')
    if override:
        host = urlparse(override).hostname or ''
        if urlparse(override).scheme == 'https' and host.endswith(('.green-api.com', '.greenapi.com')):
            return override
        raise ValueError('GREEN_API_MEDIA_URL must be an official GREEN-API HTTPS host')
    parsed = urlparse(api_base)
    host = parsed.hostname or ''
    parts = host.split('.')
    if 'api' in parts:
        parts[parts.index('api')] = 'media'
    else:
        parts.insert(0, 'media')
    return f'https://{".".join(parts)}'


def upload_hosts(api_base):
    """Media host first (documented for uploads), then the API host as a fallback."""
    hosts = [media_base(api_base)]
    if api_base.rstrip('/') not in hosts:
        hosts.append(api_base.rstrip('/'))
    return hosts


def upload_with_fallback(api_base, instance, token, chat_id, caption, filename, content):
    errors = []
    for host in upload_hosts(api_base):
        try:
            return upload_file(f'{host}/waInstance{instance}/sendFileByUpload/{token}',
                               chat_id, caption, filename, content)
        except RuntimeError as exc:
            # Only network-level failures are retried on the other host. An HTTP
            # error means the server got the request; do not risk a duplicate.
            if 'network failure' not in str(exc):
                raise
            errors.append(f'{host.split("//", 1)[1]}: {exc}')
            print('UPLOAD: ' + errors[-1])
    raise RuntimeError('GREEN-API upload failed on all hosts: ' + ' | '.join(errors))


def upload_file(url, chat_id, caption, filename, content):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for name, value in (('chatId', chat_id), ('caption', caption), ('fileName', filename)):
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(value.encode('utf-8') + b'\r\n')
    body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
               f'filename="{filename}"\r\nContent-Type: image/png\r\n\r\n'.encode())
    body.write(content + b'\r\n')
    body.write(f'--{boundary}--\r\n'.encode())
    request = Request(url, data=body.getvalue(), method='POST',
                      headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        with urlopen(request, timeout=60) as response:
            import json
            return json.loads(response.read(100000).decode('utf-8'))
    except HTTPError as exc:
        raise RuntimeError(f'GREEN-API upload returned HTTP {exc.code}') from None
    except URLError as exc:
        raise RuntimeError(f'GREEN-API upload network failure ({exc.reason})'
                           .replace(url.rsplit('/', 1)[-1], '***')) from None
