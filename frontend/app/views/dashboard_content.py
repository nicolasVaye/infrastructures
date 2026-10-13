"""Dashboard page: KPI overview, revenue trend, order status and throughput charts."""

from nicegui import ui
import services.dashboard_data as data
from components.notifications import notify
from services.i18n import t


# Shared EChart base style

from services.theme import chart_colors as _cc

_GRID    = {'left': '3%', 'right': '3%', 'bottom': '3%', 'top': '12%', 'containLabel': True}

def _TT_AXIS():
    c = _cc()
    return {'trigger': 'axis', 'backgroundColor': c['tt_bg'], 'borderColor': c['tt_border'],
            'textStyle': {'color': c['tt_fg'], 'fontSize': 12}}

def _TT_ITEM():
    c = _cc()
    return {'trigger': 'item', 'backgroundColor': c['tt_bg'], 'borderColor': c['tt_border'],
            'textStyle': {'color': c['tt_fg'], 'fontSize': 12}}

def _LEGEND():
    return {'textStyle': {'color': _cc()['label'], 'fontSize': 12}}


# KPI helpers

def _kpi_card(container, label: str, icon: str, key: str, kpis: dict) -> dict:
    v    = kpis[key]
    val  = v['value']
    d    = v['delta']
    unit = v['unit']
    refs = {}
    with container:
        with ui.element('div').classes('card flex-1').style('min-width:160px'):
            with ui.row().classes('items-center justify-between mb-3'):
                ui.label(label).classes('label-text')
                ui.icon(icon).style('font-size:1.2rem;color:var(--muted-fg)')
            refs['value'] = ui.label(f"{unit}{val:,}").classes('text-2xl font-bold')
            delta_color  = 'text-success' if d >= 0 else 'text-danger'
            delta_prefix = '▲' if d >= 0 else '▼'
            refs['delta'] = ui.label(f"{delta_prefix} {abs(d)}{unit} {t('dashboard.vs_yesterday')}").classes(f'text-xs {delta_color} mt-1')
    return refs


# Chart builders

def _revenue_chart(rev: dict):
    return ui.echart({
        'tooltip': {**_TT_AXIS(), 'axisPointer': {'type': 'cross', 'label': {'backgroundColor': '#18181b'}}},
        'legend': {**_LEGEND(), 'data': [t('dashboard.series.revenue'), t('dashboard.series.forecast')], 'left': 'center', 'top': 0},
        'grid': {'left': '3%', 'right': '3%', 'bottom': '3%', 'top': '14%', 'containLabel': True},
        'xAxis': {'type': 'category', 'boundaryGap': False, 'data': rev['days'],
                  'axisLine': {'lineStyle': {'color': _cc()['axis']}},
                  'axisTick': {'show': False},
                  'axisLabel': {'color': _cc()['label'], 'fontSize': 11}},
        'yAxis': {'type': 'value',
                  'splitLine': {'lineStyle': {'color': _cc()['split'], 'type': 'dashed'}},
                  'axisLabel': {':formatter': 'v => "€" + v.toLocaleString()', 'color': _cc()['label'], 'fontSize': 11}},
        'series': [
            {
                'name': t('dashboard.series.revenue'), 'type': 'line', 'smooth': 0.3,
                'data': rev['revenue'],
                'symbol': 'circle', 'symbolSize': 6,
                'lineStyle': {'width': 2.5, 'color': '#64748b'},
                'itemStyle': {'color': '#64748b', 'borderWidth': 2, 'borderColor': _cc()['symbol']},
                'emphasis': {'focus': 'series'},
            },
            {
                'name': t('dashboard.series.forecast'), 'type': 'line', 'smooth': 0.3,
                'data': rev['forecast'], 'symbol': 'diamond', 'symbolSize': 7,
                'lineStyle': {'width': 2.5, 'type': 'dashed', 'color': '#60a5fa'},
                'itemStyle': {'color': '#60a5fa', 'borderWidth': 2, 'borderColor': _cc()['symbol']},
                'emphasis': {'focus': 'series'},
            },
        ],
    }).classes('w-full').style('height:300px')


