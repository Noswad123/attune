"""Main application window with sidebar navigation."""

import os
from collections import Counter
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from hyprland_config import ParseError, Rule, coerce_config_value
from hyprland_socket import HyprlandError
from hyprland_state import ANIM_LOOKUP, HyprlandState

from hyprmod.core import config, persistence, schema, scoped_recovery
from hyprmod.core.focused_ui import PAGE_IDS, ReviewSnapshot, filter_schema
from hyprmod.core.state import AppState
from hyprmod.core.undo import OptionChange, PairedOptionChange, UndoManager
from hyprmod.pages.animations import AnimationsPage
from hyprmod.pages.backups import BackupsPage
from hyprmod.pages.binds import BindsPage
from hyprmod.pages.cursor import CursorPage
from hyprmod.pages.health import HealthPage
from hyprmod.pages.monitors import MonitorsPage
from hyprmod.pages.pending import PendingChangesPage
from hyprmod.pages.scope_recovery import ScopeRecoveryPage
from hyprmod.pages.section import SectionPage
from hyprmod.pages.settings import SettingsPage
from hyprmod.ui import (
    KeyboardLayoutsOptionRow,
    OptionRow,
    clear_children,
    confirm,
    create_option_row,
    make_page_layout,
)
from hyprmod.ui.about import build_about_dialog
from hyprmod.ui.banner import DirtyBanner
from hyprmod.ui.options import digits_for_step
from hyprmod.ui.pending_chip import PendingChipGroup
from hyprmod.ui.search import MIN_QUERY_LENGTH, SearchPage
from hyprmod.ui.shortcuts import build_shortcuts_window
from hyprmod.ui.sidebar import Sidebar

# Hyprland option keys
ANIMATIONS_ENABLED = "animations:enabled"


CSS_PATH = Path(__file__).parent / "style.css"


class HyprModWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title("Attune")
        self.set_default_size(900, 650)

        # Warm the managed-config cache so the first ``saved_sections`` access
        # below doesn't pay for a parse synchronously during widget construction.
        config.read_cached()
        # IPC-only state: never execute Lua or load the user's configuration tree.
        # Managed records are decoded separately by config.read_cached().
        self.hypr = HyprlandState(path=Path("/dev/null"))
        self._hyprland_available = self.hypr.online
        # Load the option catalog matching the running compositor version.
        # Falls back to the bundled catalog when Hyprland is offline or the
        # version cannot be resolved (see core.schema.load_schema).
        self._schema = filter_schema(schema.load_schema(version=self.hypr.version))
        self.app_state = AppState(self.hypr)
        self._option_rows: dict[str, OptionRow] = {}
        # Track the PreferencesGroup that owns each option row so we can hide
        # whole groups that turn out empty on the running Hyprland version
        # (e.g. all rows in a "Frame rate" group are options removed in 0.55).
        self._row_owner_group: dict[str, Adw.PreferencesGroup] = {}
        self._dependents: dict[str, list[str]] = {}  # parent_key -> [dependent_keys]
        self._options_flat: dict[str, dict] = schema.get_options_flat(self._schema)
        self._key_to_group: dict[str, str] = {}  # option key -> sidebar group_id
        self._undo = UndoManager()
        self._restore_in_progress = False
        self._restore_owner: str | None = None
        self._editor_invalidated = False

        # Optional page/widget references (populated during _build_ui)
        self._anim_details_box: Gtk.Box | None = None
        self._animations_page: AnimationsPage | None = None
        self._monitors_page: MonitorsPage | None = None
        # Dormant undo entry types still reference these optional pages.
        self._binds_page: BindsPage | None = None
        self._cursor_page: CursorPage | None = None
        self._settings_page: SettingsPage | None = None
        self._pending_page: PendingChangesPage | None = None
        self._health_page: HealthPage | None = None
        self._backups_page: BackupsPage | None = None
        self._scope_recovery_page: ScopeRecoveryPage | None = None
        self._pre_search_page_id: str | None = None
        self._search_results: list | None = None
        # Populated at the end of _build_ui() once section pages exist;
        # initialized empty so has_dirty() is safe during initial builds.
        self._section_pages: list[SectionPage] = []

        self._load_css()
        self._build_ui()
        self._register_state()
        self._refresh_all_modified_indicators()
        self.connect("close-request", self._on_close_request)
        if self._scope_recovery_page is not None:
            self._scope_recovery_page.ensure_loaded()

    def _on_close_request(self, *_args) -> bool:
        if self._restore_in_progress:
            self.show_toast("Wait for the restoration outcome before closing Attune.", 5)
            return True
        if self._monitors_page and self._monitors_page.is_confirm_pending():
            self.show_toast("Keep or revert the monitor preview before closing Attune.", 5)
            self.show_page("monitors")
            return True
        return False

    def editor_edit_allowed(self) -> bool:
        if self._restore_in_progress or self._editor_invalidated:
            self.show_toast("Editor locked. Restart Attune to load restored disk state.", 5)
            return False
        return True

    def restore_permission(self) -> None:
        if not self.editor_edit_allowed():
            raise ValueError("Editor is locked; restart Attune")
        if self.has_dirty():
            raise ValueError("Review or discard pending editor changes before restoration")
        if self._monitors_page and self._monitors_page.is_confirm_pending():
            raise ValueError("Keep or revert the monitor preview before restoration")

    def begin_restore(self) -> None:
        self.restore_permission()
        self._restore_in_progress = True
        self._restore_owner = "backups"
        self._set_editor_sensitive(False)

    def scope_restore_permission(self) -> None:
        # Invalidated baselines must not prevent subsequent explicit journal recovery.
        if self._restore_in_progress:
            raise ValueError("Another restoration or recovery owns this window")
        if self.has_dirty():
            raise ValueError("Pending editor changes are retained; restart or resolve them first")
        if self._monitors_page and self._monitors_page.is_confirm_pending():
            raise ValueError("Keep or revert the monitor preview before scope recovery")

    def begin_scope_restore(self) -> None:
        self.scope_restore_permission()
        self._restore_in_progress = True
        self._restore_owner = "scope"
        self._set_editor_sensitive(False)

    def finish_scope_restore(self, invalidate: bool) -> None:
        if self._restore_owner != "scope":
            return
        self._restore_owner = None
        self.finish_restore(invalidate)

    def scope_assessed(self, assessment: scoped_recovery.LayoutAssessment) -> None:
        if assessment.mode != "legacy-clear":
            self._lock_legacy_editor(
                "Scoped evidence discovered. Legacy editor locked; pending changes retained. "
                "Use Scope Recovery explicitly. No runtime loading or activation is established."
            )

    def _lock_legacy_editor(self, message: str) -> None:
        config.invalidate_cache()
        self._editor_invalidated = True
        self._set_editor_sensitive(False)
        self._hyprland_banner.set_title(message)
        self._hyprland_banner.set_revealed(True)

    def finish_restore(self, invalidate: bool) -> None:
        # Backups calls finish even after a refused begin; it cannot release a scoped writer.
        if self._restore_owner == "scope":
            return
        self._restore_owner = None
        if invalidate:
            config.invalidate_cache()
        self._editor_invalidated |= invalidate
        self._restore_in_progress = False
        self._set_editor_sensitive(not self._editor_invalidated)
        if self._editor_invalidated:
            self._hyprland_banner.set_title(
                "Disk output may have changed. Restart Attune to load restored disk state. "
                "The cached editor is disabled."
            )
            self._hyprland_banner.set_revealed(True)
            self.show_toast("Restart Attune to load restored disk state. Editor disabled.", 0)

    def _set_editor_sensitive(self, sensitive: bool) -> None:
        for name in self._page_titles:
            if name not in {"health", "backups", "scope-recovery", "settings"}:
                page = self._page_stack.get_child_by_name(name)
                if page is not None:
                    page.set_sensitive(sensitive)
        self._banner.set_sensitive(sensitive)
        for name in ("save", "undo", "redo"):
            action = self.lookup_action(name)
            if isinstance(action, Gio.SimpleAction):
                action.set_enabled(sensitive)

    @property
    def saved_sections(self) -> dict[str, list[str]]:
        """The keyword sections parsed from the managed config on disk.

        Delegates to :func:`config.read_cached` so pages and the save flow
        share one parse instead of re-reading per call. The cache is
        invalidated whenever hyprmod writes the managed file, so reads
        always reflect on-disk state without explicit refresh.
        """
        return config.read_cached()[1]

    @property
    def saved_values(self) -> dict[str, str]:
        """The option ``key = value`` assignments parsed from the managed config."""
        return config.read_cached()[0]

    @property
    def saved_rules(self) -> list[Rule]:
        """Structured window/layer rules parsed from the managed config."""
        return config.read_cached()[2]

    @property
    def option_rows(self) -> dict[str, OptionRow]:
        """Read-only view of option-key → row mapping for cross-page navigation."""
        return self._option_rows

    @property
    def section_pages(self) -> list[SectionPage]:
        """The section pages whose dirty/save/discard the window orchestrates."""
        return self._section_pages

    @property
    def options_flat(self) -> dict[str, dict]:
        """Flattened option catalog keyed by dotted option name."""
        return self._options_flat

    def group_for_option(self, key: str) -> str | None:
        """Return the sidebar group id that contains *key* (or ``None``)."""
        return self._key_to_group.get(key)

    @property
    def config_path(self) -> str:
        return str(config.managed_path())

    def _load_css(self):
        if CSS_PATH.exists():
            provider = Gtk.CssProvider()
            provider.load_from_path(str(CSS_PATH))
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
                )

    def _build_ui(self):
        self._toast_overlay = Adw.ToastOverlay()
        self._main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toast_overlay.set_child(self._main_box)
        self.set_content(self._toast_overlay)

        # About action (window-level, referenced by menu)
        about_action = Gio.SimpleAction.new("show-about", None)
        about_action.connect("activate", self._on_show_about)
        self.add_action(about_action)

        # Hyprland status banner
        self._hyprland_banner = Adw.Banner(
            title="Hyprland not detected. Changes can be reviewed and saved, "
            "but not previewed live."
        )
        self._hyprland_banner.set_revealed(not self._hyprland_available)
        self._main_box.append(self._hyprland_banner)

        # Navigation split view
        self._split_view = Adw.NavigationSplitView()
        self._split_view.set_vexpand(True)
        self._main_box.append(self._split_view)

        self._sidebar = Sidebar(
            on_page_selected=self._on_sidebar_selected,
            on_search_changed=self._on_search_changed,
            on_search_activate=self._on_search_activate,
            on_search_dismissed=self._on_search_dismissed,
        )
        self._split_view.set_sidebar(self._sidebar.nav_page)

        # Pending-changes chip lives in every page header (except the Pending
        # Changes page itself); the group keeps every chip's count in sync.
        self._pending_chips = PendingChipGroup(
            on_click=self._show_pending,
        )

        self._search_page_builder = SearchPage(self._schema)

        self._build_content_pane()
        groups, groups_by_id = self._build_pages()
        self._sidebar.populate(groups_by_id)
        self._build_search_page()

        # Stable after build; only these pages contribute section drafts.
        self._section_pages = [
            p
            for p in (
                self._animations_page,
                self._monitors_page,
            )
            if p is not None
        ]

        self._setup_shortcuts()
        self._setup_help_overlay()

        if groups:
            first_id = groups[0]["id"]
            self.show_page(first_id)
            self._sidebar.select_first()

    def _build_content_pane(self):
        """Build the content pane with page stack and banner."""
        self._content_nav = Adw.NavigationPage(title="")

        self._page_stack = Gtk.Stack()
        self._page_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._page_stack.set_transition_duration(150)
        self._page_stack.set_vexpand(True)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content_box.append(self._page_stack)

        self._banner = DirtyBanner(
            on_save=self._on_save,
            on_discard=self._on_discard,
        )
        content_box.append(self._banner)

        self._content_nav.set_child(content_box)
        self._split_view.set_content(self._content_nav)

    def _build_pages(self) -> tuple[list[dict], dict[str, dict]]:
        """Build focused schema pages and supported utilities."""
        self._page_titles: dict[str, str] = {}
        groups = schema.get_groups(self._schema)
        groups_by_id: dict[str, dict] = {}

        for group in groups:
            target_group = group.get("parent_page", group["id"])
            for section in group.get("sections", []):
                for option in section.get("options", []):
                    self._key_to_group[option["key"]] = target_group

            if group.get("hidden"):
                continue
            groups_by_id[group["id"]] = group

            page = self._build_page(group)
            self._page_stack.add_named(page, group["id"])
            self._page_titles[group["id"]] = group["label"]

        # Section pages share dirty notifications and the undo stack.
        section_page_specs: list[tuple[type, str, str, str]] = [
            (MonitorsPage, "_monitors_page", "monitors", "Monitors"),
        ]
        for cls, attr, slug, title in section_page_specs:
            page = cls(
                self,
                on_dirty_changed=self._on_section_dirty,
                push_undo=self._undo.push,
            )
            setattr(self, attr, page)
            self._page_stack.add_named(page.build(header=self._make_page_header(title)), slug)
            self._page_titles[slug] = title
            if cls is MonitorsPage:
                self._search_page_builder.add_entries(page.get_search_entries())

        # Standalone pages have no separate dirty/undo state.
        self._health_page = HealthPage(config.managed_path())
        self._page_stack.add_named(
            self._health_page.build(header=self._make_page_header("Health")), "health"
        )
        self._page_titles["health"] = "Health"
        self._health_page.bind_lifecycle(self)
        self._backups_page = BackupsPage(
            config.managed_path(),
            restore_permission=self.restore_permission,
            begin_restore=self.begin_restore,
            finish_restore=self.finish_restore,
        )
        self._page_stack.add_named(
            self._backups_page.build(header=self._make_page_header("Backups")), "backups"
        )
        self._page_titles["backups"] = "Backups"
        self._backups_page.bind_lifecycle(self)
        self._scope_recovery_page = ScopeRecoveryPage(
            Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")),
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")),
            restore_permission=self.scope_restore_permission,
            begin_restore=self.begin_scope_restore,
            finish_restore=self.finish_scope_restore,
        )
        self._scope_recovery_page.on_assessment = self.scope_assessed
        self._scope_recovery_page.on_assessment_error = lambda error: self._lock_legacy_editor(
            f"Layout assessment failed: {error}. Legacy editor locked; pending changes retained. "
            "Inspect Scope Recovery and restart Attune after resolving the layout."
        )
        self._page_stack.add_named(
            self._scope_recovery_page.build(header=self._make_page_header("Scope Recovery")),
            "scope-recovery",
        )
        self._page_titles["scope-recovery"] = "Scope Recovery"
        self._scope_recovery_page.bind_lifecycle(self)
        standalone_page_specs: list[tuple[type, str, str, str]] = [
            (PendingChangesPage, "_pending_page", "pending", "Pending Changes"),
            (SettingsPage, "_settings_page", "settings", "Settings"),
        ]
        for cls, attr, slug, title in standalone_page_specs:
            page = cls(self)
            setattr(self, attr, page)
            # The Pending Changes page header omits the pending chip — it
            # would just be a no-op shortcut to the page the user is on.
            with_chip = cls is not PendingChangesPage
            header = self._make_page_header(title, with_pending_chip=with_chip)
            self._page_stack.add_named(page.build(header=header), slug)
            self._page_titles[slug] = title

        return groups, groups_by_id

    def _build_search_page(self):
        """Build the search results page in the content stack."""
        toolbar, _, self._search_content_box, _ = make_page_layout(
            header=self._make_page_header("Search Results")
        )
        self._page_stack.add_named(toolbar, "search")
        self._page_titles["search"] = "Search Results"

    def _make_page_header(self, title: str, *, with_pending_chip: bool = True) -> Adw.HeaderBar:
        """Create a content page header with menu button.

        When *with_pending_chip* is true (the default), a fresh
        :class:`PendingChip` from ``self._pending_chips`` is added before
        the menu button. The Pending Changes page itself opts out — the
        chip would just navigate back to the same page.
        """
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=title))

        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("menu-symbolic")

        menu = Gio.Menu()
        help_section = Gio.Menu()
        help_section.append("Keyboard Shortcuts", "win.show-help-overlay")
        help_section.append("About Attune", "win.show-about")
        menu.append_section(None, help_section)

        menu_button.set_menu_model(menu)
        header.pack_end(menu_button)

        if with_pending_chip:
            # ``pack_end`` stacks right-to-left, so the chip appears to the
            # left of the menu button — like a status indicator next to the
            # primary action.
            header.pack_end(self._pending_chips.new_chip())

        return header

    def _build_page(self, group: dict) -> Adw.ToolbarView:
        toolbar_view, _, content_box, _ = make_page_layout(
            header=self._make_page_header(group["label"])
        )

        is_animations = group.get("id") == "animations"

        if is_animations:
            self._animations_page = AnimationsPage(
                self,
                on_dirty_changed=self._on_section_dirty,
                push_undo=self._undo.push,
                saved_sections=self.saved_sections,
            )
            content_box.append(self._animations_page.build_curve_editor_widget())

        for pref_group in self._build_section_widgets(group):
            content_box.append(pref_group)

        if is_animations and self._animations_page is not None:
            self._anim_details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
            self._anim_details_box.append(self._animations_page.build_widget())
            content_box.append(self._anim_details_box)

        return toolbar_view

    def _build_section_widgets(self, group: dict) -> list[Adw.PreferencesGroup]:
        """Build PreferencesGroup widgets for a schema group's sections.

        Registers option rows in the window's state and row tracking.
        """
        result = []
        for section in group.get("sections", []):
            pref_group = Adw.PreferencesGroup(title=section.get("label", ""))
            if section.get("description"):
                pref_group.set_description(section["description"])

            for option in section.get("options", []):
                # Companion keys are driven by another row (e.g. kb_variant by
                # the keyboard-layouts row); they stay tracked but render no row.
                if option.get("managed_by"):
                    continue
                value = option.get("default")
                opt_row = create_option_row(
                    option,
                    value,
                    on_change=self._on_option_changed,
                    on_reset=self._on_option_reset,
                    on_discard=self.discard_option,
                )
                if opt_row:
                    self._option_rows[option["key"]] = opt_row
                    self._row_owner_group[option["key"]] = pref_group
                    pref_group.add(opt_row.row)
                    parent = option.get("depends_on")
                    if parent:
                        self._dependents.setdefault(parent, []).append(option["key"])
                    companion = option.get("companion_key")
                    if companion and isinstance(opt_row, KeyboardLayoutsOptionRow):
                        # The row owns a second key for value/state sync; bind
                        # state so it can read both keys' live + managed values,
                        # and apply both as one atomic undo step.
                        self._option_rows[companion] = opt_row
                        opt_row.bind_state(self.app_state, self._on_paired_option_changed)

            result.append(pref_group)
        return result

    def build_schema_group_widgets(
        self, group_id_or_dict: str | dict
    ) -> list[Adw.PreferencesGroup]:
        """Build PreferencesGroup widgets for a schema group by ID or dictionary."""
        if isinstance(group_id_or_dict, str):
            groups = schema.get_groups(self._schema)
            group = next((g for g in groups if g["id"] == group_id_or_dict), None)
        else:
            group = group_id_or_dict

        if not group:
            return []
        pref_groups = self._build_section_widgets(group)
        # _register_state only runs once at startup; rebuilds (e.g. monitor
        # refresh) need to re-push live values and the managed indicator.
        self._sync_group_widgets_to_state(group, pref_groups)
        return pref_groups

    def _sync_group_widgets_to_state(
        self, group: dict, pref_groups: list[Adw.PreferencesGroup]
    ) -> None:
        groups_with_visible: set[Adw.PreferencesGroup] = set()
        any_state = False
        for section in group.get("sections", []):
            for option in section.get("options", []):
                key = option["key"]
                opt_row = self._option_rows.get(key)
                state = self.app_state.get(key)
                if opt_row is None or state is None:
                    continue
                any_state = True
                if not state.available:
                    opt_row.row.set_visible(False)
                    continue
                owner = self._row_owner_group.get(key)
                if owner is not None:
                    groups_with_visible.add(owner)
                if state.live_value is not None:
                    opt_row.set_value_silent(state.live_value)
                opt_row.update_modified_state(state.managed, state.is_dirty, state.saved_managed)
        if not any_state:
            return
        for pref_group in pref_groups:
            if pref_group not in groups_with_visible:
                pref_group.set_visible(False)

    def _register_state(self):
        options_flat = self._options_flat
        saved_values = self.saved_values
        for key, option in options_flat.items():
            saved = saved_values.get(key)
            if saved is not None:
                saved = coerce_config_value(saved, option.get("type", ""))
            # Compute display digits for float options so AppState can
            # normalize values to widget precision on ingress.
            digits = None
            if option.get("type") == "float":
                digits = digits_for_step(option.get("step", 0.01))
            self.app_state.register(key, option.get("default"), saved, digits=digits)

        # Hide rows for options the running Hyprland doesn't recognise —
        # both removed-in-this-version options and not-yet-introduced ones.
        # We used to grey them out with a "not available" tooltip, but a
        # disabled row is noisier than just dropping it: cross-version
        # support is built from version-paired entries in ``options.json``
        # (e.g. ``misc:vfr`` and ``debug:vfr`` both labelled "Variable
        # frame rate") and only the right one for this Hyprland should
        # render.
        groups_with_visible: set[Adw.PreferencesGroup] = set()
        for key, opt_row in self._option_rows.items():
            state = self.app_state.get(key)
            owner = self._row_owner_group.get(key)
            if state and not state.available:
                opt_row.row.set_visible(False)
            elif owner is not None:
                groups_with_visible.add(owner)
        # A group whose every row was hidden becomes a stray title with no
        # content. Hide the whole group so the page doesn't show an empty
        # "Frame rate" / "Glow" / ... section header.
        for group in set(self._row_owner_group.values()):
            if group not in groups_with_visible:
                group.set_visible(False)

        # Push AppState's authoritative values to widgets (AppState normalizes
        # floats and hex strings, so the widget must show the same value).
        for key, opt_row in self._option_rows.items():
            state = self.app_state.get(key)
            if state and state.live_value is not None:
                opt_row.set_value_silent(state.live_value)

        self.app_state.on_change(self._on_state_changed)

        # Set initial visibility of animation details based on animations:enabled
        if self._anim_details_box is not None:
            state = self.app_state.get(ANIMATIONS_ENABLED)
            self._anim_details_box.set_visible(bool(state and state.live_value))

    def _notify_ui_change(self):
        """Update banner and sidebar badges after an option change."""
        self._update_banner()
        self._update_sidebar_badges()

    def _schedule_pending_refresh(self):
        """Coalesce a Pending Changes page rebuild if the page exists."""
        if self._pending_page is not None:
            self._pending_page.schedule_refresh()

    def _refresh_all_modified_indicators(self):
        for key, opt_row in self._option_rows.items():
            state = self.app_state.get(key)
            if state:
                opt_row.update_modified_state(state.managed, state.is_dirty, state.saved_managed)
        self._refresh_all_dependents()
        self._update_sidebar_badges()

    def _update_sidebar_badges(self):
        """Update pending-change count badges on sidebar rows."""
        # Count dirty options per schema group
        counts: Counter[str] = Counter()
        for key, state in self.app_state.options.items():
            if state.is_dirty:
                group_id = self._key_to_group.get(key)
                if group_id:
                    counts[group_id] += 1

        # Special pages: count dirty items
        if self._animations_page and self._animations_page.is_dirty():
            n = sum(1 for name in ANIM_LOOKUP if self._animations_page.is_anim_dirty(name))
            n += len(self._animations_page.changed_curve_names)
            counts["animations"] += n
        if self._monitors_page and self._monitors_page.is_dirty():
            counts["monitors"] += self._monitors_page.dirty_count()

        # The pending-changes chip totals everything else
        counts["pending"] = sum(counts.values())

        self._sidebar.update_badges(counts)
        self._pending_chips.set_count(counts["pending"])

    def _refresh_all_dependents(self):
        """Show/hide dependent options based on their parent's current value."""
        for parent_key in self._dependents:
            self._update_dependents(parent_key)

    def _is_option_visible(self, key: str) -> bool:
        """Check if an option should be visible (parent enabled and visible)."""
        # Walk up the depends_on chain
        option = self._options_flat.get(key)
        if not option:
            return True
        parent_key = option.get("depends_on")
        if not parent_key:
            return True
        # Parent must be visible itself and have a truthy value
        if not self._is_option_visible(parent_key):
            return False
        parent_state = self.app_state.get(parent_key)
        return bool(parent_state.live_value) if parent_state else True

    def _update_dependents(self, parent_key: str):
        """Update visibility and source values of options that depend on parent_key."""
        parent_state = self.app_state.get(parent_key)
        parent_value = parent_state.live_value if parent_state else None

        for dep_key in self._dependents.get(parent_key, []):
            opt_row = self._option_rows.get(dep_key)
            if opt_row:
                visible = self._is_option_visible(dep_key)
                opt_row.row.set_visible(visible)
                # Refresh dynamic source if the dependent has one
                if parent_value is not None:
                    source_args = opt_row.option.get("source_args", {})
                    # Find which source_arg maps to this parent key
                    refresh_kwargs = {}
                    for arg_name, _default in source_args.items():
                        if opt_row.option.get("depends_on") == parent_key:
                            refresh_kwargs[arg_name] = str(parent_value)
                    if refresh_kwargs:
                        opt_row.refresh_source(**refresh_kwargs)
                        dep_state = self.app_state.get(dep_key)
                        if dep_state and dep_state.live_value is not None:
                            opt_row.set_value_silent(dep_state.live_value)
                # Recurse: if this dependent also has dependents, update them too
                if dep_key in self._dependents:
                    self._update_dependents(dep_key)

    # -- Keyboard shortcuts --

    def _setup_shortcuts(self):
        """Register keyboard shortcuts as window actions with accels.

        Using Gio actions + set_accels_for_action ensures shortcuts are handled
        at the application level, before GTK's built-in widget shortcuts
        (e.g. Ctrl+Z undo in text entries) can intercept them.
        """
        app = self.get_application()
        if app is None:
            return

        shortcuts = [
            ("save", self._on_save, ["<Control>s"]),
            ("undo", self._on_undo, ["<Control>z"]),
            ("redo", self._on_redo, ["<Control><Shift>z"]),
            ("search", self._on_show_search, ["<Control>f"]),
            ("clear-search", self._on_hide_search, ["Escape"]),
        ]

        for name, handler, accels in shortcuts:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _a, _p, fn=handler: fn())
            self.add_action(action)
            app.set_accels_for_action(f"win.{name}", accels)

    def _setup_help_overlay(self):
        """Attach a ``Gtk.ShortcutsWindow`` and bind ``win.show-help-overlay``.

        ``set_help_overlay`` registers the action automatically; we only need
        to add the accelerators. ``<Control>question`` is the GNOME-standard
        shortcut; ``F1`` is included as a familiar fallback.
        """
        shortcuts_window = build_shortcuts_window()
        self.set_help_overlay(shortcuts_window)

        app = self.get_application()
        if app is not None:
            app.set_accels_for_action("win.show-help-overlay", ["<Control>question", "F1"])

    def _on_show_about(self, *_args):
        """Show the About dialog."""
        build_about_dialog(running_hyprland_version=self.hypr.version).present(self)

    # -- Search --

    def _on_show_search(self, *_args):
        """Focus the always-visible search entry (Ctrl+F)."""
        self._sidebar.focus_search()

    def _on_hide_search(self, *_args):
        """Clear search and restore the previously visible page (Escape)."""
        self._sidebar.clear_search()

    def _on_search_dismissed(self):
        """Restore the previous page when search is cleared.

        Invoked synchronously by ``Sidebar.clear_search()`` so the page
        switch doesn't wait for the 150 ms ``search-changed`` debounce.
        """
        if self._pre_search_page_id:
            self.show_page(self._pre_search_page_id)
            self._pre_search_page_id = None

    def _on_search_changed(self, entry):
        query = entry.get_text().strip()
        if not query or len(query) < MIN_QUERY_LENGTH:
            if self._pre_search_page_id:
                self.show_page(self._pre_search_page_id)
            return

        # Save current page before showing search
        if not self._pre_search_page_id:
            self._pre_search_page_id = self._sidebar.get_selected_group_id()

        self._search_results = self._search_page_builder.search(query)
        widget = self._search_page_builder.build_results_widget(
            self._search_results,
            on_activate=self._on_search_result_activate,
        )
        clear_children(self._search_content_box)
        self._search_content_box.append(widget)
        self.show_page("search")
        self._sidebar.deselect_all()

    def _on_search_activate(self, _entry):
        """Enter pressed — focus the first search result row for keyboard navigation."""
        if not self._search_results:
            return
        widget = self._search_content_box.get_first_child()
        if widget:
            widget.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def _on_search_result_activate(self, group_id: str, option_key: str):
        """Navigate to a supported result from the filtered search index."""
        # Clear the entry text and bypass the page-restore in
        # ``_on_search_dismissed`` — the navigate() call below sends the
        # user where they actually want to go.
        self._pre_search_page_id = None
        self._sidebar.clear_search()
        self.navigate(group_id, option_key=option_key)

        opt_row = self._option_rows.get(option_key)
        if opt_row:

            def _scroll_and_highlight():
                opt_row.row.grab_focus()
                opt_row.flash_highlight()
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_scroll_and_highlight)

    # -- Sidebar --

    def show_page(self, gid: str):
        """Switch the content pane to the given page."""
        if gid in PAGE_IDS and gid in self._page_titles:
            if (
                self._monitors_page
                and gid != "monitors"
                and self._monitors_page.is_confirm_pending()
            ):
                self.show_toast("Keep or revert the monitor preview before leaving this page.", 5)
                self._sidebar.select_row("monitors")
                return
            if gid == "pending" and self._pending_page is not None:
                # Catch up on any changes that happened while the page wasn't visible
                self._pending_page.refresh()
            if gid == "health" and self._health_page is not None:
                self._health_page.ensure_loaded()
            if gid == "backups" and self._backups_page is not None:
                self._backups_page.ensure_loaded()
            if gid == "scope-recovery" and self._scope_recovery_page is not None:
                self._scope_recovery_page.ensure_loaded()
            self._page_stack.set_visible_child_name(gid)
            self._content_nav.set_title(self._page_titles[gid])

    def _show_pending(self):
        self.show_page("pending")
        if self._page_stack.get_visible_child_name() == "pending":
            self._sidebar.select_row("pending")

    def navigate(self, group_id: str, *, option_key: str | None = None) -> None:
        """Navigate from search or pending changes, preserving their shared API."""
        self.show_page(group_id)
        if self._page_stack.get_visible_child_name() == group_id:
            self._sidebar.select_row(group_id)

    def _on_sidebar_selected(self, group_id: str):
        self.show_page(group_id)

    # -- Option changes --

    def _on_option_changed(self, key: str, value):
        if not self.editor_edit_allowed():
            return
        # Skip no-op changes (e.g. SpinButton rounding triggers on focus-out)
        state = self.app_state.get(key)
        if state and value == state.live_value:
            return

        # Clear dependent before applying the parent change to avoid invalid configs
        for dep_key in self._dependents.get(key, []):
            dep_option = self._options_flat.get(dep_key)
            if dep_option and dep_option.get("source") and not dep_option.get("multi"):
                self.app_state.set_live(dep_key, dep_option.get("default", ""))

        opt_row = self._option_rows.get(key)
        try:
            entry = self.app_state.set_live(key, value)
        except HyprlandError as e:
            if opt_row:
                opt_row.flash_error()
                if state:
                    opt_row.set_value_silent(state.live_value)
            self.show_bug_toast(f"Failed to set {key} — {e}", detail=str(e), timeout=5)
            return
        if entry is None and opt_row:
            opt_row.flash_error()
            if state:
                opt_row.set_value_silent(state.live_value)
        elif entry is not None:
            self._undo.push(entry)

    def _on_paired_option_changed(self, changes: list[tuple[str, object]]):
        """Apply several keys as one atomic undo step (keyboard layouts own two).

        Used where a single user action writes more than one config key, so
        undo/redo moves them together instead of one key per step.
        """
        if not self.editor_edit_allowed():
            return
        entries = []
        for key, value in changes:
            state = self.app_state.get(key)
            if state and value == state.live_value:
                continue
            opt_row = self._option_rows.get(key)
            try:
                entry = self.app_state.set_live(key, value)
            except HyprlandError as e:
                if opt_row:
                    opt_row.flash_error()
                self.show_bug_toast(f"Failed to set {key} — {e}", detail=str(e), timeout=5)
                continue
            if entry is not None:
                entries.append(entry)
        if entries:
            self._undo.push(PairedOptionChange(entries))

    def _sync_option_row(self, key: str, *, flash: bool = False):
        """Push current AppState to the widget and update dependents."""
        opt_row = self._option_rows.get(key)
        state = self.app_state.get(key)
        if opt_row and state:
            if state.live_value is not None:
                opt_row.set_value_silent(state.live_value)
            opt_row.update_modified_state(state.managed, state.is_dirty, state.saved_managed)
            if flash:
                opt_row.flash_highlight(duration_ms=600)
        if key in self._dependents:
            self._update_dependents(key)

    def _on_option_reset(self, key: str, _default_value):
        """Remove override — preview the fallback value and mark pending."""
        if not self.editor_edit_allowed():
            return
        if key not in self._option_rows:
            return

        # Do not parse or execute the user's entrypoint to discover a fallback.
        fallback = self._options_flat[key].get("default")
        self.app_state.reset_to_value(key, fallback)
        self._sync_option_row(key, flash=True)
        self._notify_ui_change()
        self.show_toast(
            "Override removed. Preview uses the default; your own config may differ.", 5
        )

    def discard_option(self, key: str):
        """Discard changes on a single option — revert to saved state."""
        if not self.editor_edit_allowed():
            return
        state = self.app_state.get(key)
        if state and state.is_dirty:
            self._undo.push(
                OptionChange(
                    key=key,
                    old_value=state.live_value,
                    new_value=state.saved_value,
                    old_managed=state.managed,
                    new_managed=state.saved_managed,
                ),
                merge=False,
            )
        if not self.app_state.discard_one(key):
            return
        self._sync_option_row(key, flash=True)
        self._notify_ui_change()

    def has_dirty(self) -> bool:
        """Check if any section has unsaved changes."""
        if self.app_state.has_dirty():
            return True
        return any(s.is_dirty() for s in self._section_pages)

    def _update_banner(self):
        """Show or hide the unsaved changes banner."""
        has_dirty = self.has_dirty()
        if has_dirty:
            self._banner.show_dirty()
        else:
            self._banner.hide()

    def _on_state_changed(self, key: str):
        self._update_banner()
        self._update_sidebar_badges()
        self._sync_option_row(key)
        self._schedule_pending_refresh()

        if key == ANIMATIONS_ENABLED and self._anim_details_box is not None:
            state = self.app_state.get(key)
            self._anim_details_box.set_visible(bool(state and state.live_value))

    def _on_section_dirty(self):
        """Called when animations or monitors change."""
        self._update_banner()
        self._update_sidebar_badges()
        self._schedule_pending_refresh()

    # -- Undo / Redo --

    def _on_undo(self, *_args):
        self._apply_undo_redo(undo=True)

    def _on_redo(self, *_args):
        self._apply_undo_redo(undo=False)

    def _apply_undo_redo(self, undo: bool):
        if not self.editor_edit_allowed():
            return
        entry = self._undo.pop_undo() if undo else self._undo.pop_redo()
        if entry is None:
            return
        if entry.apply(self, undo=undo):
            (self._undo.confirm_undo if undo else self._undo.confirm_redo)(entry)

    # -- Save with animation --

    def collect_save_sections(self) -> config.ConfigSections:
        """Collect only supported sections already managed or edited this session."""
        saved_sections = self.saved_sections
        sections = config.ConfigSections()

        monitors = self._monitors_page
        existing_monitors = config.collect_section(saved_sections, config.KEYWORD_MONITOR)
        if monitors is not None and monitors.is_dirty():
            sections.monitors = monitors.get_monitor_lines()
        elif existing_monitors:
            sections.monitors = existing_monitors

        # Animations: bezier extraction is bespoke (curves used by emitted
        # animations need their definitions emitted alongside), so this one
        # stays inline.
        if self._animations_page is not None:
            anim_dirty = self._animations_page.is_dirty()
            existing_anims = config.collect_section(saved_sections, config.KEYWORD_ANIMATION)
            if anim_dirty:
                sections.animations, used_curves = self._animations_page.get_animation_lines()
                sections.beziers = self._animations_page.get_curve_definitions(used_curves) or None
            else:
                sections.animations = existing_anims or None
                sections.beziers = (
                    config.collect_section(saved_sections, config.KEYWORD_BEZIER) or None
                )

        return sections

    def review_snapshot(self) -> ReviewSnapshot:
        path = config.managed_path()
        resolved_path = persistence.resolve_target(path)
        try:
            saved_text = resolved_path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            saved_text = ""
        proposed_text = persistence.build_text(
            self.app_state.get_all_live_values(),
            self.collect_save_sections(),
        )
        if persistence.resolve_target(path) != resolved_path:
            raise ValueError("Destination changed during review; review again")
        return ReviewSnapshot(path, saved_text, proposed_text, resolved_path)

    def save_reviewed(self, reviewed: ReviewSnapshot) -> None:
        """Persist only the exact draft and destination displayed for review."""
        if not self.editor_edit_allowed():
            return
        if self._page_stack.get_visible_child_name() != "pending":
            self._show_pending()
            return
        if self._monitors_page and self._monitors_page.is_confirm_pending():
            self.show_toast("Keep or revert the monitor preview before saving.", timeout=5)
            return
        try:
            current = self.review_snapshot()
            if current != reviewed:
                self._show_pending()
                self.show_toast("Changes or the output file changed. Review the updated diff.", 5)
                return
            if current.saved_text == current.proposed_text:
                return
            backup = persistence.persist_reviewed(
                reviewed, self.app_state.get_all_live_values(), self.collect_save_sections()
            )
            self._perform_save()
        except persistence.PersistenceFailure as exc:
            if exc.may_have_written:
                config.invalidate_cache()
                self.finish_restore(True)
                self.show_toast(
                    f"Saving failed: {exc}. Output may have changed; inspect and restart Attune.",
                    timeout=0,
                    copy=True,
                )
            else:
                self.show_toast(f"Could not save reviewed changes: {exc}", timeout=5, copy=True)
            return
        except (OSError, ValueError, ParseError) as exc:
            self.show_toast(f"Could not save reviewed changes: {exc}", timeout=5, copy=True)
            return
        self._banner.show_saved()
        if backup is not None:
            self.show_toast(f"Saved. Backup: {config.display_path(backup)}", timeout=5, copy=True)

    def _perform_save(self):
        """Commit UI baselines only after persist_reviewed succeeds."""
        config.invalidate_cache()
        self.app_state.mark_saved()

        self.hypr.clear_pending()
        for section in self._section_pages:
            section.mark_saved()
        self._undo.clear()
        self._refresh_all_modified_indicators()
        self._schedule_pending_refresh()
        self._update_banner()

    def save(self):
        """Open review. Persisting requires the separate reviewed-save action."""
        if not self.editor_edit_allowed():
            return
        self._show_pending()

    def add_toast(self, toast: Adw.Toast):
        """Add a pre-built toast to the overlay."""
        self._toast_overlay.add_toast(toast)

    def show_toast(self, message: str, timeout: int = 2, *, copy: bool = False):
        """Show a transient toast. With *copy*, add a Copy button for *message*."""
        toast = Adw.Toast(title=message, timeout=timeout, use_markup=False)
        if copy:
            toast.set_button_label("Copy")
            toast.connect("button-clicked", lambda _t: self.get_clipboard().set(message))
        self.add_toast(toast)

    def show_bug_toast(self, message: str, *, detail: str | None = None, timeout: int = 5) -> None:
        """Keep page error callbacks local rather than reporting to upstream."""
        self.show_toast(message, timeout=timeout, copy=True)

    def _on_save(self, *_args):
        self.save()

    # -- Discard --

    def _on_discard(self, *_args):
        if not self.editor_edit_allowed():
            return
        n = len(self.app_state.get_dirty_values())
        for page in self._section_pages:
            if page.is_dirty():
                n += 1

        confirm(
            self,
            "Discard All Changes?",
            f"{n} unsaved change{'s' if n != 1 else ''} will be reverted.",
            "Discard",
            self._do_discard,
        )

    def _do_discard(self):
        if not self.editor_edit_allowed():
            return
        # Restore captured runtime baselines, not defaults from the managed-only document.
        reverted = [key for key, state in self.app_state.options.items() if state.is_dirty]
        for key in reverted:
            self.app_state.discard_one(key)
        self.hypr.clear_pending()
        for key in reverted:
            opt_row = self._option_rows.get(key)
            state = self.app_state.get(key)
            if opt_row and state and state.live_value is not None:
                opt_row.set_value_silent(state.live_value)
        for section in self._section_pages:
            section.discard()
        self._banner.hide()
        self._undo.clear()
        self._refresh_all_modified_indicators()
        self._schedule_pending_refresh()
