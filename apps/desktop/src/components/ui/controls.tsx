import type { KeyboardEvent, ReactNode } from "react";

import { Icon, type IconName, type IconSize } from "../icons/Icon";

/**
 * The small controls (Phase 20): a button that is only an icon, a switch for
 * on and off, and a segmented choice between a few views. Each is a real
 * button with its state in ARIA, so its state never rests on colour alone.
 */

export interface IconButtonProps {
  icon: IconName;
  /** The button's name. An icon alone says nothing to a screen reader. */
  label: string;
  /** The tooltip, when it says more than the name: a shortcut, say. */
  title?: string | undefined;
  size?: IconSize | undefined;
  /** For a button that toggles something: its state, announced as pressed. */
  pressed?: boolean | undefined;
  disabled?: boolean | undefined;
  className?: string | undefined;
  testId?: string | undefined;
  onClick: () => void;
}

export function IconButton({ icon, label, title, size = 20, pressed, disabled, className, testId, onClick }: IconButtonProps) {
  return (
    <button
      type="button"
      className={`icon-button${className === undefined ? "" : ` ${className}`}`}
      aria-label={label}
      title={title ?? label}
      aria-pressed={pressed}
      disabled={disabled}
      data-testid={testId}
      onClick={onClick}
    >
      <Icon name={icon} size={size} />
    </button>
  );
}

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  /** The switch's name, when no visible label points at it. */
  label?: string | undefined;
  /** The id of the visible text that names it. */
  labelledBy?: string | undefined;
  describedBy?: string | undefined;
  disabled?: boolean | undefined;
  id?: string | undefined;
  testId?: string | undefined;
}

/** On or off, taking effect at once. Space and Enter flip it, as on a button. */
export function Switch({ checked, onChange, label, labelledBy, describedBy, disabled, id, testId }: SwitchProps) {
  return (
    <button
      type="button"
      id={id}
      className="switch"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      disabled={disabled}
      data-testid={testId}
      onClick={() => {
        onChange(!checked);
      }}
    />
  );
}

export interface SegmentedOption<Value extends string> {
  readonly value: Value;
  readonly label: ReactNode;
  readonly icon?: IconName | undefined;
}

export interface SegmentedProps<Value extends string> {
  /** Names the group: "Theme", "View". */
  label: string;
  value: Value;
  options: readonly SegmentedOption<Value>[];
  onChange: (value: Value) => void;
  testId?: string | undefined;
}

/**
 * One choice among a few, all visible: a radio group drawn as joined
 * segments. Tab reaches the chosen segment; the arrow keys move the choice.
 */
export function Segmented<Value extends string>({ label, value, options, onChange, testId }: SegmentedProps<Value>) {
  const move = (event: KeyboardEvent<HTMLDivElement>) => {
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    const index = options.findIndex((option) => option.value === value);
    const next =
      event.key === "Home"
        ? options[0]
        : event.key === "End"
          ? options.at(-1)
          : step === 0
            ? undefined
            : options[(index + step + options.length) % options.length];
    if (next === undefined) return;
    event.preventDefault();
    onChange(next.value);
    // Focus follows the choice, as it does in a native radio group.
    const buttons = event.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]');
    buttons[options.indexOf(next)]?.focus();
  };

  return (
    <div className="segmented" role="radiogroup" aria-label={label} data-testid={testId} onKeyDown={move}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="segmented__option"
          role="radio"
          aria-checked={option.value === value}
          tabIndex={option.value === value ? 0 : -1}
          onClick={() => {
            onChange(option.value);
          }}
        >
          {option.icon !== undefined && <Icon name={option.icon} size={16} />}
          {option.label}
        </button>
      ))}
    </div>
  );
}