def _donut_chart(status: list):
    return ui.echart({
        'tooltip': _TT_ITEM(),
        'legend': {**_LEGEND(), 'orient': 'horizontal', 'bottom': 0, 'left': 'center',
                   'itemWidth': 10, 'itemHeight': 10, 'itemGap': 12},
        'color': ['#4ade80', '#fbbf24', '#60a5fa', '#f87171'],
        'series': [{
            'type': 'pie', 'radius': ['44%', '68%'], 'center': ['50%', '44%'],
            'avoidLabelOverlap': False,
            'label': {'show': False},
            'emphasis': {'label': {'show': True, 'fontSize': 13, 'fontWeight': 'bold', 'color': _cc()['emph']}},
            'labelLine': {'show': False},
            'data': status,
        }],
    }).classes('w-full').style('height:300px')


def _bar_chart(orders: dict):
    return ui.echart({
        'tooltip': _TT_AXIS(),
        'legend': {**_LEGEND(), 'data': [t('dashboard.series.completed'), t('dashboard.series.returned')], 'left': 'center', 'top': 0},
        'grid': _GRID,
        'xAxis': {'type': 'category', 'data': orders['days'],
                  'axisLine': {'lineStyle': {'color': _cc()['axis']}},
                  'axisLabel': {'color': _cc()['label'], 'fontSize': 11}},
        'yAxis': {'type': 'value', 'splitLine': {'lineStyle': {'color': _cc()['split']}},
                  'axisLabel': {'color': _cc()['label'], 'fontSize': 11}},
        'series': [
            {'name': t('dashboard.series.completed'), 'type': 'bar', 'data': orders['completed'],
             'barMaxWidth': 32, 'itemStyle': {'color': '#38bdf8', 'borderRadius': [4, 4, 0, 0]}},
            {'name': t('dashboard.series.returned'), 'type': 'bar', 'data': orders['returned'],
             'barMaxWidth': 32, 'itemStyle': {'color': '#fb7185', 'borderRadius': [4, 4, 0, 0]}},
        ],
    }).classes('w-full').style('height:240px')


def _area_chart(tp: dict):
    return ui.echart({
        'tooltip': {**_TT_AXIS(), 'axisPointer': {'type': 'cross', 'label': {'backgroundColor': '#4ade80'}}},
        'legend': {**_LEGEND(), 'data': [t('dashboard.series.actual'), t('dashboard.series.target')], 'left': 'center', 'top': 0},
        'grid': _GRID,
        'xAxis': {'type': 'category', 'boundaryGap': False, 'data': tp['hours'],
                  'axisLabel': {'color': _cc()['label'], 'fontSize': 10, 'interval': 2},
                  'axisLine': {'lineStyle': {'color': _cc()['axis']}}},
        'yAxis': {'type': 'value', 'min': 50, 'max': 100,
                  'splitLine': {'lineStyle': {'color': _cc()['split']}},
                  'axisLabel': {':formatter': 'v => v + "%"', 'color': _cc()['label'], 'fontSize': 11}},
        'series': [
            {'name': t('dashboard.series.actual'), 'type': 'line', 'smooth': True,
             'data': tp['actual'], 'symbol': 'none',
             'lineStyle': {'width': 2, 'color': '#4ade80'},
             'itemStyle': {'color': '#4ade80'},
             'areaStyle': {'color': '#4ade80', 'opacity': 0.18}},
            {'name': t('dashboard.series.target'), 'type': 'line',
             'data': tp['target'], 'symbol': 'none',
             'lineStyle': {'width': 1.5, 'type': 'dashed', 'color': '#fbbf24'},
             'itemStyle': {'color': '#fbbf24'}},
        ],
    }).classes('w-full').style('height:240px')


