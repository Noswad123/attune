"""Scalar option rows: bool switch, int/float spinners, vec2 pair of spinners."""

import locale
import math
from decimal import Decimal

from gi.repository import Adw, Gtk

from hyprmod.ui.managed_row import make_spin_float_row, make_spin_int_row
from hyprmod.ui.options.base import OptionRow, digits_for_step
from hyprmod.ui.signals import SignalBlocker


class SwitchOptionRow(OptionRow):
    def __init__(self, option, value, on_change, on_reset, on_discard=None):
        row = Adw.SwitchRow(
            title=option.get("label", option["key"]),
            subtitle=option.get("description", ""),
        )
        super().__init__(row, option, on_change, on_reset, on_discard)
        row.set_active(bool(value))

        def on_active_changed(row_, _pspec):
            self._emit_change(row_.get_active())

        self._change_handler_id = row.connect("notify::active", on_active_changed)

    def _set_widget_value(self, value):
        self.row.set_active(bool(value))  # type: ignore[attr-defined]


class SpinIntOptionRow(OptionRow):
    def __init__(self, option, value, on_change, on_reset, on_discard=None):
        row, self._spin = make_spin_int_row(
            option.get("label", option["key"]),
            subtitle=option.get("description", ""),
            value=int(value) if value is not None else option.get("default", 0),
            lower=option.get("min", 0),
            upper=option.get("max", 9999),
        )
        super().__init__(row, option, on_change, on_reset, on_discard)
        self._signal_widget = self._spin

        def on_value_changed(btn):
            self._emit_change(int(btn.get_value()))

        self._change_handler_id = self._spin.connect("value-changed", on_value_changed)

    def _set_widget_value(self, value):
        self._spin.set_value(int(value))


class SpinFloatOptionRow(OptionRow):
    def __init__(self, option, value, on_change, on_reset, on_discard=None):
        step = option.get("step", 0.01)
        self._digits = digits_for_step(step)
        row, self._spin = make_spin_float_row(
            option.get("label", option["key"]),
            subtitle=option.get("description", ""),
            value=float(value) if value is not None else option.get("default", 0.0),
            lower=option.get("min", 0.0),
            upper=option.get("max", 100.0),
            step=step,
            digits=self._digits,
        )
        super().__init__(row, option, on_change, on_reset, on_discard)
        self._signal_widget = self._spin

        def on_value_changed(btn):
            self._emit_change(round(btn.get_value(), self._digits))

        self._change_handler_id = self._spin.connect("value-changed", on_value_changed)

    def _set_widget_value(self, value):
        self._spin.set_value(float(value))


class PreciseFloatOptionRow(OptionRow):
    """Explicit numeric Apply with decimal steps, independent of GTK spin tolerances."""

    row: Adw.EntryRow

    def __init__(self, option, value, on_change, on_reset, on_discard=None):
        row = Adw.EntryRow(title=option.get("label", option["key"]))
        row.set_show_apply_button(True)
        super().__init__(row, option, on_change, on_reset, on_discard)
        self._set_widget_value(value)
        step = option["step"]
        for direction, icon, action in (
            (-1, "list-remove-symbolic", "Decrease"),
            (1, "list-add-symbolic", "Increase"),
        ):
            button = Gtk.Button(icon_name=icon, valign=Gtk.Align.CENTER)
            button.set_tooltip_text(f"{action} by {step} and apply")
            button.add_css_class("flat")
            button.connect("clicked", lambda _button, d=direction: self.apply_increment(d))
            row.add_suffix(button)
        self._change_handler_id = row.connect("apply", lambda _row: self.apply_increment(0))

    def apply_increment(self, direction: int):
        try:
            value = locale.atof(self.row.get_text())
            if not math.isfinite(value) or not self.option["min"] <= value <= self.option["max"]:
                raise ValueError("Number outside range")
            if direction:
                value = float(Decimal(str(value)) + direction * Decimal(str(self.option["step"])))
            if not math.isfinite(value) or not self.option["min"] <= value <= self.option["max"]:
                raise ValueError("Number outside range")
        except ValueError:
            self.flash_error()
            self.row.set_tooltip_text(
                f"Enter a finite number from {self.option['min']} to {self.option['max']}. "
                "Not applied."
            )
            return
        if value != self._value:
            self._emit_change(value)
        else:
            self.set_value_silent(value)

    def _set_widget_value(self, value):
        self._value = float(value)
        self.row.set_text(locale.localize(repr(self._value), grouping=False))


class Vec2OptionRow(OptionRow):
    """Two-spinbutton row for vec2 values like shadow offset ('x y')."""

    def __init__(self, option, value, on_change, on_reset, on_discard=None):
        x_val, y_val = self._parse_vec2(value, option.get("default", "0 0"))
        min_val = option.get("min", -10000)
        max_val = option.get("max", 10000)

        self._spin_x = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(
                value=x_val,
                lower=min_val,
                upper=max_val,
                step_increment=1,
                page_increment=5,
            ),
            digits=0,
        )
        self._spin_x.set_valign(Gtk.Align.CENTER)
        self._spin_y = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(
                value=y_val,
                lower=min_val,
                upper=max_val,
                step_increment=1,
                page_increment=5,
            ),
            digits=0,
        )
        self._spin_y.set_valign(Gtk.Align.CENTER)

        row = Adw.ActionRow(
            title=option.get("label", option["key"]),
            subtitle=option.get("description", ""),
        )
        for label_text, widget, margin_start, margin_end in [
            ("X", self._spin_x, 0, 4),
            ("Y", self._spin_y, 12, 4),
        ]:
            lbl = Gtk.Label(label=label_text)
            lbl.add_css_class("dim-label")
            lbl.set_valign(Gtk.Align.CENTER)
            lbl.set_margin_start(margin_start)
            lbl.set_margin_end(margin_end)
            row.add_suffix(lbl)
            row.add_suffix(widget)

        super().__init__(row, option, on_change, on_reset, on_discard)

        self._signals = SignalBlocker()
        self._change_handler_id = self._signals.connect(
            self._spin_x,
            "value-changed",
            lambda _: self._emit_vec2(),
        )
        self._signals.connect(
            self._spin_y,
            "value-changed",
            lambda _: self._emit_vec2(),
        )

    @staticmethod
    def _parse_vec2(value, default: str) -> tuple[int, int]:
        raw = str(value) if value is not None else default
        parts = raw.split()
        try:
            return int(float(parts[0])), int(float(parts[1]))
        except (ValueError, IndexError):
            return 0, 0

    def _emit_vec2(self):
        x = int(self._spin_x.get_value())
        y = int(self._spin_y.get_value())
        self._emit_change(f"{x} {y}")

    def _set_widget_value(self, value):
        x, y = self._parse_vec2(value, self.option.get("default", "0 0"))
        self._spin_x.set_value(x)
        self._spin_y.set_value(y)
