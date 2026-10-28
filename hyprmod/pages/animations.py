"""Animation configuration page — flat list with detail dialogs."""

from collections.abc import Iterator
from dataclasses import dataclass, replace

from gi.repository import Adw, GLib, Gtk
from hyprland_config import BezierData
from hyprland_socket import HyprlandError
from hyprland_state import (
    ANIM_CHILDREN,
    ANIM_FLAT,
    ANIM_LOOKUP,
    AnimState,
    get_styles_for,
)

from hyprmod.core import config
from hyprmod.core.ownership import OwnershipSet
from hyprmod.core.pending import ChangeKind, PendingChange
from hyprmod.core.undo import AnimationUndoEntry, UndoEntry
from hyprmod.data.bezier_data import get_curve_store
from hyprmod.pages.section import SectionPage
from hyprmod.ui import try_with_toast
from hyprmod.ui.bezier_editor import BezierEditorDialog
from hyprmod.ui.icons import ANIMATIONS_ICON
from hyprmod.ui.row_actions import RowActions
from hyprmod.ui.signals import SignalBlocker

ANIM_LABELS: dict[str, str] = {
    "global": "Global",
    "windows": "Windows",
    "windowsIn": "Open",
    "windowsOut": "Close",
    "windowsMove": "Move",
    "layers": "Layers",
    "layersIn": "Open",
    "layersOut": "Close",
    "fade": "Fade",
    "fadeIn": "Fade In",
    "fadeOut": "Fade Out",
    "fadeSwitch": "Switch",
    "fadeShadow": "Shadow",
    "fadeDim": "Dim",
    "fadeLayers": "Layers",
    "fadeLayersIn": "Layers In",
    "fadeLayersOut": "Layers Out",
    "fadePopups": "Popups",
    "fadePopupsIn": "Popups In",
    "fadePopupsOut": "Popups Out",
    "fadeDpms": "DPMS",
    "border": "Border",
    "borderangle": "Border Angle",
    "workspaces": "Workspaces",
    "workspacesIn": "Switch In",
    "workspacesOut": "Switch Out",
    "specialWorkspace": "Special",
    "specialWorkspaceIn": "Special In",
    "specialWorkspaceOut": "Special Out",
    "zoomFactor": "Zoom Factor",
    "monitorAdded": "Monitor Added",
}

GROUP_ORDER = [
    "Global",
    "Windows & Layers",
    "Fading",
    "Workspaces",
    "Other",
]

CAT_TO_GROUP: dict[str, str] = {
    "global": "Global",
    "windows": "Windows & Layers",
    "layers": "Windows & Layers",
    "fade": "Fading",
    "border": "Other",
    "borderangle": "Other",
    "workspaces": "Workspaces",
    "zoomFactor": "Other",
    "monitorAdded": "Other",
}


def _curve_display_names(curve_names: list[str]) -> list[str]:
    """Build display labels for curve names, starring user curves."""
    user_set = set(get_curve_store().get_user_curve_names())
    return [f"\u2605 {n}" if n in user_set else n for n in curve_names]


@dataclass
class _CurveChange(UndoEntry):
    page: "AnimationsPage"
    name: str
    old_points: tuple | None
    new_points: tuple | None

    def apply(self, window, *, undo: bool) -> bool:
        self.page.restore_curve(self.name, self.old_points if undo else self.new_points)
        return True


