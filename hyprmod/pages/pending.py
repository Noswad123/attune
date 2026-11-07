"""Pending Changes page — aggregated overview of unsaved edits.

Walks every section page's ``iter_pending_changes()`` plus the
window-level option diff, and renders a unified diff between the
on-disk config and the next-save serialization so users can verify
what's about to land in Attune's managed config.
"""

import hashlib
import logging
import threading
from html import escape as html_escape
from typing import TYPE_CHECKING

from gi.repository import Adw, GLib, Gtk
from hyprland_config import ParseError, value_to_conf

from hyprmod.core import bindings, editor_layout, schema
from hyprmod.core import input as input_config
from hyprmod.core.focused_ui import ReviewSnapshot
from hyprmod.core.pending import ChangeKind, PendingChange
from hyprmod.core.scoped_review import GroupReviewPlan
from hyprmod.core.state import OptionState
from hyprmod.ui import clear_children, make_page_layout
from hyprmod.ui.diff import ConfigDiffWidget
from hyprmod.ui.empty_state import EmptyState
from hyprmod.ui.icons import FALLBACK_ICON, MONITORS_ICON

log = logging.getLogger(__name__)

PAIR_REVIEW_FAILURE_GUIDANCE = (
    "Session-local edits retained (not saved across restart). Retry review for temporary failures. "
    "If files or routes changed, this session cannot adopt external edits: manually correct or "
    "restore the registered canonical files/routes, then restart/reopen Attune."
)

if TYPE_CHECKING:
    from hyprmod.window import HyprModWindow


# Categories shown in the page, in the order they appear.
_CATEGORY_ORDER = (
    "Options",
    "Animations",
    "Monitors",
    "Source Shortcuts",
    "Keybindings",
    "Input",
    "Cursor",
)

# Visual label and CSS class for each kind of change.
_KIND_BADGE = {
    "modified": ("Modified", "pending-badge-modified"),
    "added": ("Added", "pending-badge-added"),
    "removed": ("Removed", "pending-badge-removed"),
}


