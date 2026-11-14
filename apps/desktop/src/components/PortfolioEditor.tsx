import type { PersonalPortfolio, PortfolioHolding, PortfolioResponse, PortfolioStock } from "@agentbase/schemas";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import * as api from "../lib/api";
import { failureMessage } from "../lib/errors";
import { useFetched } from "../state/useFetched";

import { Skeleton } from "./Skeleton";
import "./PortfolioEditor.css";

type FormData = PersonalPortfolio;
// Switching spaces retains unsaved edits in this window. Saved files remain
// canonical; the original revision still protects the eventual save.
const drafts = new Map<string, { base: PortfolioResponse; form: FormData; owner: string }>();

const SECTORS = ["Technology", "Communication Services", "Financials", "Healthcare", "Industrials", "Consumer Discretionary", "Consumer Staples", "Energy", "Materials", "Real Estate", "Utilities"];

function formOf(data: PersonalPortfolio): FormData {
  return {
    currency: data.currency, cash: data.cash,
    holdings: data.holdings.map((row) => ({ ...row })),
    watchlist: data.watchlist.map((row) => ({ ...row })),
    limits: { ...data.limits },
  };
}

function newStock(): PortfolioStock {
  return { ticker: "", company_name: "", sector: "Technology", industry: "", exchange: "US" };
}