class AnimationsPage(SectionPage):
    def __init__(self, window, on_dirty_changed=None, push_undo=None, saved_sections=None):
        super().__init__(window, on_dirty_changed, push_undo)
        self._rows: dict[str, _AnimRow] = {}
        self._anims = window.hypr.animations

        # Initialize library cache from IPC
        self._anims.sync()
        self.load_owned_names(saved_sections)
        self.load_hyprland_curves()

        # Subscribe to reactive change notifications
        window.hypr.on_change(self._on_hypr_change)

    def _on_hypr_change(self, category: str, key: str | None):
        """React to library state changes (e.g. after sync)."""
        if category == "animations" and key:
            self._refresh_row(key)
            self._refresh_children(key)
            self._notify_dirty()

    @property
    def window(self):
        return self._window

    @property
    def anims(self):
        return self._anims

    def is_owned(self, name: str) -> bool:
        return self._ownership.is_owned(name)

    def is_saved(self, name: str) -> bool:
        return self._ownership.is_saved(name)

    def get_curve_usage(self, curve_name: str) -> int:
        """Count how many overridden animations use a given curve."""
        return sum(
            1
            for s in self._anims.get_all_cached().values()
            if s.overridden and s.curve == curve_name
        )

    def _apply_with_curves(self, state: AnimState) -> bool:
        """Apply an AnimState with automatic curve point resolution."""
        points = self.get_curve_points(state.curve) if state.curve else None
        return try_with_toast(
            self._window.show_bug_toast,
            "Animation preview failed",
            lambda: self._anims.apply_state(state, curve_points=points),
            catch=HyprlandError,
        )

    def replace_curve(self, old_name: str, new_name: str):
        """Replace all references to a curve name and re-apply affected animations."""
        for name, state in self._anims.get_all_cached().items():
            if state.curve == old_name:
                self._ownership.own(name)
                updated = replace(state, curve=new_name)
                self._anims.update_cached(name, updated)
                self._apply_with_curves(updated)

    def reset_curve_to_default(self, deleted_name: str):
        """Reset animations using a deleted curve to 'default' and re-apply."""
        for name, state in self._anims.get_all_cached().items():
            if state.overridden and state.curve == deleted_name:
                self._ownership.own(name)
                updated = replace(state, curve="default")
                self._anims.update_cached(name, updated)
                self._apply_with_curves(updated)

    def load_owned_names(self, saved_sections=None):
        """Load which animation names HyprMod owns from the config file."""
        sections = saved_sections if saved_sections is not None else self._window.saved_sections
        saved_lines = config.collect_section(sections, config.KEYWORD_ANIMATION)
        self._saved_lines: dict[str, str] = {}
        for line in saved_lines:
            _, _, val = line.partition("=")
            parts = [p.strip() for p in val.split(",")]
            if parts and parts[0]:
                name = parts[0]
                self._saved_lines[name] = line
                if self._anims.get_cached(name) is None:
                    state = AnimState.from_keyword(name, parts)
                    self._anims.set_baseline(name, state)
                    self._anims.update_cached(name, state)
        self._ownership = OwnershipSet(set(self._saved_lines))
        self._saved_curve_lines = {
            line.partition("=")[2].split(",", 1)[0].strip(): line
            for line in config.collect_section(sections, config.KEYWORD_BEZIER)
        }

    def load_hyprland_curves(self):
        """Load bezier curves from Hyprland."""
        store = get_curve_store()
        store.set_hyprland_curves(self._anims.get_curves())
        self._curve_baselines = {
            name: points
            for name in store.get_all_curve_names()
            if (points := store.get_curve_points(name)) is not None
        }
        for name, line in self._saved_curve_lines.items():
            self._curve_baselines[name] = BezierData.from_body(line.partition("=")[2]).points
        self._changed_curves: dict[str, tuple] = {}

    def get_curve_points(self, name: str) -> tuple | None:
        if name in self._changed_curves:
            return self._changed_curves[name]
        if name in self._curve_baselines:
            return self._curve_baselines[name]
        return get_curve_store().get_curve_points(name)

    @property
    def changed_curve_names(self) -> set[str]:
        return set(self._changed_curves)

    def curve_saved(self, name: str) -> None:
        """Stage an explicitly saved preset for compositor review, even if its name is unchanged."""
        points = get_curve_store().get_curve_points(name)
        if points is None:
            return
        old_points = self._changed_curves.get(name)
        new_points = points if points != self._curve_baselines.get(name) else None
        if old_points != new_points and self._push_undo:
            self._push_undo(_CurveChange(self, name, old_points, new_points))
        self.restore_curve(name, new_points)

    def restore_curve(self, name: str, points: tuple | None) -> None:
        """Restore the compositor draft without rewriting the separately saved preset library."""
        if points is None:
            self._changed_curves.pop(name, None)
        else:
            self._changed_curves[name] = points
        baseline = self._curve_baselines.get(name)
        live_points = points if points is not None else baseline
        if live_points is not None:
            try_with_toast(
                self._window.show_bug_toast,
                "Curve preview failed",
                lambda: self._anims.define_bezier(name, live_points),
                catch=HyprlandError,
            )
        self._notify_dirty()

    def revert_curve(self, name: str) -> None:
        if name in self._changed_curves:
            self.restore_curve(name, None)

    def get_curve_definitions(self, used_curves: set[str]) -> list[str]:
        """Keep canonical definitions unless explicitly edited; resolve only new references."""
        records = dict(self._saved_curve_lines)
        for line in get_curve_store().get_curve_definitions(used_curves - records.keys()):
            name = line.partition("=")[2].split(",", 1)[0].strip()
            records[name] = line
        for name, points in self._changed_curves.items():
            records[name] = BezierData(name=name, points=points).to_line()
        return list(records.values())

    def _promote_to_overridden(self, name: str) -> AnimState:
        """Promote an inherited animation to overridden, copying effective values.

        Returns the new overridden AnimState (updates cache).
        """
        eff_en, eff_sp, eff_cu, eff_st = self._anims.get_effective(name)
        state = self._anims.get_cached(name)
        promoted = (
            replace(
                state, overridden=True, enabled=eff_en, speed=eff_sp, curve=eff_cu, style=eff_st
            )
            if state
            else AnimState(
                name=name, overridden=True, enabled=eff_en, speed=eff_sp, curve=eff_cu, style=eff_st
            )
        )
        self._anims.update_cached(name, promoted)
        return promoted

    def set_overridden(self, name: str, overridden: bool):
        """Toggle whether an animation has explicit settings."""
        if not overridden:
            self.unmanage_anim(name)
            return
        state = self._anims.get_cached(name)
        if not state:
            return
        old_copy = state, self.is_owned(name)
        self._ownership.own(name)
        if not state.overridden:
            self._promote_to_overridden(name)
            self._apply_live(name)
        new_copy = self._anims.get_cached(name), self.is_owned(name)
        if self._push_undo:
            entry = AnimationUndoEntry(anim_name=name, anim_old=old_copy, anim_new=new_copy)
            self._push_undo(entry)
        self._refresh_row(name)
        self._refresh_children(name)
        self._notify_dirty()

    def set_field(self, name: str, field_name: str, value):
        """Set a specific field on an animation, making it overridden."""
        state = self._anims.get_cached(name)
        if not state:
            return
        if state.overridden and self.is_owned(name) and getattr(state, field_name) == value:
            return
        old_copy = state, self.is_owned(name)
        self._ownership.own(name)
        if not state.overridden:
            state = self._promote_to_overridden(name)

        updated = replace(state, **{field_name: value})
        self._anims.update_cached(name, updated)
        if self._push_undo:
            self._push_undo(
                AnimationUndoEntry(anim_name=name, anim_old=old_copy, anim_new=(updated, True))
            )
        self._apply_live(name)
        self._refresh_row(name)
        self._refresh_children(name)

    def restore_state(self, name: str, snapshot: tuple[AnimState | None, bool]):
        """Restore an animation to a given state (used by undo/redo)."""
        state_copy, owned = snapshot
        if owned:
            self._ownership.own(name)
        else:
            self._ownership.disown(name)
        if state_copy is not None and state_copy != self._anims.get_cached(name):
            if state_copy.overridden:
                self._apply_with_curves(state_copy)
            else:
                self._window.show_toast(
                    "Reload your config to restore the live animation baseline."
                )
            self._anims.update_cached(name, state_copy)
        self._refresh_row(name)
        self._refresh_children(name)
        self._notify_dirty()

    def _apply_live(self, name: str):
        """Apply animation to Hyprland via IPC."""
        state = self._anims.get_cached(name)
        if state:
            self._apply_with_curves(state)
        self._notify_dirty()

    def _refresh_row(self, name: str):
        """Update the UI row for an animation."""
        row = self._rows.get(name)
        if row:
            row.refresh()

    def _refresh_children(self, name: str):
        """Refresh all descendant rows that inherit from this animation."""
        for child_name in ANIM_CHILDREN.get(name, []):
            self._refresh_row(child_name)
            self._refresh_children(child_name)

    def get_animation_lines(self) -> tuple[list[str], set[str]]:
        """Merge explicit edits into saved directives, including names absent from IPC."""
        records = dict(self._saved_lines)
        for name in self._saved_lines:
            if not self.is_owned(name):
                records.pop(name)
        for name, state in self._anims.get_all_cached().items():
            if not self.is_owned(name) or not state.overridden:
                continue
            if self.is_anim_dirty(name):
                records[name] = state.to_line() if state.enabled else f"animation = {name}, 0"
        used_curves: set[str] = set()
        for line in records.values():
            parts = [part.strip() for part in line.partition("=")[2].split(",")]
            if len(parts) >= 4 and parts[3]:
                used_curves.add(parts[3])
        return list(records.values()), used_curves

    def is_anim_dirty(self, name: str) -> bool:
        """Check if a single animation has unsaved changes."""
        if self._anims.is_dirty(name):
            return True
        return self._ownership.is_item_dirty(name)

    def is_dirty(self) -> bool:
        """Check if any animation has unsaved changes."""
        if self._changed_curves or self._anims.is_dirty():
            return True
        return self._ownership.is_dirty()

    def revert_anim(self, name: str):
        """Revert a single animation to its saved state (value + ownership)."""
        baseline = self._anims.get_baseline(name)
        if baseline is not None and baseline != self._anims.get_cached(name):
            if baseline.overridden:
                self._apply_with_curves(baseline)
            else:
                self._window.show_toast(
                    "Reload your config to restore the live animation baseline."
                )
            self._anims.update_cached(name, baseline)
        self._ownership.discard(name)
        self._refresh_row(name)
        self._refresh_children(name)
        self._notify_dirty()

    def unmanage_anim(self, name: str):
        """Remove only the saved override, without guessing a live fallback."""
        state = self._anims.get_cached(name)
        was_owned = self.is_owned(name)
        self._ownership.disown(name)
        if was_owned and self._push_undo:
            self._push_undo(AnimationUndoEntry(name, (state, True), (state, False)))
        self._window.show_toast(
            "Save removes override; reload your config to restore baseline.", timeout=5
        )
        self._refresh_row(name)
        self._refresh_children(name)
        self._notify_dirty()

    def mark_saved(self):
        lines, used_curves = self.get_animation_lines()
        definitions = self.get_curve_definitions(used_curves)
        self._saved_curve_lines = {}
        for line in definitions:
            curve = BezierData.from_body(line.partition("=")[2])
            self._saved_curve_lines[curve.name] = line
            self._curve_baselines[curve.name] = curve.points
        self._changed_curves.clear()
        self._saved_lines = {line.partition("=")[2].split(",")[0].strip(): line for line in lines}
        self._ownership.mark_saved()
        self._anims.mark_saved()
        for name in ANIM_LOOKUP:
            self._refresh_row(name)

    def discard(self):
        """Revert to saved state and re-apply via IPC."""
        for name in list(self._changed_curves):
            self.revert_curve(name)
        self._ownership.discard_all()
        try_with_toast(
            self._window.show_bug_toast,
            "Animation discard failed",
            self._anims.discard,
            catch=HyprlandError,
        )
        # Match ``revert_anim``: refresh every row + tell the window the page is
        # clean again. Without this the rows render with stale dirty indicators
        # until the next change forces a paint.
        for name in ANIM_LOOKUP:
            self._refresh_row(name)
        self._notify_dirty()

    # ── Pending changes ──

    def iter_pending_changes(self) -> Iterator[PendingChange]:
        if not self.is_dirty():
            return
        for name, points in self._changed_curves.items():
            baseline = self._curve_baselines.get(name)
            yield PendingChange(
                category="Animations",
                title=f"Curve: {name}",
                subtitle=f"Control points: {baseline} to {points}",
                kind="modified" if baseline is not None else "added",
                revert=lambda n=name: self.revert_curve(n),
                navigate_to="animations",
                icon=ANIMATIONS_ICON,
            )
        for name, *_ in ANIM_FLAT:
            if name not in ANIM_LOOKUP or not self.is_anim_dirty(name):
                continue
            current = self._anims.get_cached(name)
            baseline = self._anims.get_baseline(name)
            kind, subtitle = self._describe_change(name, baseline, current)
            yield PendingChange(
                category="Animations",
                title=ANIM_LABELS.get(name, name),
                subtitle=subtitle,
                kind=kind,
                revert=lambda n=name: self.revert_anim(n),
                navigate_to="animations",
                icon=ANIMATIONS_ICON,
            )

    def _describe_change(
        self,
        name: str,
        baseline: AnimState | None,
        current: AnimState | None,
    ) -> tuple[ChangeKind, str]:
        was_owned = self._ownership.is_saved(name)
        is_owned = self._ownership.is_owned(name)
        # Pure ownership flips
        if was_owned and not is_owned:
            return "removed", "remove override on save"
        if not was_owned and is_owned and (baseline is None or not baseline.overridden):
            return "added", "new override"

        # Field-level diff between baseline and current
        if baseline is None or current is None:
            return "modified", "updated"

        diffs: list[str] = []
        if baseline.enabled != current.enabled:
            diffs.append(
                f"{'on' if baseline.enabled else 'off'} → {'on' if current.enabled else 'off'}"
            )
        if abs(baseline.speed - current.speed) > 1e-6:
            diffs.append(f"speed {baseline.speed:g} → {current.speed:g}")
        if (baseline.curve or "") != (current.curve or ""):
            diffs.append(f"curve {baseline.curve or '—'} → {current.curve or '—'}")
        if (baseline.style or "") != (current.style or ""):
            diffs.append(f"style {baseline.style or '—'} → {current.style or '—'}")
        return "modified", " · ".join(diffs) if diffs else "updated"

    # -- UI building --

    def build_widget(self) -> Gtk.Box:
        """Build the animation list with ExpanderRows for categories with children."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        # Group animations by top-level category, then merge into UI groups.
        categories = {}
        current_cat = None
        for name, parent, depth, styles in ANIM_FLAT:
            if name == "global":
                current_cat = "global"
                categories.setdefault(current_cat, [])
                categories[current_cat].append((name, parent, depth, styles))
            elif depth == 1:
                current_cat = name
                categories.setdefault(current_cat, [])
                categories[current_cat].append((name, parent, depth, styles))
            else:
                if current_cat:
                    categories[current_cat].append((name, parent, depth, styles))

        # Merge categories into broader groups in defined order.
        groups: dict[str, list[tuple[str, list]]] = {}
        for cat_name, entries in categories.items():
            grp = CAT_TO_GROUP.get(cat_name, "Other")
            groups.setdefault(grp, []).append((cat_name, entries))

        for grp_name in GROUP_ORDER:
            cat_list = groups.get(grp_name)
            if not cat_list:
                continue
            group = Adw.PreferencesGroup(title=GLib.markup_escape_text(grp_name))

            for _, entries in cat_list:
                has_children = any(depth > 1 for _, _, depth, _ in entries)
                parent_row = None

                for name, _parent, depth, _styles in entries:
                    avail_styles = get_styles_for(name)
                    if depth <= 1 and has_children:
                        row = _AnimRow(self, name, depth, avail_styles, is_parent=True)
                        parent_row = row
                        group.add(row.widget)
                    elif depth > 1 and parent_row is not None:
                        row = _AnimRow(self, name, depth, avail_styles)
                        parent_row.add_child(row)
                    else:
                        row = _AnimRow(self, name, depth, avail_styles)
                        group.add(row.widget)
                    self._rows[name] = row

            box.append(group)

        return box

    def build_curve_editor_widget(self) -> Adw.PreferencesGroup:
        """Build the Bezier Curve Editor row as a standalone group."""
        group = Adw.PreferencesGroup()
        curves_row = Adw.ActionRow(
            title="Bezier Curve Editor",
            subtitle="Create and manage animation curves",
        )
        curves_row.add_prefix(Gtk.Image.new_from_icon_name("draw-arc-symbolic"))
        curves_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        curves_row.set_activatable(True)
        curves_row.connect("activated", self._on_open_curve_editor)
        group.add(curves_row)
        return group

    def _on_open_curve_editor(self, _row):
        BezierEditorDialog(
            self._window,
            animation_page=self,
            get_curve_usage=self.get_curve_usage,
            animations=self._anims,
        )


class _AnimRow:
    """A single animation row.

    Parent rows (is_parent=True) use ExpanderRow to reveal child sub-animations.
    Child/standalone rows use ActionRow — click to open the detail dialog.
    """

    def __init__(
        self,
        page: AnimationsPage,
        name: str,
        depth: int,
        styles: tuple[str, ...] | list[str],
        is_parent: bool = False,
    ):
        self._page = page
        self._name = name
        self._depth = depth
        self._styles = styles
        self._is_parent = is_parent
        self._signals = SignalBlocker()

        if is_parent:
            self._row = Adw.ExpanderRow(title=ANIM_LABELS.get(name, name))
        else:
            self._row = Adw.ActionRow(title=ANIM_LABELS.get(name, name))
            self._row.set_activatable(True)
            self._row.connect("activated", self._on_activated)

        # Enable switch as a prefix — consistent left-edge alignment across all rows
        self._switch = Gtk.Switch()
        self._switch.set_valign(Gtk.Align.CENTER)
        self._signals.connect(self._switch, "notify::active", self._on_switch)
        self._row.add_prefix(self._switch)

        if is_parent:
            # Edit button to open the detail dialog (clicking the row expands children)
            edit_btn = Gtk.Button(icon_name="menu-symbolic")
            edit_btn.set_valign(Gtk.Align.CENTER)
            edit_btn.add_css_class("flat")
            edit_btn.set_tooltip_text("Edit animation settings")
            edit_btn.connect("clicked", lambda _b: self._on_activated(None))
            self._row.add_suffix(edit_btn)

        self._actions = RowActions(
            self._row,
            on_discard=self._on_discard,
            on_reset=self._on_reset,
        )
        self._row.add_suffix(self._actions.box)

        self.refresh()

    def add_child(self, child_row: "_AnimRow"):
        """Add a child row to this parent's ExpanderRow."""
        self._row.add_row(child_row.widget)  # type: ignore[union-attr]

    @property
    def widget(self):
        return self._row

    def refresh(self):
        """Update the row subtitle and switch from the current state."""
        with self._signals:
            state = self._page.anims.get_cached(self._name)
            if not state:
                return

            eff_en, eff_sp, eff_cu, eff_st = self._page.anims.get_effective(self._name)
            is_override = state.overridden
            is_dirty = self._page.is_anim_dirty(self._name)

            self._switch.set_active(eff_en)
            is_owned = self._page.is_owned(self._name)
            is_saved = self._page.is_saved(self._name)
            self._actions.update(is_managed=is_owned, is_dirty=is_dirty, is_saved=is_saved)

            # Build subtitle showing effective values
            parts = []
            if not eff_en:
                parts.append("disabled")
            parts.append(f"{eff_sp:.1f}ds")
            parts.append(eff_cu)
            if eff_st:
                parts.append(eff_st)

            if is_override:
                self._row.set_subtitle(" \u00b7 ".join(parts))
            else:
                self._row.set_subtitle("inherited \u00b7 " + " \u00b7 ".join(parts))

            # Dim inherited values
            self._switch.set_opacity(1.0 if is_override else 0.5)

    def _on_switch(self, switch, _pspec):
        self._page.set_field(self._name, "enabled", switch.get_active())

    def _on_discard(self):
        self._page.revert_anim(self._name)

    def _on_reset(self):
        self._page.unmanage_anim(self._name)

    def _on_activated(self, _row):
        """Open the detail dialog for this animation."""
        _AnimDetailDialog(self._page, self._name, self._styles)


