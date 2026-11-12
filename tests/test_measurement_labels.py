"""Alpha release measurement wording regression tests."""
from appfootprint.measurement_labels import allocated_tooltip


def test_exact_bytes_are_visible():
    label = allocated_tooltip(1186148352)
    assert "1 186 148 352 bytes" in label
    assert "reclaimable" in label


def test_unknown_is_not_zero():
    assert "Unknown" in allocated_tooltip(None)
    assert "0 bytes" not in allocated_tooltip(None)


def test_partial_subtotal_is_not_presented_as_complete():
    label = allocated_tooltip(32768, incomplete=True)
    assert "Known subtotal" in label
    assert "32 768 bytes" in label


def test_zero_is_valid_measured_value():
    assert "0 bytes" in allocated_tooltip(0)
