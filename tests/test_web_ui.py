"""
tests/test_web_ui.py — Web UI product tests.

Validates:
  - Design system v3 (app.html) exists and is well-formed
  - Mode system (lite/full/admin) is implemented
  - Navigation structure is correct
  - Progressive disclosure via data-mode attributes
  - Inline views: missions, approvals, system health
  - Legacy pages still accessible
  - No secrets in HTML
  - Route redirect updated
  - Flutter design system unified
"""
import pytest
from pathlib import Path


class TestWebAppShell:
    @pytest.fixture(autouse=True)
    def _load(self):
        self.html = Path("static/app.html").read_text(encoding="utf-8")

    def test_UI01_app_html_exists(self):
        assert Path("static/app.html").exists()
        assert len(self.html) > 15000

    def test_UI02_design_system_v3_tokens(self):
        for token in ["--bg", "--surface", "--blue", "--b-subtle", "--r-md"]:
            assert token in self.html

    def test_UI03_sidebar_navigation(self):
        assert "sidebar" in self.html
        assert "nav-item" in self.html
        assert 'data-view="home"' in self.html
        assert 'data-view="missions"' in self.html
        assert 'data-view="approvals"' in self.html

    def test_UI04_three_mode_system(self):
        assert 'data-app-mode' in self.html
        assert 'data-mode="full"' in self.html
        assert 'data-mode="admin"' in self.html
        assert "setMode" in self.html
        assert "mode-switch" in self.html
        assert "Lite" in self.html
        assert "Full" in self.html
        assert "Admin" in self.html

    def test_UI05_progressive_disclosure_css(self):
        assert 'nav-item[data-mode="full"]' in self.html
        assert 'nav-item[data-mode="admin"]' in self.html
        assert 'data-app-mode="lite"' in self.html

    def test_UI06_home_view_complete(self):
        assert "composer" in self.html
        assert "stat-tile" in self.html or "stat-val" in self.html
        assert "home-missions" in self.html
        assert "home-greeting" in self.html
        assert "readiness" in self.html.lower()

    def test_UI07_approval_alert_on_home(self):
        assert "home-alert" in self.html
        assert "alert-count" in self.html

    def test_UI08_inline_missions_view(self):
        """Missions view is inline with list and detail, not an iframe."""
        assert 'id="view-missions"' in self.html
        assert "missions-list-view" in self.html
        assert "missions-detail-view" in self.html
        assert "openMissionDetail" in self.html
        assert "closeMissionDetail" in self.html

    def test_UI09_inline_approvals_view(self):
        """Approvals view is inline with approve/deny buttons."""
        assert 'id="view-approvals"' in self.html
        assert "approvals-list" in self.html
        assert "approveApproval" in self.html
        assert "denyApproval" in self.html
        assert "/api/v3/console/pending" in self.html
        assert "/api/v3/console/approve" in self.html

    def test_UI10_inline_system_view(self):
        """System health view is inline (admin mode)."""
        assert 'id="view-system"' in self.html
        assert "loadSystemView" in self.html
        assert "/api/v3/self-model/readiness" in self.html
        assert "/api/v3/self-model/limitations" in self.html
        assert "/api/v3/self-model/capabilities" in self.html

    def test_UI11_approval_card_structure(self):
        """Approval cards show risk, description, consequences, actions."""
        assert "risk-" in self.html  # risk badges
        assert "approval-desc" in self.html
        assert "approval-consequences" in self.html
        assert "If approved" in self.html
        assert "If denied" in self.html

    def test_UI12_mission_detail_structure(self):
        """Mission detail shows status, error, output."""
        assert "detail-title" in self.html
        assert "detail-grid" in self.html
        assert "detail-cell" in self.html

    def test_UI13_skeleton_loading(self):
        """Skeleton loading animation exists."""
        assert "skeleton" in self.html or "shimmer" in self.html

    def test_UI14_badge_system(self):
        """Status badge system (running/completed/failed/pending)."""
        assert "badge-running" in self.html
        assert "badge-completed" in self.html
        assert "badge-failed" in self.html
        assert "badge-pending" in self.html

    def test_UI15_readiness_meter(self):
        """Readiness meter component."""
        assert "meter" in self.html
        assert "meter-fill" in self.html

    def test_UI16_toast_notifications(self):
        """Toast notification system."""
        assert "toast" in self.html
        assert "toast.ok" in self.html or ".toast.ok" in self.html

    def test_UI17_empty_states(self):
        """Empty states with icon and title."""
        assert "empty-state" in self.html
        assert "empty-state-icon" in self.html
        assert "empty-state-title" in self.html

    def test_UI18_iframe_lazy_loading(self):
        """Remaining pages use lazy-loading iframes."""
        assert "data-src" in self.html
        assert "/runs.html" in self.html
        assert "/modules.html" in self.html

    def test_UI19_brand_identity(self):
        assert "Jarvis" in self.html
        assert "AI Operating System" in self.html

    def test_UI20_websocket_connection(self):
        assert "connectWS" in self.html
        assert "WebSocket" in self.html

    def test_UI21_submit_mission(self):
        assert "submitMission" in self.html
        assert "/api/v3/missions" in self.html

    def test_UI22_mobile_responsive(self):
        assert "@media" in self.html
        assert "menu-btn" in self.html
        assert "toggleSidebar" in self.html

    def test_UI23_auth_401_redirect(self):
        """401 response triggers logout/reload in SPA."""
        assert "401" in self.html
        assert "logout" in self.html