class _AnimDetailDialog:
    """Dialog for editing a single animation's speed, curve, and style."""

    def __init__(self, page: AnimationsPage, name: str, styles: tuple[str, ...] | list[str]):
        self._page = page
        self._name = name
        self._styles = styles
        self._signals = SignalBlocker()

        state = page.anims.get_cached(name)
        eff_en, eff_sp, eff_cu, eff_st = page.anims.get_effective(name)

        self._dialog = Adw.Dialog()
        self._dialog.set_title(ANIM_LABELS.get(name, name))
        self._dialog.set_content_width(400)
        self._dialog.set_follows_content_size(True)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.set_margin_top(12)
        content.set_margin_bottom(24)
        content.set_margin_start(12)
        content.set_margin_end(12)

        # Inherited note
        if state and not state.overridden:
            note = Gtk.Label(
                label="Inherits from parent. Editing will create an override.",
            )
            note.set_wrap(True)
            note.add_css_class("dim-label")
            note.set_margin_bottom(12)
            content.append(note)

        group = Adw.PreferencesGroup()

        # Speed
        speed_adj = Gtk.Adjustment(
            value=eff_sp,
            lower=0.5,
            upper=30,
            step_increment=0.5,
            page_increment=1,
        )
        self._speed_spin = Gtk.SpinButton(adjustment=speed_adj, digits=1)
        self._speed_spin.set_valign(Gtk.Align.CENTER)
        self._speed_row = Adw.ActionRow(
            title="Speed",
            subtitle="Duration in deciseconds (1 = 100ms)",
        )
        self._speed_row.add_suffix(self._speed_spin)
        self._signals.connect(self._speed_spin, "value-changed", self._on_speed)
        group.add(self._speed_row)

        # Curve with the edit button
        self._curve_names = get_curve_store().get_all_curve_names()
        curve_model = Gtk.StringList.new(_curve_display_names(self._curve_names))
        self._curve_row = Adw.ComboRow(
            title="Curve",
            subtitle="Bezier easing curve",
            model=curve_model,
        )
        if eff_cu in self._curve_names:
            self._curve_row.set_selected(self._curve_names.index(eff_cu))
        self._signals.connect(self._curve_row, "notify::selected", self._on_curve)

        edit_btn = Gtk.Button(icon_name="draw-arc-symbolic")
        edit_btn.set_valign(Gtk.Align.CENTER)
        edit_btn.add_css_class("flat")
        edit_btn.set_tooltip_text("Edit curve")
        edit_btn.connect("clicked", self._on_edit_curve)
        self._curve_row.add_suffix(edit_btn)
        group.add(self._curve_row)

        # Style (only if styles available)
        self._style_row = None
        if styles:
            style_options = ["default"] + list(styles)
            self._style_names = style_options
            style_model = Gtk.StringList.new(style_options)
            self._style_row = Adw.ComboRow(
                title="Style",
                subtitle="Animation style",
                model=style_model,
            )
            base_style = eff_st.split()[0] if eff_st else ""
            if base_style in self._style_names:
                self._style_row.set_selected(self._style_names.index(base_style))
            self._signals.connect(self._style_row, "notify::selected", self._on_style)
            group.add(self._style_row)

        content.append(group)
        toolbar.set_content(content)
        self._dialog.set_child(toolbar)
        self._dialog.present(page.window)

    def _on_speed(self, btn):
        self._page.set_field(self._name, "speed", btn.get_value())

    def _on_curve(self, row, _pspec):
        idx = row.get_selected()
        if 0 <= idx < len(self._curve_names):
            self._page.set_field(self._name, "curve", self._curve_names[idx])

    def _on_style(self, row, _pspec):
        idx = row.get_selected()
        if 0 <= idx < len(self._style_names):
            val = self._style_names[idx]
            self._page.set_field(self._name, "style", "" if val == "default" else val)

    def _on_edit_curve(self, _btn):
        idx = self._curve_row.get_selected()
        curve_name = self._curve_names[idx] if 0 <= idx < len(self._curve_names) else None

        BezierEditorDialog(
            self._page.window,
            on_curve_saved=self._refresh_curves,
            initial_curve=curve_name,
            animation_name=self._name,
            animation_page=self._page,
            get_curve_usage=self._page.get_curve_usage,
            animations=self._page.anims,
        )

    def _refresh_curves(self, curve_name=None):
        """Refresh curve dropdown after curve changes."""
        self._curve_names = get_curve_store().get_all_curve_names()
        model = Gtk.StringList.new(_curve_display_names(self._curve_names))
        with self._signals:
            self._curve_row.set_model(model)
            target = curve_name or self._page.anims.get_effective(self._name)[2]
            if target in self._curve_names:
                self._curve_row.set_selected(self._curve_names.index(target))