class PendingChangesPage:
    """Live overview of every unsaved item plus a config diff preview."""

    def __init__(self, window: "HyprModWindow"):
        self._window = window
        self._toolbar: Adw.ToolbarView | None = None
        self._content_box: Gtk.Box | None = None
        self._summary_label: Gtk.Label | None = None
        self._empty_state: EmptyState | None = None
        self._groups_box: Gtk.Box | None = None
        self._diff: ConfigDiffWidget | None = None
        self._diff_group: Adw.PreferencesGroup | None = None
        self._reviewed: ReviewSnapshot | None = None
        self._save_button: Gtk.Button | None = None
        self._review_error: Gtk.Label | None = None
        self._pair_review: GroupReviewPlan | None = None
        self._pair_proposals = {}
        self._revision = 0
        self._read_cancel: threading.Event | None = None
        self._pair_box: Gtk.Box | None = None
        self._closed = False
        self._bindings_review: bindings.BindingsReview | None = None
        self._bindings_source: bindings.BindingsBaseline | None = None
        self._bindings_read_cancel: threading.Event | None = None
        self._bindings_save_request: (
            tuple[
                bindings.BindingsReview,
                bindings.BindingsConfig,
                bindings.BindingsBaseline | None,
                int,
            ]
            | None
        ) = None
        self._bindings_box: Gtk.Box | None = None
        self._bindings_save_button: Gtk.Button | None = None
        self._input_review: input_config.InputReview | None = None
        self._input_source: input_config.InputBaseline | None = None
        self._input_read_cancel: threading.Event | None = None
        self._input_save_request: (
            tuple[
                input_config.InputReview,
                input_config.InputConfig,
                input_config.InputBaseline | None,
                int,
            ]
            | None
        ) = None
        self._input_box: Gtk.Box | None = None
        self._input_save_button: Gtk.Button | None = None
        # Coalesce many quick "dirty" pings (e.g. typing in a spinbutton) into
        # a single rebuild. Without this the page rebuilds at signal speed
        # which is wasteful and can fight scroll position recovery.
        self._refresh_pending = False
        # Map sidebar group_id -> icon name, sourced from the same schema the
        # sidebar uses, so each row's icon mirrors its source page exactly.
        self._group_icons: dict[str, str] = {
            "monitors": MONITORS_ICON,
        }
        for g in schema.get_groups(window._schema):
            icon = g.get("icon")
            if icon:
                self._group_icons[g["id"]] = icon

    # ── Build ──

    def build(self, header: Adw.HeaderBar) -> Adw.ToolbarView:
        toolbar, _, content_box, _ = make_page_layout(header=header)
        self._toolbar = toolbar
        self._content_box = content_box
        content_box.append(
            Gtk.Label(
                label="Appearance / displays, Input, source shortcuts and additional bindings "
                "are four independent save units. "
                "Review and save each separately; there is no atomic Save Everything.",
                xalign=0,
                wrap=True,
            )
        )

        # Summary banner-style label at the top
        self._summary_label = Gtk.Label(xalign=0)
        self._summary_label.add_css_class("title-2")
        content_box.append(self._summary_label)

        self._empty_state = EmptyState(
            title="No Pending Changes",
            description=(
                "Edits made on any page will appear here for you to review before saving."
            ),
            icon_name="emblem-ok-symbolic",
        )
        content_box.append(self._empty_state)

        self._groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content_box.append(self._groups_box)
        source_review = Gtk.Button(label="Review Source Shortcuts...")
        source_review.connect("clicked", lambda _b: self._window.show_source_bindings_review())
        content_box.append(source_review)

        # Diff section — hidden when there are no changes (saved file already
        # matches what the next save would write).
        diff_group = Adw.PreferencesGroup()
        diff_group.set_title("Config diff preview")
        diff_group.set_description(
            "Comparison between the saved config and what the next save would write."
        )

        diff_card = Gtk.Frame()
        diff_card.add_css_class("config-diff-frame")
        self._diff = ConfigDiffWidget()
        self._diff.set_size_request(-1, 280)
        diff_card.set_child(self._diff)
        diff_group.add(diff_card)
        diff_group.set_visible(False)

        self._diff_group = diff_group
        content_box.append(diff_group)
        self._pair_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content_box.append(self._pair_box)

        self._review_error = Gtk.Label(xalign=0, wrap=True)
        self._review_error.add_css_class("error")
        self._review_error.set_visible(False)
        content_box.append(self._review_error)
        self._save_button = Gtk.Button(label="Save Reviewed Appearance / Displays")
        self._save_button.add_css_class("suggested-action")
        self._save_button.set_halign(Gtk.Align.END)
        self._save_button.set_sensitive(False)
        self._save_button.connect("clicked", self._on_save_reviewed)
        content_box.append(self._save_button)

        self._bindings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.append(self._bindings_box)
        self._bindings_save_button = Gtk.Button(label="Save Reviewed Keybindings")
        self._bindings_save_button.add_css_class("suggested-action")
        self._bindings_save_button.set_halign(Gtk.Align.END)
        self._bindings_save_button.set_sensitive(False)
        self._bindings_save_button.connect("clicked", self._on_save_bindings)
        content_box.append(self._bindings_save_button)

        self._input_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content_box.append(self._input_box)
        self._input_save_button = Gtk.Button(label="Save Reviewed Input")
        self._input_save_button.add_css_class("suggested-action")
        self._input_save_button.set_halign(Gtk.Align.END)
        self._input_save_button.set_sensitive(False)
        self._input_save_button.connect("clicked", self._on_save_input)
        content_box.append(self._input_save_button)

        self.refresh()
        return toolbar

    # ── Public refresh entry points ──

    def schedule_refresh(self) -> None:
        """Coalesce repeated change pings into a single idle-time rebuild."""
        self._reviewed = None
        self._pair_review = None
        self._revision += 1
        self._invalidate_input_review()
        self._bindings_review = None
        self._bindings_save_request = None
        if self._bindings_read_cancel is not None:
            self._bindings_read_cancel.set()
        if self._bindings_save_button is not None:
            self._bindings_save_button.set_sensitive(False)
        if self._read_cancel is not None:
            self._read_cancel.set()
        if self._save_button is not None:
            self._save_button.set_sensitive(False)
        if self._refresh_pending:
            return
        self._refresh_pending = True
        GLib.idle_add(self._refresh_idle)

    def cancel_review(self) -> None:
        self._closed = True
        self._invalidate_input_review()
        self._bindings_review = None
        self._bindings_save_request = None
        if self._bindings_read_cancel is not None:
            self._bindings_read_cancel.set()
        if self._bindings_save_button is not None:
            self._bindings_save_button.set_sensitive(False)
        self._pair_review = None
        self._revision += 1
        if self._read_cancel is not None:
            self._read_cancel.set()
        if self._save_button is not None:
            self._save_button.set_sensitive(False)

    def _refresh_idle(self) -> bool:
        self._refresh_pending = False
        self.refresh()
        return GLib.SOURCE_REMOVE

    def refresh(self) -> None:
        """Rebuild the change list and the diff preview from current state."""
        if self._closed:
            return
        # All widgets are populated together by build(); guarding on any one
        # of them is enough to skip pre-build refreshes safely.
        groups_box = self._groups_box
        summary_label = self._summary_label
        empty_state = self._empty_state
        if groups_box is None or summary_label is None or empty_state is None:
            return

        changes = self.collect_changes()
        self._render_changes(changes, groups_box, summary_label, empty_state)
        self._render_diff()
        self._render_owned_review(is_input=False)
        self._render_owned_review(is_input=True)

    def _invalidate_input_review(self) -> None:
        self._input_review = None
        self._input_save_request = None
        if self._input_read_cancel is not None:
            self._input_read_cancel.set()
        if self._input_save_button is not None:
            self._input_save_button.set_sensitive(False)

    def _render_owned_review(self, *, is_input: bool) -> None:
        box = self._input_box if is_input else self._bindings_box
        button = self._input_save_button if is_input else self._bindings_save_button
        label = "Input" if is_input else "Keybindings"
        cancel_attr = "_input_read_cancel" if is_input else "_bindings_read_cancel"
        if box is None or button is None:
            return
        if is_input:
            self._input_review = None
        else:
            self._bindings_review = None
        button.set_sensitive(False)
        clear_children(box)
        page = self._window._input_page if is_input else self._window._managed_bindings_page
        if page is None or not page.is_dirty():
            button.set_visible(False)
            return
        button.set_visible(True)
        box.append(Gtk.Label(label=f"{label}: independent save unit", xalign=0))
        if is_input:
            box.append(
                Gtk.Label(
                    label="Devices and Cursor share this complete review. Save Reviewed Input "
                    "writes both together to attune-input.lua and clears both drafts atomically.",
                    xalign=0,
                    wrap=True,
                )
            )
        baseline = page.baseline
        if baseline is None or page.locked:
            box.append(
                Gtk.Label(
                    label=page.load_error
                    or f"{label} locked. Manually correct the file and reopen Attune.",
                    xalign=0,
                    wrap=True,
                )
            )
            return
        if self._closed or self._window.editor_locked or getattr(self, cancel_attr) is not None:
            return
        proposed = page.get_config()
        revision = self._revision
        cancel = threading.Event()
        setattr(self, cancel_attr, cancel)
        box.append(Gtk.Label(label=f"Preparing complete {label} review...", xalign=0))

        def complete(review, error):
            if getattr(self, cancel_attr) is not cancel:
                return GLib.SOURCE_REMOVE
            setattr(self, cancel_attr, None)
            if self._closed:
                return GLib.SOURCE_REMOVE
            if (
                cancel.is_set()
                or revision != self._revision
                or page.baseline is not baseline
                or page.get_config() != proposed
            ):
                self.refresh()
                return GLib.SOURCE_REMOVE
            if self._window.editor_locked or page.locked:
                return GLib.SOURCE_REMOVE
            clear_children(box)
            if (
                error is not None
                or type(review)
                is not (input_config.InputReview if is_input else bindings.BindingsReview)
                or not (
                    (
                        type(baseline) is input_config.InputBaseline
                        and type(review.baseline) is input_config.InputBaseline
                        and input_config.same_source(baseline, review.baseline)
                    )
                    or (
                        type(baseline) is bindings.BindingsBaseline
                        and type(review.baseline) is bindings.BindingsBaseline
                        and bindings.same_source(baseline, review.baseline)
                    )
                )
                or review.proposed != proposed
            ):
                box.append(
                    Gtk.Label(
                        label=f"Cannot review {label}: {error or 'unexpected result'}. "
                        "Draft retained. Manually correct changed file/routes and reopen Attune.",
                        xalign=0,
                        wrap=True,
                    )
                )
                return GLib.SOURCE_REMOVE
            box.append(
                Gtk.Label(
                    label=f"{label} only. Fixed output: {baseline.lexical_path}\n"
                    f"Resolved: {baseline.resolved_path}\nPrior status: {baseline.status}\n"
                    f"SHA256: {baseline.sha256} -> "
                    f"{hashlib.sha256(review.proposed_text.encode('utf-8')).hexdigest()}\n"
                    f"Review: {review.review_hash}\n"
                    "Other units are saved separately. Only after this file exists, "
                    "manually add dofile "
                    "with this exact absolute path to your own Lua entrypoint: "
                    f"{baseline.lexical_path}. "
                    "Attune does not insert includes, unbind, apply, execute commands or reload. "
                    "Disk state is not runtime-loading proof; watchers may reload automatically.",
                    xalign=0,
                    wrap=True,
                    selectable=True,
                )
            )
            diff = ConfigDiffWidget()
            diff.set_precomputed_diff(
                review.diff,
                added_lines=review.added_lines,
                removed_lines=review.removed_lines,
                title=label,
            )
            box.append(diff)
            if (
                type(review) is input_config.InputReview
                and type(baseline) is input_config.InputBaseline
            ):
                self._input_source = baseline
                self._input_review = review
            elif (
                type(review) is bindings.BindingsReview
                and type(baseline) is bindings.BindingsBaseline
            ):
                self._bindings_source = baseline
                self._bindings_review = review
            button.set_sensitive(True)
            return GLib.SOURCE_REMOVE

        def work():
            try:
                if (
                    type(baseline) is input_config.InputBaseline
                    and type(proposed) is input_config.InputConfig
                ):
                    review = input_config.run_prepare_review(
                        baseline, proposed, cancel_event=cancel
                    )
                elif (
                    type(baseline) is bindings.BindingsBaseline
                    and type(proposed) is bindings.BindingsConfig
                ):
                    review = bindings.run_prepare_review(baseline, proposed, cancel_event=cancel)
                else:
                    raise ValueError("Mismatched review request")
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc))
            else:
                GLib.idle_add(complete, review, None)

        try:
            threading.Thread(target=work, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc))

    def _on_save_bindings(self, _button: Gtk.Button) -> None:
        review = self._bindings_review
        source = self._bindings_source
        self._bindings_review = None
        if self._bindings_save_button is not None:
            self._bindings_save_button.set_sensitive(False)
        if review is None:
            return
        proposed = review.proposed
        self._bindings_save_request = (review, proposed, source, self._revision)
        self._window.save_bindings_reviewed(review, proposed)

    def take_bindings_save_request(
        self, review: bindings.BindingsReview, proposed: bindings.BindingsConfig
    ) -> bool:
        request = self._bindings_save_request
        self._bindings_save_request = None
        page = self._window._managed_bindings_page
        return (
            request is not None
            and request[0] is review
            and request[1] == proposed
            and page is not None
            and request[2] is page.baseline
            and request[3] == self._revision
            and not self._closed
        )

    def _on_save_input(self, _button: Gtk.Button) -> None:
        review = self._input_review
        source = self._input_source
        self._input_review = None
        if self._input_save_button is not None:
            self._input_save_button.set_sensitive(False)
        if review is None:
            return
        self._input_save_request = (review, review.proposed, source, self._revision)
        self._window.save_input_reviewed(review, review.proposed)

    def take_input_save_request(
        self, review: input_config.InputReview, proposed: input_config.InputConfig
    ) -> bool:
        request = self._input_save_request
        self._input_save_request = None
        page = self._window._input_page
        return (
            request is not None
            and request[0] is review
            and request[1] == proposed
            and page is not None
            and request[2] is page.baseline
            and request[3] == self._revision
            and not self._closed
        )

    # ── Render: change list ──

    def _render_changes(
        self,
        changes: list[PendingChange],
        groups_box: Gtk.Box,
        summary_label: Gtk.Label,
        empty_state: EmptyState,
    ) -> None:
        clear_children(groups_box)

        # Group by category, preserving discovery order within each.
        by_cat: dict[str, list[PendingChange]] = {}
        for ch in changes:
            by_cat.setdefault(ch.category, []).append(ch)

        total = len(changes)
        if total == 0:
            summary_label.set_visible(False)
            empty_state.set_visible(True)
            groups_box.set_visible(False)
            return

        summary_label.set_visible(True)
        summary_label.set_label(f"{total} unsaved change{'s' if total != 1 else ''}")
        empty_state.set_visible(False)
        groups_box.set_visible(True)

        for cat in _CATEGORY_ORDER:
            cat_changes = by_cat.get(cat)
            if not cat_changes:
                continue
            group = Adw.PreferencesGroup(title=cat)
            group.set_description(
                f"{len(cat_changes)} change" + ("s" if len(cat_changes) != 1 else "")
            )
            for change in cat_changes:
                row = self._make_row(change)
                group.add(row)
            groups_box.append(group)

    def _make_row(self, change: PendingChange) -> Adw.ActionRow:
        row = Adw.ActionRow(
            title=html_escape(change.title),
            subtitle=html_escape(change.subtitle),
        )
        icon = Gtk.Image.new_from_icon_name(change.icon)
        icon.add_css_class("dim-label")
        row.add_prefix(icon)

        # Kind badge ("Modified" / "Added" / "Removed")
        badge_label, badge_class = _KIND_BADGE[change.kind]
        badge = Gtk.Label(label=badge_label)
        badge.add_css_class("pending-badge")
        badge.add_css_class(badge_class)
        badge.set_valign(Gtk.Align.CENTER)
        row.add_suffix(badge)

        # Discard button — primary action for the row
        discard_btn = Gtk.Button(icon_name="edit-undo-symbolic")
        discard_btn.set_tooltip_text("Revert this change")
        discard_btn.set_valign(Gtk.Align.CENTER)
        discard_btn.add_css_class("flat")

        def _on_discard(_btn: Gtk.Button, ch: PendingChange = change) -> None:
            try:
                ch.revert()
            except ValueError as exc:
                self._window.show_toast(str(exc), 5)
            finally:
                self.schedule_refresh()

        discard_btn.connect("clicked", _on_discard)
        row.add_suffix(discard_btn)

        # Optional navigation arrow when we know the source page
        if change.navigate_to:
            arrow = Gtk.Image.new_from_icon_name("go-next-symbolic")
            arrow.add_css_class("dim-label")
            row.add_suffix(arrow)
            row.set_activatable(True)
            row.connect("activated", self._on_row_activated, change)
        return row

    def _on_row_activated(self, _row: Adw.ActionRow, change: PendingChange) -> None:
        if not change.navigate_to:
            return
        # Pass the target key so navigate() can flip ViewSwitcher sub-tabs
        # (e.g. Layouts → Dwindle) before we try to focus the option row.
        if change.category == "Source Shortcuts":
            self._window.show_source_bindings_review()
        elif change.category == "Keybindings":
            self._window.show_additional_bindings()
        else:
            self._window.navigate(change.navigate_to, option_key=change.target_key)

        # Highlight + focus the source option once the target page has had a
        # chance to render — same pattern the search-result navigation uses.
        target_key = change.target_key
        if not target_key:
            return
        opt_row = self._window.option_rows.get(target_key)
        if opt_row is None:
            return

        def _scroll_and_highlight() -> bool:
            opt_row.row.grab_focus()
            opt_row.flash_highlight()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(_scroll_and_highlight)

    # ── Render: diff ──

    def _render_diff(self) -> None:
        if self._diff is None or self._diff_group is None:
            return
        if self._window.pair_layout is not None:
            self._render_pair_review()
            return
        self._reviewed = None
        if self._save_button is not None:
            self._save_button.set_sensitive(False)
        if self._review_error is not None:
            self._review_error.set_visible(False)
        try:
            snapshot = self._window.review_snapshot()
        except (OSError, UnicodeError, ValueError, ParseError) as exc:
            log.exception("Failed to compose pending-changes diff preview")
            self._diff_group.set_visible(False)
            if self._review_error is not None:
                self._review_error.set_label(
                    f"Cannot review this output. Saving is disabled: {exc}"
                )
                self._review_error.set_visible(True)
            return
        path = snapshot.path
        old_text, new_text = snapshot.saved_text, snapshot.proposed_text
        # Hide the whole "Config diff preview" group when there's nothing to
        # show — the standalone empty placeholder inside the diff widget is
        # redundant when the parent group is collapsed.
        if old_text == new_text:
            self._diff_group.set_visible(False)
            return
        self._diff_group.set_visible(True)
        self._diff.set_texts(
            old_text,
            new_text,
            old_label=str(path),
            new_label=f"{path} (next save)",
            title=f"{path.name}",
        )
        self._reviewed = snapshot
        if self._save_button is not None:
            self._save_button.set_sensitive(True)

    def _on_save_reviewed(self, _button: Gtk.Button) -> None:
        if self._pair_review is not None:
            plan = self._pair_review
            proposals = self._pair_proposals
            self._pair_review = None
            if self._save_button is not None:
                self._save_button.set_sensitive(False)
            self._window.save_pair_reviewed(plan, proposals)
            return
        if self._reviewed is not None:
            self._window.save_reviewed(self._reviewed)

    def _render_pair_review(self) -> None:
        self._pair_review = None
        if self._save_button is not None:
            self._save_button.set_sensitive(False)
        if self._diff_group is not None:
            self._diff_group.set_visible(False)
        if self._pair_box is not None:
            clear_children(self._pair_box)
        if self._closed or self._read_cancel is not None or self._window.editor_locked:
            return
        pair = self._window.pair_layout
        if pair is None:
            return
        try:
            proposals = self._window.pair_proposals()
        except (ValueError, ParseError) as exc:
            if self._review_error is not None:
                self._review_error.set_label(f"Cannot prepare review: {exc}")
                self._review_error.set_visible(True)
            return
        revision = self._revision
        cancel = threading.Event()
        self._read_cancel = cancel
        if self._review_error is not None:
            self._review_error.set_label("Preparing complete appearance and displays review...")
            self._review_error.set_visible(True)

        def complete(plan, error):
            if self._read_cancel is not cancel:
                return GLib.SOURCE_REMOVE
            self._read_cancel = None
            if self._closed:
                return GLib.SOURCE_REMOVE
            if (
                cancel.is_set()
                or revision != self._revision
                or self._window.pair_layout is not pair
            ):
                self.refresh()
                return GLib.SOURCE_REMOVE
            if self._window.editor_locked:
                return GLib.SOURCE_REMOVE
            if error is not None or type(plan) is not GroupReviewPlan:
                if self._review_error is not None:
                    self._review_error.set_label(
                        f"Cannot review pair. Saving disabled: {error}. "
                        + PAIR_REVIEW_FAILURE_GUIDANCE
                    )
                    self._review_error.set_visible(True)
                return GLib.SOURCE_REMOVE
            if proposals != self._window.pair_proposals():
                self.schedule_refresh()
                return GLib.SOURCE_REMOVE
            if self._review_error is not None:
                self._review_error.set_visible(False)
            if self._pair_box is not None:
                changed = ", ".join(scope.value for scope in plan.changed_scopes) or "none (no-op)"
                self._pair_box.append(
                    Gtk.Label(
                        label=f"Changed scopes: {changed}. No IPC/reload is sent. "
                        "Watchers may reload "
                        "files automatically. Disk review is not runtime-loading proof.",
                        xalign=0,
                        wrap=True,
                    )
                )
                for review in plan.scopes:
                    group = Adw.PreferencesGroup(title=review.scope.value.title())
                    metadata = Gtk.Label(
                        label=f"Registered: {review.lexical_path}\nResolved: {review.resolved_path}"
                        f"\nSHA256: {review.previous_sha256} -> {review.proposed_sha256}"
                        f"\nContent ID: {review.previous_content_id} -> "
                        f"{review.proposed_content_id}",
                        xalign=0,
                        wrap=True,
                        selectable=True,
                    )
                    group.add(metadata)
                    diff = ConfigDiffWidget()
                    diff.set_precomputed_diff(
                        review.diff,
                        added_lines=review.added_lines,
                        removed_lines=review.removed_lines,
                        title=review.scope.value,
                        empty_message="Unchanged sibling. Exact current bytes are preserved.",
                    )
                    group.add(diff)
                    self._pair_box.append(group)
            self._pair_review = plan
            self._pair_proposals = proposals
            if self._save_button is not None:
                self._save_button.set_sensitive(True)
            return GLib.SOURCE_REMOVE

        def work():
            try:
                plan = editor_layout.run_prepare_review(pair, proposals, cancel_event=cancel)
            except Exception as exc:
                GLib.idle_add(complete, None, str(exc))
            else:
                GLib.idle_add(complete, plan, None)

        try:
            threading.Thread(target=work, daemon=False).start()
        except Exception as exc:
            complete(None, str(exc))

    # ── Change collection ──

    def collect_changes(self) -> list[PendingChange]:
        """Walk every change-tracking surface and produce a flat list.

        Options are window-level (schema-driven) so they're collected
        here directly; everything else delegates to the section page's
        ``iter_pending_changes()``.
        """
        out: list[PendingChange] = list(self._collect_option_changes())
        for page in self._window.section_pages:
            out.extend(page.iter_pending_changes())
        return out

    # -- Options --

    def _collect_option_changes(self) -> list[PendingChange]:
        result: list[PendingChange] = []
        win = self._window
        options_flat = win.options_flat
        for key, state in win.app_state.options.items():
            if not state.is_dirty:
                continue
            option = options_flat.get(key, {})
            label = option.get("label") or key
            kind, subtitle = self._describe_option_change(state)
            group_id = win.group_for_option(key)
            result.append(
                PendingChange(
                    category="Options",
                    title=label,
                    subtitle=f"{key} · {subtitle}",
                    kind=kind,
                    revert=lambda k=key: win.discard_option(k),
                    navigate_to=group_id,
                    icon=self._group_icon(group_id),
                    target_key=key,
                )
            )
        return result

    def _group_icon(self, group_id: str | None) -> str:
        """Resolve the sidebar icon for a schema group id."""
        if group_id is None:
            return FALLBACK_ICON
        return self._group_icons.get(group_id, FALLBACK_ICON)

    @staticmethod
    def _describe_option_change(state: OptionState) -> tuple[ChangeKind, str]:
        old, new = state.saved_value, state.live_value
        old_str = "" if old is None else value_to_conf(old)
        new_str = "" if new is None else value_to_conf(new)

        # Override added (was unmanaged, now a value is set)
        if not state.saved_managed and state.managed:
            return "added", f"set to {new_str or '—'}"
        # Override removed (was managed, no longer)
        if state.saved_managed and not state.managed:
            return "removed", "removing override"
        # Same managed flag, value changed
        if old_str != new_str:
            return "modified", f"{old_str or '—'} → {new_str or '—'}"
        return "modified", "value updated"