export function PortfolioEditor({ spaceId, onSaved, reloadNonce = 0, running = false }: {
  spaceId: string; onSaved?: (() => void) | undefined; reloadNonce?: number | undefined; running?: boolean | undefined;
}) {
  const id = useId();
  const cached = drafts.get(spaceId);
  const [base, setBase] = useState<PortfolioResponse | null>(cached?.base ?? null);
  const [form, setForm] = useState<FormData | null>(cached?.form ?? null);
  const [editing, setEditing] = useState(cached !== undefined);
  const [loading, setLoading] = useState(cached === undefined);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const generation = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const existing = drafts.get(spaceId);
    if (existing !== undefined) drafts.set(spaceId, { ...existing, owner: id });
    return () => { mounted.current = false; };
  }, [id, spaceId]);

  const load = useCallback(async (discardEdits = false) => {
    if (!discardEdits && drafts.has(spaceId)) return;
    const request = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const loaded = await api.getPortfolio(spaceId);
      if (request !== generation.current || (!discardEdits && drafts.has(spaceId))) return;
      setBase(loaded);
      setForm(formOf(loaded.portfolio));
      drafts.delete(spaceId);
    } catch (failure) {
      if (request === generation.current) setError(failureMessage(failure));
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [spaceId]);

  useEffect(() => {
    const scheduled = ++generation.current;
    void Promise.resolve().then(() => {
      if (scheduled === generation.current) return load();
      return undefined;
    });
    return () => { generation.current += 1; };
  }, [reloadNonce, spaceId, load]);

  useEffect(() => {
    const focus = () => { if (!drafts.has(spaceId) && !saving) void load(); };
    const leaving = (event: BeforeUnloadEvent) => {
      if (drafts.size === 0) return;
      event.preventDefault();
    };
    window.addEventListener("focus", focus);
    window.addEventListener("beforeunload", leaving);
    return () => {
      window.removeEventListener("focus", focus);
      window.removeEventListener("beforeunload", leaving);
    };
  }, [load, saving, spaceId]);

  const update = (next: FormData) => {
    setForm(next);
    setSaved(false);
    if (base !== null) drafts.set(spaceId, { base: drafts.get(spaceId)?.base ?? base, form: next, owner: id });
  };

  const save = async () => {
    if (base === null || form === null) return;
    setSaving(true);
    setError(null);
    const submitted = form;
    const original = drafts.get(spaceId)?.base ?? base;
    drafts.set(spaceId, { base: original, form: submitted, owner: id });
    try {
      const response = await api.savePortfolio(spaceId, { portfolio: submitted, revision: original.revision });
      const current = drafts.get(spaceId);
      if (current !== undefined && (current.owner !== id || current.form !== submitted)) {
        drafts.set(spaceId, { ...current, base: response });
      } else {
        drafts.delete(spaceId);
      }
      if (!mounted.current) return;
      setBase(response);
      setForm(formOf(response.portfolio));
      setEditing(false);
      setSaved(true);
      onSaved?.();
    } catch (failure) {
      if (mounted.current) setError(failureMessage(failure));
    } finally {
      if (mounted.current) setSaving(false);
    }
  };

  const changeRow = (group: "holdings" | "watchlist", index: number, key: string, value: string) => {
    if (form === null) return;
    update({ ...form, [group]: form[group].map((row, at) => at === index ? { ...row, [key]: value } : row) });
  };

  const field = (label: string, value: string, change: (value: string) => void, options: { required?: boolean; decimal?: boolean; type?: string; placeholder?: string; list?: string } = {}) => (
    <label className="portfolio-editor__field">
      <span>{label}</span>
      <input value={value} onChange={(event) => { change(event.target.value); }} type={options.type ?? "text"}
        required={options.required ?? false} inputMode={options.decimal === true ? "decimal" : undefined}
        placeholder={options.placeholder} list={options.list} />
    </label>
  );

  const stockRow = (row: PortfolioStock | PortfolioHolding, index: number, group: "holdings" | "watchlist") => {
    const holding = group === "holdings" ? row as PortfolioHolding : null;
    const change = (key: string) => (value: string) => { changeRow(group, index, key, value); };
    return (
      <fieldset className="portfolio-editor__stock" key={`${group}-${String(index)}`}>
        <legend>{holding === null ? "Watched stock" : "Holding"} {index + 1}{row.ticker !== "" && `: ${row.ticker}`}</legend>
        <div className="portfolio-editor__grid">
          {field("Ticker", row.ticker, change("ticker"), { required: true, placeholder: "MU" })}
          {field("Sector", row.sector, change("sector"), { required: true, list: `${id}-sectors`, placeholder: "Technology" })}
          {holding !== null && <>
            {field("Number of shares", holding.shares, change("shares"), { required: true, decimal: true })}
            {field("Average purchase price (optional)", holding.cost_per_share ?? "", change("cost_per_share"), { decimal: true })}
            {field("First purchase date (optional)", holding.opened ?? "", change("opened"), { type: "date" })}
          </>}
          {field("Company name (optional)", row.company_name ?? "", change("company_name"))}
        </div>
        <details>
          <summary>Industry and exchange</summary>
          <div className="portfolio-editor__grid">
            {field("Industry (optional)", row.industry ?? "", change("industry"), { placeholder: "Semiconductors" })}
            {field("Exchange", row.exchange ?? "US", change("exchange"), { placeholder: "US" })}
          </div>
          <p className="settings__hint">For stocks outside the US, use the Yahoo ticker, such as 2330.TW for Taiwan.</p>
        </details>
        <button className="button" type="button" onClick={() => {
          if (form !== null) update({ ...form, [group]: form[group].filter((_, at) => at !== index) });
        }}>Remove {holding === null ? "watched stock" : "holding"} {index + 1}</button>
      </fieldset>
    );
  };

  return (
    <section className="card portfolio-editor" aria-label="My portfolio" data-testid="portfolio-editor">
      <div className="portfolio-editor__heading">
        <div><h2 className="card__title">My portfolio</h2><p>Your holdings, cash and limits for this space&apos;s stock research.</p></div>
        {!editing && base !== null && <button type="button" className="button" disabled={loading} onClick={() => { setEditing(true); setSaved(false); }}>Edit portfolio</button>}
      </div>
      {loading && <Skeleton label="Loading your portfolio" lines={3} />}
      {saved && <p className="settings__saved" role="status">Portfolio saved. Upcoming runs will use these details.</p>}
      {error !== null && <div role="alert"><p className="field-error">{error}</p>
        <button type="button" className="button" disabled={saving || loading} onClick={() => void load(true)}>{drafts.has(spaceId) ? "Reload and discard edits" : "Try again"}</button>
      </div>}
      {!editing && base !== null && <p className="portfolio-editor__summary">
        {base.portfolio.holdings.length} holdings{base.portfolio.holdings.length > 0 && ` (${base.portfolio.holdings.map((row) => row.ticker).join(", ")})`}
        {` · ${base.portfolio.cash} ${base.portfolio.currency} available · ${String(base.portfolio.watchlist.length)} additional watched stocks`}
      </p>}
      {!editing && <ValuationNote spaceId={spaceId} reloadNonce={reloadNonce} />}
      {editing && form !== null && <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <fieldset disabled={saving || loading} className="portfolio-editor__form">
          <datalist id={`${id}-sectors`}>{SECTORS.map((sector) => <option key={sector} value={sector} />)}</datalist>
          <section><h3>Cash and currency</h3><div className="portfolio-editor__grid">
            {field("Cash available to invest", form.cash, (cash) => { update({ ...form, cash }); }, { required: true, decimal: true })}
            {field("Currency", form.currency, (currency) => { update({ ...form, currency }); }, { required: true, placeholder: "USD" })}
          </div><p className="settings__hint">Use one currency for all amounts, such as USD. Changing the currency label does not convert your amounts.</p></section>
          <section><h3>Stocks you own</h3><p className="settings__hint">Owned stocks are automatically watched. Leave purchase price or date blank if you do not know them.</p>
            {form.holdings.map((row, index) => stockRow(row, index, "holdings"))}
            <button type="button" className="button" disabled={form.holdings.length + form.watchlist.length >= 50} onClick={() => { update({ ...form, holdings: [...form.holdings, { ...newStock(), shares: "", cost_per_share: null, opened: null }] }); }}>Add holding</button>
          </section>
          <section><h3>Other stocks to watch</h3><p className="settings__hint">Add stocks you do not own. Daily research also discovers movers and stocks in the news.</p>
            {form.watchlist.map((row, index) => stockRow(row, index, "watchlist"))}
            <button type="button" className="button" disabled={form.holdings.length + form.watchlist.length >= 50} onClick={() => { update({ ...form, watchlist: [...form.watchlist, newStock()] }); }}>Add watched stock</button>
          </section>
          <section><h3>Your limits</h3><div className="portfolio-editor__grid">
            {field("Maximum in one stock (%)", form.limits.max_position_pct, (value) => { update({ ...form, limits: { ...form.limits, max_position_pct: value } }); }, { required: true, decimal: true })}
            {field("Maximum in one sector (%)", form.limits.max_sector_pct, (value) => { update({ ...form, limits: { ...form.limits, max_sector_pct: value } }); }, { required: true, decimal: true })}
            {field("Maximum daily loss (%)", form.limits.max_daily_loss_pct, (value) => { update({ ...form, limits: { ...form.limits, max_daily_loss_pct: value } }); }, { required: true, decimal: true })}
          </div><p className="settings__hint">These percentages apply to your total portfolio, including cash. Use Technology as the sector for chips, software and other technology industries.</p></section>
          <div className="card__actions">
            <button type="submit" className="button button--primary" disabled={running} aria-busy={saving}>{saving ? "Saving…" : "Save portfolio"}</button>
            <button type="button" className="button" onClick={() => { const latest = drafts.get(spaceId)?.base ?? base; if (latest !== null) { setBase(latest); setForm(formOf(latest.portfolio)); } drafts.delete(spaceId); setEditing(false); setError(null); }}>Cancel</button>
          </div>
          {running && <p role="status">A run is using this portfolio. Finish or cancel it before saving your edits.</p>}
          <p className="settings__hint">Edits stay in this window until saved, including when switching spaces. Finish or cancel any ongoing run before saving.</p>
        </fieldset>
      </form>}
    </section>
  );
}

