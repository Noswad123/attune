"""Shared draft-only Devices and Cursor overrides, independent of visual state."""

import locale
import os
import threading
import weakref
from collections.abc import Iterator
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from hyprmod.core import input as backend
from hyprmod.core import schema
from hyprmod.core.input import InputBaseline, InputConfig, Scalar
from hyprmod.core.pending import PendingChange
from hyprmod.core.state import OptionState
from hyprmod.core.undo import SavedListSnapshot
from hyprmod.pages.section import SectionPage
from hyprmod.ui import make_inline_hint, make_page_layout
from hyprmod.ui.options import KeyboardLayoutsOptionRow, OptionRow, create_option_row
from hyprmod.ui.options.numeric import PreciseFloatOptionRow

_LAYOUT_KEYS = ("input:kb_layout", "input:kb_variant")


class _InputStateView:
    def __init__(self, page: "InputPage"):
        self._page = page

    def get(self, key: str) -> OptionState | None:
        if key not in backend.INPUT_KEYS:
            return None
        page = self._page
        current, saved = dict(page._current.values), dict(page._saved.values)
        fallback = page._hints.get(key, backend.DEFAULTS[key])
        return OptionState(
            key=key,
            live_value=current.get(key, fallback),
            saved_value=saved.get(key, fallback),
            default_value=backend.DEFAULTS[key],
            managed=key in current,
            saved_managed=key in saved,
        )


