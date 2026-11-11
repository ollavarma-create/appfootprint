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