/**
 * The newest valuation, what changed since the report before it, and the
 * sessions in between that got no research. Three mornings once went by with
 * AgentBase closed, and nothing on Home said so (2026-10-20).
 */
function ValuationNote({ spaceId, reloadNonce }: { spaceId: string; reloadNonce: number }) {
  const load = useCallback(() => api.getPortfolioValuation(spaceId), [spaceId]);
  const valuation = useFetched(load, null);
  const { reload } = valuation;
  useEffect(() => {
    if (reloadNonce > 0) reload();
  }, [reloadNonce, reload]);
  useEffect(() => {
    window.addEventListener("focus", reload);
    return () => {
      window.removeEventListener("focus", reload);
    };
  }, [reload]);

  const value = valuation.data;
  if (value === null) return null;
  const since = value.since_previous ?? null;
  const skipped = since?.skipped_sessions ?? [];
  const percent = since?.value_change_pct ?? null;
  return (
    <div className="portfolio-editor__valuation" data-testid="portfolio-valuation">
      <p>
        Valued at the {day(value.as_of)} close: {AMOUNT.format(value.total_value)} {value.currency}
        {since !== null &&
          `, ${signed(since.value_change)}${percent === null ? "" : ` (${signed(percent)}%)`} since ${day(since.session)}`}
        .
      </p>
      {skipped.length > 0 && (
        <p className="portfolio-editor__gap">
          No research for {sessions(skipped)}: AgentBase runs the daily research only while it is open.
        </p>
      )}
    </div>
  );
}

const AMOUNT = new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/** "Oct 19" for `2026-10-19`, read as a calendar day wherever the window is. */
function day(date: string): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function signed(value: number): string {
  return `${value < 0 ? "\u2212" : "+"}${AMOUNT.format(Math.abs(value))}`;
}

/** "the Oct 14, Oct 15 and Oct 16 sessions"; a long gap by its ends. */
function sessions(days: readonly string[]): string {
  const first = days[0] ?? "";
  const last = days[days.length - 1] ?? "";
  if (days.length > 4) return `the ${String(days.length)} sessions from ${day(first)} to ${day(last)}`;
  const named = days.map(day);
  const listed = named.length > 1 ? `${named.slice(0, -1).join(", ")} and ${named[named.length - 1] ?? ""}` : (named[0] ?? "");
  return `the ${listed} session${days.length === 1 ? "" : "s"}`;
}
