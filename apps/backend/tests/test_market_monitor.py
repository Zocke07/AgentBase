"""Market watch (Phase 18): quotes, alert rules, explanations and delivery.

Quotes come from a recorded Yahoo spark response and from small synthetic
ones; no test reaches the network. The launcher and the run list are fakes:
the watcher only starts runs and reads their status.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import httpx2
import pytest

from agentbase.events.store import EventStore
from agentbase.orchestrator.monitor import (
    MONITOR_PATH,
    MarketMonitor,
    MonitorConfig,
    MonitorConfigError,
    Quote,
    Seen,
    default_config_text,
    detect,
    parse_config,
    parse_spark,
    within_market_hours,
)
from agentbase.store.alerts import AlertStore
from agentbase.store.spaces import DEFAULT_SPACE_ID, SpaceStore

if TYPE_CHECKING:
    from agentbase.config import AppPaths
    from agentbase.events.types import Run
    from agentbase.orchestrator.launcher import RunLauncher
    from agentbase.store.db import Database

anyio_tests = pytest.mark.anyio
FIXTURES = Path(__file__).parent / "fixtures"
# Monday 2026-10-12, 11:54 New York time: the recorded quotes' minute.
RECORDED_AT = datetime(2026, 10, 12, 15, 54, 30, tzinfo=UTC)


# --- configuration ---------------------------------------------------------------


def test_the_starter_file_spells_out_every_setting_and_parses_back() -> None:
    text = default_config_text(enabled=True)
    config = parse_config(text)
    assert config.enabled is True
    assert config.indexes == ["^GSPC", "^IXIC", "^DJI"]
    assert (config.stock_move_pct, config.stock_jump_pct, config.index_move_pct) == (
        5,
        2.5,
        1.5,
    )
    assert set(json.loads(text)) == set(MonitorConfig.model_fields)


@pytest.mark.parametrize(
    ("text", "words"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "one JSON object"),
        ('{"enabled": true, "stock_mvoe_pct": 4}', "stock_mvoe_pct"),
        ('{"symbols": ["MU", "not a ticker"]}', "not a ticker"),
        ('{"check_every_minutes": 0}', "check_every_minutes"),
    ],
)
def test_a_file_it_cannot_use_is_refused_in_words(text: str, words: str) -> None:
    with pytest.raises(MonitorConfigError, match=words):
        parse_config(text)


@pytest.mark.parametrize(
    ("when", "open_"),
    [
        (datetime(2026, 10, 13, 7, 59, tzinfo=UTC), False),  # 03:59 New York
        (datetime(2026, 10, 13, 8, 0, tzinfo=UTC), True),  # 04:00, pre-market opens
        (datetime(2026, 10, 13, 23, 59, tzinfo=UTC), True),  # 19:59, after hours
        (datetime(2026, 10, 14, 0, 0, tzinfo=UTC), False),  # 20:00, closed
        (datetime(2026, 10, 17, 15, 0, tzinfo=UTC), False),  # Saturday
    ],
)
def test_it_watches_from_pre_market_to_after_hours_on_weekdays(
    when: datetime, open_: bool
) -> None:
    assert within_market_hours(when) is open_


# --- quotes ---------------------------------------------------------------------


def test_a_recorded_spark_response_gives_each_symbols_latest_price() -> None:
    quotes = parse_spark((FIXTURES / "yahoo_spark_mu_gspc.json").read_bytes())

    micron, sp500 = quotes["MU"], quotes["^GSPC"]
    assert micron.name == "Micron Technology, Inc."
    assert micron.is_index is False and sp500.is_index is True
    assert micron.previous_close == 1029.0 and micron.price == 998.18
    assert micron.session == "regular"
    # Pre-market bars count, so a move before the open is seen.
    assert micron.bars[0][0] == datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    assert sp500.previous_close == 7811.54


def test_the_recorded_quotes_alert_nothing_at_these_thresholds() -> None:
    # Micron was down 2.99%: under 5% from the close, and no 2.5% jump.
    quotes = parse_spark((FIXTURES / "yahoo_spark_mu_gspc.json").read_bytes())
    assert detect(quotes.values(), MonitorConfig(), Seen(), now=RECORDED_AT) == []
    sensitive = MonitorConfig(stock_move_pct=2.5)
    [alert] = detect(quotes.values(), sensitive, Seen(), now=RECORDED_AT)
    assert (alert.symbol, alert.kind, alert.direction) == ("MU", "move", "down")
    assert alert.change_pct == -3.0 and alert.level_pct == 2.5


def test_a_malformed_response_is_refused_and_a_malformed_symbol_left_out() -> None:
    from agentbase.tools.base import ToolExecutionError

    with pytest.raises(ToolExecutionError):
        parse_spark(b'{"spark": {}}')
    body = json.dumps({"spark": {"result": [{"symbol": "MU", "response": []}]}}).encode()
    assert parse_spark(body) == {}


# --- the alert rules --------------------------------------------------------------

NOW = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)  # Tuesday 11:00 New York


def _quote(
    symbol: str = "MU",
    *,
    price: float,
    previous: float = 100.0,
    regular: float | None = None,
    session: str | None = "regular",
    at: datetime = NOW,
    earlier: float | None = None,
    is_index: bool = False,
) -> Quote:
    """A quote with a bar 20 minutes earlier at ``earlier``; by default the price
    has not moved within the window, so only a move from the close can alert."""
    start = earlier if earlier is not None else price
    return Quote(
        symbol=symbol,
        name=None,
        is_index=is_index,
        price=price,
        quoted_at=at,
        session=session,  # type: ignore[arg-type]
        previous_close=previous,
        regular_close=regular,
        bars=((at - timedelta(minutes=20), start), (at, price)),
    )


def test_a_move_alerts_once_per_step_from_the_previous_close() -> None:
    config, seen = MonitorConfig(), Seen()

    [first] = detect([_quote(price=94.5)], config, seen, now=NOW)
    assert (first.kind, first.direction, first.level_pct) == ("move", "down", 5)
    assert first.reference == "previous_close" and first.change_pct == -5.5
    # The same level again tells the person nothing new.
    assert detect([_quote(price=94.0)], config, seen, now=NOW) == []
    # Past the next step, 5% + 3%, it does.
    [second] = detect([_quote(price=91.8)], config, seen, now=NOW)
    assert second.level_pct == 8 and second.change_pct == -8.2


def test_a_sudden_jump_alerts_and_again_once_its_window_has_passed() -> None:
    config, seen = MonitorConfig(), Seen()

    # 2.6% in 20 minutes, 3.1% on the day: a jump, not yet a 5% move.
    [alert] = detect([_quote(price=103.1, earlier=100.49)], config, seen, now=NOW)
    assert (alert.kind, alert.reference, alert.window_minutes) == ("jump", "window", 15)
    assert alert.direction == "up" and alert.change_pct == 2.6
    # Twenty minutes on, past the 15-minute window, a new jump alerts again.
    later = NOW + timedelta(minutes=20)
    again = _quote(price=104.1, previous=104.0, earlier=101.5, at=later)
    [next_jump] = detect([again], config, seen, now=later)
    assert next_jump.kind == "jump" and next_jump.change_pct == 2.56


def test_a_jump_inside_its_window_is_not_repeated() -> None:
    config, seen = MonitorConfig(), Seen()
    detect([_quote(price=103.1, earlier=100.49)], config, seen, now=NOW)
    later = NOW + timedelta(minutes=10)
    assert detect([_quote(price=103.0, earlier=100.3, at=later)], config, seen, now=later) == []


def test_indexes_alert_at_their_own_smaller_thresholds() -> None:
    config = MonitorConfig()
    stock = _quote("MU", price=98.4)
    index = _quote("^IXIC", price=98.4, is_index=True)
    [alert] = detect([stock, index], config, Seen(), now=NOW)
    assert (alert.symbol, alert.instrument, alert.level_pct) == ("^IXIC", "index", 1.5)


def test_after_hours_compares_with_the_days_close() -> None:
    # Closed at 104 after a 4% day; 109.2 after hours is 5% on the close.
    after_hours = NOW.replace(hour=21)
    quote = _quote(price=109.2, regular=104.0, session="post", at=after_hours, earlier=109.0)
    [alert] = detect([quote], MonitorConfig(), Seen(), now=after_hours)
    assert alert.reference == "regular_close" and alert.session == "post"
    assert alert.change_pct == 5.0


def test_a_stale_or_closed_market_quote_alerts_nothing() -> None:
    config = MonitorConfig()
    stale = _quote(price=80.0, at=NOW - timedelta(minutes=40))
    closed = _quote(price=80.0, session=None)
    assert detect([stale, closed], config, Seen(), now=NOW) == []


async def _recorded(store: AlertStore, alerts: list[Any]) -> None:
    await store.record_batch(
        DEFAULT_SPACE_ID, alerts, status="off", explanation_path=None, now=NOW
    )


@anyio_tests
async def test_what_was_already_alerted_today_comes_back_after_a_restart(db: Database) -> None:
    store = AlertStore(db)
    seen = Seen()
    found = detect(
        [_quote(price=94.5), _quote("NOW", price=103.1, earlier=100.49)],
        MonitorConfig(),
        seen,
        now=NOW,
    )
    await _recorded(store, found)

    restored = Seen.from_alerts(await store.day(DEFAULT_SPACE_ID, "2026-10-13"))
    assert restored.levels == {("MU", "down", "previous_close"): 5.0}
    assert set(restored.jumps) == {("NOW", "up")}
    assert detect([_quote(price=94.0)], MonitorConfig(), restored, now=NOW) == []


# --- the service ------------------------------------------------------------------


@dataclass
class _Launcher:
    """Records each start and creates its run row, as ``RunLauncher`` does."""

    events: EventStore
    started: list[dict[str, Any]] = field(default_factory=list)

    async def launch(self, goal: str, **options: Any) -> Run:
        run = await self.events.create_run(
            goal=goal,
            origin=options["origin"],
            origin_ref=options["origin_ref"],
            space_id=options["space_id"],
        )
        await self.events.set_run_status(run.id, "running")
        self.started.append({"goal": goal, **options, "run": run})
        return run


def _spark(previous: float, closes: list[float], at: datetime) -> dict[str, Any]:
    """A spark result for MU with five-minute bars ending at ``at``."""
    stamps = [
        int((at - timedelta(minutes=5 * (len(closes) - 1 - i))).timestamp())
        for i in range(len(closes))
    ]
    day = at.replace(hour=0, minute=0, second=0, microsecond=0)
    period = {
        "pre": {
            "start": int((day + timedelta(hours=8)).timestamp()),
            "end": int((day + timedelta(hours=13, minutes=30)).timestamp()),
        },
        "regular": {
            "start": int((day + timedelta(hours=13, minutes=30)).timestamp()),
            "end": int((day + timedelta(hours=20)).timestamp()),
        },
        "post": {
            "start": int((day + timedelta(hours=20)).timestamp()),
            "end": int((day + timedelta(hours=24)).timestamp()),
        },
    }
    return {
        "symbol": "MU",
        "response": [
            {
                "meta": {
                    "symbol": "MU",
                    "longName": "Micron Technology, Inc.",
                    "instrumentType": "EQUITY",
                    "previousClose": previous,
                    "regularMarketPrice": closes[-1],
                    "currentTradingPeriod": period,
                },
                "timestamp": stamps,
                "indicators": {"quote": [{"close": closes}]},
            }
        ],
    }


@dataclass
class _Yahoo:
    """Serves one spark document and records each request it was asked."""

    results: list[dict[str, Any]]
    requests: list[str] = field(default_factory=list)

    def factory(self) -> httpx2.AsyncClient:
        def answer(request: httpx2.Request) -> httpx2.Response:
            self.requests.append(str(request.url))
            return httpx2.Response(200, json={"spark": {"result": self.results}})

        return httpx2.AsyncClient(transport=httpx2.MockTransport(answer))


@dataclass
class _Harness:
    monitor: MarketMonitor
    alerts: AlertStore
    launcher: _Launcher
    events: EventStore
    yahoo: _Yahoo
    folder: Path
    posted: list[str]
    clock: list[datetime]


def _harness(
    db: Database,
    app_paths: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
    *,
    config: dict[str, Any] | None = None,
    closes: list[float] | None = None,
) -> _Harness:
    spaces = SpaceStore(db, app_paths.spaces_dir)
    folder = spaces.folder_for(DEFAULT_SPACE_ID)
    (folder / "config").mkdir(parents=True, exist_ok=True)
    settings = {"enabled": True, "indexes": [], **(config or {})}
    (folder / MONITOR_PATH).write_text(json.dumps(settings), encoding="utf-8")
    (folder / "portfolio").mkdir(exist_ok=True)
    (folder / "portfolio/positions.csv").write_text(
        "ticker,shares,cost_per_share,opened,sector,currency\nMU,1,,,Technology,USD\nCASH,2500,,,Cash,USD\n",
        encoding="utf-8",
    )
    # Every address is public in a test: the check itself is the sandbox's.
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("98.137.11.163", 0))],
    )
    clock = [NOW]
    yahoo = _Yahoo([_spark(100.0, closes or [100.0, 99.0, 94.5], NOW)])
    alerts = AlertStore(db)
    events = EventStore(db)
    launcher, posted = _Launcher(events), []

    async def announce(text: str) -> bool:
        posted.append(text)
        return True

    monitor = MarketMonitor(
        spaces=spaces,
        alerts=alerts,
        launcher=cast("RunLauncher", launcher),
        events=events,
        announce=announce,
        clock=lambda: clock[0],
        client_factory=yahoo.factory,
    )
    return _Harness(monitor, alerts, launcher, events, yahoo, folder, posted, clock)


@anyio_tests
async def test_a_move_alerts_posts_and_starts_one_explanation_run(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch)

    await h.monitor.tick()

    [alert] = await h.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert (alert.symbol, alert.change_pct, alert.explanation_status) == ("MU", -5.5, "running")
    assert alert.explanation_path == "alerts/2026-10-13-1100.md"
    assert len(h.yahoo.requests) == 1 and "symbols=MU" in h.yahoo.requests[0]
    [started] = h.launcher.started
    assert started["origin"] == "monitor" and started["origin_ref"] == alert.batch_id
    assert "MU (Micron Technology, Inc.) down 5.50% since the previous close" in started["goal"]
    assert "write alerts/2026-10-13-1100.md" in started["goal"]
    assert h.posted[0].startswith("Market alert, Tuesday 2026-10-13 11:00 New York time")
    assert "Looking for the reason now." in h.posted[0]

    # The same price on the next check is not news.
    h.clock[0] = NOW + timedelta(minutes=5)
    await h.monitor.tick()
    assert len(await h.alerts.recent(DEFAULT_SPACE_ID, 10)) == 1
    assert len(h.yahoo.requests) == 2


@anyio_tests
async def test_a_finished_explanation_reaches_the_alert_and_the_channel(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch)
    await h.monitor.tick()
    [started] = h.launcher.started
    note = h.folder / "alerts/2026-10-13-1100.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "# MU down 5.5% at 11:00 New York time\n\n"
        "**Likely reason:** A *downgrade* at a large broker, reported at 10:40.\n\n"
        "**Evidence:** ...\n",
        encoding="utf-8",
    )
    await h.events.set_run_status(started["run"].id, "completed")

    await h.monitor.follow(started["run"].id)

    [alert] = await h.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert alert.explanation_status == "done"
    assert alert.explanation == "A downgrade at a large broker, reported at 10:40."
    assert h.posted[-1] == "Why MU moved: A downgrade at a large broker, reported at 10:40."


@anyio_tests
async def test_an_explanation_that_wrote_no_note_is_a_failure(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch)
    await h.monitor.tick()
    run_id = h.launcher.started[0]["run"].id
    await h.events.set_run_status(run_id, "completed")

    await h.monitor.follow(run_id)

    [alert] = await h.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert alert.explanation_status == "failed"
    # A run the watcher did not start changes no alert.
    await h.monitor.follow("someone-elses-run")


@anyio_tests
async def test_explanations_stop_at_the_days_cap_or_when_turned_off(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    capped = _harness(db, app_paths, monkeypatch, config={"max_explanations_per_day": 0})
    await capped.monitor.tick()
    [alert] = await capped.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert alert.explanation_status == "skipped" and capped.launcher.started == []
    assert capped.posted[0].endswith("since the previous close, at 94.50 USD")


@anyio_tests
async def test_with_explanations_off_an_alert_arrives_alone(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch, config={"explain": False})
    await h.monitor.tick()
    [alert] = await h.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert alert.explanation_status == "off" and h.launcher.started == []


@anyio_tests
async def test_an_explanation_waits_for_a_busy_space(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch)
    morning = await h.events.create_run(
        goal="morning collection", origin="schedule", origin_ref=None, space_id=DEFAULT_SPACE_ID
    )
    await h.events.set_run_status(morning.id, "running")

    await h.monitor.tick()
    [alert] = await h.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert alert.explanation_status == "queued" and h.launcher.started == []

    await h.events.set_run_status(morning.id, "completed")
    h.clock[0] = NOW + timedelta(minutes=1)
    await h.monitor.tick()
    [alert] = await h.alerts.recent(DEFAULT_SPACE_ID, 10)
    assert alert.explanation_status == "running" and len(h.launcher.started) == 1


@anyio_tests
async def test_outside_market_hours_it_makes_no_request(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch)
    h.clock[0] = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)  # Saturday

    await h.monitor.tick()

    assert h.yahoo.requests == []
    assert await h.alerts.recent(DEFAULT_SPACE_ID, 10) == []
    status = h.monitor.status(DEFAULT_SPACE_ID)
    assert status is not None and status.enabled and not status.market_open


@anyio_tests
async def test_a_space_without_the_file_or_switched_off_is_not_watched(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch, config={"enabled": False})
    await h.monitor.tick()
    assert h.yahoo.requests == []
    (h.folder / MONITOR_PATH).unlink()
    await h.monitor.tick()
    assert h.yahoo.requests == []


@anyio_tests
async def test_switching_on_writes_the_starter_file_and_keeps_the_persons_edits(
    db: Database, app_paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = _harness(db, app_paths, monkeypatch)
    space = await SpaceStore(db, app_paths.spaces_dir).require(DEFAULT_SPACE_ID)
    path = h.folder / MONITOR_PATH

    path.unlink()
    h.monitor.set_enabled(space, enabled=True)
    assert parse_config(path.read_text(encoding="utf-8")) == MonitorConfig(enabled=True)

    path.write_text('{"enabled": true, "stock_move_pct": 4}', encoding="utf-8")
    h.monitor.set_enabled(space, enabled=False)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "enabled": False,
        "stock_move_pct": 4,
    }

    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(MonitorConfigError, match="left alone"):
        h.monitor.set_enabled(space, enabled=True)
    assert path.read_text(encoding="utf-8") == "{broken"
