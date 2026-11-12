"""Small server-side charts, drawn as plain HTML so pages need no chart library.

Colours come from a palette checked for colour-blind safety; every chart
also has a legend, a hover tooltip with the numbers, and a table on its page.
"""
import math

from markupsafe import Markup, escape

COLORS = {"Fabric": "#2a78d6", "Uniforms": "#eb6834", "Sarees": "#1baf7a", "Flags": "#eda100", "Dhoti & Safi": "#e87ba4"}


def _ticks(top: float) -> list[float]:
    step = 10 ** math.floor(math.log10(top / 4)) if top > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if top / (step * m) <= 5:
            step *= m
            break
    return [step * i for i in range(int(top // step) + 1)]


def stacked_columns(labels, series: dict, colors: dict = COLORS, forecast_from: int | None = None, height: int = 250,
                    unit: str = "₹ lakh", scale: float = 1e5, notes=(), show_totals=(), digits: int = 1) -> Markup:
    n = len(labels)
    totals = [sum(series[s][i] for s in series) / scale for i in range(n)]
    top = max(totals + [1e-9]) * 1.08
    ticks = _ticks(top)
    top = max(top, ticks[-1])
    px = height / top
    legend = "".join(f'<span><i style="background:{colors[s]}"></i>{escape(s)}</span>' for s in series)
    if forecast_from is not None:
        legend += '<span class="muted"><i class="hatch" style="background-color:#86868b"></i>Forecast</span>'
    grid = "".join(f'<div style="bottom:{t * px:.1f}px"><span>{t:g}</span></div>' for t in ticks)
    cols = []
    for i in range(n):
        fc = forecast_from is not None and i >= forecast_from
        segs, tip = [], []
        for s in series:
            v = series[s][i] / scale
            if v <= 0:
                continue
            segs.append(f'<div class="{"hatch" if fc else ""}" style="height:{max(1.5, v * px - 2):.1f}px;background-color:{colors[s]}"></div>')
        for s in reversed(list(series)):
            tip.append(f'<span><span><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:{colors[s]}"></i> {escape(s)}</span>'
                       f'<b style="display:inline;margin:0">{series[s][i] / scale:,.{digits}f}</b></span>')
        val = f'<div class="chart-val">{totals[i]:,.{digits}f}</div>' if i in show_totals else ""
        title = f'{escape(labels[i])}{" · forecast" if fc else ""}'
        cols.append(f'<div class="chart-col" tabindex="0" aria-label="{title}: {totals[i]:,.{digits}f} {unit}">'
                    f'<div class="tip"><b>{title}</b>{"".join(tip)}<span>Total<b style="display:inline;margin:0">{totals[i]:,.{digits}f}</b></span></div>'
                    f'{val}<div class="stackc">{"".join(segs)}</div></div>')
    note_html = ""
    if notes:
        parts = []
        for a, b, text in notes:
            left, width = a / n * 100, (b - a + 1) / n * 100
            parts.append(f'<div style="position:absolute;top:0;left:{left:.2f}%;width:{width:.2f}%;text-align:center;font-size:11px;color:var(--ink2)">'
                         f'<div style="border-bottom:1px solid var(--line);margin:0 6px;padding-bottom:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{escape(text)}</div></div>')
        note_html = f'<div style="position:relative;height:24px;margin-left:34px">{"".join(parts)}</div>'
    xs = "".join(f'<div style="{"font-style:italic" if forecast_from is not None and i >= forecast_from else ""}">{escape(l)}</div>' for i, l in enumerate(labels))
    return Markup(f'<div class="chart-legend">{legend}</div>{note_html}'
                  f'<div class="chart-plot" style="height:{height}px"><div class="chart-grid">{grid}</div>'
                  f'<div class="chart-bars">{"".join(cols)}</div></div><div class="chart-x">{xs}</div>'
                  f'<div class="muted" style="font-size:11px;margin:6px 0 0 34px">{escape(unit)}</div>')


def single_columns(labels, values, color="#2a78d6", height=180, unit="₹ lakh", scale=1e5, digits=1, label="Net profit") -> Markup:
    """Columns for one series that can go below zero (profit by month)."""
    vals = [v / scale for v in values]
    hi, lo = max(vals + [0]), min(vals + [0])
    span = (hi - lo) or 1
    px = height / span
    zero = -lo * px
    cols = []
    for l, v in zip(labels, vals):
        h = abs(v) * px
        c = color if v >= 0 else "#b64400"
        pos = f"bottom:{zero:.1f}px" if v >= 0 else f"bottom:{zero - h:.1f}px"
        rad = "4px 4px 0 0" if v >= 0 else "0 0 4px 4px"
        cols.append(f'<div class="chart-col" tabindex="0" aria-label="{escape(l)}: {v:,.{digits}f} {unit}">'
                    f'<div class="tip"><b>{escape(l)}</b><span>{escape(label)}<b style="display:inline;margin:0">{v:,.{digits}f}</b></span></div>'
                    f'<div style="position:absolute;left:22%;right:22%;{pos};height:{max(h, 1.5):.1f}px;background:{c};border-radius:{rad}"></div></div>')
    xs = "".join(f"<div>{escape(l)}</div>" for l in labels)
    return Markup(f'<div class="chart-plot" style="height:{height}px;padding-left:0"><div class="chart-grid" style="left:0">'
                  f'<div style="bottom:{zero:.1f}px;border-color:var(--line)"></div></div>'
                  f'<div class="chart-bars">{"".join(cols)}</div></div><div class="chart-x" style="padding-left:0">{xs}</div>'
                  f'<div class="muted" style="font-size:11px;margin-top:6px">{escape(unit)}{" · below the line = loss" if lo < 0 else ""}</div>')
