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
    assert len(dialog._history) == 2
    dialog.navigate(b)
    assert dialog.stack.currentWidget() is b_page
    assert dialog.stack.count() == 3
    dialog.close()
