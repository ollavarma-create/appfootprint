from appfootprint.scanner import Item, direct_runtime_users


def test_runtime_users_match_exact_ref_and_include_cross_scope():
    runtime = Item("org.kde.Platform", "runtime/org.kde.Platform/x86_64/6.10", "system", "runtime")
    good = Item("org.example.A", "app/org.example.A/x86_64/stable", "user", "app",
                runtime="org.kde.Platform/x86_64/6.10")
    wrong_branch = Item("org.example.B", "app/org.example.B/x86_64/stable", "system", "app",
                        runtime="org.kde.Platform/x86_64/6.9")
    assert direct_runtime_users(runtime, [wrong_branch, good]) == [good]


def test_no_claim_about_indirect_dependencies():
    runtime = Item("org.kde.Platform", "runtime/org.kde.Platform/x86_64/6.10", "system", "runtime")
    assert direct_runtime_users(runtime, []) == []


def test_flatpak_list_ref_without_runtime_prefix():
    """Regression: actual 'flatpak list --runtime --columns=ref' format."""
    runtime = Item(
        "org.kde.Platform", "org.kde.Platform/x86_64/6.10", "system", "runtime"
    )
    prism = Item(
        "org.prismlauncher.PrismLauncher",
        "org.prismlauncher.PrismLauncher/x86_64/stable",
        "system", "app", runtime="org.kde.Platform/x86_64/6.10",
    )
    assert direct_runtime_users(runtime, [prism]) == [prism]


def test_runtime_architecture_and_branch_must_match():
    runtime = Item("org.kde.Platform", "org.kde.Platform/x86_64/6.10", "system", "runtime")
    other_arch = Item("other", "other/x86_64/stable", "system", "app",
                      runtime="org.kde.Platform/aarch64/6.10")
    other_branch = Item("old", "old/x86_64/stable", "system", "app",
                        runtime="org.kde.Platform/x86_64/6.9")
    assert direct_runtime_users(runtime, [other_arch, other_branch]) == []
