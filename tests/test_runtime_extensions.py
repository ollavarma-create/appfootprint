from appfootprint.scanner import Item, runtime_extension_hint


def test_gl_extension_is_not_mistaken_for_unused_base_runtime():
    item = Item("org.freedesktop.Platform.GL.default",
                "org.freedesktop.Platform.GL.default/x86_64/25.08-extra",
                "system", "runtime")
    hint = runtime_extension_hint(item)
    assert hint is not None
    assert "extension points" in hint
    assert "cannot establish" in hint


def test_prefixed_runtime_ref_is_also_supported():
    item = Item("org.freedesktop.Platform.GL.default",
                "runtime/org.freedesktop.Platform.GL.default/x86_64/25.08-extra",
                "system", "runtime")
    assert runtime_extension_hint(item) is not None


def test_regular_platform_is_not_an_extension():
    item = Item("org.kde.Platform", "org.kde.Platform/x86_64/6.10",
                "system", "runtime")
    assert runtime_extension_hint(item) is None


def test_unknown_extension_is_not_guessed():
    item = Item("org.example.Extension", "org.example.Extension/x86_64/stable",
                "system", "runtime")
    assert runtime_extension_hint(item) is None