def content() -> None:

    # Header
    with ui.row().classes('w-full items-center justify-between mb-2'):
        with ui.column().classes('gap-0'):
            ui.label(t('dashboard.title')).classes('page-title')
            ui.label(t('dashboard.subtitle')).classes('text-sm text-muted')
        refresh_btn = ui.button(t('dashboard.refresh'), icon='refresh', color='white') \
            .props('flat no-caps').classes('button button-outline')

    ui.element('div').classes('divider mb-4')

    # KPI cards
    kpis = data.get_kpis()
    kpi_refs = {}
    with ui.row().classes('w-full gap-4 flex-wrap mb-4') as kpi_row:
        kpi_refs['orders']     = _kpi_card(kpi_row, t('dashboard.kpi.orders'),       'receipt_long',            'orders',     kpis)
        kpi_refs['revenue']    = _kpi_card(kpi_row, t('dashboard.kpi.revenue'),            'euro',                    'revenue',    kpis)
        kpi_refs['shipments']  = _kpi_card(kpi_row, t('dashboard.kpi.shipments'),   'local_shipping',          'shipments',  kpis)
        kpi_refs['throughput'] = _kpi_card(kpi_row, t('dashboard.kpi.throughput'),    'precision_manufacturing', 'throughput', kpis)

    # Revenue trend + order status
    with ui.row().classes('w-full gap-4 flex-wrap mb-4'):
        with ui.element('div').classes('card flex-1').style('min-width:320px'):
            with ui.row().classes('items-center justify-between mb-3'):
                ui.label(t('dashboard.revenue_trend')).classes('section-title')
                ui.label(t('dashboard.last_30_days')).classes('text-xs text-muted')
            rev_data  = data.get_revenue_series()
            rev_chart = _revenue_chart(rev_data)

        with ui.element('div').classes('card').style('min-width:240px;width:280px'):
            with ui.row().classes('items-center justify-between mb-3'):
                ui.label(t('dashboard.order_status')).classes('section-title')
                ui.label(t('dashboard.this_month')).classes('text-xs text-muted')
            status_data  = data.get_order_status()
            donut_chart  = _donut_chart(status_data)

    # Daily orders + throughput
    with ui.row().classes('w-full gap-4 flex-wrap mb-4'):
        with ui.element('div').classes('card flex-1').style('min-width:280px'):
            with ui.row().classes('items-center justify-between mb-3'):
                ui.label(t('dashboard.daily_orders')).classes('section-title')
                ui.label(t('dashboard.last_7_days')).classes('text-xs text-muted')
            order_data = data.get_daily_orders()
            bar_chart  = _bar_chart(order_data)

        with ui.element('div').classes('card flex-1').style('min-width:280px'):
            with ui.row().classes('items-center justify-between mb-3'):
                ui.label(t('dashboard.throughput')).classes('section-title')
                ui.label(t('dashboard.last_24h')).classes('text-xs text-muted')
            tp_data    = data.get_throughput_series()
            area_chart = _area_chart(tp_data)

    # Refresh handler
    def refresh() -> None:
        # KPIs
        new_kpis = data.get_kpis()
        for key, refs in kpi_refs.items():
            v    = new_kpis[key]
            unit = v['unit']
            val  = v['value']
            d    = v['delta']
            refs['value'].set_text(f"{unit}{val:,}")
            delta_color  = 'text-success' if d >= 0 else 'text-danger'
            delta_prefix = '▲' if d >= 0 else '▼'
            refs['delta'].set_text(f"{delta_prefix} {abs(d)}{unit} {t('dashboard.vs_yesterday')}")
            refs['delta'].classes(replace=f'text-xs {delta_color} mt-1')

        # Revenue chart
        rev = data.get_revenue_series()
        rev_chart.options['xAxis']['data']     = rev['days']
        rev_chart.options['series'][0]['data'] = rev['revenue']
        rev_chart.options['series'][1]['data'] = rev['forecast']
        rev_chart.update()

        # Donut
        donut_chart.options['series'][0]['data'] = data.get_order_status()
        donut_chart.update()

        # Bar chart
        orders = data.get_daily_orders()
        bar_chart.options['xAxis']['data']     = orders['days']
        bar_chart.options['series'][0]['data'] = orders['completed']
        bar_chart.options['series'][1]['data'] = orders['returned']
        bar_chart.update()

        # Area chart
        tp = data.get_throughput_series()
        area_chart.options['xAxis']['data']     = tp['hours']
        area_chart.options['series'][0]['data'] = tp['actual']
        area_chart.options['series'][1]['data'] = tp['target']
        area_chart.update()

        notify(t('dashboard.refreshed'), type='positive', title=t('dashboard.refresh'))

    refresh_btn.on('click', refresh)