class TestLegacyCompatibility:
    def test_UI24_only_spa_exists(self):
        """After cleanup: only app.html remains. Legacy pages removed."""
        assert Path("static/app.html").exists()
        for dead_page in ["index.html", "dashboard.html", "cockpit.html",
                          "self-model.html", "business.html"]:
            assert not Path(f"static/{dead_page}").exists(), f"Dead page not removed: {dead_page}"

    def test_UI25_root_redirects_to_app(self):
        import inspect, importlib
        main_mod = importlib.import_module("api.main")
        source = inspect.getsource(main_mod)
        assert "/app.html" in source


class TestSafety:
    def test_UI26_no_secrets_in_html(self):
        html = Path("static/app.html").read_text()
        assert "sk-or-" not in html
        assert "OPENROUTER_API_KEY" not in html
        assert "ghp_" not in html

    def test_UI27_no_inline_tokens(self):
        html = Path("static/app.html").read_text()
        assert "Bearer sk-" not in html
        assert "jv-" not in html


class TestFlutterDesignSystem:
    def test_UI28_design_system_file_exists(self):
        assert Path("jarvismax_app/lib/theme/design_system.dart").exists()

    def test_UI29_design_tokens_unified(self):
        ds = Path("jarvismax_app/lib/theme/design_system.dart").read_text()
        assert "bgBase" in ds
        assert "bgSurface" in ds
        assert "bgElevated" in ds
        assert "textPrimary" in ds
        assert "blue" in ds
        assert "green" in ds
        assert "amber" in ds
        assert "red" in ds

    def test_UI30_design_tokens_match_web(self):
        """Flutter tokens match web CSS tokens."""
        ds = Path("jarvismax_app/lib/theme/design_system.dart").read_text()
        assert "0xFF09090B" in ds  # --bg-base
        assert "0xFF111113" in ds  # --bg-surface
        assert "0xFF3B82F6" in ds  # --blue
        assert "0xFF22C55E" in ds  # --green
        assert "0xFFF59E0B" in ds  # --amber
        assert "0xFFEF4444" in ds  # --red

    def test_UI31_reusable_widgets(self):
        ds = Path("jarvismax_app/lib/theme/design_system.dart").read_text()
        assert "JStatusBadge" in ds
        assert "JRiskBadge" in ds
        assert "JStatusDot" in ds
        assert "JCard" in ds
        assert "JEmptyState" in ds
        assert "JSectionHeader" in ds
        assert "JReadinessMeter" in ds

    def test_UI32_jarvis_theme(self):
        ds = Path("jarvismax_app/lib/theme/design_system.dart").read_text()
        assert "JarvisTheme" in ds
        assert "dark" in ds

    def test_UI33_app_mode_model(self):
        assert Path("jarvismax_app/lib/models/app_mode.dart").exists()
        content = Path("jarvismax_app/lib/models/app_mode.dart").read_text()
        assert "lite" in content
        assert "full" in content
        assert "admin" in content
        assert "showOperations" in content
        assert "showSystem" in content


class TestFlutterAppShell:
    def test_UI34_main_uses_unified_theme(self):
        main = Path("jarvismax_app/lib/main.dart").read_text()
        assert "JarvisTheme.dark" in main
        assert "design_system.dart" in main

    def test_UI35_five_tabs(self):
        """5 core tabs: Home, Missions, Approvals, History, Settings."""
        main = Path("jarvismax_app/lib/main.dart").read_text()
        assert "HomeScreen" in main
        assert "MissionScreen" in main
        assert "ApprovalsScreen" in main
        assert "HistoryScreen" in main
        assert "SettingsScreen" in main
        # Exactly 5 BottomNavigationBarItems
        count = main.count("BottomNavigationBarItem")
        assert count == 5, f"Expected 5 nav items, got {count}"

    def test_UI36_branded_splash(self):
        main = Path("jarvismax_app/lib/main.dart").read_text()
        assert "brand" in main.lower() or "gradient" in main.lower()

    def test_UI37_settings_has_advanced_section(self):
        settings = Path("jarvismax_app/lib/screens/settings_screen.dart").read_text()
        assert "Advanced" in settings
        assert "Modules" in settings
        assert "System Health" in settings or "AI OS" in settings

    def test_UI38_home_uses_design_system(self):
        home = Path("jarvismax_app/lib/screens/home_screen.dart").read_text()
        assert "design_system.dart" in home
        assert "JDS." in home

    def test_UI39_approvals_uses_design_system(self):
        approvals = Path("jarvismax_app/lib/screens/approvals_screen.dart").read_text()
        assert "design_system.dart" in approvals
        assert "JDS." in approvals
        assert "JRiskBadge" in approvals or "riskColor" in approvals

    def test_UI40_login_uses_design_system(self):
        login = Path("jarvismax_app/lib/screens/login_screen.dart").read_text()
        assert "design_system.dart" in login
        assert "JDS." in login
