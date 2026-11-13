import { useRef, useState, type ReactNode } from "react";

import { Icon } from "../../components/icons/Icon";
import { MenuButton, MenuRows, type MenuItem } from "../../components/ui/Menu";
import { Popover } from "../../components/ui/Popover";
import { Sheet } from "../../components/ui/Sheet";
import { IconButton, Segmented, Switch } from "../../components/ui/controls";

/**
 * The primitives of stage 20.2. The buttons open the real popover, menu and
 * sheet; beside each is the same thing drawn at rest, in the page, so a
 * screenshot holds it. A floating layer renders into the document's body,
 * outside any page.
 */

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="wb-group">
      <h3 className="wb-group__title">{title}</h3>
      <div className="wb-group__row">{children}</div>
    </section>
  );
}

const nothing = () => undefined;

const NOTE_ACTIONS: readonly MenuItem[] = [
  { id: "open", label: "Open in Preview", icon: "search", shortcut: "Space", onSelect: nothing },
  { id: "rename", label: "Rename", onSelect: nothing },
  { id: "move", label: "Move to folder", disabled: true, onSelect: nothing },
  { id: "line", separator: true },
  { id: "delete", label: "Delete note", danger: true, onSelect: nothing },
];

const SORT: readonly MenuItem[] = [
  { id: "name", label: "Name", checked: false, onSelect: nothing },
  { id: "date", label: "Date changed", checked: true, onSelect: nothing },
  { id: "size", label: "Size", checked: false, onSelect: nothing },
];

function LivePopover() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={button}
        type="button"
        className="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => {
          setOpen((was) => !was);
        }}
      >
        Open a popover
      </button>
      <Popover
        open={open}
        onClose={() => {
          setOpen(false);
        }}
        anchor={button}
        role="dialog"
        label="An example"
        className="wb-popover"
      >
        <p className="type-headline">Spending in September</p>
        <p className="type-control">$4.12 of your $20 monthly limit.</p>
      </Popover>
    </>
  );
}

function LiveSheet() {
  const [open, setOpen] = useState(false);
  const close = () => {
    setOpen(false);
  };
  return (
    <>
      <button
        type="button"
        className="button"
        onClick={() => {
          setOpen(true);
        }}
      >
        Open a sheet
      </button>
      <Sheet
        open={open}
        onClose={close}
        title="Delete this run?"
        size="small"
        footer={
          <>
            <button type="button" className="button" onClick={close}>
              Keep it
            </button>
            <button type="button" className="button button--danger" onClick={close}>
              Delete run
            </button>
          </>
        }
      >
        <p>Its log and its spend record go with it. The files it wrote stay where they are.</p>
      </Sheet>
    </>
  );
}

export function PrimitivesPage() {
  const [on, setOn] = useState(true);
  const [off, setOff] = useState(false);
  const [view, setView] = useState<"office" | "diagram">("office");
  const [theme, setTheme] = useState<"system" | "light" | "dark">("system");
  const [pressed, setPressed] = useState(true);

  return (
    <div className="wb-controls">
      <Group title="Icon buttons">
        <IconButton icon="search" label="Open a note" title="Open a note (Ctrl+O)" onClick={nothing} />
        <IconButton icon="file-plus" label="New note" onClick={nothing} />
        <IconButton
          icon="panel-left"
          label="Hide the sidebar"
          pressed={pressed}
          onClick={() => {
            setPressed((was) => !was);
          }}
        />
        <IconButton icon="calendar-days" label="Daily note" disabled onClick={nothing} />
        <IconButton icon="x" label="Close" size={16} onClick={nothing} />
      </Group>

      <Group title="Switch">
        <label className="wb-controls__check">
          <Switch checked={on} onChange={setOn} label="Notify me, on" /> <span>On</span>
        </label>
        <label className="wb-controls__check">
          <Switch checked={off} onChange={setOff} label="Notify me, off" /> <span>Off</span>
        </label>
        <label className="wb-controls__check">
          <Switch checked onChange={nothing} label="Disabled, on" disabled /> <span>Disabled</span>
        </label>
      </Group>

      <Group title="Segmented choice">
        <Segmented
          label="View"
          value={view}
          onChange={setView}
          options={[
            { value: "office", label: "Office", icon: "users" },
            { value: "diagram", label: "Diagram", icon: "network" },
          ]}
        />
        <Segmented
          label="Theme"
          value={theme}
          onChange={setTheme}
          options={[
            { value: "system", label: "Follow the system" },
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]}
        />
      </Group>

      <Group title="Menu">
        <MenuButton label="Note actions" items={NOTE_ACTIONS} />
        <MenuButton label="Sort by" items={SORT} />
        <div className="popover popover--menu wb-static" role="menu" aria-label="Note actions, at rest">
          <div className="menu" role="presentation">
            <MenuRows items={NOTE_ACTIONS} onClose={nothing} />
          </div>
        </div>
        <div className="popover popover--menu wb-static" role="menu" aria-label="Sort by, at rest">
          <div className="menu" role="presentation">
            <MenuRows items={SORT} onClose={nothing} />
          </div>
        </div>
      </Group>

      <Group title="Popover">
        <LivePopover />
        <div className="popover wb-popover wb-static" role="group" aria-label="A popover, at rest">
          <p className="type-headline">Spending in September</p>
          <p className="type-control">$4.12 of your $20 monthly limit.</p>
        </div>
      </Group>

      <Group title="Sheet">
        <LiveSheet />
        <div className="sheet__panel wb-static wb-static--sheet" role="group" aria-label="A sheet, at rest">
          <header className="sheet__head">
            <h4 className="sheet__title">Delete this run?</h4>
            <span className="icon-button" aria-hidden="true">
              <Icon name="x" size={16} />
            </span>
          </header>
          <div className="sheet__body">
            <p>Its log and its spend record go with it. The files it wrote stay where they are.</p>
          </div>
          <footer className="sheet__foot">
            <button type="button" className="button">
              Keep it
            </button>
            <button type="button" className="button button--danger">
              Delete run
            </button>
          </footer>
        </div>
      </Group>
    </div>
  );
}