class InputPage(SectionPage):
    def __init__(self, window, on_dirty_changed=None, push_undo=None):
        super().__init__(window, on_dirty_changed, push_undo)
        self.baseline: InputBaseline | None = None
        self.load_error: str | None = None
        self.locked = False
        self._current = InputConfig()
        self._saved = InputConfig()
        self._hints: dict[str, Scalar] = {}
        self._hint_status = "Runtime hints not observed. Unmanaged values show defaults."
        self._state = _InputStateView(self)
        self._rows: dict[str, OptionRow] = {}
        self._origin_labels: dict[str, Gtk.Label] = {}
        self._status: Adw.ActionRow | None = None
        self._cursor_status: Adw.ActionRow | None = None
        self._started = False
        self._loading = False
        self._closed = False
        self._generation = 0
        self._cancel = threading.Event()
        self._config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        self._state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        self._sections = []
        self._cursor_sections = []
        self._options: dict[str, dict] = {}
        groups = [g for g in schema.load_schema()["groups"] if g["id"] in {"input", "cursor"}]
        for group in groups:
            sections = self._sections if group["id"] == "input" else self._cursor_sections
            for section in group["sections"]:
                options = []
                for original in section["options"]:
                    key = original["key"]
                    if key not in backend.INPUT_KEYS:
                        continue
                    option = dict(original)
                    spec = backend.OPTION_SPECS[key]
                    option["default"] = spec.default
                    if spec.minimum is not None:
                        option["min"], option["max"] = spec.minimum, spec.maximum
                    if spec.step is not None:
                        option["step"] = spec.step
                    if key in {"cursor:zoom_factor", "cursor:inactive_timeout"}:
                        option["step"] = 0.1
                        option["preserve_precision"] = True
                    if key == "input:kb_options":
                        option.pop("source", None)
                        option.pop("multi", None)
                        option["type"] = "string"
                        option["description"] = (
                            "Raw XKB options, comma separated. Examples: grp:alt_shift_toggle,"
                            "caps:escape. Existing unknown options are preserved."
                        )
                    self._options[key] = option
                    options.append(option)
                if options:
                    sections.append((section["label"], options))

    def build(self, header=None):
        self._status = Adw.ActionRow(title="Input not loaded")
        return self._build_view(
            self._sections,
            self._status,
            "Draft only. No input preview or reload. Save Reviewed Input writes Devices and "
            "Cursor together to dedicated attune-input.lua, which must be loaded manually after "
            "it exists. Touchpad settings may not apply without a touchpad device.",
            header,
        )

    def build_cursor(self, header=None):
        self._cursor_status = Adw.ActionRow(title="Input not loaded")
        return self._build_view(
            self._cursor_sections,
            self._cursor_status,
            "Draft only. No cursor preview or reload. Cursor shares the Input draft: "
            "Save Reviewed Input writes Devices and Cursor together to attune-input.lua and "
            "clears both drafts atomically. Load it manually only after it exists. "
            "Runtime hints do not prove loading or actual cursor state.",
            header,
        )

    def _build_view(self, sections, status, hint, header):
        toolbar, _page_box, content, _scrolled = make_page_layout(header=header or Adw.HeaderBar())
        content.append(make_inline_hint(hint))
        status_group = Adw.PreferencesGroup()
        status_group.add(status)
        content.append(status_group)
        for label, options in sections:
            group = Adw.PreferencesGroup(title=label)
            for option in options:
                key = option["key"]
                if option.get("managed_by"):
                    continue
                factory = (
                    PreciseFloatOptionRow if option.get("preserve_precision") else create_option_row
                )
                row = factory(
                    option,
                    backend.DEFAULTS[key],
                    self._on_change,
                    self._on_reset,
                    self._on_discard,
                )
                if row is None:
                    raise ValueError(f"Unsupported input row: {key}")
                self._rows[key] = row
                if isinstance(row, KeyboardLayoutsOptionRow):
                    row.bind_state(self._state, self._on_sources)
                    self._rows[_LAYOUT_KEYS[1]] = row
                origin = Gtk.Label(valign=Gtk.Align.CENTER, wrap=True, max_width_chars=28)
                origin.add_css_class("dim-label")
                origin.add_css_class("caption")
                row.row.add_suffix(origin)
                self._origin_labels[key] = origin
                if isinstance(row.row, Adw.EntryRow):
                    row.row.connect("changed", lambda _entry: self._refresh(()))
                group.add(row.row)
            content.append(group)
        self._refresh(tuple(option["key"] for _label, options in sections for option in options))
        toolbar.connect("map", lambda _widget: self.ensure_loaded())
        return toolbar

    def bind_lifecycle(self, window):
        window.connect("unrealize", self.close)
        window.connect("destroy", self.close)
        application = window.get_application()
        if application is not None:

            def removed(app, removed_window):
                if removed_window is window:
                    self.close()
                    app.disconnect(handler)

            handler = application.connect("window-removed", removed)

    def close(self, *_args):
        self._closed = True
        self._generation += 1
        self._cancel.set()

    def ensure_loaded(self):
        if self._started or self._loading or self._closed or self.locked:
            return
        self._started = self._loading = True
        generation, cancel = self._generation, self._cancel
        config_root, state_root = self._config_root, self._state_root
        hypr = self._window.hypr
        page_ref = weakref.ref(self)
        self._refresh()

        def complete(baseline, error, hints, hint_status):
            page = page_ref()
            if page is None:
                return GLib.SOURCE_REMOVE
            page._loading = False
            if page._closed or generation != page._generation or cancel.is_set():
                return GLib.SOURCE_REMOVE
            if not page.locked:
                if error is not None:
                    page.invalidate(error)
                else:
                    page.baseline = baseline
                    page._current = page._saved = baseline.config
                    page._hints, page._hint_status = hints, hint_status
                    page._refresh()
            return GLib.SOURCE_REMOVE

        def collect():
            baseline, error = None, None
            hints: dict[str, Scalar] = {}
            try:
                baseline = backend.run_observe(config_root, state_root, cancel_event=cancel)
                if type(baseline) is not InputBaseline or (
                    baseline.config_root,
                    baseline.state_root,
                ) != (str(config_root), str(state_root)):
                    raise ValueError("Unexpected input observation context")
            except Exception as exc:
                error = str(exc) or type(exc).__name__
            if not cancel.is_set() and hypr.online is True:
                for key, default in backend.DEFAULTS.items():
                    if cancel.is_set():
                        break
                    try:
                        value, available = hypr.get_live(key, default)
                        if available is True:
                            hints[key] = backend.normalize_value(key, value)
                    except Exception:
                        # A hint failure must not replace a valid owned baseline.
                        continue
            hint_status = (
                "Unmanaged values show read-only runtime hints, not saved overrides."
                if len(hints) == len(backend.INPUT_KEYS)
                else "Runtime hints unavailable or incomplete. Unobserved values show defaults, "
                "not actual device state."
            )
            GLib.idle_add(complete, baseline, error, hints, hint_status)

        try:
            threading.Thread(target=collect, daemon=False).start()
        except RuntimeError as exc:
            complete(None, str(exc), {}, "Runtime hints unavailable. Defaults shown.")

    def _require_edit(self):
        if self.locked or self._closed or not self._window.editor_edit_allowed():
            raise ValueError(self.load_error or "Input editing is locked")
        if self.baseline is None:
            raise ValueError("Wait for the input observation before editing")

    def get_config(self) -> InputConfig:
        return self._current

    def set_value(self, key: str, value: Scalar):
        self._require_edit()
        value = backend.normalize_value(key, value)
        values = dict(self._current.values)
        values[key] = value
        if key in _LAYOUT_KEYS:
            values.setdefault(_LAYOUT_KEYS[0], self._effective(_LAYOUT_KEYS[0]))
            values.setdefault(_LAYOUT_KEYS[1], self._effective(_LAYOUT_KEYS[1]))
        self._replace(
            InputConfig.from_mapping(values), _LAYOUT_KEYS if key in _LAYOUT_KEYS else (key,)
        )

    def set_keyboard_sources(self, layout: str, variant: str):
        self._require_edit()
        values = dict(self._current.values)
        if layout == "":
            for key in _LAYOUT_KEYS:
                values.pop(key, None)
        else:
            values.update(zip(_LAYOUT_KEYS, (layout, variant), strict=True))
        self._replace(InputConfig.from_mapping(values), _LAYOUT_KEYS)

    def remove_override(self, key: str):
        self._require_edit()
        if key not in backend.INPUT_KEYS:
            raise ValueError("Unknown input option")
        values = dict(self._current.values)
        for item in _LAYOUT_KEYS if key in _LAYOUT_KEYS else (key,):
            values.pop(item, None)
        self._replace(
            InputConfig.from_mapping(values), _LAYOUT_KEYS if key in _LAYOUT_KEYS else (key,)
        )

    def discard_option(self, key: str):
        self._require_edit()
        if key not in backend.INPUT_KEYS:
            raise ValueError("Unknown input option")
        values, saved = dict(self._current.values), dict(self._saved.values)
        for item in _LAYOUT_KEYS if key in _LAYOUT_KEYS else (key,):
            values.pop(item, None)
            if item in saved:
                values[item] = saved[item]
        self._replace(
            InputConfig.from_mapping(values), _LAYOUT_KEYS if key in _LAYOUT_KEYS else (key,)
        )

    def _replace(self, config: InputConfig, keys: tuple[str, ...] | None = None):
        old = self._current
        self._current = config
        if old != config:
            if self._push_undo is not None:
                self._push_undo(
                    SavedListSnapshot(
                        page_attr="_input_page",
                        old_items=list(old.values),
                        new_items=list(config.values),
                        old_baselines=list(self._saved.values),
                        new_baselines=list(self._saved.values),
                    )
                )
            self._notify_dirty()
        self._refresh(keys)

    def restore_snapshot(self, items, baselines):
        self._require_edit()
        checked = InputConfig(tuple(items))
        saved = InputConfig(tuple(baselines))
        if saved != self._saved or list(checked.values) != items:
            raise ValueError("Input snapshot refers to a different saved baseline")
        current, restored = dict(self._current.values), dict(checked.values)
        keys = {
            key
            for key in current.keys() | restored.keys()
            if (key in current) != (key in restored) or current.get(key) != restored.get(key)
        }
        if keys.intersection(_LAYOUT_KEYS):
            keys.update(_LAYOUT_KEYS)
        self._current = checked
        self._refresh(tuple(keys))
        self._notify_dirty()

    def adopt_saved(self, baseline: InputBaseline):
        if self.locked or self._closed or type(baseline) is not InputBaseline:
            raise ValueError("Input baseline cannot be adopted")
        if (
            self.baseline is None
            or baseline.status != "owned"
            or (
                baseline.config_root,
                baseline.state_root,
                baseline.lexical_path,
                baseline.resolved_path,
            )
            != (
                self.baseline.config_root,
                self.baseline.state_root,
                self.baseline.lexical_path,
                self.baseline.resolved_path,
            )
            or baseline.config != self._current
        ):
            raise ValueError("Saved input differs from the exact draft or route")
        self.baseline = baseline
        self.mark_saved()
        self._notify_dirty()

    def mark_saved(self):
        if (
            self.locked
            or self._closed
            or self.baseline is None
            or self.baseline.status != "owned"
            or self.baseline.config != self._current
        ):
            raise ValueError("Only a verified exact input baseline can be marked saved")
        self._saved = self.baseline.config
        self._refresh()

    def invalidate(self, message):
        self.locked = True
        self.load_error = message
        self._refresh()

    def is_dirty(self) -> bool:
        return self._current != self._saved

    def discard(self):
        self._require_edit()
        self._replace(self._saved)

    def pending_change_count(self) -> int:
        return sum(1 for _change in self.iter_pending_changes())

    def iter_pending_changes(self) -> Iterator[PendingChange]:
        current, saved = dict(self._current.values), dict(self._saved.values)
        for key in sorted(current.keys() | saved.keys()):
            if (key in current) == (key in saved) and current.get(key) == saved.get(key):
                continue
            is_cursor = key in backend.CURSOR_KEYS
            yield PendingChange(
                category="Cursor" if is_cursor else "Input",
                title=self._options[key].get("label", key),
                subtitle=f"{saved.get(key, 'Unmanaged')!r} -> {current.get(key, 'Unmanaged')!r}",
                kind="removed" if key not in current else "modified" if key in saved else "added",
                revert=lambda k=key: self._on_discard(k),
                navigate_to="cursor" if is_cursor else "input",
                icon="hyprmod-cursor-symbolic" if is_cursor else "input-keyboard-symbolic",
            )

    def get_search_entries(self) -> list[dict]:
        return [
            dict(option, _group_id=group_id, _group_label=group_label, _section_label=label)
            for group_id, group_label, sections in (
                ("input", "Devices", self._sections),
                ("cursor", "Cursor", self._cursor_sections),
            )
            for label, options in sections
            for option in options
        ]

    def highlight_option(self, key):
        row = self._rows.get(key)
        if row is not None:
            row.row.grab_focus()
            row.flash_highlight()

    def _effective(self, key: str) -> Scalar:
        return dict(self._current.values).get(key, self._hints.get(key, backend.DEFAULTS[key]))

    def _value_origin(self, key: str) -> str:
        current, saved = dict(self._current.values), dict(self._saved.values)
        if key in current:
            return (
                "Saved override"
                if key in saved and current[key] == saved[key]
                else "Draft override"
            )
        return "Current runtime snapshot" if key in self._hints else "Default, not observed"

    def _refresh(self, keys: tuple[str, ...] | None = None):
        for status in (self._status, self._cursor_status):
            if status is None:
                continue
            status.set_title(
                "Input locked"
                if self.locked
                else "Loading input..."
                if self._loading
                else "Input draft"
                if self.baseline is not None
                else "Input not loaded"
            )
            status.set_subtitle(self.load_error or self._hint_status)
        for key, row in self._rows.items():
            if key == _LAYOUT_KEYS[1]:
                continue
            state = self._state.get(key)
            if state is not None:
                if (
                    keys is None
                    or key in keys
                    or (key == _LAYOUT_KEYS[0] and _LAYOUT_KEYS[1] in keys)
                ):
                    row.set_value_silent(state.live_value)
                if key == _LAYOUT_KEYS[0]:
                    origin = (
                        f"Layout: {self._value_origin(key)}\n"
                        f"Variant: {self._value_origin(_LAYOUT_KEYS[1])}"
                    )
                else:
                    origin = self._value_origin(key)
                rendered = (
                    locale.localize(repr(float(state.live_value)), grouping=False)
                    if isinstance(row, PreciseFloatOptionRow)
                    else str(state.live_value)
                )
                if isinstance(row.row, Adw.EntryRow) and row.row.get_text() != rendered:
                    origin = f"Unapplied text (not in draft)\nModel: {origin}"
                self._origin_labels[key].set_label(origin)
                row.row.set_tooltip_text(f"{row.option.get('description', '')}\n{origin}".strip())
                row.update_modified_state(state.managed, state.is_dirty, state.saved_managed)
                row.row.set_sensitive(
                    self.baseline is not None and not self.locked and not self._closed
                )

    def _on_change(self, key, value):
        try:
            self.set_value(key, value)
        except ValueError as exc:
            self._window.show_toast(str(exc))
            self._refresh((key,))

    def _on_reset(self, key, _value):
        try:
            self.remove_override(key)
        except ValueError as exc:
            self._window.show_toast(str(exc))
            self._refresh((key,))

    def _on_discard(self, key):
        try:
            self.discard_option(key)
        except ValueError as exc:
            self._window.show_toast(str(exc))
            self._refresh((key,))

    def _on_sources(self, items):
        try:
            values = dict(items)
            self.set_keyboard_sources(values[_LAYOUT_KEYS[0]], values[_LAYOUT_KEYS[1]])
        except ValueError as exc:
            self._window.show_toast(str(exc))
            self._refresh(_LAYOUT_KEYS)
