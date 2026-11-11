from appfootprint.extensions import parse_extension_points, compatible_extension


METADATA = """
[Runtime]
name = org.freedesktop.Platform
[Extension org.freedesktop.Platform.GL]
versions = 25.08;25.08-extra;1.4
version = 1.4
subdirectories = true
enable-if = active-gl-driver
[Extension org.freedesktop.Platform.codecs-extra]
version = 25.08-extra
autodelete = true
[Extension org.freedesktop.Platform.Locale]
locale-subset = true
"""


def test_gl_versions_and_conditions():
    points = parse_extension_points(METADATA)
    gl = points[0]
    assert gl.name == "org.freedesktop.Platform.GL"
    assert gl.versions == ("25.08", "25.08-extra", "1.4")
    assert gl.subdirectories
    assert "enable-if=active-gl-driver" in gl.conditions


def test_compatible_gl_extra_branch_and_architecture():
    gl = parse_extension_points(METADATA)[0]
    platform = "org.freedesktop.Platform/x86_64/25.08"
    assert compatible_extension(gl, "org.freedesktop.Platform.GL.default/x86_64/25.08-extra", platform)
    assert not compatible_extension(gl, "org.freedesktop.Platform.GL.default/aarch64/25.08-extra", platform)
    assert not compatible_extension(gl, "org.freedesktop.Platform.GL.default/x86_64/24.08", platform)


def test_exact_name_and_default_platform_branch():
    points = parse_extension_points(METADATA)
    codecs = points[1]
    assert compatible_extension(codecs, "org.freedesktop.Platform.codecs-extra/x86_64/25.08-extra",
                                "org.freedesktop.Platform/x86_64/25.08")
    assert not compatible_extension(codecs, "org.freedesktop.Platform.codecs-extra.foo/x86_64/25.08-extra",
                                    "org.freedesktop.Platform/x86_64/25.08")
    locale = points[2]
    assert compatible_extension(locale, "org.freedesktop.Platform.Locale/x86_64/25.08",
                                "org.freedesktop.Platform/x86_64/25.08")
