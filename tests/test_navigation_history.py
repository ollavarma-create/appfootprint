"""Regression tests for in-window dependency history."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from appfootprint.gui import NavigationDialog
from appfootprint.scanner import Item


def test_back_forward_and_branching_preserve_pages():
    app = QApplication.instance() or QApplication([])
    a = Item("org.example.A", "org.example.A/x86_64/1", "system", "runtime")
    b = Item("org.example.B", "org.example.B/x86_64/1", "system", "runtime")
    c = Item("org.example.C", "org.example.C/x86_64/1", "system", "runtime")
    dialog = NavigationDialog(a, [a, b, c])
    assert not dialog.back_button.isEnabled()
    dialog.navigate(b)
    assert dialog.back_button.isEnabled()
    assert not dialog.forward_button.isEnabled()
    b_page = dialog.stack.currentWidget()
    dialog.back()
    assert dialog.forward_button.isEnabled()
    dialog.forward()
    assert dialog.stack.currentWidget() is b_page
    dialog.back()
    dialog.navigate(c)
    assert not dialog.forward_button.isEnabled()
    assert len(dialog._navigation.entries) == 2
    dialog.navigate(b)
    assert dialog.stack.currentWidget() is b_page
    assert dialog.stack.count() == 3
    dialog.close()


def test_history_revisit_and_long_trail():
    from appfootprint.navigation import NavigationHistory, history_labels
    h = NavigationHistory()
    keys = [("runtime", f"org.example.{n}/x86_64/1", "system")
            for n in ("A", "B", "C", "D")]
    for key in keys:
        assert h.visit(key)
    assert not h.visit(keys[-1])
    assert h.visit(keys[0])
    visible, full = history_labels(h.entries, h.position)
    assert visible.startswith("History: …")
    assert "↩ org.example.A" in visible
    assert all(key[1] in full for key in keys)
    assert h.back()
    assert h.visit(keys[1])
    assert not h.can_forward


def test_revisit_detection_uses_full_ref_and_scope():
    from appfootprint.navigation import history_labels
    entries = [
        ("runtime", "org.example.Platform/x86_64/1", "system"),
        ("runtime", "org.example.Platform/x86_64/2", "system"),
        ("runtime", "org.example.Platform/x86_64/1", "user"),
    ]
    visible, _ = history_labels(entries, 2)
    assert "↩" not in visible


def test_missing_or_unknown_target_does_not_change_history():
    app = QApplication.instance() or QApplication([])
    runtime = Item("org.example.A", "org.example.A/x86_64/1", "system", "runtime")
    unknown = Item("org.example.Unknown", "org.example.Unknown/x86_64/1", "system", "unknown")
    dialog = NavigationDialog(runtime, [runtime])
    dialog.navigate(unknown)
    assert len(dialog._navigation.entries) == 1
    assert dialog.stack.count() == 1
    dialog.close()
